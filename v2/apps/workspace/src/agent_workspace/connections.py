"""Fixed MCP adapter, scoped grants and durable effect/approval catalogue.

The MCP host is synthetic and localhost-only; not a generic connector launcher.
Authority is in this server, never in descriptor text or model arguments.
"""
import asyncio
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys
import time

from .store import WorkspaceError, identity


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class FixtureTransport:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.io_slots = asyncio.Semaphore(2)

    async def call(self, tool, scope, **arguments):
        async with self.io_slots:
            return await self._call(tool, scope, **arguments)

    async def _call(self, tool, scope, **arguments):
        from mcp import ClientSession
        from mcp.client.stdio import DEFAULT_INHERITED_ENV_VARS, StdioServerParameters, stdio_client
        # SDK merges get_default_environment() before server.env. Override EVERY
        # inherited key, including HOME and SHELL, not only API key variable names.
        env = {key: "" for key in DEFAULT_INHERITED_ENV_VARS}
        env.update(PATH="/usr/bin:/bin", PYTHONNOUSERSITE="1", PYTHONUTF8="1")
        server = Path(__file__).with_name("mcp_fixture_server.py")
        params = StdioServerParameters(command=sys.executable, args=["-I", str(server), "--database", str(self.data_dir / "fixture-outbox.sqlite")], env=env, cwd=str(self.data_dir))
        try:
            async with asyncio.timeout(8):
                async with stdio_client(params) as streams:
                    async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=6)) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        # Schemas are a pinned contract, not untrusted tool permission hints.
                        from .mcp_fixture_server import SCHEMAS
                        actual = {t.name: t.inputSchema for t in listed.tools}
                        if actual != SCHEMAS or tool not in SCHEMAS:
                            raise WorkspaceError("mcp_schema_changed", 409)
                        result = await session.call_tool(tool, {"scope": scope, **arguments})
                        if result.isError or len(result.content) != 1 or result.content[0].type != "text":
                            raise WorkspaceError("mcp_fixture_failed", 502)
                        raw = result.content[0].text
                        if len(raw.encode()) > 12000:
                            raise WorkspaceError("mcp_result_limit", 413)
                        value = json.loads(raw)
                        if not isinstance(value, dict) or value.get("fixture") is not True:
                            raise WorkspaceError("mcp_invalid_result", 502)
                        return value
        except WorkspaceError:
            raise
        except Exception:
            # Protocol exceptions can contain tool text/process data; never relay raw.
            raise WorkspaceError("mcp_fixture_unavailable", 502) from None


