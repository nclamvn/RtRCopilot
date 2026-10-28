"""Independent reviewer synthetic probes, not human or semantic acceptance.

Run from repository root with PYTHONPATH=v2/apps/workspace/src using workspace
Python. Real SQLite, native DBOS and fixed MCP stdio; zero provider calls.
"""
import asyncio
import json
from pathlib import Path

import pytest

from agent_workspace.store import Store, WorkspaceError
from agent_workspace.connections import Connections, FixtureTransport
from agent_workspace.workspace_state import WorkspaceState


def configured(tmp_path):
    store = Store(tmp_path / "catalogue.sqlite")
    _, owner = store.session(None)
    wid = store.workspaces(owner, "Independent new domain 71429")["id"]
    state = WorkspaceState(store)
    conn = Connections(store, tmp_path, True)
    conn.set_connection(owner, wid, True, 0, "independent-enable")
    run = store.create_run(owner, wid, "Synthetic independent operation", "independent-run", dict(deadline_seconds=90, output_bytes_limit=256000))["id"]
    return store, owner, wid, state, conn, run


def test_quota_does_not_trap_enabled_permission(tmp_path):
    store, owner, wid, state, conn, run = configured(tmp_path)
    with store.tx() as db:
        db.executemany("INSERT INTO connection_requests VALUES(?,?,?,?)", [(owner, f"fill-{i}", "digest", "{}") for i in range(1999)])
    revoked = conn.set_connection(owner, wid, False, 1, "independent-full-revoke")
    assert revoked["enabled"] is False
    assert conn.set_connection(owner, wid, False, 1, "independent-full-revoke")["revision"] == 2
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM connection_requests").fetchone()[0] == 2000
    with pytest.raises(WorkspaceError):
        conn.set_connection(owner, wid, True, 2, "independent-full-reenable")


def test_concurrent_dispatch_and_reconcile_have_one_effect(tmp_path):
    store, owner, wid, state, conn, run = configured(tmp_path)
    approval = conn.prepare(owner, run, "independent-call", "Decimal 91.125 and ID004173")
    conn.resolve(owner, approval["id"], "approve", "independent-decision")
    async def scenario():
        results = await asyncio.gather(*(conn.dispatch(owner, approval["id"]) for _ in range(3)), return_exceptions=True)
        assert sum(isinstance(value, dict) for value in results) == 1
        assert all(isinstance(value, (dict, WorkspaceError)) for value in results)
        effect = conn.effects(owner, wid)["items"][0]
        await asyncio.gather(*(conn.reconcile(owner, effect["id"]) for _ in range(3)))
        assert (await conn.transport.call("read_status", owner + ":" + wid))["outbox_count"] == 1
    asyncio.run(scenario())
    assert len(conn.effects(owner, wid)["items"]) == 1
    assert len([x for x in store.events(owner, run, 0) if x["type"] == "effect.receipt"]) == 1


def test_foreign_approval_never_changes_state_and_digest_tamper_is_denied(tmp_path):
    store, owner, wid, state, conn, run = configured(tmp_path)
    approval = conn.prepare(owner, run, "independent-call", "Before-approval exact body 71429")
    _, stranger = store.session(None)
    with pytest.raises(WorkspaceError, match="not_found"):
        conn.resolve(stranger, approval["id"], "approve", "independent-foreign")
    assert conn.approvals(owner, wid)["items"][0]["status"] == "pending"
    conn.resolve(owner, approval["id"], "approve", "independent-approve")
    with store.tx() as db:
        db.execute("UPDATE approvals SET args=? WHERE id=?", (json.dumps(dict(note="Tampered body", artifact_id=None, expected_version=None)), approval["id"]))
    with pytest.raises(WorkspaceError, match="approval_binding_changed"):
        asyncio.run(conn.dispatch(owner, approval["id"]))
    assert conn.effects(owner, wid)["items"] == []


def test_descriptor_change_cannot_authorize_or_dispatch(tmp_path, monkeypatch):
    import agent_workspace.mcp_fixture_server as server
    monkeypatch.setattr(server, "SCHEMAS", {"tool_says_it_is_safe": {"type": "object"}})
    with pytest.raises(WorkspaceError):
        asyncio.run(FixtureTransport(tmp_path).call("tool_says_it_is_safe", "independent-scope"))


def test_pending_approval_does_not_hold_other_workspace_chat(tmp_path):
    import time
    from fastapi.testclient import TestClient
    from agent_workspace.api import create_app
    from agent_workspace.config import Settings
    headers = {"origin": "http://localhost:3110"}
    with TestClient(create_app(Settings(tmp_path, test_mode=True)), base_url="http://localhost") as client:
        def post(path, data=None):
            response = client.post("/api/workspace" + path, headers=headers, json=data or {})
            response.raise_for_status()
            return response.json()
        post("/session")
        one = post("/workspaces", {"name": "Paused field notebook"})["id"]
        two = post("/workspaces", {"name": "Independent planning"})["id"]
        post(f"/workspaces/{one}/connection", dict(enabled=True, expected_revision=0, request_id="independent-hol-grant"))
        paused = post("/runs", dict(workspace_id=one, message="fixture:mcp-effect", client_request_id="independent-hol-paused"))["run_id"]
        for _ in range(150):
            if client.get("/api/workspace/runs/" + paused).json()["state"] == "waiting_approval":
                break
            time.sleep(.02)
        approval = client.get(f"/api/workspace/workspaces/{one}/approvals").json()["items"][0]
        try:
            other = post("/runs", dict(workspace_id=two, message="fixture:chat", client_request_id="independent-hol-other"))["run_id"]
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                final = client.get("/api/workspace/runs/" + other).json()
                if final["state"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(.02)
            assert final["state"] == "completed", final
            assert client.get("/api/workspace/runs/" + paused).json()["state"] == "waiting_approval"
        finally:
            post(f"/approvals/{approval['id']}/resolve", dict(decision="reject", request_id="independent-hol-reject"))
