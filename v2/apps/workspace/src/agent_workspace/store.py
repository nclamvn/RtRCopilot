"""SQLite catalogue, scoped authority, event journal and transactional tool receipts.

This is not a recovery executor: only the DBOS workflow may execute an agent run.
No filename is resolved as a host filesystem path. User bytes live inside SQLite.
"""
from contextlib import contextmanager
import difflib
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

TERMINAL = {"completed", "failed", "cancelled"}


class WorkspaceError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


def identity() -> str:
    return str(uuid.uuid4())


def valid_filename(value: str) -> str:
    if (not value or len(value) > 160 or value in {".", ".."}
            or any(c in value for c in "/\\\x00\r\n")
            or any(ord(c) < 32 for c in value)):
        raise WorkspaceError("invalid_filename")
    if Path(value).suffix.lower() not in {".txt", ".md", ".csv", ".pdf", ".docx", ".xlsx"}:
        raise WorkspaceError("unsupported_format")
    return value


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("catalogue_symlink_not_allowed")
        self.path = path
        with self.tx() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,owner TEXT,expires REAL);
            CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY,owner TEXT,name TEXT,created_at REAL);
            CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY,workspace_id TEXT,filename TEXT,
              media_type TEXT,content TEXT,bytes INTEGER,created_at REAL);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,workspace_id TEXT,owner TEXT,
              request_key TEXT,message TEXT,state TEXT,cancel_requested INTEGER DEFAULT 0,
              error TEXT,created_at REAL,deadline_at REAL,limits TEXT,usage TEXT,
              history TEXT,dispatch_pending INTEGER DEFAULT 1,UNIQUE(owner,request_key));
            CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,workspace_id TEXT,run_id TEXT,
              role TEXT,content TEXT,created_at REAL,UNIQUE(run_id,role));
            CREATE TABLE IF NOT EXISTS events(run_id TEXT,seq INTEGER,type TEXT,data TEXT,
              created_at REAL,PRIMARY KEY(run_id,seq));
            CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,workspace_id TEXT,title TEXT,
              filename TEXT,media_type TEXT,version INTEGER,created_at REAL);
            CREATE TABLE IF NOT EXISTS versions(artifact_id TEXT,version INTEGER,content TEXT,
              run_id TEXT,created_at REAL,PRIMARY KEY(artifact_id,version));
            CREATE TABLE IF NOT EXISTS receipts(run_id TEXT,call_id TEXT,kind TEXT,args_digest TEXT,
              result TEXT,PRIMARY KEY(run_id,call_id));
            CREATE TABLE IF NOT EXISTS revisions(owner TEXT,request_id TEXT,args_digest TEXT,
              result TEXT,PRIMARY KEY(owner,request_id));
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(runs)")}
            if "output_bytes" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN output_bytes INTEGER NOT NULL DEFAULT 0")
            if "stream_bytes" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN stream_bytes INTEGER NOT NULL DEFAULT 0")
            if "workflow_version" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN workflow_version TEXT NOT NULL DEFAULT 'workspace-aw01-v1'")
            file_columns = {r[1] for r in db.execute("PRAGMA table_info(files)")}
            for column, definition in {"raw_content": "BLOB", "sha256": "TEXT", "warnings": "TEXT NOT NULL DEFAULT '[]'", "provenance": "TEXT NOT NULL DEFAULT '{}'", "metadata": "TEXT NOT NULL DEFAULT '{}'"}.items():
                if column not in file_columns:
                    db.execute(f"ALTER TABLE files ADD COLUMN {column} {definition}")
            artifact_columns = {r[1] for r in db.execute("PRAGMA table_info(artifacts)")}
            if "kind" not in artifact_columns:
                db.execute("ALTER TABLE artifacts ADD COLUMN kind TEXT NOT NULL DEFAULT 'document'")
            version_columns = {r[1] for r in db.execute("PRAGMA table_info(versions)")}
            if "metadata" not in version_columns:
                db.execute("ALTER TABLE versions ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def session(self, token: str | None) -> tuple[str, str]:
        with self.tx() as db:
            if token:
                row = db.execute("SELECT owner FROM sessions WHERE token_hash=? AND expires>?",
                                 (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
                if row:
                    return token, row["owner"]
            token, owner = secrets.token_urlsafe(32), identity()
            db.execute("INSERT INTO sessions VALUES(?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), owner, time.time() + 30 * 86400))
            return token, owner

    def authenticate(self, token: str | None) -> str:
        with self.tx() as db:
            row = db.execute("SELECT owner FROM sessions WHERE token_hash=? AND expires>?",
                             (hashlib.sha256((token or "").encode()).hexdigest(), time.time())).fetchone()
            if not row:
                raise WorkspaceError("session_required", 401)
            return row["owner"]

    def _workspace(self, db, owner, workspace_id):
        row = db.execute("SELECT * FROM workspaces WHERE id=? AND owner=?", (workspace_id, owner)).fetchone()
        if not row:
            raise WorkspaceError("not_found", 404)
        return row

    def _run(self, db, owner, run_id):
        row = db.execute("SELECT * FROM runs WHERE id=? AND owner=?", (run_id, owner)).fetchone()
        if not row:
            raise WorkspaceError("not_found", 404)
        self._workspace(db, owner, row["workspace_id"])
        return row

    def workspaces(self, owner, name=None):
        with self.tx() as db:
            if name is not None:
                item = {"id": identity(), "name": name, "created_at": time.time()}
                db.execute("INSERT INTO workspaces VALUES(?,?,?,?)", (item["id"], owner, name, item["created_at"]))
                return item
            return [dict(r) for r in db.execute("SELECT id,name,created_at FROM workspaces WHERE owner=? ORDER BY created_at", (owner,))]

    def items(self, owner, workspace_id, table):
        columns = {"messages": "id,role,content,run_id,created_at",
                   "files": "id,filename,media_type,bytes,created_at,sha256,warnings,provenance,metadata",
                   "artifacts": "id,title,filename,version,media_type,created_at,kind"}[table]
        with self.tx() as db:
            self._workspace(db, owner, workspace_id)
            return [self._file_view(r) if table == "files" else dict(r) for r in db.execute(f"SELECT {columns} FROM {table} WHERE workspace_id=? ORDER BY created_at", (workspace_id,))]

    def upload(self, owner, workspace_id, filename, content, media_type):
        return self.upload_bytes(owner, workspace_id, filename, content.encode(), media_type)

    def _file_view(self, row):
        item = dict(row)
        item.pop("raw_content", None)
        item.pop("content", None)
        item["warnings"] = json.loads(item.get("warnings") or "[]")
        item["provenance"] = json.loads(item.get("provenance") or "{}")
        item["metadata"] = json.loads(item.get("metadata") or "{}")
        return item

    def upload_bytes(self, owner, workspace_id, filename, raw, media_type=None, provenance=None, run_id=None):
        valid_filename(filename)
        size = len(raw)
        if size > 256000:
            raise WorkspaceError("file_too_large_or_binary", 413)
        # Scope is checked before parsing to avoid processing another owner's input.
        with self.tx() as db:
            self._workspace(db, owner, workspace_id)
        from .formats import extract_upload
        try:
            extracted = extract_upload(filename, raw)
            content, warnings = extracted.text, extracted.warnings
        except Exception:
            raise WorkspaceError("source_parse_failed") from None
        if not isinstance(content, str) or "\x00" in content or len(content.encode()) > 1000000:
            raise WorkspaceError("source_parse_failed")
        media_type = {".md": "text/markdown", ".txt": "text/plain", ".csv": "text/csv", ".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}[Path(filename).suffix.lower()]
        with self.tx() as db:
            self._workspace(db, owner, workspace_id)
            if run_id and self.fence(db, owner, run_id)["workspace_id"] != workspace_id:
                raise WorkspaceError("not_found", 404)
            count, total = db.execute("SELECT COUNT(*),COALESCE(SUM(bytes),0) FROM files WHERE workspace_id=?", (workspace_id,)).fetchone()
            if count >= 20 or total + size > 1000000:
                raise WorkspaceError("workspace_file_limit", 413)
            item = dict(id=identity(), filename=filename, media_type=media_type, bytes=size, created_at=time.time(), sha256=hashlib.sha256(raw).hexdigest(), warnings=list(warnings), provenance=provenance or {}, metadata=extracted.metadata)
            db.execute("INSERT INTO files(id,workspace_id,filename,media_type,content,bytes,created_at,raw_content,sha256,warnings,provenance,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (item["id"], workspace_id, filename, media_type, content, size, item["created_at"], raw, item["sha256"], json.dumps(item["warnings"]), json.dumps(item["provenance"]), json.dumps(item["metadata"])))
            return item

    def source(self, owner, file_id, offset=0, limit=16000, *, raw=False):
        if offset < 0 or not 1 <= limit <= 32000:
            raise WorkspaceError("invalid_source_range")
        with self.tx() as db:
            row = db.execute("SELECT f.* FROM files f JOIN workspaces w ON w.id=f.workspace_id WHERE f.id=? AND w.owner=?", (file_id, owner)).fetchone()
            if not row:
                raise WorkspaceError("not_found", 404)
            item = self._file_view(row)
            if raw:
                item["raw_content"] = bytes(row["raw_content"]) if row["raw_content"] is not None else row["content"].encode()
                return item
            content = row["content"]
            chunk = content[offset:offset + limit]
            item.update(content=chunk, offset=offset, next_offset=offset + len(chunk), has_more=offset + len(chunk) < len(content), total_characters=len(content))
            return item

    def create_run(self, owner, workspace_id, message, request_key, limits):
        with self.tx() as db:
            self._workspace(db, owner, workspace_id)
            old = db.execute("SELECT * FROM runs WHERE owner=? AND request_key=?", (owner, request_key)).fetchone()
            if old:
                if old["workspace_id"] != workspace_id or old["message"] != message:
                    raise WorkspaceError("idempotency_conflict", 409)
                return self._view(old)
            if db.execute("SELECT 1 FROM runs WHERE workspace_id=? AND state NOT IN ('completed','failed','cancelled')", (workspace_id,)).fetchone():
                raise WorkspaceError("workspace_busy", 409)
            run_id, now = identity(), time.time()
            usage = {"requests": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": None, "complete": False}
            db.execute("INSERT INTO runs(id,workspace_id,owner,request_key,message,state,created_at,deadline_at,limits,usage,workflow_version) VALUES(?,?,?,?,?,'queued',?,?,?,?, 'workspace-aw02-v1')",
                       (run_id, workspace_id, owner, request_key, message, now, now + limits["deadline_seconds"], json.dumps(limits), json.dumps(usage)))
            db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", (identity(), workspace_id, run_id, "user", message, now))
            self._event(db, run_id, "run.state", {"state": "queued"})
            return self._view(self._run(db, owner, run_id))

    def _view(self, row):
        result = {k: row[k] for k in ("id", "workspace_id", "state", "error", "created_at", "deadline_at")}
        result.update(cancel_requested=bool(row["cancel_requested"]), limits=json.loads(row["limits"]), usage=json.loads(row["usage"]))
        return result

    def run(self, owner, run_id):
        with self.tx() as db:
            return self._view(self._run(db, owner, run_id))

    def _event(self, db, run_id, kind, data):
        seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
        db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (run_id, seq, kind, json.dumps(data, ensure_ascii=False), time.time()))

    def event(self, owner, run_id, kind, data):
        with self.tx() as db:
            self._run(db, owner, run_id)
            self._event(db, run_id, kind, data)

    def event_once(self, owner, run_id, key, kind, data):
        with self.tx() as db:
            run = self.fence(db, owner, run_id)
            if db.execute("SELECT 1 FROM receipts WHERE run_id=? AND call_id=?", (run_id, key)).fetchone():
                return
            if kind == "message.delta":
                size = len(data.get("text", "").encode())
                if run["stream_bytes"] + run["output_bytes"] + size > json.loads(run["limits"])["output_bytes_limit"]:
                    raise WorkspaceError("stream_output_limit", 413)
                db.execute("UPDATE runs SET stream_bytes=stream_bytes+? WHERE id=?", (size, run_id))
            elif len(json.dumps(data).encode()) > 4096:
                raise WorkspaceError("event_payload_limit", 413)
            db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)", (run_id, key, "event", "", "{}"))
            self._event(db, run_id, kind, data)

    def reserve_model_dispatch(self, owner, run_id, step_id, *, allow_replay=False):
        """Reserve physical calls before dispatch, independently of SDK logical usage.

        An uncheckpointed network outcome is uncertain, even if streaming emitted text.
        Only the explicitly scripted/no-network test lane may replay that operation.
        """
        with self.tx() as db:
            run = self.fence(db, owner, run_id)
            prefix = f"model:{step_id}:"
            existing = db.execute("SELECT COUNT(*) FROM receipts WHERE run_id=? AND kind='model.dispatch' AND call_id LIKE ?", (run_id, prefix + "%")).fetchone()[0]
            if existing and not allow_replay:
                raise WorkspaceError("uncertain_provider_dispatch", 409)
            count = db.execute("SELECT COUNT(*) FROM receipts WHERE run_id=? AND kind='model.dispatch'", (run_id,)).fetchone()[0]
            if count >= json.loads(run["limits"])["request_limit"]:
                raise WorkspaceError("physical_request_limit", 409)
            db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)", (run_id, prefix + str(existing + 1), "model.dispatch", "", "{}"))
            usage = json.loads(run["usage"])
            usage["physical_requests"] = count + 1
            db.execute("UPDATE runs SET usage=? WHERE id=?", (json.dumps(usage), run_id))

    def events(self, owner, run_id, after):
        with self.tx() as db:
            self._run(db, owner, run_id)
            return [dict(run_id=r["run_id"], seq=r["seq"], type=r["type"], data=json.loads(r["data"]), created_at=r["created_at"]) for r in db.execute("SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 500", (run_id, after))]

    def fence(self, db, owner, run_id):
        row = self._run(db, owner, run_id)
        if row["cancel_requested"] or row["state"] == "cancelled":
            raise WorkspaceError("cancelled", 409)
        if row["state"] in TERMINAL:
            raise WorkspaceError("run_terminal", 409)
        if row["deadline_at"] <= time.time():
            raise WorkspaceError("deadline_exceeded", 409)
        return row

    def check(self, owner, run_id):
        with self.tx() as db:
            return dict(self.fence(db, owner, run_id))

    def pending(self):
        with self.tx() as db:
            return [dict(r) for r in db.execute("SELECT id,owner FROM runs WHERE dispatch_pending=1 AND state NOT IN ('completed','failed','cancelled')")]

    def dispatched(self, owner, run_id):
        with self.tx() as db:
            self._run(db, owner, run_id)
            db.execute("UPDATE runs SET dispatch_pending=0 WHERE id=?", (run_id,))

    def running(self, owner, run_id):
        with self.tx() as db:
            row = self.fence(db, owner, run_id)
            db.execute("UPDATE runs SET state='running' WHERE id=?", (run_id,))
            self._event(db, run_id, "run.state", {"state": "running"})
            return dict(row)

    def cancel(self, owner, run_id):
        with self.tx() as db:
            row = self._run(db, owner, run_id)
            if row["state"] not in TERMINAL:
                db.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))
                self._event(db, run_id, "run.state", {"state": "cancel_requested"})
        return self.run(owner, run_id)

    def finish(self, owner, run_id, state, *, content=None, error=None, history=None, usage=None):
        with self.tx() as db:
            row = self._run(db, owner, run_id)
            if row["state"] in TERMINAL:
                return
            if row["cancel_requested"]:
                state, content, error = "cancelled", None, None
            if state == "completed" and row["deadline_at"] <= time.time():
                state, content, error = "failed", None, "deadline_exceeded"
            if content is not None and len(content.encode()) + row["output_bytes"] > json.loads(row["limits"])["output_bytes_limit"]:
                state, content, error = "failed", None, "run_output_limit"
            if content is not None:
                db.execute("INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?)", (identity(), row["workspace_id"], run_id, "assistant", content, time.time()))
                self._event(db, run_id, "message.final", {"content": content})
            if usage:
                usage = {**json.loads(row["usage"]), **usage}
                self._event(db, run_id, "usage", usage)
            db.execute("UPDATE runs SET state=?,error=?,history=COALESCE(?,history),usage=COALESCE(?,usage),dispatch_pending=0 WHERE id=?", (state, error, history, json.dumps(usage) if usage else None, run_id))
            if error:
                self._event(db, run_id, "run.error", {"code": error})
            self._event(db, run_id, "run.state", {"state": state})

    def context(self, owner, run_id):
        with self.tx() as db:
            row = self._run(db, owner, run_id)
            history = db.execute("SELECT history FROM runs WHERE workspace_id=? AND state='completed' AND history IS NOT NULL ORDER BY created_at DESC LIMIT 1", (row["workspace_id"],)).fetchone()
            files = [dict(r) for r in db.execute("SELECT id,filename,bytes FROM files WHERE workspace_id=?", (row["workspace_id"],))]
            artifacts = [dict(r) for r in db.execute("SELECT id,title,filename,version FROM artifacts WHERE workspace_id=?", (row["workspace_id"],))]
            return (history[0] if history else None), files, artifacts

    def read_file(self, owner, run_id, file_id, offset=0, limit=16000):
        with self.tx() as db:
            run = self.fence(db, owner, run_id)
            row = db.execute("SELECT id FROM files WHERE id=? AND workspace_id=?", (file_id, run["workspace_id"])).fetchone()
            if not row:
                raise WorkspaceError("not_found", 404)
        return self.source(owner, file_id, offset, limit)

    def artifact(self, owner, artifact_id, version=None):
        if version is not None and version < 1:
            raise WorkspaceError("invalid_version")
        with self.tx() as db:
            row = db.execute("SELECT a.* FROM artifacts a JOIN workspaces w ON w.id=a.workspace_id WHERE a.id=? AND w.owner=?", (artifact_id, owner)).fetchone()
            if not row:
                raise WorkspaceError("not_found", 404)
            item = dict(row)
            item["version"] = version if version is not None else row["version"]
            old = db.execute("SELECT content,metadata FROM versions WHERE artifact_id=? AND version=?", (artifact_id, item["version"])).fetchone()
            if not old:
                raise WorkspaceError("not_found", 404)
            item.update(json.loads(old["metadata"]))
            item.update(content=old[0], status="draft")
            return item

    def read_artifact(self, owner, run_id, artifact_id):
        with self.tx() as db:
            run = self.fence(db, owner, run_id)
            target = db.execute("SELECT workspace_id FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
            if not target or target[0] != run["workspace_id"]:
                raise WorkspaceError("not_found", 404)
        return self.artifact(owner, artifact_id)

    def publish(self, owner, run_id, call_id, title, filename, content, artifact_id=None, expected_version=None, *, receipt_args=None):
        valid_filename(filename)
        if not title.strip() or len(title) > 160:
            raise WorkspaceError("invalid_artifact_title")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".md", ".csv"} or not content.strip() or "\x00" in content:
            raise WorkspaceError("invalid_markdown_draft")
        if suffix == ".csv":
            from .formats import validate_artifact
            try:
                validate_artifact("table", content)
            except Exception:
                raise WorkspaceError("invalid_table_draft") from None
        kind, media_type = ("table", "text/csv") if suffix == ".csv" else ("document", "text/markdown")
        args = dict(title=title, filename=filename, content=content, artifact_id=artifact_id, expected_version=expected_version)
        digest = hashlib.sha256(json.dumps(receipt_args or args, sort_keys=True).encode()).hexdigest()
        with self.tx() as db:
            run = self.fence(db, owner, run_id)
            receipt = db.execute("SELECT * FROM receipts WHERE run_id=? AND call_id=?", (run_id, call_id)).fetchone()
            if receipt:
                if receipt["args_digest"] != digest:
                    raise WorkspaceError("receipt_argument_conflict", 409)
                return json.loads(receipt["result"])
            if len(content.encode()) + run["output_bytes"] + run["stream_bytes"] > json.loads(run["limits"])["output_bytes_limit"]:
                raise WorkspaceError("artifact_output_limit", 413)
            now = time.time()
            if artifact_id:
                old = db.execute("SELECT * FROM artifacts WHERE id=? AND workspace_id=?", (artifact_id, run["workspace_id"])).fetchone()
                if not old:
                    raise WorkspaceError("not_found", 404)
                if expected_version != old["version"]:
                    raise WorkspaceError("stale_artifact_version", 409)
                if kind != old["kind"]:
                    raise WorkspaceError("artifact_kind_conflict", 409)
                version = old["version"] + 1
                db.execute("UPDATE artifacts SET title=?,filename=?,version=? WHERE id=?", (title, filename, version, artifact_id))
            else:
                artifact_id, version = identity(), 1
                db.execute("INSERT INTO artifacts(id,workspace_id,title,filename,media_type,version,created_at,kind) VALUES(?,?,?,?,?,?,?,?)", (artifact_id, run["workspace_id"], title, filename, media_type, version, now, kind))
            db.execute("INSERT INTO versions(artifact_id,version,content,run_id,created_at,metadata) VALUES(?,?,?,?,?,?)", (artifact_id, version, content, run_id, now, json.dumps(dict(title=title, filename=filename, kind=kind, media_type=media_type))))
            db.execute("UPDATE runs SET output_bytes=output_bytes+? WHERE id=?", (len(content.encode()), run_id))
            result = {"artifact_id": artifact_id, "version": version, "status": "draft"}
            db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)", (run_id, call_id, "artifact.publish", digest, json.dumps(result)))
            self._event(db, run_id, "artifact.published", result)
            return result

    def patch(self, owner, run_id, call_id, artifact_id, expected_version, old_text, new_text):
        args = dict(artifact_id=artifact_id, expected_version=expected_version, old_text=old_text, new_text=new_text)
        digest = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()
        with self.tx() as db:
            self.fence(db, owner, run_id)
            receipt = db.execute("SELECT * FROM receipts WHERE run_id=? AND call_id=?", (run_id, call_id)).fetchone()
            if receipt:
                if receipt["args_digest"] != digest:
                    raise WorkspaceError("receipt_argument_conflict", 409)
                return json.loads(receipt["result"])
        item = self.read_artifact(owner, run_id, artifact_id)
        if item["version"] != expected_version:
            raise WorkspaceError("stale_artifact_version", 409)
        if not old_text or item["content"].count(old_text) != 1:
            raise WorkspaceError("patch_region_not_unique", 409)
        content = item["content"].replace(old_text, new_text, 1)
        return self.publish(owner, run_id, call_id, item["title"], item["filename"], content, artifact_id, expected_version, receipt_args=args)

    def revise(self, owner, artifact_id, expected_version, content, request_id):
        if not content.strip() or "\x00" in content or len(content.encode()) > 256000:
            raise WorkspaceError("invalid_artifact_content", 413)
        digest = hashlib.sha256(json.dumps(dict(artifact_id=artifact_id, expected_version=expected_version, content=content), sort_keys=True).encode()).hexdigest()
        # Parse outside the transaction, then reauthorize/fence inside the mutation.
        item = self.artifact(owner, artifact_id)
        from .formats import validate_artifact
        try:
            validate_artifact(item["kind"], content)
        except Exception:
            raise WorkspaceError("invalid_artifact_content") from None
        with self.tx() as db:
            self._workspace(db, owner, item["workspace_id"])
            old_receipt = db.execute("SELECT * FROM revisions WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
            if old_receipt:
                if old_receipt["args_digest"] != digest:
                    raise WorkspaceError("idempotency_conflict", 409)
                result = json.loads(old_receipt["result"])
            else:
                if db.execute("SELECT 1 FROM runs WHERE workspace_id=? AND state NOT IN ('completed','failed','cancelled')", (item["workspace_id"],)).fetchone():
                    raise WorkspaceError("workspace_busy", 409)
                current = db.execute("SELECT version FROM artifacts WHERE id=?", (artifact_id,)).fetchone()[0]
                if current != expected_version:
                    raise WorkspaceError("stale_artifact_version", 409)
                version = current + 1
                db.execute("INSERT INTO versions(artifact_id,version,content,run_id,created_at,metadata) VALUES(?,?,?,?,?,?)", (artifact_id, version, content, None, time.time(), json.dumps({k: item[k] for k in ("title", "filename", "kind", "media_type")})))
                db.execute("UPDATE artifacts SET version=? WHERE id=?", (version, artifact_id))
                result = dict(artifact_id=artifact_id, version=version)
                db.execute("INSERT INTO revisions VALUES(?,?,?,?)", (owner, request_id, digest, json.dumps(result)))
        return self.artifact(owner, artifact_id, result["version"])

    def create_artifact(self, owner, workspace_id, title, kind, content, request_id):
        if kind not in {"document", "table"} or not title.strip() or len(title) > 160:
            raise WorkspaceError("invalid_artifact")
        if not content.strip() or "\x00" in content or len(content.encode()) > 256000:
            raise WorkspaceError("invalid_artifact_content", 413)
        # Scope check precedes parsing; mutation repeats authority under its lock.
        with self.tx() as db:
            self._workspace(db, owner, workspace_id)
        from .formats import validate_artifact
        try:
            validate_artifact(kind, content)
        except Exception:
            raise WorkspaceError("invalid_artifact_content") from None
        args = dict(workspace_id=workspace_id, title=title, kind=kind, content=content)
        digest = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()
        with self.tx() as db:
            self._workspace(db, owner, workspace_id)
            receipt = db.execute("SELECT * FROM revisions WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
            if receipt:
                if receipt["args_digest"] != digest:
                    raise WorkspaceError("idempotency_conflict", 409)
                artifact_id = json.loads(receipt["result"])["artifact_id"]
            else:
                if db.execute("SELECT 1 FROM runs WHERE workspace_id=? AND state NOT IN ('completed','failed','cancelled')", (workspace_id,)).fetchone():
                    raise WorkspaceError("workspace_busy", 409)
                if db.execute("SELECT COUNT(*) FROM artifacts WHERE workspace_id=?", (workspace_id,)).fetchone()[0] >= 100:
                    raise WorkspaceError("workspace_artifact_limit", 413)
                artifact_id, now = identity(), time.time()
                filename, media_type = ("table.csv", "text/csv") if kind == "table" else ("draft.md", "text/markdown")
                metadata = dict(title=title, filename=filename, kind=kind, media_type=media_type)
                db.execute("INSERT INTO artifacts(id,workspace_id,title,filename,media_type,version,created_at,kind) VALUES(?,?,?,?,?,1,?,?)", (artifact_id, workspace_id, title, filename, media_type, now, kind))
                db.execute("INSERT INTO versions(artifact_id,version,content,run_id,created_at,metadata) VALUES(?,1,?,NULL,?,?)", (artifact_id, content, now, json.dumps(metadata)))
                db.execute("INSERT INTO revisions VALUES(?,?,?,?)", (owner, request_id, digest, json.dumps(dict(artifact_id=artifact_id, version=1))))
        return self.artifact(owner, artifact_id, 1)

    def versions(self, owner, artifact_id):
        self.artifact(owner, artifact_id)
        with self.tx() as db:
            return [dict(r) for r in db.execute("SELECT version,created_at,run_id,length(content) AS characters FROM versions WHERE artifact_id=? ORDER BY version", (artifact_id,))]

    def diff(self, owner, artifact_id, from_version, to_version):
        if from_version < 1 or to_version < 1:
            raise WorkspaceError("invalid_version")
        before = self.artifact(owner, artifact_id, from_version)
        after = self.artifact(owner, artifact_id, to_version)
        # Bounded diff work, no quadratic unbounded matching on a hostile draft.
        if (len(before["content"].encode()) + len(after["content"].encode()) > 256000
                or len(before["content"].splitlines()) + len(after["content"].splitlines()) > 4000):
            raise WorkspaceError("diff_size_limit", 413)
        diff = "".join(difflib.unified_diff(before["content"].splitlines(keepends=True), after["content"].splitlines(keepends=True), fromfile=f"version-{from_version}", tofile=f"version-{to_version}"))
        if len(diff.encode()) > 256000:
            raise WorkspaceError("diff_size_limit", 413)
        return dict(from_version=from_version, to_version=to_version, diff=diff)

    def fail_incompatible_runs(self, version):
        with self.tx() as db:
            rows = [dict(r) for r in db.execute("SELECT id,owner FROM runs WHERE workflow_version<>? AND state NOT IN ('completed','failed','cancelled')", (version,))]
        for row in rows:
            self.finish(row["owner"], row["id"], "failed", error="workflow_version_incompatible")
