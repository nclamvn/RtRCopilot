"""Actual SQLite memory and manual-clock semantics; no provider or scheduler."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from agent_workspace.store import Store, WorkspaceError
from agent_workspace.workspace_state import WorkspaceState


LIMITS = dict(deadline_seconds=120, request_limit=8, tool_limit=16, token_limit=32000, output_bytes_limit=256000)


@pytest.fixture
def state(tmp_path):
    store = Store(tmp_path / "catalogue.sqlite")
    service = WorkspaceState(store)
    _, owner = store.session(None)
    wid = store.workspaces(owner, "Explicit state")["id"]
    return store, service, owner, wid


def test_memory_explicit_revision_and_delete_does_not_resurrect(state):
    store, service, owner, wid = state
    assert service.memories(owner, wid) == dict(items=[], revision=0)
    value = "Private synthetic preference: Vietnamese output 135000"
    item = service.save_memory(owner, wid, value, "memory-create-01")
    assert item["source"] == "user" and item["version"] == 1
    assert service.save_memory(owner, wid, value, "memory-create-01")["id"] == item["id"]
    with pytest.raises(WorkspaceError, match="idempotency_conflict"):
        service.save_memory(owner, wid, "different", "memory-create-01")
    edited = service.save_memory(owner, wid, value + " updated", "memory-edit-001", item["id"], 1)
    assert edited["version"] == 2
    with pytest.raises(WorkspaceError, match="stale_memory_version"):
        service.save_memory(owner, wid, "stale", "memory-edit-old", item["id"], 1)
    deletion = service.delete_memory(owner, wid, item["id"], 2, "memory-delete01")
    assert deletion["deleted"] is True
    assert service.delete_memory(owner, wid, item["id"], 2, "memory-delete01") == deletion
    for key, text, version in [("memory-create-01", value, None), ("memory-edit-001", value + " updated", 1)]:
        with pytest.raises(WorkspaceError, match="memory_deleted"):
            service.save_memory(owner, wid, text, key, item["id"] if version else None, version)
    restarted = WorkspaceState(Store(store.path))
    assert restarted.memories(owner, wid) == dict(items=[], revision=3)
    with store.tx() as db:
        assert db.execute("SELECT content FROM workspace_memory WHERE id=?", (item["id"],)).fetchone()[0] is None
        assert value not in str([tuple(r) for r in db.execute("SELECT * FROM workspace_state_requests")])


def test_memory_mutation_fences_consumer_and_clears_reusable_history(state):
    store, service, owner, wid = state
    item = service.save_memory(owner, wid, "Temporary synthetic memory 120.50", "memory-seed0001")
    seed = store.create_run(owner, wid, "old history", "memory-history0", LIMITS)
    store.finish(owner, seed["id"], "completed", content="Visible record remains", history="cached model body")
    run = store.create_run(owner, wid, "consume", "memory-consume0", LIMITS)
    assert service.read_memories(owner, run["id"])["items"][0]["content"] == item["content"]
    service.delete_memory(owner, wid, item["id"], 1, "memory-drop0001")
    assert store.run(owner, run["id"])["cancel_requested"] is True
    with store.tx() as db:
        with pytest.raises(WorkspaceError, match="memory_scope_changed"):
            service.assert_memory_current(db, owner, run["id"])
        assert all(row[0] is None for row in db.execute("SELECT history FROM runs WHERE workspace_id=?", (wid,)))
    # User-visible messages are separate retained work, not an unlearning claim.
    assert "Visible record remains" in str(store.items(owner, wid, "messages"))
    store.finish(owner, run["id"], "cancelled")
    next_run = store.create_run(owner, wid, "new run", "memory-next0001", LIMITS)
    assert service.read_memories(owner, next_run["id"])["items"] == []
    assert store.context(owner, next_run["id"])[0] is None


def test_memory_owner_workspace_boundaries_and_bounds(state):
    store, service, owner, wid = state
    item = service.save_memory(owner, wid, "Original", "memory-bound001")
    _, other = store.session(None)
    second = store.workspaces(owner, "Second")["id"]
    for call in [lambda: service.memories(other, wid), lambda: service.save_memory(other, wid, "No", "memory-foreign0"), lambda: service.delete_memory(owner, second, item["id"], 1, "memory-foreign1"), lambda: service.save_memory(owner, second, "No", "memory-foreign2", item["id"], 1)]:
        with pytest.raises(WorkspaceError, match="not_found"):
            call()
    for value in ["", " ", "x" * 4001, "unsafe\x00value", "\ud800"]:
        with pytest.raises(WorkspaceError, match="invalid_memory_content"):
            service.save_memory(owner, wid, value, "memory-invalid0")
    assert service.memories(owner, wid)["items"] == [item]


def test_memory_concurrent_same_key_and_stale_saves(state):
    store, service, owner, wid = state
    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(lambda _: service.save_memory(owner, wid, "Once only", "memory-parallel"), range(4)))
    assert len({x["id"] for x in items}) == 1
    mid = items[0]["id"]
    def edit(key):
        try:
            return service.save_memory(owner, wid, key, key, mid, 1)["version"]
        except WorkspaceError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["memory-race-one", "memory-race-two"]))
    assert sorted(map(str, results)) == ["2", "stale_memory_version"]


def test_inherited_history_consumer_binds_epoch_and_late_finish_cannot_reinstall(state):
    store, service, owner, wid = state
    item = service.save_memory(owner, wid, "Ephemeral memory 987654", "memory-epoch-seed")
    first = store.create_run(owner, wid, "seed", "memory-epoch-first", LIMITS)
    service.read_memories(owner, first["id"])
    store.finish(owner, first["id"], "completed", history="memory-bearing initial history")
    followup = store.create_run(owner, wid, "follow up", "memory-epoch-next", LIMITS)
    assert service.bind_run_epoch(owner, followup["id"]) == {"revision": 1}
    assert store.context(owner, followup["id"])[0] == "memory-bearing initial history"
    service.delete_memory(owner, wid, item["id"], 1, "memory-epoch-delete")
    with pytest.raises(WorkspaceError):
        service.bind_run_epoch(owner, followup["id"])
    assert store.run(owner, followup["id"])["cancel_requested"] is True
    store.finish(owner, followup["id"], "completed", history="late stale memory-bearing history")
    assert store.run(owner, followup["id"])["state"] == "cancelled"
    with store.tx() as db:
        assert all(row[0] is None for row in db.execute("SELECT history FROM runs WHERE workspace_id=?", (wid,)))


def test_manual_clock_once_pause_cancel_busy_and_restart(state):
    store, service, owner, wid = state
    assert service.schedules(owner, wid) == dict(clock=0, items=[])
    first = service.create_schedule(owner, wid, "fixture:chat", 60, "schedule-first0")
    second = service.create_schedule(owner, wid, "fixture:chat", 60, "schedule-second")
    paused = service.change_schedule(owner, wid, second["id"], "pause", 1, "schedule-pause0")
    assert paused["state"] == "paused"
    result = service.tick(owner, wid, 60, "schedule-tick01", LIMITS)
    assert len(result["dispatched"]) == 1 and not result["blocked"]
    assert result["dispatched"][0]["id"] == first["id"]
    assert service.tick(owner, wid, 60, "schedule-tick01", LIMITS) == result
    assert service.tick(owner, wid, 60, "schedule-tick02", LIMITS)["dispatched"] == []
    service.change_schedule(owner, wid, second["id"], "resume", paused["version"], "schedule-resume")
    blocked = service.tick(owner, wid, 60, "schedule-tick03", LIMITS)
    assert blocked["blocked"] == [{"id": second["id"], "error": "workspace_busy"}]
    assert next(x for x in blocked["items"] if x["id"] == second["id"])["state"] == "pending"
    rid = result["dispatched"][0]["run_id"]
    store.finish(owner, rid, "completed", content="Synthetic finished")
    restart = WorkspaceState(Store(store.path))
    done = restart.tick(owner, wid, 60, "schedule-tick04", LIMITS)
    assert len(done["dispatched"]) == 1
    third = restart.create_schedule(owner, wid, "fixture:chat", 100, "schedule-third0")
    cancelled = restart.change_schedule(owner, wid, third["id"], "cancel", 1, "schedule-cancel")
    assert cancelled["state"] == "cancelled"
    assert restart.create_schedule(owner, wid, "fixture:chat", 100, "schedule-third0")["state"] == "cancelled"
    assert restart.tick(owner, wid, 120, "schedule-tick05", LIMITS)["dispatched"] == []
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM runs WHERE workspace_id=?", (wid,)).fetchone()[0] == 2
        assert len({r[0] for r in db.execute("SELECT request_key FROM runs WHERE workspace_id=?", (wid,))}) == 2


def test_schedule_concurrent_ticks_exactly_one_logical_run(state):
    store, service, owner, wid = state
    item = service.create_schedule(owner, wid, "fixture:chat", 1, "schedule-atomic")
    def tick(i):
        return service.tick(owner, wid, 1, "schedule-tick-" + str(i), LIMITS)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(tick, range(4)))
    assert sum(len(x["dispatched"]) for x in results) == 1
    restarted = WorkspaceState(Store(store.path))
    assert restarted.tick(owner, wid, 1, "schedule-reboot", LIMITS)["dispatched"] == []
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM runs WHERE request_key=?", ("schedule-" + item["id"],)).fetchone()[0] == 1


def test_schedule_scope_input_idempotency_stale_and_no_clock_reversal(state):
    store, service, owner, wid = state
    item = service.create_schedule(owner, wid, "fixture:chat", 10, "schedule-scope0")
    _, other = store.session(None)
    for call in [lambda: service.schedules(other, wid), lambda: service.tick(other, wid, 10, "schedule-other0", LIMITS), lambda: service.change_schedule(other, wid, item["id"], "cancel", 1, "schedule-other1")]:
        with pytest.raises(WorkspaceError, match="not_found"):
            call()
    for value in [float("nan"), float("inf"), -1, 31_536_001, True, "1"]:
        with pytest.raises(WorkspaceError, match="invalid_manual_clock"):
            service.create_schedule(owner, wid, "fixture:chat", value, "schedule-invalid")
    service.tick(owner, wid, 5, "schedule-forward", LIMITS)
    with pytest.raises(WorkspaceError, match="manual_clock_cannot_reverse"):
        service.tick(owner, wid, 4, "schedule-reverse", LIMITS)
    with pytest.raises(WorkspaceError, match="schedule_in_past"):
        service.create_schedule(owner, wid, "fixture:chat", 4, "schedule-late00")
    with pytest.raises(WorkspaceError, match="idempotency_conflict"):
        service.create_schedule(owner, wid, "changed", 10, "schedule-scope0")
    service.change_schedule(owner, wid, item["id"], "pause", 1, "schedule-edit01")
    with pytest.raises(WorkspaceError, match="stale_schedule_version"):
        service.change_schedule(owner, wid, item["id"], "resume", 1, "schedule-stale0")


def test_full_work_quota_cannot_prevent_forget_or_cancel(state, monkeypatch):
    store, service, owner, wid = state
    memory = service.save_memory(owner, wid, "May be forgotten", "quota-memory001")
    schedule = service.create_schedule(owner, wid, "fixture:chat", 1, "quota-schedule1")
    monkeypatch.setattr("agent_workspace.workspace_state.MAX_REQUESTS", 2)
    with pytest.raises(WorkspaceError, match="workspace_state_request_limit"):
        service.tick(owner, wid, 1, "quota-tick00001", LIMITS)
    assert service.delete_memory(owner, wid, memory["id"], 1, "quota-delete001")["deleted"] is True
    assert service.change_schedule(owner, wid, schedule["id"], "cancel", 1, "quota-cancel001")["state"] == "cancelled"
    assert service.memories(owner, wid)["items"] == []


def test_tick_receipts_do_not_duplicate_all_scheduled_prompt_bodies(state):
    store, service, owner, wid = state
    content = "Synthetic task " + "x" * 14000
    service.create_schedule(owner, wid, content, 60, "compact-receipt1")
    service.tick(owner, wid, 1, "compact-receipt2", LIMITS)
    with store.tx() as db:
        row = db.execute("SELECT result FROM workspace_state_requests WHERE owner=? AND request_id='compact-receipt2'", (owner,)).fetchone()
        assert content not in row[0] and len(row[0].encode()) < 1000
        assert "dispatched_ids" in json.loads(row[0])