class Connections:
    def __init__(self, store, data_dir, enabled):
        self.store, self.enabled = store, enabled
        store.connection_guard = self.assert_current
        self.transport = FixtureTransport(data_dir)
        with store.tx() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS connection_grants(workspace_id TEXT PRIMARY KEY,enabled INTEGER,revision INTEGER);
            CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,owner TEXT,workspace_id TEXT,run_id TEXT,call_id TEXT,args TEXT,args_digest TEXT,policy_revision INTEGER,status TEXT,expires_at REAL,created_at REAL,UNIQUE(run_id,call_id));
            CREATE TABLE IF NOT EXISTS effects(id TEXT PRIMARY KEY,approval_id TEXT UNIQUE,owner TEXT,workspace_id TEXT,run_id TEXT,status TEXT,receipt TEXT,error TEXT,created_at REAL);
            CREATE TABLE IF NOT EXISTS connection_requests(owner TEXT,key TEXT,args_digest TEXT,result TEXT,PRIMARY KEY(owner,key));
            CREATE TABLE IF NOT EXISTS connection_reads(run_id TEXT PRIMARY KEY,workspace_id TEXT,revision INTEGER);
            """)

    def bind_run(self, owner, run_id):
        with self.store.tx() as db:
            run = self.store.fence(db, owner, run_id)
            grant = self._grant(db, owner, run["workspace_id"])
            db.execute("INSERT OR IGNORE INTO connection_reads VALUES(?,?,?)", (run_id, run["workspace_id"], grant["revision"]))
            self.assert_current(db, owner, run_id)

    def assert_current(self, db, owner, run_id):
        row = db.execute("SELECT c.revision AS consumed,COALESCE(g.revision,0) AS current FROM connection_reads c JOIN runs r ON r.id=c.run_id LEFT JOIN connection_grants g ON g.workspace_id=c.workspace_id WHERE c.run_id=? AND r.owner=?", (run_id, owner)).fetchone()
        if row and row["consumed"] != row["current"]:
            raise WorkspaceError("connection_scope_changed", 409)

    def _grant(self, db, owner, wid, *, required=False):
        self.store._workspace(db, owner, wid)
        row = db.execute("SELECT * FROM connection_grants WHERE workspace_id=?", (wid,)).fetchone()
        value = dict(row) if row else dict(workspace_id=wid, enabled=0, revision=0)
        if required and (not self.enabled or not value["enabled"]):
            raise WorkspaceError("connection_not_authorized", 403)
        return value

    def connection(self, owner, wid):
        with self.store.tx() as db:
            row = self._grant(db, owner, wid)
            return dict(fixture=True, enabled=bool(row["enabled"] and self.enabled), revision=row["revision"], external=False,
                        available=self.enabled, tools=[dict(name="read_status", effect=False), dict(name="send_note", effect=True)])

    def _once(self, db, owner, key, args, operation, *, safety=False):
        hashed = digest(args)
        prior = db.execute("SELECT * FROM connection_requests WHERE owner=? AND key=?", (owner, key)).fetchone()
        if prior:
            if prior["args_digest"] != hashed:
                raise WorkspaceError("idempotency_conflict", 409)
            return json.loads(prior["result"])
        if db.execute("SELECT COUNT(*) FROM connection_requests WHERE owner=?", (owner,)).fetchone()[0] >= 2000:
            if safety:
                # Revocation must remain possible when the ordinary command
                # ledger is full. Do not grow that ledger for this escape path.
                return operation()
            raise WorkspaceError("connection_request_limit", 409)
        result = operation()
        db.execute("INSERT INTO connection_requests VALUES(?,?,?,?)", (owner, key, hashed, json.dumps(result)))
        return result

    def set_connection(self, owner, wid, enabled, expected_revision, request_id):
        if not self.enabled:
            raise WorkspaceError("fixture_connection_disabled", 403)
        with self.store.tx() as db:
            self._grant(db, owner, wid)
            def change():
                old = self._grant(db, owner, wid)
                if not enabled and not old["enabled"]:
                    return dict(fixture=True, enabled=False, revision=old["revision"], external=False, available=True,
                                tools=[dict(name="read_status", effect=False), dict(name="send_note", effect=True)])
                if old["revision"] != expected_revision:
                    raise WorkspaceError("stale_connection_revision", 409)
                revision = old["revision"] + 1
                db.execute("INSERT INTO connection_grants VALUES(?,?,?) ON CONFLICT(workspace_id) DO UPDATE SET enabled=excluded.enabled,revision=excluded.revision", (wid, int(enabled), revision))
                db.execute("UPDATE approvals SET status='invalidated' WHERE workspace_id=? AND status IN ('pending','approved')", (wid,))
                db.execute("UPDATE runs SET history=NULL WHERE workspace_id=?", (wid,))
                consumers = db.execute("SELECT r.id FROM runs r JOIN connection_reads c ON c.run_id=r.id WHERE c.workspace_id=? AND c.revision<>? AND r.state NOT IN ('completed','failed','cancelled')", (wid, revision)).fetchall()
                for consumer in consumers:
                    db.execute("UPDATE runs SET cancel_requested=1,error='connection_scope_changed' WHERE id=?", (consumer["id"],))
                    self.store._event(db, consumer["id"], "run.error", {"code": "connection_scope_changed"})
                    self.store._event(db, consumer["id"], "run.state", {"state": "cancel_requested"})
                return dict(fixture=True, enabled=enabled, revision=revision, external=False, available=True,
                            tools=[dict(name="read_status", effect=False), dict(name="send_note", effect=True)])
            self._once(db, owner, request_id, dict(wid=wid, enabled=enabled, expected_revision=expected_revision), change, safety=not enabled)
            # Command replay is idempotent, but the representation is live. A
            # lost ACK retry after later revocation must not display stale grant.
            current = self._grant(db, owner, wid)
            return dict(fixture=True, enabled=bool(current["enabled"]), revision=current["revision"], external=False, available=True,
                        tools=[dict(name="read_status", effect=False), dict(name="send_note", effect=True)])

    def _approval_view(self, row):
        value = dict(row)
        value["arguments"] = json.loads(value.pop("args"))
        value.pop("owner", None)
        value.pop("call_id", None)
        value["tool"] = "send_note"
        if value["status"] == "pending" and value["expires_at"] <= time.time():
            value["status"] = "expired"
        return value

    def approvals(self, owner, wid):
        with self.store.tx() as db:
            self.store._workspace(db, owner, wid)
            return dict(items=[self._approval_view(r) for r in db.execute("SELECT * FROM approvals WHERE workspace_id=? ORDER BY created_at DESC LIMIT 100", (wid,))])

    def _resource(self, db, wid, args):
        if args.get("artifact_id"):
            row = db.execute("SELECT version FROM artifacts WHERE id=? AND workspace_id=?", (args["artifact_id"], wid)).fetchone()
            if not row or row[0] != args.get("expected_version"):
                raise WorkspaceError("approval_resource_changed", 409)

    def prepare(self, owner, run_id, call_id, note, artifact_id=None, expected_version=None):
        if not self.enabled or not note.strip() or len(note) > 2000:
            raise WorkspaceError("invalid_fixture_effect")
        args = dict(note=note, artifact_id=artifact_id, expected_version=expected_version)
        with self.store.tx() as db:
            run = self.store.fence(db, owner, run_id)
            grant = self._grant(db, owner, run["workspace_id"], required=True)
            self._resource(db, run["workspace_id"], args)
            old = db.execute("SELECT * FROM approvals WHERE run_id=? AND call_id=?", (run_id, call_id)).fetchone()
            if old:
                if old["args_digest"] != digest(args):
                    raise WorkspaceError("approval_argument_conflict", 409)
                return self._approval_view(old)
            count = db.execute("SELECT COUNT(*) FROM approvals WHERE workspace_id=?", (run["workspace_id"],)).fetchone()[0]
            if count >= 100:
                raise WorkspaceError("approval_limit", 409)
            now, aid = time.time(), identity()
            db.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?,?,?,?)", (aid, owner, run["workspace_id"], run_id, call_id, json.dumps(args), digest(args), grant["revision"], "pending", min(run["deadline_at"], now + 90), now))
            db.execute("UPDATE runs SET state='waiting_approval' WHERE id=?", (run_id,))
            self.store._event(db, run_id, "run.state", {"state": "waiting_approval"})
            self.store._event(db, run_id, "approval.requested", {"approval_id": aid, "tool": "send_note"})
            return self._approval_view(db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone())

    def resolve(self, owner, aid, decision, key):
        with self.store.tx() as db:
            approval = db.execute("SELECT * FROM approvals WHERE id=? AND owner=?", (aid, owner)).fetchone()
            if not approval:
                raise WorkspaceError("not_found", 404)
            self.store._workspace(db, owner, approval["workspace_id"])
            def change():
                run = self.store.fence(db, owner, approval["run_id"])
                grant = self._grant(db, owner, run["workspace_id"], required=True)
                self._resource(db, run["workspace_id"], json.loads(approval["args"]))
                if grant["revision"] != approval["policy_revision"] or approval["status"] != "pending":
                    raise WorkspaceError("approval_no_longer_pending", 409)
                if approval["expires_at"] <= time.time():
                    raise WorkspaceError("approval_expired", 409)
                state = "approved" if decision == "approve" else "rejected"
                db.execute("UPDATE approvals SET status=? WHERE id=?", (state, aid))
                self.store._event(db, approval["run_id"], "approval.resolved", {"approval_id": aid, "status": state})
                return self._approval_view(db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone())
            self._once(db, owner, key, dict(approval_id=aid, decision=decision), change, safety=decision == "reject")
            return self._approval_view(db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone())

    def wakeups(self):
        with self.store.tx() as db:
            db.execute("UPDATE approvals SET status='expired' WHERE status='pending' AND expires_at<=?", (time.time(),))
            return [dict(r) for r in db.execute("SELECT a.id,a.run_id,a.status FROM approvals a JOIN runs r ON r.id=a.run_id WHERE r.state='waiting_approval' AND a.status!='pending' AND NOT EXISTS (SELECT 1 FROM workspace_tombstones t WHERE t.workspace_id=r.workspace_id)")]

    def waiting_ids(self, owner, run_id):
        with self.store.tx() as db:
            self.store._run(db, owner, run_id)
            return [r[0] for r in db.execute("SELECT id FROM approvals WHERE owner=? AND run_id=?", (owner, run_id))]

    async def read(self, owner, run_id):
        with self.store.tx() as db:
            run = self.store.fence(db, owner, run_id)
            self._grant(db, owner, run["workspace_id"], required=True)
            scope = owner + ":" + run["workspace_id"]
        value = await self.transport.call("read_status", scope)
        # Recheck after I/O so a revoked grant cannot publish a stale read.
        with self.store.tx() as db:
            run = self.store.fence(db, owner, run_id)
            self._grant(db, owner, run["workspace_id"], required=True)
        return value

    async def dispatch(self, owner, aid):
        with self.store.tx() as db:
            approval = db.execute("SELECT * FROM approvals WHERE id=? AND owner=?", (aid, owner)).fetchone()
            if not approval:
                raise WorkspaceError("not_found", 404)
            run = self.store.fence(db, owner, approval["run_id"])
            grant = self._grant(db, owner, run["workspace_id"], required=True)
            args = json.loads(approval["args"])
            self._resource(db, run["workspace_id"], args)
            if digest(args) != approval["args_digest"] or grant["revision"] != approval["policy_revision"]:
                raise WorkspaceError("approval_binding_changed", 409)
            old = db.execute("SELECT * FROM effects WHERE approval_id=?", (aid,)).fetchone()
            if old:
                if old["status"] == "completed":
                    return json.loads(old["receipt"])
                # An existing before-dispatch intent could have reached the MCP
                # server. It is not evidence of failure and MUST NOT resend.
                raise WorkspaceError("effect_needs_reconciliation", 409)
            if approval["status"] != "approved" or approval["expires_at"] <= time.time():
                code = "approval_rejected" if approval["status"] == "rejected" else "approval_expired" if approval["expires_at"] <= time.time() else "approval_not_valid"
                raise WorkspaceError(code, 409)
            eid = identity()
            db.execute("INSERT INTO effects VALUES(?,?,?,?,?,?,?,?,?)", (eid, aid, owner, run["workspace_id"], approval["run_id"], "intent", None, None, time.time()))
        try:
            result = await self.transport.call("send_note", owner + ":" + run["workspace_id"], key=eid, note=args["note"])
            if result.get("key") != eid or result.get("delivered") is not True or result.get("note") != args["note"]:
                raise WorkspaceError("mcp_invalid_receipt", 502)
            self.complete(owner, eid, result)
            self.store.check(owner, approval["run_id"])
            return result
        except BaseException:
            with self.store.tx() as db:
                db.execute("UPDATE effects SET status='uncertain',error='effect_needs_reconciliation' WHERE id=? AND status='intent'", (eid,))
            raise

    def complete(self, owner, eid, receipt):
        with self.store.tx() as db:
            row = db.execute("SELECT * FROM effects WHERE id=? AND owner=?", (eid, owner)).fetchone()
            if not row:
                raise WorkspaceError("not_found", 404)
            if row["status"] == "completed":
                return
            db.execute("UPDATE effects SET status='completed',receipt=?,error=NULL WHERE id=?", (json.dumps(receipt), eid))
            self.store._event(db, row["run_id"], "effect.receipt", {"effect_id": eid, "status": "completed", "fixture": True})

    def effects(self, owner, wid):
        with self.store.tx() as db:
            self.store._workspace(db, owner, wid)
            rows = db.execute("SELECT e.*,a.args FROM effects e JOIN approvals a ON a.id=e.approval_id WHERE e.workspace_id=? ORDER BY e.created_at DESC LIMIT 100", (wid,))
            return dict(items=[dict(id=r["id"], run_id=r["run_id"], tool="send_note", status="uncertain" if r["status"] == "intent" else r["status"], arguments=json.loads(r["args"]), receipt=json.loads(r["receipt"]) if r["receipt"] else None, error=r["error"]) for r in rows])

    async def reconcile(self, owner, eid):
        with self.store.tx() as db:
            row = db.execute("SELECT * FROM effects WHERE id=? AND owner=?", (eid, owner)).fetchone()
            if not row:
                raise WorkspaceError("not_found", 404)
            self.store._workspace(db, owner, row["workspace_id"])
            if not self.enabled:
                raise WorkspaceError("fixture_connection_disabled", 403)
        if row["status"] != "completed":
            result = await self.transport.call("lookup_receipt", owner + ":" + row["workspace_id"], key=eid)
            if result.get("key") != eid or not isinstance(result.get("found"), bool):
                raise WorkspaceError("mcp_invalid_receipt", 502)
            if result.get("found"):
                with self.store.tx() as db:
                    note = json.loads(db.execute("SELECT args FROM approvals WHERE id=?", (row["approval_id"],)).fetchone()[0])["note"]
                if result.get("delivered") is not True or result.get("note") != note:
                    raise WorkspaceError("mcp_invalid_receipt", 502)
                self.complete(owner, eid, result)
        return next(e for e in self.effects(owner, row["workspace_id"])["items"] if e["id"] == eid)
