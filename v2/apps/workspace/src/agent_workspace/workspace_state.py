"""Explicit user memory and manual-clock schedule records, not another executor.

The owning Store provides all scope checks and the atomic run-creation primitive.
No timer, provider, connector, host-clock mutation or background worker lives here.
"""
import hashlib
import json
import math
import re
import time

from .store import WorkspaceError, identity


MAX_CLOCK = 31_536_000
MAX_MEMORY = 100
MAX_MEMORY_BYTES = 64_000
MAX_SCHEDULES = 100
MAX_REQUESTS = 2000


def request_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,160}", value):
        raise WorkspaceError("invalid_request_id")
    return value


def bounded_text(value, maximum, code):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise WorkspaceError(code)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise WorkspaceError(code) from None
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise WorkspaceError(code)
    return value


def clock_value(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= MAX_CLOCK:
        raise WorkspaceError("invalid_manual_clock")
    return float(value)


class WorkspaceState:
    def __init__(self, store):
        self.store = store
        self.initialize()
        store.memory_guard = self.assert_memory_current

    def initialize(self):
        """Called only in app startup, never on import or app construction."""
        with self.store.tx() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS workspace_memory_meta(
              workspace_id TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS workspace_memory(
              id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,content TEXT,
              version INTEGER NOT NULL,deleted INTEGER NOT NULL DEFAULT 0,
              created_at REAL NOT NULL,updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS workspace_memory_reads(
              run_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS workspace_clocks(
              workspace_id TEXT PRIMARY KEY,value REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS workspace_schedules(
              id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,message TEXT NOT NULL,
              due_at REAL NOT NULL,state TEXT NOT NULL,version INTEGER NOT NULL,
              run_id TEXT,error TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS workspace_state_requests(
              owner TEXT NOT NULL,request_id TEXT NOT NULL,args_digest TEXT NOT NULL,
              result TEXT NOT NULL,workspace_id TEXT NOT NULL,
              PRIMARY KEY(owner,request_id));
            """)

    def _scope(self, db, owner, workspace_id):
        self.store._workspace(db, owner, workspace_id)

    def _revision(self, db, workspace_id):
        db.execute("INSERT OR IGNORE INTO workspace_memory_meta VALUES(?,0)", (workspace_id,))
        return db.execute("SELECT revision FROM workspace_memory_meta WHERE workspace_id=?", (workspace_id,)).fetchone()[0]

    def _clock(self, db, workspace_id):
        db.execute("INSERT OR IGNORE INTO workspace_clocks VALUES(?,0)", (workspace_id,))
        return db.execute("SELECT value FROM workspace_clocks WHERE workspace_id=?", (workspace_id,)).fetchone()[0]

    def _request(self, db, owner, workspace_id, key, operation, args):
        request_key(key)
        digest = hashlib.sha256(json.dumps([workspace_id, operation, args], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        old = db.execute("SELECT args_digest,result FROM workspace_state_requests WHERE owner=? AND request_id=?", (owner, key)).fetchone()
        if old:
            if old["args_digest"] != digest:
                raise WorkspaceError("idempotency_conflict", 409)
            return digest, json.loads(old["result"])
        # Exhausting a work quota must not prevent forgetting memory or cancelling
        # an unclaimed schedule. These terminal operations remain bounded by the
        # existing 100-entry/100-schedule catalogue, not an unbounded exemption.
        terminal_cleanup = operation == "memory.delete" or (operation == "schedule.action" and args[1] == "cancel")
        if not terminal_cleanup and db.execute("SELECT COUNT(*) FROM workspace_state_requests WHERE workspace_id=?", (workspace_id,)).fetchone()[0] >= MAX_REQUESTS:
            raise WorkspaceError("workspace_state_request_limit", 409)
        return digest, None

    def _receipt(self, db, owner, workspace_id, key, digest, result):
        db.execute("INSERT INTO workspace_state_requests VALUES(?,?,?,?,?)", (owner, key, digest, json.dumps(result, ensure_ascii=False), workspace_id))
        return result

    @staticmethod
    def _memory(row):
        return {key: row[key] for key in ("id", "content", "version", "created_at", "updated_at")} | {"source": "user"}

    def memories(self, owner, workspace_id):
        with self.store.tx() as db:
            self._scope(db, owner, workspace_id)
            revision = self._revision(db, workspace_id)
            rows = db.execute("SELECT * FROM workspace_memory WHERE workspace_id=? AND deleted=0 ORDER BY created_at,id", (workspace_id,))
            return {"items": [self._memory(row) for row in rows], "revision": revision}

    def _changed(self, db, owner, workspace_id):
        revision = self._revision(db, workspace_id) + 1
        db.execute("UPDATE workspace_memory_meta SET revision=? WHERE workspace_id=?", (revision, workspace_id))
        # Model histories are reusable execution inputs, unlike the user's visible
        # messages/artifacts. Remove old reusable histories after ANY memory change.
        db.execute("UPDATE runs SET history=NULL WHERE workspace_id=?", (workspace_id,))
        from .reviews import forget
        forget(db, workspace_id)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "run_contexts" in tables:
            db.execute("DELETE FROM run_contexts WHERE workspace_id=?", (workspace_id,))
        if "context_reads" in tables:
            db.execute("DELETE FROM context_reads WHERE workspace_id=?", (workspace_id,))
        consumers = db.execute("SELECT r.id FROM runs r JOIN workspace_memory_reads m ON m.run_id=r.id WHERE r.workspace_id=? AND m.revision<>? AND r.state NOT IN ('completed','failed','cancelled','interrupted')", (workspace_id, revision)).fetchall()
        for row in consumers:
            db.execute("UPDATE runs SET cancel_requested=1,error='memory_scope_changed' WHERE id=?", (row["id"],))
            self.store._event(db, row["id"], "run.error", {"code": "memory_scope_changed"})
            self.store._event(db, row["id"], "run.state", {"state": "cancel_requested"})
        return revision

    def save_memory(self, owner, workspace_id, content, key, memory_id=None, expected_version=None):
        content = bounded_text(content, 4000, "invalid_memory_content")
        with self.store.tx() as db:
            self._scope(db, owner, workspace_id)
            digest, receipt = self._request(db, owner, workspace_id, key, "memory.save", [content, memory_id, expected_version])
            if receipt is not None:
                # A replay after deletion must not restore deleted body to a caller.
                current = db.execute("SELECT * FROM workspace_memory WHERE id=? AND workspace_id=? AND deleted=0", (receipt["id"], workspace_id)).fetchone()
                if not current:
                    raise WorkspaceError("memory_deleted", 409)
                if current["version"] != receipt["version"]:
                    raise WorkspaceError("stale_memory_version", 409)
                return self._memory(current)
            now = time.time()
            if memory_id is not None:
                old = db.execute("SELECT * FROM workspace_memory WHERE id=? AND workspace_id=? AND deleted=0", (memory_id, workspace_id)).fetchone()
                if not old:
                    raise WorkspaceError("not_found", 404)
                if expected_version != old["version"]:
                    raise WorkspaceError("stale_memory_version", 409)
                version = old["version"] + 1
            else:
                if expected_version is not None:
                    raise WorkspaceError("invalid_memory_version")
                if db.execute("SELECT COUNT(*) FROM workspace_memory WHERE workspace_id=? AND deleted=0", (workspace_id,)).fetchone()[0] >= MAX_MEMORY:
                    raise WorkspaceError("memory_limit", 409)
                memory_id, version = identity(), 1
                old = None
            total = sum(len(row[0].encode()) for row in db.execute("SELECT content FROM workspace_memory WHERE workspace_id=? AND deleted=0 AND id<>?", (workspace_id, memory_id)))
            if total + len(content.encode()) > MAX_MEMORY_BYTES:
                raise WorkspaceError("memory_limit", 413)
            if old:
                db.execute("UPDATE workspace_memory SET content=?,version=?,updated_at=? WHERE id=?", (content, version, now, memory_id))
            else:
                db.execute("INSERT INTO workspace_memory VALUES(?,?,?,?,0,?,?)", (memory_id, workspace_id, content, version, now, now))
            self._changed(db, owner, workspace_id)
            row = db.execute("SELECT * FROM workspace_memory WHERE id=?", (memory_id,)).fetchone()
            result = self._memory(row)
            # Receipt deliberately contains no memory body; mutation payload is
            # digested, not retained in a generic idempotency log.
            self._receipt(db, owner, workspace_id, key, digest, {"id": memory_id, "version": version})
            return result

    def delete_memory(self, owner, workspace_id, memory_id, expected_version, key):
        with self.store.tx() as db:
            self._scope(db, owner, workspace_id)
            digest, receipt = self._request(db, owner, workspace_id, key, "memory.delete", [memory_id, expected_version])
            if receipt is not None:
                return receipt
            old = db.execute("SELECT * FROM workspace_memory WHERE id=? AND workspace_id=? AND deleted=0", (memory_id, workspace_id)).fetchone()
            if not old:
                raise WorkspaceError("not_found", 404)
            if old["version"] != expected_version:
                raise WorkspaceError("stale_memory_version", 409)
            db.execute("UPDATE workspace_memory SET content=NULL,deleted=1,version=version+1,updated_at=? WHERE id=?", (time.time(), memory_id))
            revision = self._changed(db, owner, workspace_id)
            return self._receipt(db, owner, workspace_id, key, digest, {"id": memory_id, "deleted": True, "revision": revision})

    def read_memories(self, owner, run_id):
        """Read current entries, not a durable step result. Never cache this body."""
        with self.store.tx() as db:
            run = self.store.fence(db, owner, run_id)
            revision = self._revision(db, run["workspace_id"])
            db.execute("INSERT OR IGNORE INTO workspace_memory_reads VALUES(?,?,?)", (run_id, run["workspace_id"], revision))
            self.assert_memory_current(db, owner, run_id)
            rows = db.execute("SELECT * FROM workspace_memory WHERE workspace_id=? AND deleted=0 ORDER BY created_at,id", (run["workspace_id"],))
            return {"items": [self._memory(row) for row in rows], "revision": revision}

    def bind_run_epoch(self, owner, run_id):
        """Register live before any replayed history/context is given to a model.

        Return metadata only: no memory body enters this binding or its receipts.
        INSERT OR IGNORE intentionally never refreshes an old run's generation.
        """
        with self.store.tx() as db:
            run = self.store.fence(db, owner, run_id)
            revision = self._revision(db, run["workspace_id"])
            db.execute("INSERT OR IGNORE INTO workspace_memory_reads VALUES(?,?,?)", (run_id, run["workspace_id"], revision))
            self.assert_memory_current(db, owner, run_id)
            return {"revision": revision}

    def assert_memory_current(self, db, owner, run_id):
        row = db.execute("SELECT m.revision AS consumed,COALESCE(s.revision,0) AS current FROM workspace_memory_reads m LEFT JOIN workspace_memory_meta s ON s.workspace_id=m.workspace_id JOIN runs r ON r.id=m.run_id WHERE m.run_id=? AND r.owner=?", (run_id, owner)).fetchone()
        if row and row["consumed"] != row["current"]:
            raise WorkspaceError("memory_scope_changed", 409)

    @staticmethod
    def _schedule(row):
        return {key: row[key] for key in ("id", "message", "due_at", "state", "version", "run_id", "error", "created_at", "updated_at")}

    def _schedules(self, db, workspace_id):
        return [self._schedule(row) for row in db.execute("SELECT * FROM workspace_schedules WHERE workspace_id=? ORDER BY due_at,created_at,id", (workspace_id,))]

    def schedules(self, owner, workspace_id):
        with self.store.tx() as db:
            self._scope(db, owner, workspace_id)
            return {"clock": self._clock(db, workspace_id), "items": self._schedules(db, workspace_id)}

    def create_schedule(self, owner, workspace_id, message, due_at, key):
        message = bounded_text(message, 16000, "invalid_schedule_message")
        due_at = clock_value(due_at)
        with self.store.tx() as db:
            self._scope(db, owner, workspace_id)
            digest, receipt = self._request(db, owner, workspace_id, key, "schedule.create", [message, due_at])
            if receipt is not None:
                row = db.execute("SELECT * FROM workspace_schedules WHERE id=? AND workspace_id=?", (receipt["id"], workspace_id)).fetchone()
                return self._schedule(row)
            if due_at < self._clock(db, workspace_id):
                raise WorkspaceError("schedule_in_past", 409)
            if db.execute("SELECT COUNT(*) FROM workspace_schedules WHERE workspace_id=?", (workspace_id,)).fetchone()[0] >= MAX_SCHEDULES:
                raise WorkspaceError("schedule_limit", 409)
            sid, now = identity(), time.time()
            db.execute("INSERT INTO workspace_schedules VALUES(?,?,?,?,'pending',1,NULL,NULL,?,?)", (sid, workspace_id, message, due_at, now, now))
            self._receipt(db, owner, workspace_id, key, digest, {"id": sid})
            return self._schedule(db.execute("SELECT * FROM workspace_schedules WHERE id=?", (sid,)).fetchone())

    def change_schedule(self, owner, workspace_id, schedule_id, action, expected_version, key):
        if action not in {"pause", "resume", "cancel"}:
            raise WorkspaceError("invalid_schedule_action")
        with self.store.tx() as db:
            self._scope(db, owner, workspace_id)
            digest, receipt = self._request(db, owner, workspace_id, key, "schedule.action", [schedule_id, action, expected_version])
            row = db.execute("SELECT * FROM workspace_schedules WHERE id=? AND workspace_id=?", (schedule_id, workspace_id)).fetchone()
            if not row:
                raise WorkspaceError("not_found", 404)
            if receipt is not None:
                return self._schedule(row)
            if expected_version != row["version"]:
                raise WorkspaceError("stale_schedule_version", 409)
            target = {"pause": "paused", "resume": "pending", "cancel": "cancelled"}[action]
            if row["state"] in {"dispatched", "cancelled"}:
                raise WorkspaceError("schedule_terminal", 409)
            if (action == "pause" and row["state"] != "pending") or (action == "resume" and row["state"] != "paused"):
                raise WorkspaceError("invalid_schedule_transition", 409)
            db.execute("UPDATE workspace_schedules SET state=?,version=version+1,error=NULL,updated_at=? WHERE id=?", (target, time.time(), schedule_id))
            result = self._schedule(db.execute("SELECT * FROM workspace_schedules WHERE id=?", (schedule_id,)).fetchone())
            self._receipt(db, owner, workspace_id, key, digest, {"id": schedule_id, "version": result["version"]})
            return result

    def tick(self, owner, workspace_id, target, key, limits):
        """Advance simulation time and create logical runs atomically, no dispatch."""
        target = clock_value(target)
        with self.store.tx() as db:
            self._scope(db, owner, workspace_id)
            digest, receipt = self._request(db, owner, workspace_id, key, "clock.tick", [target])
            if receipt is not None:
                items = self._schedules(db, workspace_id)
                return {"clock": receipt["clock"], "dispatched": [item for item in items if item["id"] in receipt["dispatched_ids"]], "blocked": receipt["blocked"], "items": items}
            current = self._clock(db, workspace_id)
            if target < current:
                raise WorkspaceError("manual_clock_cannot_reverse", 409)
            db.execute("UPDATE workspace_clocks SET value=? WHERE workspace_id=?", (target, workspace_id))
            dispatched, blocked = [], []
            rows = db.execute("SELECT * FROM workspace_schedules WHERE workspace_id=? AND state='pending' AND due_at<=? ORDER BY due_at,created_at,id", (workspace_id, target)).fetchall()
            for row in rows:
                try:
                    run = self.store._create_run(db, owner, workspace_id, row["message"], "schedule-" + row["id"], limits)
                except WorkspaceError as exc:
                    if exc.code != "workspace_busy":
                        raise
                    db.execute("UPDATE workspace_schedules SET error='workspace_busy',updated_at=? WHERE id=?", (time.time(), row["id"]))
                    blocked.append({"id": row["id"], "error": "workspace_busy"})
                    continue
                db.execute("UPDATE workspace_schedules SET state='dispatched',version=version+1,run_id=?,error=NULL,updated_at=? WHERE id=?", (run["id"], time.time(), row["id"]))
                dispatched.append(self._schedule(db.execute("SELECT * FROM workspace_schedules WHERE id=?", (row["id"],)).fetchone()))
            result = {"clock": target, "dispatched": dispatched, "blocked": blocked, "items": self._schedules(db, workspace_id)}
            self._receipt(db, owner, workspace_id, key, digest, {"clock": target, "dispatched_ids": [item["id"] for item in dispatched], "blocked": blocked})
            return result
