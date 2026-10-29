"""Synthetic local context/lineage checks; not an AI quality evaluation."""
import base64
import json

import pytest

from agent_workspace.continuity import Continuity, MAX_CONTEXT
from agent_workspace.data_lifecycle import DataLifecycle
from agent_workspace.portability import SnapshotImporter, inspect_archive
from agent_workspace.store import Store, WorkspaceError
from agent_workspace.workspace_state import WorkspaceState

LIMITS = dict(deadline_seconds=120, request_limit=8, tool_limit=24, token_limit=32000, output_bytes_limit=256000)


@pytest.fixture
def project(tmp_path):
    s = Store(tmp_path / "catalogue.sqlite")
    state = WorkspaceState(s)
    c = Continuity(s)
    _, owner = s.session(None)
    wid = s.workspaces(owner, "Synthetic museum project")["id"]
    a = s.upload(owner, wid, "museum.txt", "Museum admission 120.50.\nTiếng Việt", "text/plain")
    b = s.upload(owner, wid, "update.txt", "Museum admission 125.75.\nTiếng Việt", "text/plain")
    return s, state, c, owner, wid, a, b


def start(project, key="context-run-001", context=None):
    s, state, c, owner, wid, *_ = project
    run = s.create_run(owner, wid, "fixture:create", key, LIMITS, context=context)["id"]
    state.bind_run_epoch(owner, run)
    return run


def test_explicit_selection_honors_exact_source_and_discloses_omitted(project):
    s, state, c, owner, wid, a, b = project
    manifest = c.preview(owner, wid, "Museum", {"references": [{"kind": "file", "id": a["id"]}]})
    assert [r["id"] for r in manifest["selections"]] == [a["id"]]
    assert "120.50" in manifest["selections"][0]["content"]
    assert "125.75" not in json.dumps(manifest)
    assert manifest["omissions"] and manifest["context_bytes"] < MAX_CONTEXT
    assert manifest["mode"] == "explicit"


def test_source_chunks_are_partial_and_full_reads_tracked(project):
    s, state, c, owner, wid, a, b = project
    large = s.upload(owner, wid, "long.txt", "X" * 9000, "text/plain")
    run = start(project, context={"references": [{"kind": "file", "id": large["id"]}]})
    manifest = c.snapshot(owner, run)
    assert manifest["selections"][0]["has_more"]
    s.read_file(owner, run, large["id"], 4000, 5000)
    ledger = c.run_context(owner, run)["read_ledger"]
    assert [r["offset"] for r in ledger] == [0, 4000]
    assert [r["end"] for r in ledger] == [4000, 9000]


def test_context_snapshot_immutable_replayed_after_upload(project):
    s, state, c, owner, wid, a, b = project
    run = start(project)
    first = c.snapshot(owner, run)
    s.upload(owner, wid, "late.txt", "Late 999.0", "text/plain")
    assert c.snapshot(owner, run) == first
    assert first["digest"] == c.run_context(owner, run)["digest"]


def test_search_is_scoped_and_bounds_matches(project):
    s, state, c, owner, wid, a, b = project
    result = c.search(owner, wid, "125.75")
    assert b["id"] in [i["id"] for i in result["items"]]
    _, foreign = s.session(None)
    with pytest.raises(WorkspaceError, match="not_found"):
        c.search(foreign, wid, "Museum")


def test_changed_run_context_is_idempotency_conflict(project):
    s, state, c, owner, wid, a, b = project
    opts = {"references": [{"kind": "file", "id": a["id"]}]}
    run = s.create_run(owner, wid, "request", "same-run-key", LIMITS, opts)
    assert s.create_run(owner, wid, "request", "same-run-key", LIMITS, opts)["id"] == run["id"]
    with pytest.raises(WorkspaceError, match="idempotency_conflict"):
        s.create_run(owner, wid, "request", "same-run-key", LIMITS, {"references": [{"kind": "file", "id": b["id"]}]})


def test_foreign_or_invalid_context_selection_rejected(project):
    s, state, c, owner, wid, a, b = project
    foreign = s.workspaces(owner, "Other project")["id"]
    f = s.upload(owner, foreign, "other.txt", "Private", "text/plain")
    with pytest.raises(WorkspaceError, match="context_reference_not_found"):
        c.preview(owner, wid, "question", {"references": [{"kind": "file", "id": f["id"]}]})
    with pytest.raises(WorkspaceError, match="invalid_context_reference"):
        c.preview(owner, wid, "question", {"references": [{"kind": "file", "id": a["id"], "version": 1}]})


def test_pinned_historical_version_and_stale_target_cas(project):
    s, state, c, owner, wid, a, b = project
    artifact = s.create_artifact(owner, wid, "First", "document", "# First 120.50", "artifact-first-001")
    s.revise(owner, artifact["id"], 1, "# Second 125.75", "artifact-second-001")
    target = dict(kind="artifact", id=artifact["id"], version=1)
    run = start(project, context={"target": target})
    c.snapshot(owner, run)
    assert s.read_artifact(owner, run, artifact["id"])["content"] == "# First 120.50"
    with pytest.raises(WorkspaceError, match="stale_artifact_version"):
        s.publish(owner, run, "write-new", "Wrong escape", "new.md", "# New unrelated")
    assert s.artifact(owner, artifact["id"])["version"] == 2


