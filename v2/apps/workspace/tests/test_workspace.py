"""Offline API/store safety integration, including actual DBOS SQLite execution."""
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from agent_workspace.api import create_app
from agent_workspace.config import Settings
from agent_workspace.store import Store, WorkspaceError

ORIGIN = {"origin": "http://localhost:3110"}
P = "/api/workspace"


def post(client, path, data=None):
    return client.post(P + path, headers=ORIGIN, json=data or {})


def terminal(client, run_id):
    for _ in range(500):
        value = client.get(P + "/runs/" + run_id).json()
        if value["state"] in {"completed", "failed", "cancelled"}:
            return value
        time.sleep(.03)
    pytest.fail("run did not become terminal")


@pytest.fixture(scope="module")
def offline(tmp_path_factory):
    with TestClient(create_app(Settings(tmp_path_factory.mktemp("workspace-api"), test_mode=True)), base_url="http://localhost") as client:
        assert post(client, "/session").status_code == 200
        yield client


def workspace(client):
    return post(client, "/workspaces", {"name": "Synthetic integration"}).json()["id"]


def start(client, wid, command, key):
    value = post(client, "/runs", dict(workspace_id=wid, message=command, client_request_id=key))
    assert value.status_code == 200, value.text
    return value.json()["run_id"]


def test_chat_create_followup_versions_replay_isolation(offline):
    c = offline
    assert c.get(P + "/status").json()["test_mode"] is True
    wid = workspace(c)
    assert post(c, f"/workspaces/{wid}/files", dict(filename="source.txt", content="Budget: 120.\nRevenue: 240.\nUnicode: Việt Nam", media_type="text/plain")).status_code == 200
    rid = start(c, wid, "fixture:chat", "test-chat-01")
    assert terminal(c, rid)["state"] == "completed"
    rid = start(c, wid, "fixture:create", "test-create-01")
    assert terminal(c, rid)["state"] == "completed"
    duplicate = start(c, wid, "fixture:create", "test-create-01")
    assert duplicate == rid
    item = c.get(P + f"/workspaces/{wid}/artifacts").json()["items"][0]
    old = c.get(P + f"/artifacts/{item['id']}").json()
    assert "120" in old["content"] and "Việt Nam" in old["content"]
    rid2 = start(c, wid, "fixture:edit", "test-edit-0001")
    assert terminal(c, rid2)["state"] == "completed"
    new = c.get(P + f"/artifacts/{item['id']}").json()
    assert new["version"] == 2 and old["content"] in new["content"]
    assert c.get(P + f"/artifacts/{item['id']}?version=1").json()["content"] == old["content"]
    assert c.get(P + f"/artifacts/{item['id']}/download").text == new["content"]
    stream = c.get(P + f"/runs/{rid2}/events?after=0").text
    assert '"type": "message.final"' in stream and '"type": "artifact.published"' in stream
    lines = [int(line[4:]) for line in stream.splitlines() if line.startswith("id: ")]
    assert lines == sorted(set(lines))
    after = c.get(P + f"/runs/{rid2}/events?after={max(lines)}").text
    assert after == ""
    # New opaque session cannot list, read, download, subscribe or cancel another owner's resources.
    c.cookies.clear()
    post(c, "/session")
    assert c.get(P + "/workspaces").json() == {"items": []}
    for path in [f"/workspaces/{wid}/messages", f"/workspaces/{wid}/files", f"/workspaces/{wid}/artifacts", f"/artifacts/{item['id']}", f"/artifacts/{item['id']}/download", f"/runs/{rid2}", f"/runs/{rid2}/events"]:
        assert c.get(P + path).status_code == 404, path
    assert post(c, f"/runs/{rid2}/cancel").status_code == 404


