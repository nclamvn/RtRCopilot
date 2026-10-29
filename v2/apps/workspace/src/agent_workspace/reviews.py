"""Opt-in review candidates and bounded saved-version handoff, no extra agent loop."""
import difflib
import csv
import hashlib
import io
import json
import threading
import time
import zipfile

from .formats import _csv_text, render_artifact, validate_artifact
from .store import WorkspaceError, identity
from .workspace_state import request_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS artifact_proposals(
 id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,artifact_id TEXT NOT NULL,run_id TEXT NOT NULL,
 base_version INTEGER NOT NULL,base_sha256 TEXT NOT NULL,base_content TEXT NOT NULL,
 proposed_content TEXT NOT NULL,changes TEXT NOT NULL,diff_unit TEXT NOT NULL,
 memory_revision INTEGER NOT NULL,brief_revision INTEGER NOT NULL,
 status TEXT NOT NULL,created_at REAL NOT NULL,result_version INTEGER);
CREATE TABLE IF NOT EXISTS proposal_decisions(owner TEXT NOT NULL,request_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL,args_digest TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(owner,request_id));
"""
_HANDOFF = threading.BoundedSemaphore(1)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def epochs(db, wid):
    memory = db.execute("SELECT revision FROM workspace_memory_meta WHERE workspace_id=?", (wid,)).fetchone()
    brief = db.execute("SELECT revision FROM project_briefs WHERE workspace_id=?", (wid,)).fetchone()
    return (memory[0] if memory else 0, brief[0] if brief else 0)


def forget(db, wid):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for name in ("artifact_proposals", "proposal_decisions"):
        if name in tables:
            db.execute(f"DELETE FROM {name} WHERE workspace_id=?", (wid,))


def units(kind, content):
    return [tuple(row) for row in csv.reader(io.StringIO(content, newline=""), strict=True)] if kind == "table" else content.splitlines(keepends=True)


def serialize(kind, value):
    if kind == "table":
        return _csv_text(value) if value else ""
    return "".join(value)


def changes_for(kind, base, proposed):
    before, after = units(kind, base), units(kind, proposed)
    if len(before) > 4000 or len(after) > 4000:
        raise WorkspaceError("proposal_diff_limit", 413)
    changes = []
    for tag, a, b, c, d in difflib.SequenceMatcher(None, before, after, autojunk=True).get_opcodes():
        if tag != "equal":
            changes.append(dict(id=f"change-{len(changes) + 1}", start_line=a, end_line=b,
                                old_text=serialize(kind, before[a:b]), new_text=serialize(kind, after[c:d])))
    if not changes:
        raise WorkspaceError("proposal_no_changes", 409)
    if len(changes) > 100:
        raise WorkspaceError("proposal_diff_limit", 413)
    return changes


class Reviews:
    def __init__(self, store):
        self.store = store
        with store.tx() as db:
            db.executescript(SCHEMA)
        store.reviews = self

    def capture(self, db, run, artifact_id, expected_version, content, title, filename):
        options = json.loads(run["context_options"])
        if not options.get("review_edits"):
            return None
        target = options.get("target") or {}
        if artifact_id != target.get("id") or expected_version != target.get("version"):
            raise WorkspaceError("context_target_mismatch", 409)
        item = db.execute("SELECT a.*,v.content FROM artifacts a JOIN versions v ON v.artifact_id=a.id AND v.version=a.version WHERE a.id=? AND a.workspace_id=?", (artifact_id, run["workspace_id"])).fetchone()
        if not item or item["version"] != expected_version:
            raise WorkspaceError("stale_artifact_version", 409)
        if item["title"] != title or item["filename"] != filename:
            raise WorkspaceError("proposal_metadata_change_not_supported", 409)
        try:
            if len(content.encode()) > 256000:
                raise WorkspaceError("proposal_content_limit", 413)
            validate_artifact(item["kind"], content)
        except ValueError:
            raise WorkspaceError("invalid_proposal_content") from None
        if db.execute("SELECT COUNT(*) FROM artifact_proposals WHERE run_id=?", (run["id"],)).fetchone()[0] >= 8 or db.execute("SELECT COUNT(*) FROM artifact_proposals WHERE workspace_id=?", (run["workspace_id"],)).fetchone()[0] >= 128:
            raise WorkspaceError("proposal_capacity", 413)
        changes = changes_for(item["kind"], item["content"], content)
        memory, brief = epochs(db, run["workspace_id"])
        pid = identity()
        for change in changes:
            change["id"] = pid + ":" + change["id"]
        db.execute("INSERT INTO artifact_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                   (pid, run["workspace_id"], artifact_id, run["id"], expected_version, sha(item["content"]), item["content"], content,
                    json.dumps(changes), "csv_row" if item["kind"] == "table" else "line", memory, brief, "pending", time.time()))
        # Metadata only: bodies are not copied into tool receipts/checkpoints.
        return dict(candidate_id=pid, artifact_id=artifact_id, version=expected_version, status="pending_review")

    def _row(self, db, owner, pid):
        row = db.execute("SELECT p.* FROM artifact_proposals p JOIN workspaces w ON w.id=p.workspace_id WHERE p.id=? AND w.owner=?", (pid, owner)).fetchone()
        if not row:
            raise WorkspaceError("not_found", 404)
        self.store._workspace(db, owner, row["workspace_id"])
        return row

    def _blocked(self, db, row):
        if epochs(db, row["workspace_id"]) != (row["memory_revision"], row["brief_revision"]):
            return "proposal_scope_changed"
        run = db.execute("SELECT owner,state,cancel_requested FROM runs WHERE id=?", (row["run_id"],)).fetchone()
        if not run or run["state"] != "completed" or run["cancel_requested"]:
            return "proposal_producer_not_completed"
        guard = getattr(self.store, "connection_guard", None)
        if guard:
            try:
                guard(db, run["owner"], row["run_id"])
            except WorkspaceError:
                return "connection_scope_changed"
        artifact = db.execute("SELECT a.version,v.content FROM artifacts a JOIN versions v ON v.artifact_id=a.id AND v.version=a.version WHERE a.id=?", (row["artifact_id"],)).fetchone()
        if not artifact or artifact[0] != row["base_version"] or sha(artifact[1]) != row["base_sha256"]:
            return "stale_artifact_version"
        return None

    def _view(self, db, row, full=False):
        keys = ("id", "workspace_id", "artifact_id", "run_id", "base_version", "base_sha256", "status", "created_at", "result_version", "diff_unit")
        result = {key: row[key] for key in keys}
        scope_reason = self._blocked(db, row)
        reason = scope_reason if row["status"] == "pending" else "proposal_already_decided"
        producer = db.execute("SELECT state FROM runs WHERE id=?", (row["run_id"],)).fetchone()
        can_reject = row["status"] == "pending" and bool(producer and producer[0] in {"completed", "failed", "cancelled"})
        result.update(can_decide=reason is None, can_reject=can_reject, blocked_reason=reason)
        if full:
            if scope_reason in {"proposal_scope_changed", "proposal_producer_not_completed", "connection_scope_changed"}:
                raise WorkspaceError(scope_reason, 409)
            result.update(base_content=row["base_content"], proposed_content=row["proposed_content"], changes=json.loads(row["changes"]))
        return result

    def get(self, owner, pid):
        with self.store.tx() as db:
            return self._view(db, self._row(db, owner, pid), True)

    def listing(self, owner, wid):
        with self.store.tx() as db:
            self.store._workspace(db, owner, wid)
            return dict(items=[self._view(db, row) for row in db.execute("SELECT * FROM artifact_proposals WHERE workspace_id=? ORDER BY created_at,id", (wid,))])

    def decide(self, owner, pid, decision, ids, key):
        request_key(key)
        if not isinstance(decision, str) or decision not in {"accept", "reject"} or not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)) or decision == "reject" and ids or decision == "accept" and not ids:
            raise WorkspaceError("invalid_proposal_decision")
        digest = sha(json.dumps([pid, decision, sorted(ids)]))
        with self.store.tx() as db:
            row = self._row(db, owner, pid)
            receipt = db.execute("SELECT * FROM proposal_decisions WHERE owner=? AND request_id=?", (owner, key)).fetchone()
            if receipt:
                if receipt["args_digest"] != digest:
                    raise WorkspaceError("idempotency_conflict", 409)
                return json.loads(receipt["result"])
            if row["status"] != "pending":
                raise WorkspaceError("proposal_already_decided", 409)
            if decision == "accept":
                reason = self._blocked(db, row)
                if reason:
                    raise WorkspaceError(reason, 409)
            else:
                producer = db.execute("SELECT state FROM runs WHERE id=?", (row["run_id"],)).fetchone()
                if not producer or producer[0] not in {"completed", "failed", "cancelled"}:
                    raise WorkspaceError("proposal_producer_not_completed", 409)
            version = None
            if decision == "accept":
                item = db.execute("SELECT * FROM artifacts WHERE id=?", (row["artifact_id"],)).fetchone()
                changes = json.loads(row["changes"])
                if set(ids) - {c["id"] for c in changes}:
                    raise WorkspaceError("invalid_proposal_changes")
                if len(ids) == len(changes):
                    content = row["proposed_content"]
                else:
                    value = units(item["kind"], row["base_content"])
                    for change in reversed(changes):
                        if change["id"] in ids:
                            replacement = units(item["kind"], change["new_text"]) if change["new_text"] else []
                            value[change["start_line"]:change["end_line"]] = replacement
                    content = serialize(item["kind"], value)
                try:
                    if len(content.encode()) > 256000:
                        raise ValueError("subset exceeds canonical save bound")
                    validate_artifact(item["kind"], content)
                except ValueError:
                    raise WorkspaceError("invalid_proposal_subset", 409) from None
                version = item["version"] + 1
                meta = {k: item[k] for k in ("title", "filename", "kind", "media_type")}
                db.execute("INSERT INTO versions VALUES(?,?,?,?,?,?)", (item["id"], version, content, row["run_id"], time.time(), json.dumps(meta)))
                db.execute("UPDATE artifacts SET version=? WHERE id=?", (version, item["id"]))
                if getattr(self.store, "continuity", None):
                    run = self.store._run(db, owner, row["run_id"])
                    self.store.continuity.record_publish(db, run, item["id"], version)
            status = "accepted" if decision == "accept" else "rejected"
            db.execute("UPDATE artifact_proposals SET status=?,result_version=? WHERE id=?", (status, version, pid))
            result = dict(proposal_id=pid, status=status, artifact_id=row["artifact_id"], version=version, selected_change_ids=sorted(ids))
            db.execute("INSERT INTO proposal_decisions VALUES(?,?,?,?,?)", (owner, key, row["workspace_id"], digest, json.dumps(result)))
            return result

    def handoff(self, owner, wid, selections):
        if not isinstance(selections, list) or not 1 <= len(selections) <= 10 or any(not isinstance(v, dict) or set(v) != {"artifact_id", "version", "format"} or not isinstance(v["artifact_id"], str) or type(v["version"]) is not int or v["version"] < 1 or not isinstance(v["format"], str) or v["format"] not in {"md", "docx", "pdf", "csv", "xlsx"} for v in selections):
            raise WorkspaceError("invalid_handoff_selection")
        if len({s["artifact_id"] for s in selections}) != len(selections):
            raise WorkspaceError("duplicate_handoff_artifact")
        if not _HANDOFF.acquire(blocking=False):
            raise WorkspaceError("handoff_busy", 409)
        try:
            with self.store.tx() as db:
                self.store._workspace(db, owner, wid)
                epoch = epochs(db, wid)
                items = []
                for selection in selections:
                    item = db.execute("SELECT a.id,a.workspace_id,v.version,v.content,v.run_id,v.metadata FROM artifacts a JOIN versions v ON v.artifact_id=a.id WHERE a.id=? AND a.workspace_id=? AND v.version=?", (selection["artifact_id"], wid, selection["version"])).fetchone()
                    if not item:
                        raise WorkspaceError("not_found", 404)
                    items.append(dict(item) | json.loads(item["metadata"]) | {"format": selection["format"]})
                if sum(len(i["content"].encode()) for i in items) > 2_560_000:
                    raise WorkspaceError("handoff_limit", 413)
            start, captured, payload, entries = time.monotonic(), time.time(), {}, []
            for n, item in enumerate(items, 1):
                if time.monotonic() - start > 45:
                    raise WorkspaceError("handoff_time_limit", 413)
                try:
                    output = render_artifact(item["kind"], item["content"], item["format"], item["title"])
                except Exception:
                    raise WorkspaceError("artifact_export_failed", 422) from None
                name = f"deliverable-{n:02d}-v{item['version']}.{output.extension}"
                payload[name] = output.data
                if sum(map(len, payload.values())) > 8 * 1024 * 1024:
                    raise WorkspaceError("handoff_limit", 413)
                entries.append(dict(artifact_id=item["id"], version=item["version"], title=item["title"], kind=item["kind"], format=item["format"], member=name,
                                    content_sha256=sha(item["content"]), export_sha256=hashlib.sha256(output.data).hexdigest(), bytes=len(output.data), warnings=output.warnings,
                                    capture="saved_version", origin="agent_run" if item["run_id"] else "manual_or_imported", run_id=item["run_id"]))
            manifest = dict(format="agent-workspace-handoff-v1", version=1, captured_at=captured, entries=entries,
                            omissions=["Unselected sources and outputs", "Conversations and memory", "Proposals, permissions, sessions, runtime state and credentials"], authority="Content export only; not execution or approval authority")
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, data in payload.items():
                    archive.writestr(name, data)
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            if stream.tell() > 8 * 1024 * 1024:
                raise WorkspaceError("handoff_limit", 413)
            with self.store.tx() as db:
                self.store._workspace(db, owner, wid)
                if epochs(db, wid) != epoch:
                    raise WorkspaceError("handoff_scope_changed", 409)
            return stream.getvalue()
        finally:
            _HANDOFF.release()