def test_valid_target_update_and_wrong_target_rejected(project):
    s, state, c, owner, wid, a, b = project
    artifact = s.create_artifact(owner, wid, "First", "document", "# First 120.50", "artifact-first-001")
    target = dict(kind="artifact", id=artifact["id"], version=1)
    run = start(project, context={"target": target})
    c.snapshot(owner, run)
    with pytest.raises(WorkspaceError, match="context_target_mismatch"):
        s.publish(owner, run, "write-new", "Wrong escape", "new.md", "# New unrelated")
    result = s.publish(owner, run, "write-right", "First", "new.md", "# New 120.50", artifact["id"], 1)
    assert result["version"] == 2
    assert s.artifact(owner, artifact["id"], 1)["content"] == "# First 120.50"


def test_own_target_progress_allows_local_repair_but_external_edit_fences(project):
    s, state, c, owner, wid, a, b = project
    artifact = s.create_artifact(owner, wid, "First", "document", "# First 120.50", "artifact-first-001")
    target = dict(kind="artifact", id=artifact["id"], version=1)
    run = start(project, context={"target": target})
    original = c.snapshot(owner, run)
    s.publish(owner, run, "write-first", "First", "new.md", "# Second 120.50", artifact["id"], 1)
    assert s.read_artifact(owner, run, artifact["id"])["version"] == 2
    result = s.publish(owner, run, "write-repair", "First", "new.md", "# Repaired 120.50", artifact["id"], 2)
    assert result["version"] == 3
    assert c.snapshot(owner, run) == original
    # A replayed receipt returns its exact old result, not another publication.
    assert s.publish(owner, run, "write-first", "First", "new.md", "# Second 120.50", artifact["id"], 1)["version"] == 2
    s.revise(owner, artifact["id"], 3, "# Manual 125.75", "manual-interleave-001")
    assert s.read_artifact(owner, run, artifact["id"])["version"] == 3
    with pytest.raises(WorkspaceError, match="stale_artifact_version"):
        s.publish(owner, run, "late-write", "First", "new.md", "# Wrong", artifact["id"], 3)
    assert s.artifact(owner, artifact["id"])["version"] == 4


def test_transitive_source_replacement_surfaces_upstream_staleness(project):
    s, state, c, owner, wid, a, b = project
    first = start(project, context={"references": [{"kind": "file", "id": a["id"]}]})
    c.snapshot(owner, first)
    output = s.publish(owner, first, "first-write", "First", "first.md", "# 120.50")
    s.finish(owner, first, "completed")
    second = start(project, "context-run-002", {"references": [{"kind": "artifact", "id": output["artifact_id"], "version": 1}]})
    c.snapshot(owner, second)
    other = s.publish(owner, second, "second-write", "Second", "second.md", "# Derived 120.50")
    s.finish(owner, second, "completed")
    assert not c.dependencies(owner, other["artifact_id"])["stale"]
    c.replace(owner, wid, a["id"], b["id"], "replace-upstream-001")
    info = c.dependencies(owner, other["artifact_id"])
    assert info["stale"] and any("upstream" in r for r in info["reasons"])


def test_affected_dependency_stale_not_unrelated(project):
    s, state, c, owner, wid, a, b = project
    run = start(project, context={"references": [{"kind": "file", "id": a["id"]}]})
    c.snapshot(owner, run)
    output = s.publish(owner, run, "write-001", "Read A", "out.md", "# Output 120.50")
    s.finish(owner, run, "completed", content="Done")
    unrelated = s.create_artifact(owner, wid, "Manual", "document", "# Unrelated", "manual-create-001")
    assert c.dependencies(owner, output["artifact_id"])["status"] == "known"
    assert not c.dependencies(owner, output["artifact_id"])["stale"]
    c.replace(owner, wid, a["id"], b["id"], "replacement-001")
    assert c.dependencies(owner, output["artifact_id"])["stale"]
    assert c.dependencies(owner, unrelated["id"])["status"] == "unknown"
    assert s.source(owner, a["id"])["content"].startswith("Museum admission 120.50")


def test_replacement_idempotency_ambiguity_cycle(project):
    s, state, c, owner, wid, a, b = project
    x = c.replace(owner, wid, a["id"], b["id"], "replacement-001")
    assert c.replace(owner, wid, a["id"], b["id"], "replacement-001") == x
    with pytest.raises(WorkspaceError, match="source_replacement_cycle"):
        c.replace(owner, wid, b["id"], a["id"], "replacement-cycle")
    with pytest.raises(WorkspaceError, match="source_replacement_conflict"):
        c.replace(owner, wid, a["id"], b["id"], "replacement-another")


