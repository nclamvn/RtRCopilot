"""Contractor-authored synthetic boundary probes, no provider/network calls.

Run with PYTHONPATH=v2/apps/workspace/src and the workspace Python environment.
These exercise real SQLite authority/state, not semantic model quality.
"""
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_workspace.store import Store, WorkspaceError
from agent_workspace.workspace_state import WorkspaceState


LIMITS = dict(deadline_seconds=120, request_limit=8, tool_limit=16,
              token_limit=32000, output_bytes_limit=256000)


def setup(tmp_path):
    store = Store(tmp_path / "catalogue.sqlite")
    state = WorkspaceState(store)
    _, owner = store.session(None)
    wid = store.workspaces(owner, "Unseen field study")["id"]
    return store, state, owner, wid


def test_memory_deleted_create_ack_cannot_resurrect(tmp_path):
    store, state, owner, wid = setup(tmp_path)
    body = "Use EUR; preserve batch reference 004173."
    first = state.save_memory(owner, wid, body, "independent-create-memory")
    run = store.create_run(owner, wid, "read", "independent-reader-run", LIMITS)
    assert state.read_memories(owner, run["id"])["items"][0]["content"] == body
    deleted = state.delete_memory(owner, wid, first["id"], 1, "independent-delete-memory")
    assert deleted["deleted"]
    assert state.memories(owner, wid)["items"] == []
    with pytest.raises(WorkspaceError):
        state.save_memory(owner, wid, body, "independent-create-memory")
    with pytest.raises(WorkspaceError):
        state.read_memories(owner, run["id"])
    with store.tx() as db:
        assert db.execute("SELECT content FROM workspace_memory WHERE id=?", (first["id"],)).fetchone()[0] is None
        assert not any(body in row[0] for row in db.execute("SELECT result FROM workspace_state_requests"))
    # Reconstruct application state from disk, not an in-memory cache.
    assert WorkspaceState(Store(store.path)).memories(owner, wid)["items"] == []


def test_foreign_ids_and_stale_memory_revision(tmp_path):
    store, state, owner, wid = setup(tmp_path)
    other_wid = store.workspaces(owner, "Other workspace")["id"]
    _, stranger = store.session(None)
    item = state.save_memory(owner, wid, "Keep 43.75 in source units.", "independent-scope-create")
    for actor, target in ((stranger, wid), (owner, other_wid)):
        with pytest.raises(WorkspaceError):
            state.delete_memory(actor, target, item["id"], 1, "independent-scope-delete")
    state.save_memory(owner, wid, "Keep 91.125 in source units.", "independent-scope-edit", item["id"], 1)
    with pytest.raises(WorkspaceError, match="stale_memory_version"):
        state.delete_memory(owner, wid, item["id"], 1, "independent-stale-delete")
    assert state.memories(owner, wid)["items"][0]["content"] == "Keep 91.125 in source units."


def test_concurrent_ticks_create_one_run_and_cancel_never_revives(tmp_path):
    store, state, owner, wid = setup(tmp_path)
    item = state.create_schedule(owner, wid, "fixture:chat", 17.25, "independent-schedule-create")
    def tick(index):
        return state.tick(owner, wid, 17.25, f"independent-tick-{index}", LIMITS)
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(tick, range(4)))
    jobs = state.schedules(owner, wid)["items"]
    assert jobs[0]["state"] == "dispatched"
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM runs WHERE workspace_id=?", (wid,)).fetchone()[0] == 1
    cancelled = state.create_schedule(owner, wid, "fixture:chat", 29, "independent-cancel-create")
    state.change_schedule(owner, wid, cancelled["id"], "cancel", 1, "independent-cancel-action")
    replay = state.create_schedule(owner, wid, "fixture:chat", 29, "independent-cancel-create")
    assert replay["state"] == "cancelled"
    with pytest.raises(WorkspaceError):
        state.change_schedule(owner, wid, cancelled["id"], "resume", 2, "independent-invalid-resume")
    assert item["id"] == jobs[0]["id"]


def test_manual_clock_invalid_values_and_reversal_are_atomic(tmp_path):
    store, state, owner, wid = setup(tmp_path)
    for index, value in enumerate((float("nan"), float("inf"), -1, True, 31536001)):
        with pytest.raises(WorkspaceError):
            state.tick(owner, wid, value, f"independent-invalid-tick-{index}", LIMITS)
    assert state.schedules(owner, wid)["clock"] == 0
    state.tick(owner, wid, 41.75, "independent-clock-forward", LIMITS)
    with pytest.raises(WorkspaceError, match="manual_clock_cannot_reverse"):
        state.tick(owner, wid, 41, "independent-clock-reverse", LIMITS)
    assert state.schedules(owner, wid)["clock"] == 41.75
