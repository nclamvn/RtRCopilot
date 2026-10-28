"""Bounded workspace snapshot export and confirmed application-data deletion.

DBOS history, backups, provider storage and already downloaded copies are not a
forensic-erasure surface. The application never reuses a deleted workspace ID.
"""
import hashlib
import io
import json
import secrets
import time
import zipfile

from .store import WorkspaceError
from .workspace_state import request_key

MAX_EXPORT_BYTES = 20 * 1024 * 1024
MAX_EXPORT_MEMBERS = 2500
RETAINED = ["DBOS audit history", "private backups", "previously downloaded exports", "provider retention if any", "synthetic MCP fixture outbox receipts"]


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


class DataLifecycle:
    def __init__(self, store, *, active_runs=None):
        self.store = store
        self.active_runs = active_runs if active_runs is not None else set()

    def _snapshot(self, db, owner, wid, *, content=False):
        workspace = dict(self.store._workspace(db, owner, wid))
        workspace.pop("owner")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if content:
            # Refuse oversized snapshots BEFORE fetching BLOBs/history into RAM.
            total = 0
            for table, expr in [("files", "COALESCE(length(raw_content),length(CAST(content AS BLOB)))+length(CAST(content AS BLOB))"),
                ("messages", "length(CAST(content AS BLOB))"), ("workspace_memory", "length(CAST(content AS BLOB))"),
                ("workspace_schedules", "length(CAST(message AS BLOB))")]:
                if table in tables:
                    total += db.execute(f"SELECT COALESCE(SUM({expr}),0) FROM {table} WHERE workspace_id=?", (wid,)).fetchone()[0]
            total += db.execute("SELECT COALESCE(SUM(length(CAST(v.content AS BLOB))),0) FROM versions v JOIN artifacts a ON a.id=v.artifact_id WHERE a.workspace_id=?", (wid,)).fetchone()[0]
            files = db.execute("SELECT COUNT(*) FROM files WHERE workspace_id=?", (wid,)).fetchone()[0]
            versions = db.execute("SELECT COUNT(*) FROM versions v JOIN artifacts a ON a.id=v.artifact_id WHERE a.workspace_id=?", (wid,)).fetchone()[0]
            if total > MAX_EXPORT_BYTES or files * 2 + versions * 2 + 6 > MAX_EXPORT_MEMBERS:
                raise WorkspaceError("workspace_export_limit", 413)
        value = {"workspace": workspace}
        # Export only explicit application content, not sessions/model checkpoint
        # history, generic receipts, prompts, DBOS internals or provider settings.
        for table, key, columns in [
            ("files", "files", "*" if content else "id,sha256,bytes,created_at"), ("artifacts", "artifacts", "*"),
            ("messages", "messages", "id,run_id,role,content,created_at" if content else "id,run_id,role,created_at"),
            ("workspace_memory", "memory", "id,content,version,created_at,updated_at" if content else "id,version,created_at,updated_at"),
            ("workspace_schedules", "schedules", "id,message,due_at,state,version,run_id,error,created_at,updated_at" if content else "id,due_at,state,version,run_id,error,created_at,updated_at"),
        ]:
            if table in tables:
                suffix = " AND deleted=0" if table == "workspace_memory" else ""
                order = "created_at,rowid" if table == "messages" else "created_at,id"
                value[key] = [dict(r) for r in db.execute(f"SELECT {columns} FROM {table} WHERE workspace_id=?{suffix} ORDER BY {order}", (wid,))]
            else:
                value[key] = []
        columns = "v.*" if content else "v.artifact_id,v.version,v.run_id,v.created_at,v.metadata"
        value["versions"] = [dict(r) for r in db.execute(f"SELECT {columns} FROM versions v JOIN artifacts a ON a.id=v.artifact_id WHERE a.workspace_id=? ORDER BY v.artifact_id,v.version", (wid,))]
        value["runs"] = [dict(r) for r in db.execute("SELECT id,state,cancel_requested,error,usage,output_bytes,stream_bytes FROM runs WHERE workspace_id=? ORDER BY id", (wid,))]
        value["effect_states"] = [dict(r) for r in db.execute("SELECT id,status FROM effects WHERE workspace_id=? ORDER BY id", (wid,))] if "effects" in tables else []
        if content and "workspace_import_lineage" in tables:
            row = db.execute("SELECT archive_sha256,source_workspace_id,id_map,imported_at FROM workspace_import_lineage WHERE workspace_id=?", (wid,)).fetchone()
            if row:
                value["import_lineage"] = dict(row) | {"id_map": json.loads(row["id_map"])}
        return value

    def _digest(self, value):
        # Files immutable digests, artifact/memory/schedule immutable versions,
        # message identity and run/effect state cover API mutations without
        # materializing unbounded historical bodies in confirmation previews.
        def safe(item):
            if isinstance(item, bytes):
                return {"sha256": hashlib.sha256(item).hexdigest(), "bytes": len(item)}
            if isinstance(item, dict):
                return {key: safe(val) for key, val in item.items()}
            if isinstance(item, list):
                return [safe(val) for val in item]
            return item
        return hashlib.sha256(encoded(safe(value))).hexdigest()

    def _blocked(self, value):
        if any(r["state"] not in {"completed", "failed", "cancelled"} or r["id"] in self.active_runs for r in value["runs"]):
            return "workspace_busy"
        if any(e["status"] != "completed" for e in value["effect_states"]):
            return "workspace_unsettled_effects"
        return None

    def preview(self, owner, wid):
        with self.store.tx() as db:
            value = self._snapshot(db, owner, wid)
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO workspace_delete_previews VALUES(?,?,?,?,?) ON CONFLICT(workspace_id) DO UPDATE SET token_hash=excluded.token_hash,snapshot_digest=excluded.snapshot_digest,expires_at=excluded.expires_at", (wid, owner, hashlib.sha256(token.encode()).hexdigest(), self._digest(value), time.time() + 300))
            return dict(workspace_id=wid, name=value["workspace"]["name"], confirmation_token=token,
                artifact_ids=[a["id"] for a in value["artifacts"]],
                counts={key: len(value[key]) for key in ("files", "artifacts", "versions", "messages", "memory", "runs")},
                blocked_reason=self._blocked(value), retained=RETAINED)

    def export(self, owner, wid):
        # One snapshot transaction while copying bounded content. ZIP compression
        # runs after releasing SQLite, never holding a lock for network streaming.
        with self.store.tx() as db:
            value = self._snapshot(db, owner, wid, content=True)
        members, total = {}, 0
        def add(path, body):
            nonlocal total
            total += len(body)
            if total > MAX_EXPORT_BYTES or len(members) >= MAX_EXPORT_MEMBERS:
                raise WorkspaceError("workspace_export_limit", 413)
            members[path] = body
        manifest = dict(format="agent-workspace-export-v1", workspace=value["workspace"],
            exported_at=time.time(), retained=RETAINED, entries=[])
        if "import_lineage" in value:
            manifest["import_lineage"] = value["import_lineage"]
        file_metadata = []
        for item in value["files"]:
            item = item.copy()
            original = item.pop("raw_content")
            raw = original if original is not None else item["content"].encode()
            # Opaque ID paths, not user filenames, prevent archive traversal.
            path = "sources/" + item["id"] + "/original"
            add(path, raw)
            add("sources/" + item["id"] + "/extracted.txt", item.pop("content").encode())
            for key in ("metadata", "provenance", "warnings"):
                item[key] = json.loads(item[key])
            file_metadata.append(item | {"original_path": path})
        add("sources/index.json", encoded(file_metadata))
        for item in value["versions"]:
            path = f"artifacts/{item['artifact_id']}/v{item['version']}"
            add(path + ".txt", item["content"].encode())
            add(path + ".json", encoded({k: v for k, v in item.items() if k != "content"}))
        for key in ("artifacts", "messages", "memory", "schedules"):
            add(key + ".json", encoded(value[key]))
        manifest["entries"] = [{"path": p, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for p, b in members.items()]
        add("manifest.json", encoded(manifest))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, body in members.items():
                archive.writestr(path, body)
        return output.getvalue()

    def delete(self, owner, wid, token, name, key):
        request_key(key)
        digest = hashlib.sha256(encoded([wid, token, name])).hexdigest()
        with self.store.tx() as db:
            prior = db.execute("SELECT * FROM workspace_deletions WHERE owner=? AND request_id=?", (owner, key)).fetchone()
            if prior:
                if prior["workspace_id"] != wid or prior["args_digest"] != digest:
                    raise WorkspaceError("idempotency_conflict", 409)
                return json.loads(prior["result"])
            value = self._snapshot(db, owner, wid)
            confirmation = db.execute("SELECT * FROM workspace_delete_previews WHERE workspace_id=? AND owner=?", (wid, owner)).fetchone()
            if not confirmation or not secrets.compare_digest(confirmation["token_hash"], hashlib.sha256(token.encode()).hexdigest()) or confirmation["expires_at"] <= time.time() or confirmation["snapshot_digest"] != self._digest(value):
                raise WorkspaceError("delete_confirmation_stale", 409)
            if name != value["workspace"]["name"]:
                raise WorkspaceError("delete_confirmation_mismatch")
            blocked = self._blocked(value)
            if blocked:
                raise WorkspaceError(blocked, 409)
            # Identity tombstone and application purge are one transaction. All
            # future reads, tools and callbacks authorize through _workspace.
            db.execute("INSERT INTO workspace_tombstones VALUES(?,?,?)", (wid, owner, time.time()))
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            aids = {a["id"] for a in value["artifacts"]}
            for row in db.execute("SELECT request_id,result FROM revisions WHERE owner=?", (owner,)).fetchall():
                if json.loads(row["result"]).get("artifact_id") in aids:
                    db.execute("DELETE FROM revisions WHERE owner=? AND request_id=?", (owner, row["request_id"]))
            if "connection_requests" in tables:
                # Replayed connection command receipts may include note bodies.
                # Select only this workspace's approval/grant references.
                approval_ids = {r[0] for r in db.execute("SELECT id FROM approvals WHERE workspace_id=?", (wid,))}
                for row in db.execute("SELECT key,result FROM connection_requests WHERE owner=?", (owner,)).fetchall():
                    result = json.loads(row["result"])
                    if result.get("workspace_id") == wid or result.get("id") in approval_ids:
                        db.execute("DELETE FROM connection_requests WHERE owner=? AND key=?", (owner, row["key"]))
            for table, relation in [("versions", "artifact_id IN (SELECT id FROM artifacts WHERE workspace_id=?)"),
                ("events", "run_id IN (SELECT id FROM runs WHERE workspace_id=?)"),
                ("receipts", "run_id IN (SELECT id FROM runs WHERE workspace_id=?)"),
                ("workspace_memory_reads", "workspace_id=?"), ("connection_reads", "workspace_id=?")]:
                if table in tables:
                    db.execute(f"DELETE FROM {table} WHERE {relation}", (wid,))
            for table in ("files", "artifacts", "messages", "workspace_memory", "workspace_memory_meta", "workspace_schedules", "workspace_clocks", "workspace_state_requests", "effects", "approvals", "connection_grants", "runs", "workspace_delete_previews"):
                if table in tables:
                    db.execute(f"DELETE FROM {table} WHERE workspace_id=?", (wid,))
            for table in ("workspace_import_lineage", "workspace_metadata_requests"):
                if table in tables:
                    db.execute(f"DELETE FROM {table} WHERE workspace_id=?", (wid,))
            if "workspace_import_receipts" in tables:
                # Preserve the consumed idempotency key, not the deleted title.
                db.execute("UPDATE workspace_import_receipts SET result='{}' WHERE workspace_id=?", (wid,))
            # Keep only opaque identity/owner timestamp, not even the old title.
            db.execute("DELETE FROM workspaces WHERE id=? AND owner=?", (wid, owner))
            result = dict(deleted=True, workspace_id=wid, retained=RETAINED)
            db.execute("INSERT INTO workspace_deletions VALUES(?,?,?,?,?)", (owner, key, wid, digest, json.dumps(result)))
            return result