def test_cancel_outage_and_file_boundaries(offline):
    c = offline
    wid = workspace(c)
    for name in ["../secret.md", "x/y.txt", "x\\y.md", "a\n.md", "report.pdf"]:
        assert post(c, f"/workspaces/{wid}/files", dict(filename=name, content="unsafe")).status_code == 400
    assert post(c, f"/workspaces/{wid}/files", dict(filename="x.txt", content="x" * 256001)).status_code in {413, 422}
    rid = start(c, wid, "fixture:slow", "slow-cancel-01")
    actor = c.app.state.store.authenticate(c.cookies.get("workspace_session"))
    for _ in range(100):
        if any(e["type"] == "message.delta" for e in c.app.state.store.events(actor, rid, 0)):
            break
        time.sleep(.02)
    else:
        pytest.fail("no live model delta before final")
    assert c.get(P + f"/runs/{rid}").json()["state"] == "running"
    busy = post(c, "/runs", dict(workspace_id=wid, message="fixture:chat", client_request_id="busy-next-01"))
    assert busy.status_code == 409
    result = post(c, f"/runs/{rid}/cancel")
    assert result.status_code == 200 and result.json()["cancel_requested"]
    assert terminal(c, rid)["state"] == "cancelled"
    assert c.get(P + f"/workspaces/{wid}/artifacts").json() == {"items": []}
    rid2 = start(c, wid, "fixture:error", "outage-test-01")
    assert terminal(c, rid2)["state"] == "failed"
    assert c.get(P + f"/runs/{rid2}").json()["error"] == "provider_request_failed"


def test_persisted_request_tool_deadline_output_limits(offline):
    c = offline
    store = c.app.state.store
    actor = store.authenticate(c.cookies.get("workspace_session"))
    for name, overrides, command in [
        ("request", {"request_limit": 1}, "fixture:create"),
        ("tools", {"tool_limit": 1}, "fixture:create"),
        ("deadline", {"deadline_seconds": .15}, "fixture:slow"),
        ("output", {"output_bytes_limit": 20}, "fixture:chat"),
    ]:
        wid = workspace(c)
        post(c, f"/workspaces/{wid}/files", dict(filename="source.txt", content="Synthetic 120"))
        limits = dict(deadline_seconds=20, request_limit=8, tool_limit=16, token_limit=32000, output_bytes_limit=256000)
        limits.update(overrides)
        value = store.create_run(actor, wid, command, "limits-test-" + name, limits)
        # The API/worker background outbox dispatches this durable row.
        final = terminal(c, value["id"])
        assert final["state"] == "failed", (name, final)
        assert final["limits"] == limits
        assert c.get(P + f"/workspaces/{wid}/artifacts").json() == {"items": []}


def test_origin_session_host_and_unavailable(tmp_path):
    with TestClient(create_app(Settings(tmp_path)), base_url="http://localhost") as c:
        assert c.get(P + "/status").status_code == 401
        assert c.post(P + "/session", json={}).status_code == 403
        assert c.post(P + "/session", headers={"origin": "https://attacker.invalid"}, json={}).status_code == 403
        assert c.get(P + "/status", headers={"host": "attacker.invalid"}).status_code == 400
        assert post(c, "/session").status_code == 200
        status = c.get(P + "/status").json()
        assert status["available"] is False and status["reason"] == "model_not_configured"
        wid = workspace(c)
        assert post(c, "/runs", dict(workspace_id=wid, message="hi", client_request_id="no-model-0001")).status_code == 503
        assert post(c, "/runs", dict(workspace_id=wid, message="hi", client_request_id="no-model-0001", owner="forged")).status_code == 422
        assert c.get(P + f"/workspaces/{wid}/messages").json() == {"items": []}


def test_receipt_fencing_stale_revision_and_failed_render(tmp_path):
    s = Store(tmp_path / "catalogue.sqlite")
    _, owner = s.session(None)
    wid = s.workspaces(owner, "Tools")["id"]
    limits = dict(deadline_seconds=30, output_bytes_limit=10000)
    run = s.create_run(owner, wid, "draft", "request-key", limits)["id"]
    s.running(owner, run)
    item = s.publish(owner, run, "call1", "Draft", "draft.md", "Valid draft: 120")
    assert s.publish(owner, run, "call1", "Draft", "draft.md", "Valid draft: 120") == item
    assert len(s.items(owner, wid, "artifacts")) == 1
    with pytest.raises(WorkspaceError, match="receipt_argument_conflict"):
        s.publish(owner, run, "call1", "Draft", "draft.md", "Changed argument")
    with pytest.raises(WorkspaceError, match="stale_artifact_version"):
        s.publish(owner, run, "call2", "Draft", "draft.md", "New", item["artifact_id"], 0)
    with pytest.raises(WorkspaceError, match="invalid_markdown_draft"):
        s.publish(owner, run, "call2", "Draft", "draft.md", "")
    assert s.artifact(owner, item["artifact_id"])["content"] == "Valid draft: 120"
    s.cancel(owner, run)
    with pytest.raises(WorkspaceError, match="cancelled"):
        s.publish(owner, run, "call3", "Draft", "draft.md", "late publish")
    s.finish(owner, run, "completed", content="late text")
    assert s.run(owner, run)["state"] == "cancelled"
    assert len(s.items(owner, wid, "messages")) == 1


