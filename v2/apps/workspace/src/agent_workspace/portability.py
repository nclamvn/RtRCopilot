"""Untrusted, bounded AW-04 snapshot import. No executor or authority is restored.

Preview stores only a digest/options/token, never the uploaded archive. Commit
validates the same bytes again and inserts a new identity atomically. Checksum
agreement proves transport consistency, not the truth of imported statements.
"""
import base64
import binascii
import hashlib
import io
import json
import math
import re
import secrets
import sqlite3
import stat
import time
import zipfile
import zlib

from .data_lifecycle import MAX_EXPORT_BYTES, MAX_EXPORT_MEMBERS
from .store import WorkspaceError, identity, valid_filename
from .workspace_state import WorkspaceState, bounded_text, request_key

MAX_BASE64 = ((MAX_EXPORT_BYTES + 2) // 3) * 4
ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
SHA = re.compile(r"^[a-f0-9]{64}$")
OMISSIONS = ["No credentials, sessions, tool grants, approvals or receipts are imported.",
    "Conversation is a displayed archive, not reusable model history or resumable execution.",
    "Schedules and execution checkpoints are not imported or activated.",
    "Imported statements and source provenance are unverified archive data, not authority."]


def fail(code="invalid_workspace_snapshot", status=400):
    raise WorkspaceError(code, status)


def record(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        fail()
    return value


def identifier(value, nullable=False):
    if nullable and value is None:
        return value
    if not isinstance(value, str) or not ID.fullmatch(value):
        fail()
    return value


def integer(value, minimum=0, maximum=1_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        fail()
    return value


def timestamp(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10**13:
        fail()
    return value


def text(value, maximum, *, empty=True):
    if not isinstance(value, str):
        fail()
    try:
        raw = value.encode("utf-8")
    except UnicodeError:
        fail()
    if len(raw) > maximum or (not empty and not value.strip()) or any(ord(c) < 32 and c not in "\t\n\r" for c in value):
        fail()
    return value


def json_value(raw):
    # Bound structural fanout/depth BEFORE json.loads allocates objects. Text in
    # strings is not counted as structure. Duplicate keys/NaN are never accepted.
    quoted = escaped = False
    depth = structures = separators = 0
    for c in raw:
        if quoted:
            if escaped:
                escaped = False
            elif c == 92:
                escaped = True
            elif c == 34:
                quoted = False
        elif c == 34:
            quoted = True
        elif c in (91, 123):
            depth += 1
            structures += 1
            if depth > 20 or structures > 100_000:
                fail("snapshot_structure_limit", 413)
        elif c in (93, 125):
            depth -= 1
        elif c == 44:
            separators += 1
            if separators > 200_000:
                fail("snapshot_structure_limit", 413)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail()
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: fail())
    except (UnicodeError, ValueError, RecursionError, TypeError):
        fail()


def bounded_object(value, maximum=64000):
    if not isinstance(value, dict):
        fail()
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, UnicodeError, RecursionError):
        fail()
    if len(raw) > maximum:
        fail("snapshot_metadata_limit", 413)
    return value


def decode_archive(encoded):
    if not isinstance(encoded, str) or not encoded or len(encoded) > MAX_BASE64:
        fail("snapshot_archive_limit", 413)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        fail()
    if not raw or len(raw) > MAX_EXPORT_BYTES:
        fail("snapshot_archive_limit", 413)
    return raw


def inspect_archive(raw):
    try:
        return _inspect_archive(raw)
    except (TypeError, ValueError, KeyError, OverflowError, UnicodeError, RecursionError):
        fail()


def _inspect_archive(raw):
    members = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_EXPORT_MEMBERS:
                fail("snapshot_archive_limit", 413)
            total = 0
            for info in infos:
                path = info.filename
                mode = stat.S_IFMT(info.external_attr >> 16)
                if (path in members or not path or info.orig_filename != path or "\\" in path or path.startswith("/")
                    or any(p in {"", ".", ".."} for p in path.split("/"))
                    or "\x00" in path or len(path) > 400 or info.is_dir()
                    or mode not in (0, stat.S_IFREG) or info.flag_bits & 1
                    or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                    fail()
                total += info.file_size
                if info.file_size < 0 or total > MAX_EXPORT_BYTES:
                    fail("snapshot_archive_limit", 413)
                body = bytearray()
                with archive.open(info) as stream:
                    while chunk := stream.read(min(65536, MAX_EXPORT_BYTES - len(body) + 1)):
                        body.extend(chunk)
                        if len(body) > info.file_size or len(body) > MAX_EXPORT_BYTES:
                            fail("snapshot_archive_limit", 413)
                if len(body) != info.file_size:
                    fail()
                members[path] = bytes(body)
    except (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, OSError, ValueError, EOFError):
        fail()
    if "manifest.json" not in members:
        fail()
    manifest = record(json_value(members["manifest.json"]), {"format", "workspace", "exported_at", "retained", "entries"}, {"import_lineage"})
    if manifest["format"] != "agent-workspace-export-v1":
        fail("unsupported_snapshot_format")
    workspace = record(manifest["workspace"], {"id", "name", "created_at"}, {"archived", "revision"})
    identifier(workspace["id"])
    text(workspace["name"], 480, empty=False)
    if len(workspace["name"]) > 120:
        fail()
    timestamp(workspace["created_at"])
    timestamp(manifest["exported_at"])
    if "archived" in workspace and (type(workspace["archived"]) not in (bool, int) or workspace["archived"] not in (0, 1)):
        fail()
    if "revision" in workspace:
        integer(workspace["revision"], 1)
    if not isinstance(manifest["retained"], list) or len(manifest["retained"]) > 20:
        fail()
    for item in manifest["retained"]:
        text(item, 1000)
    if "import_lineage" in manifest:
        bounded_object(manifest["import_lineage"], 2000000)
    if not isinstance(manifest["entries"], list) or len(manifest["entries"]) != len(members) - 1:
        fail()
    paths = set()
    for entry in manifest["entries"]:
        record(entry, {"path", "bytes", "sha256"})
        path = entry["path"]
        if not isinstance(path, str) or path == "manifest.json" or path in paths or path not in members:
            fail()
        paths.add(path)
        if integer(entry["bytes"], 0, MAX_EXPORT_BYTES) != len(members[path]) or not isinstance(entry["sha256"], str) or not SHA.fullmatch(entry["sha256"]) or hashlib.sha256(members[path]).hexdigest() != entry["sha256"]:
            fail("snapshot_digest_mismatch")
    expected = {"sources/index.json", "artifacts.json", "messages.json", "memory.json", "schedules.json"}
    if "continuity.json" in paths:
        expected.add("continuity.json")
    if not expected <= paths:
        fail()
    value = {"workspace": workspace, "sha256": hashlib.sha256(raw).hexdigest(), "files": [], "artifacts": [], "versions": [], "messages": [], "memory": [], "schedules": []}
    def collection(path, maximum):
        items = json_value(members[path])
        if not isinstance(items, list) or len(items) > maximum:
            fail("snapshot_record_limit", 413)
        return items
    def unique(items):
        ids = [identifier(i.get("id")) if isinstance(i, dict) else fail() for i in items]
        if len(set(ids)) != len(ids):
            fail()
    files = collection("sources/index.json", 20)
    unique(files)
    raw_total = 0
    for item in files:
        record(item, {"id", "workspace_id", "filename", "media_type", "bytes", "created_at", "sha256", "warnings", "provenance", "metadata", "original_path"})
        fid = item["id"]
        if item["workspace_id"] != workspace["id"] or item["original_path"] != f"sources/{fid}/original":
            fail()
        valid_filename(item["filename"])
        original, extracted = f"sources/{fid}/original", f"sources/{fid}/extracted.txt"
        expected.update([original, extracted])
        if original not in members or extracted not in members:
            fail()
        raw_total += len(members[original])
        if integer(item["bytes"], 0, 256000) != len(members[original]) or raw_total > 1000000:
            fail("snapshot_source_limit", 413)
        if item["sha256"] != hashlib.sha256(members[original]).hexdigest():
            fail("snapshot_digest_mismatch")
        timestamp(item["created_at"])
        if not isinstance(item["warnings"], list) or len(item["warnings"]) > 100:
            fail()
        for warning in item["warnings"]:
            text(warning, 4000)
        bounded_object(item["metadata"])
        bounded_object(item["provenance"])
        # Sources are parsed with the same bounded offline format implementation
        # as upload; an archive cannot bypass supported-format checks by lying
        # in its metadata/extraction. Never repair or silently re-extract a value.
        from .formats import extract_upload
        try:
            parsed = extract_upload(item["filename"], members[original])
            content = members[extracted].decode("utf-8")
        except Exception:
            fail("snapshot_source_parse_failed")
        text(content, 1000000)
        if content != parsed.text or item["media_type"] != parsed.media_type or item["metadata"] != parsed.metadata or item["warnings"] != list(parsed.warnings):
            fail("snapshot_extraction_mismatch")
        value["files"].append(item | {"raw_content": members[original], "content": content})
    artifacts = collection("artifacts.json", 100)
    unique(artifacts)
    from .formats import validate_artifact
    for item in artifacts:
        record(item, {"id", "workspace_id", "title", "filename", "media_type", "version", "created_at", "kind"})
        aid = item["id"]
        if item["workspace_id"] != workspace["id"] or item["kind"] not in {"document", "table"}:
            fail()
        text(item["title"], 640, empty=False)
        if len(item["title"]) > 160:
            fail()
        valid_filename(item["filename"])
        ext = ".csv" if item["kind"] == "table" else ".md"
        mime = "text/csv" if item["kind"] == "table" else "text/markdown"
        if not item["filename"].lower().endswith(ext) or item["media_type"] != mime:
            fail()
        version = integer(item["version"], 1, MAX_EXPORT_MEMBERS // 2)
        timestamp(item["created_at"])
        for number in range(1, version + 1):
            prefix = f"artifacts/{aid}/v{number}"
            expected.update([prefix + ".txt", prefix + ".json"])
            if prefix + ".txt" not in members or prefix + ".json" not in members:
                fail()
            old = record(json_value(members[prefix + ".json"]), {"artifact_id", "version", "run_id", "created_at", "metadata"})
            if old["artifact_id"] != aid or integer(old["version"], 1) != number:
                fail()
            identifier(old["run_id"], nullable=True)
            timestamp(old["created_at"])
            if not isinstance(old["metadata"], str):
                fail()
            metadata = bounded_object(json_value(old["metadata"].encode()))
            record(metadata, set(), {"title", "filename", "kind", "media_type", "import_lineage"})
            if metadata:
                for key in ("title", "filename", "kind", "media_type"):
                    if key not in metadata:
                        fail()
                text(metadata["title"], 640, empty=False)
                valid_filename(metadata["filename"])
                if metadata["kind"] != item["kind"] or metadata["media_type"] != mime or not metadata["filename"].lower().endswith(ext):
                    fail()
                if "import_lineage" in metadata:
                    bounded_object(metadata["import_lineage"])
            try:
                content = members[prefix + ".txt"].decode("utf-8")
                text(content, 256000, empty=False)
                validate_artifact(item["kind"], content)
            except Exception:
                fail("snapshot_artifact_invalid")
            value["versions"].append(old | {"content": content, "metadata": metadata})
        value["artifacts"].append(item)
    messages = collection("messages.json", 10000)
    unique(messages)
    previous = -1
    for item in messages:
        record(item, {"id", "run_id", "role", "content", "created_at"})
        identifier(item["run_id"], nullable=True)
        if item["role"] not in {"user", "assistant"} or timestamp(item["created_at"]) < previous:
            fail()
        previous = item["created_at"]
        text(item["content"], 256000)
        value["messages"].append(item)
    memories = collection("memory.json", 100)
    unique(memories)
    total_memory = 0
    for item in memories:
        record(item, {"id", "content", "version", "created_at", "updated_at"})
        bounded_text(item["content"], 4000, "invalid_workspace_snapshot")
        total_memory += len(item["content"].encode())
        integer(item["version"], 1)
        timestamp(item["created_at"])
        timestamp(item["updated_at"])
        value["memory"].append(item)
    if total_memory > 64000:
        fail("snapshot_memory_limit", 413)
    schedules = collection("schedules.json", 100)
    unique(schedules)
    for item in schedules:
        record(item, {"id", "message", "due_at", "state", "version", "run_id", "error", "created_at", "updated_at"})
        bounded_text(item["message"], 16000, "invalid_workspace_snapshot")
        timestamp(item["due_at"])
        timestamp(item["created_at"])
        timestamp(item["updated_at"])
        integer(item["version"], 1)
        identifier(item["run_id"], nullable=True)
        if item["state"] not in {"pending", "paused", "cancelled", "dispatched"}:
            fail()
        if item["error"] is not None:
            text(item["error"], 1000)
        value["schedules"].append(item)
    if "continuity.json" in paths:
        extension = record(json_value(members["continuity.json"]), {"format", "brief", "source_replacements", "artifact_dependencies"})
        if extension["format"] != "agent-workspace-continuity-v1":
            fail("unsupported_snapshot_continuity")
        brief = record(extension["brief"], {"revision", "goal", "decisions", "remaining", "source"})
        integer(brief["revision"], 0)
        if brief["source"] != "user":
            fail()
        for key in ("goal", "decisions", "remaining"):
            text(brief[key], 12000)
            if len(brief[key]) > 4000:
                fail()
        links = extension["source_replacements"]
        if not isinstance(links, list) or len(links) > 20:
            fail()
        file_ids = {i["id"] for i in value["files"]}
        mapping = {}
        for link in links:
            record(link, {"old_file_id", "new_file_id"})
            old, new = link["old_file_id"], link["new_file_id"]
            if old not in file_ids or new not in file_ids or old in mapping:
                fail()
            mapping[old] = new
        for old in mapping:
            seen, cursor = set(), old
            while cursor in mapping:
                if cursor in seen:
                    fail()
                seen.add(cursor)
                cursor = mapping[cursor]
        # Imported dependency claims are retained for inspection only, not
        # admitted to the live verified read ledger or execution authority.
        claims = extension["artifact_dependencies"]
        if not isinstance(claims, list) or len(claims) > MAX_EXPORT_MEMBERS:
            fail()
        for claim in claims:
            record(claim, {"artifact_id", "version", "dependencies"})
            if not any(a["id"] == claim["artifact_id"] and 1 <= integer(claim["version"], 1) <= a["version"] for a in value["artifacts"]):
                fail()
            if not isinstance(claim["dependencies"], str):
                fail()
            data = json_value(claim["dependencies"].encode())
            if not isinstance(data, list) or len(data) > 500:
                fail()
            for dep in data:
                bounded_object(dep)
        value["continuity"] = extension
    if expected != paths:
        fail("snapshot_unexpected_members")
    return value


class SnapshotImporter:
    def __init__(self, store):
        self.store = store
        WorkspaceState(store)
        from .continuity import Continuity
        if not getattr(store, "continuity", None):
            Continuity(store)
        with store.tx() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS workspace_import_previews(token_hash TEXT PRIMARY KEY,owner TEXT NOT NULL,args_digest TEXT NOT NULL,expires_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS workspace_import_receipts(owner TEXT NOT NULL,request_id TEXT NOT NULL,args_digest TEXT NOT NULL,workspace_id TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(owner,request_id));
            CREATE TABLE IF NOT EXISTS workspace_import_lineage(workspace_id TEXT PRIMARY KEY,archive_sha256 TEXT NOT NULL,source_workspace_id TEXT NOT NULL,id_map TEXT NOT NULL,imported_at REAL NOT NULL);
            """)

    def lineage(self, owner, wid):
        with self.store.tx() as db:
            self.store._workspace(db, owner, wid)
            row = db.execute("SELECT archive_sha256,source_workspace_id,id_map,imported_at FROM workspace_import_lineage WHERE workspace_id=?", (wid,)).fetchone()
            return dict(imported=True, archive_sha256=row["archive_sha256"], source_workspace_id=row["source_workspace_id"], id_map=json.loads(row["id_map"]), imported_at=row["imported_at"]) if row else {"imported": False}

    def _prepare(self, encoded, name, include_memory):
        name = bounded_text(name, 120, "invalid_workspace_name").strip()
        if type(include_memory) is not bool:
            fail()
        raw = decode_archive(encoded)
        sha = hashlib.sha256(raw).hexdigest()
        args = hashlib.sha256(json.dumps([sha, name, include_memory], ensure_ascii=False).encode()).hexdigest()
        return raw, name, sha, args

    def preview(self, owner, encoded, name, include_memory=False):
        raw, name, sha, args = self._prepare(encoded, name, include_memory)
        value = inspect_archive(raw)
        token, expires = secrets.token_urlsafe(32), time.time() + 300
        with self.store.tx() as db:
            db.execute("DELETE FROM workspace_import_previews WHERE expires_at<=?", (time.time(),))
            if db.execute("SELECT COUNT(*) FROM workspace_import_previews WHERE owner=?", (owner,)).fetchone()[0] >= 10 or db.execute("SELECT COUNT(*) FROM workspace_import_previews").fetchone()[0] >= 2000:
                fail("snapshot_preview_limit", 409)
            db.execute("INSERT INTO workspace_import_previews VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), owner, args, expires))
        return dict(confirmation_token=token, archive_sha256=sha, expires_at=expires, name=name,
            include_memory=include_memory, source_workspace={"name": value["workspace"]["name"]},
            counts={key: len(value[key]) for key in ("files", "artifacts", "versions", "messages", "memory")} | {"memory_selected": len(value["memory"]) if include_memory else 0, "schedules_omitted": len(value["schedules"])},
            omissions=OMISSIONS + ([] if include_memory else ["Saved memory is omitted because you did not opt in."]),
            limits=dict(archive_bytes=MAX_EXPORT_BYTES, uncompressed_bytes=MAX_EXPORT_BYTES, members=MAX_EXPORT_MEMBERS))

    def commit(self, owner, encoded, name, include_memory, token, key):
        try:
            return self._commit(owner, encoded, name, include_memory, token, key)
        except sqlite3.Error:
            fail("snapshot_import_failed", 503)

    def _commit(self, owner, encoded, name, include_memory, token, key):
        request_key(key)
        if not isinstance(token, str) or not 20 <= len(token) <= 160:
            fail("snapshot_confirmation_stale", 409)
        raw, name, sha, args = self._prepare(encoded, name, include_memory)
        digest = hashlib.sha256(json.dumps([args, token]).encode()).hexdigest()
        def receipt(db):
            prior = db.execute("SELECT * FROM workspace_import_receipts WHERE owner=? AND request_id=?", (owner, key)).fetchone()
            if prior:
                if prior["args_digest"] != digest:
                    fail("idempotency_conflict", 409)
                current = self.store._workspace(db, owner, prior["workspace_id"])
                # The receipt proves which import happened, not that its title
                # or archive visibility is still the old value after later edits.
                return json.loads(prior["result"]) | {"workspace": self.store._workspace_view(current)}
        with self.store.tx() as db:
            prior = receipt(db)
            if prior:
                return prior
            confirm = db.execute("SELECT * FROM workspace_import_previews WHERE token_hash=? AND owner=?", (hashlib.sha256(token.encode()).hexdigest(), owner)).fetchone()
            if not confirm or confirm["args_digest"] != args or confirm["expires_at"] <= time.time():
                fail("snapshot_confirmation_stale", 409)
        value = inspect_archive(raw)
        with self.store.tx() as db:
            prior = receipt(db)
            if prior:
                return prior
            confirm = db.execute("SELECT * FROM workspace_import_previews WHERE token_hash=? AND owner=?", (hashlib.sha256(token.encode()).hexdigest(), owner)).fetchone()
            if not confirm or confirm["args_digest"] != args or confirm["expires_at"] <= time.time():
                fail("snapshot_confirmation_stale", 409)
            if db.execute("SELECT COUNT(*) FROM workspace_import_receipts WHERE owner=?", (owner,)).fetchone()[0] >= 2000:
                fail("snapshot_import_limit", 409)
            wid, now = identity(), time.time()
            maps = {kind: {item["id"]: identity() for item in value[kind]} for kind in ("files", "artifacts", "messages", "memory")}
            db.execute("INSERT INTO workspaces(id,owner,name,created_at) VALUES(?,?,?,?)", (wid, owner, name, now))
            for item in value["files"]:
                db.execute("INSERT INTO files(id,workspace_id,filename,media_type,content,bytes,created_at,raw_content,sha256,warnings,provenance,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (maps["files"][item["id"]], wid, item["filename"], item["media_type"], item["content"], item["bytes"], item["created_at"], item["raw_content"], item["sha256"], json.dumps(item["warnings"]), json.dumps(item["provenance"]), json.dumps(item["metadata"])))
            for item in value["artifacts"]:
                db.execute("INSERT INTO artifacts(id,workspace_id,title,filename,media_type,version,created_at,kind) VALUES(?,?,?,?,?,?,?,?)", (maps["artifacts"][item["id"]], wid, item["title"], item["filename"], item["media_type"], item["version"], item["created_at"], item["kind"]))
            for item in value["versions"]:
                metadata = dict(item["metadata"])
                claims = [c for c in value.get("continuity", {}).get("artifact_dependencies", []) if c["artifact_id"] == item["artifact_id"] and c["version"] == item["version"]]
                if claims:
                    metadata["import_lineage"] = dict(metadata.get("import_lineage", {})) | {"archived_dependency_claims": json.loads(claims[0]["dependencies"]), "authority": "untrusted archive, original IDs; not live lineage"}
                db.execute("INSERT INTO versions(artifact_id,version,content,run_id,created_at,metadata) VALUES(?,?,?,NULL,?,?)", (maps["artifacts"][item["artifact_id"]], item["version"], item["content"], item["created_at"], json.dumps(metadata)))
            for item in value["messages"]:
                db.execute("INSERT INTO messages VALUES(?,?,NULL,?,?,?)", (maps["messages"][item["id"]], wid, item["role"], item["content"], item["created_at"]))
            if "continuity" in value:
                # Ensure tables exist before entering this transaction via the
                # app Runtime; direct importer users initialize below in __init__.
                extension = value["continuity"]
                brief = extension["brief"]
                db.execute("INSERT INTO project_briefs VALUES(?,?,?,?,?)", (wid, brief["revision"], brief["goal"], brief["decisions"], brief["remaining"]))
                for link in extension["source_replacements"]:
                    db.execute("INSERT INTO source_replacements VALUES(?,?,?,?)", (wid, maps["files"][link["old_file_id"]], maps["files"][link["new_file_id"]], now))
            if include_memory:
                for item in value["memory"]:
                    db.execute("INSERT INTO workspace_memory VALUES(?,?,?,?,0,?,?)", (maps["memory"][item["id"]], wid, item["content"], item["version"], item["created_at"], item["updated_at"]))
                db.execute("INSERT INTO workspace_memory_meta VALUES(?,?)", (wid, int(bool(value["memory"]))))
            else:
                maps["memory"] = {}
            db.execute("INSERT INTO workspace_import_lineage VALUES(?,?,?,?,?)", (wid, sha, value["workspace"]["id"], json.dumps(maps), now))
            result = dict(workspace=self.store._workspace_view(self.store._workspace(db, owner, wid)), imported=True,
                lineage={"archive_sha256": sha}, omissions=OMISSIONS + ([] if include_memory else ["Saved memory omitted by your choice."]) + (["Imported dependency claims are archived only; live artifact lineage is unknown until new reads occur."] if "continuity" in value else []))
            db.execute("INSERT INTO workspace_import_receipts VALUES(?,?,?,?,?)", (owner, key, digest, wid, json.dumps(result)))
            db.execute("DELETE FROM workspace_import_previews WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
            return result