def test_brief_save_cas_retry_clear_never_recovers_old_text(project):
    s, state, c, owner, wid, a, b = project
    c.save_brief(owner, wid, 0, "BRIEF_SECRET_CANARY", "", "", "brief-save-001")
    run = start(project)
    assert "BRIEF_SECRET_CANARY" in json.dumps(c.snapshot(owner, run))
    s.finish(owner, run, "completed", content="BRIEF_SECRET_CANARY paraphrase")
    with pytest.raises(WorkspaceError, match="stale_brief_revision"):
        c.save_brief(owner, wid, 0, "stale", "", "", "brief-save-stale")
    c.save_brief(owner, wid, 1, "", "", "", "brief-clear-001")
    assert c.save_brief(owner, wid, 1, "", "", "", "brief-clear-001")["revision"] == 2
    assert "BRIEF_SECRET_CANARY" not in json.dumps(c.preview(owner, wid, "next", {}))


def test_memory_clear_cannot_revive_snapshot_or_recent_messages(project):
    s, state, c, owner, wid, a, b = project
    memory = state.save_memory(owner, wid, "MEMORY_PRIVATE_CANARY", "memory-save-001")
    run = start(project)
    c.snapshot(owner, run)
    s.finish(owner, run, "completed", content="MEMORY_PRIVATE_CANARY used")
    state.delete_memory(owner, wid, memory["id"], memory["version"], "memory-delete-001")
    assert c.run_context(owner, run)["status"] == "unavailable"
    assert "MEMORY_PRIVATE_CANARY" not in json.dumps(c.preview(owner, wid, "next", {}))


def test_brief_change_cancels_active_run_before_publication(project):
    s, state, c, owner, wid, a, b = project
    run = start(project)
    c.snapshot(owner, run)
    c.save_brief(owner, wid, 0, "new", "", "", "brief-change-001")
    with pytest.raises(WorkspaceError, match="cancelled"):
        s.publish(owner, run, "late-write", "Late", "late.md", "# Must not appear")
    assert not s.items(owner, wid, "artifacts")


def test_large_old_history_is_not_loaded_and_transcript_preserved(project):
    s, state, c, owner, wid, a, b = project
    run = start(project)
    c.snapshot(owner, run)
    s.finish(owner, run, "completed", content="A" * 20000, history="X" * 700000)
    before = s.items(owner, wid, "messages")
    manifest = c.preview(owner, wid, "next", {})
    assert manifest["context_bytes"] <= MAX_CONTEXT
    assert "X" * 1000 not in json.dumps(manifest)
    assert s.items(owner, wid, "messages") == before


def test_imported_archive_not_automatic_model_history(project):
    s, state, c, owner, wid, a, b = project
    run = start(project)
    c.snapshot(owner, run)
    s.finish(owner, run, "completed", content="ARCHIVED_PRIVATE_CANARY")
    importer = SnapshotImporter(s)
    raw = DataLifecycle(s).export(owner, wid)
    encoded = base64.b64encode(raw).decode()
    preview = importer.preview(owner, encoded, "Imported", False)
    result = importer.commit(owner, encoded, "Imported", False, preview["confirmation_token"], "import-snapshot-001")
    assert "ARCHIVED_PRIVATE_CANARY" not in json.dumps(c.preview(owner, result["workspace"]["id"], "next", {}))


def test_snapshot_preserves_brief_replacements_and_archived_claims(project):
    s, state, c, owner, wid, a, b = project
    c.save_brief(owner, wid, 0, "Museum", "Preserve 120.50", "Update", "brief-save-001")
    run = start(project, context={"references": [{"kind": "file", "id": a["id"]}]})
    c.snapshot(owner, run)
    out = s.publish(owner, run, "publish-001", "Draft", "draft.md", "# 120.50")
    s.finish(owner, run, "completed")
    c.replace(owner, wid, a["id"], b["id"], "replace-source-001")
    raw = DataLifecycle(s).export(owner, wid)
    assert inspect_archive(raw)["continuity"]["brief"]["goal"] == "Museum"
    importer = SnapshotImporter(s)
    encoded = base64.b64encode(raw).decode()
    preview = importer.preview(owner, encoded, "Restored", False)
    result = importer.commit(owner, encoded, "Restored", False, preview["confirmation_token"], "import-snapshot-001")
    new_wid = result["workspace"]["id"]
    assert c.brief(owner, new_wid)["goal"] == "Museum"
    output = s.items(owner, new_wid, "artifacts")[0]
    assert c.dependencies(owner, output["id"])["status"] == "unknown"
    assert s.artifact(owner, output["id"])["import_lineage"]["archived_dependency_claims"]
    assert "archived only" in result["omissions"][-1]


def test_deletion_purges_new_scoped_records(project):
    s, state, c, owner, wid, a, b = project
    c.save_brief(owner, wid, 0, "PRIVATE_HANDOVER", "", "", "brief-save-001")
    run = start(project)
    c.snapshot(owner, run)
    s.finish(owner, run, "completed")
    lifecycle = DataLifecycle(s)
    preview = lifecycle.preview(owner, wid)
    lifecycle.delete(owner, wid, preview["confirmation_token"], "Synthetic museum project", "delete-project-001")
    with s.tx() as db:
        for table in ("project_briefs", "continuity_requests", "run_contexts", "context_reads", "source_replacements", "artifact_dependencies"):
            assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE workspace_id=?", (wid,)).fetchone()[0] == 0