def test_tool_scope_same_owner_and_deadline(tmp_path):
    s = Store(tmp_path / "catalogue.sqlite")
    _, owner = s.session(None)
    first, second = s.workspaces(owner, "First")["id"], s.workspaces(owner, "Second")["id"]
    file = s.upload(owner, second, "secret.txt", "private", "text/plain")
    run = s.create_run(owner, first, "read", "request-key", dict(deadline_seconds=30, output_bytes_limit=1000))["id"]
    with pytest.raises(WorkspaceError, match="not_found"):
        s.read_file(owner, run, file["id"])
    with pytest.raises(WorkspaceError, match="not_found"):
        s.read_file(owner, run, "/etc/passwd")
    with s.tx() as db:
        db.execute("UPDATE runs SET deadline_at=? WHERE id=?", (time.time() - 1, run))
    with pytest.raises(WorkspaceError, match="deadline_exceeded"):
        s.publish(owner, run, "late", "Draft", "draft.md", "too late")
    s.finish(owner, run, "completed", content="late")
    assert s.run(owner, run)["error"] == "deadline_exceeded"


def test_physical_dispatch_reservation_fails_closed_on_uncertainty(tmp_path):
    s = Store(tmp_path / "catalogue.sqlite")
    _, owner = s.session(None)
    wid = s.workspaces(owner, "Dispatch budgets")["id"]
    run = s.create_run(owner, wid, "request", "dispatch-key", dict(deadline_seconds=30, request_limit=2, output_bytes_limit=1000))["id"]
    s.reserve_model_dispatch(owner, run, 7)
    with pytest.raises(WorkspaceError, match="uncertain_provider_dispatch"):
        s.reserve_model_dispatch(owner, run, 7)
    assert s.run(owner, run)["usage"]["physical_requests"] == 1
    # Replays are allowed only for explicitly no-network simulations, still charged to original budget.
    s.reserve_model_dispatch(owner, run, 7, allow_replay=True)
    with pytest.raises(WorkspaceError, match="physical_request_limit"):
        s.reserve_model_dispatch(owner, run, 8, allow_replay=True)
    assert s.run(owner, run)["usage"]["physical_requests"] == 2


def test_stream_limit_is_atomic_and_deduplicated(tmp_path):
    s = Store(tmp_path / "catalogue.sqlite")
    _, owner = s.session(None)
    wid = s.workspaces(owner, "Stream limits")["id"]
    run = s.create_run(owner, wid, "request", "stream-key", dict(deadline_seconds=30, request_limit=2, output_bytes_limit=10))["id"]
    s.event_once(owner, run, "delta1", "message.delta", {"text": "123456789"})
    s.event_once(owner, run, "delta1", "message.delta", {"text": "123456789"})
    with pytest.raises(WorkspaceError, match="stream_output_limit"):
        s.event_once(owner, run, "delta2", "message.delta", {"text": "x" * 100000})
    events = s.events(owner, run, 0)
    assert len([e for e in events if e["type"] == "message.delta"]) == 1
    with s.tx() as db:
        assert db.execute("SELECT stream_bytes FROM runs WHERE id=?", (run,)).fetchone()[0] == 9
    s.cancel(owner, run)
    with pytest.raises(WorkspaceError, match="cancelled"):
        s.event_once(owner, run, "late", "message.delta", {"text": "x"})
