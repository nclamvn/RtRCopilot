"""Separate-author AW-06 probes. Real local SQLite/ASGI, synthetic inputs only.

These probes establish scoped deterministic contracts, not model quality,
provider latency/billing or human acceptance. Runtime-specific tests use the
product's explicit FunctionModel simulation; no network provider is available.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import json
import time
import zipfile

from fastapi.testclient import TestClient
import pytest

from agent_workspace.api import create_app
from agent_workspace.config import Settings
from agent_workspace.data_lifecycle import DataLifecycle
from agent_workspace.portability import SnapshotImporter
from agent_workspace.runtime import Runtime
from agent_workspace.store import Store, WorkspaceError

P = "/api/workspace"
ORIGIN = {"origin": "http://localhost:3110"}
LIMITS = dict(deadline_seconds=120, request_limit=8, tool_limit=16,
              token_limit=32000, output_bytes_limit=256000)


class NoDispatch(Runtime):
    """Actual services, but no worker/provider for mutation contract probes."""
    async def start(self):
        pass

    async def close(self):
        pass

    async def dispatch_pending(self):
        pass

    def status(self):
        return dict(available=True, test_mode=True, model="NO DISPATCH",
                    reason=None, recovery="not running")


def post(client, path, data=None):
    return client.post(P + path, headers=ORIGIN, json=data or {})


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def wid(client, name="Independent synthetic arboretum"):
    return ok(post(client, "/workspaces", {"name": name}))["id"]


def upload(client, workspace, filename="sample.txt", content="Lot 000731: quantity 17.625. Tiếng Việt."):
    return ok(post(client, f"/workspaces/{workspace}/files", {
        "filename": filename, "content": content, "media_type": "text/plain"}))


def artifact(client, workspace, content="# Arboretum\n\nLot 000731 has quantity 17.625."):
    return ok(post(client, f"/workspaces/{workspace}/artifacts", {
        "title": "Synthetic arboretum brief", "kind": "document",
        "content": content, "request_id": "review-create-artifact"}))


def preview(client, workspace, references=None, target=None, message="Describe lot 000731"):
    return post(client, f"/workspaces/{workspace}/context-preview", {
        "message": message, "references": references or [], "target": target})


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(tmp_path, test_mode=True), runtime_factory=NoDispatch)
    with TestClient(app, base_url="http://localhost") as client:
        ok(post(client, "/session"))
        yield client


def test_brief_cas_idempotency_empty_clear_and_foreign_owner(api):
    space = wid(api)
    initial = ok(api.get(P + f"/workspaces/{space}/brief"))
    args = {"goal": "Assess synthetic lot 000731", "decisions": "Use 17.625 kilograms",
            "remaining": "Check summer count", "expected_revision": initial["revision"],
            "request_id": "review-brief-save"}
    saved = ok(post(api, f"/workspaces/{space}/brief", args))
    assert saved["revision"] > initial["revision"]
    assert saved["goal"] == args["goal"]
    assert ok(post(api, f"/workspaces/{space}/brief", args))["revision"] == saved["revision"]
    assert post(api, f"/workspaces/{space}/brief", args | {"goal": "Changed same key"}).status_code == 409
    assert post(api, f"/workspaces/{space}/brief", args | {"request_id": "review-stale-brief"}).status_code == 409
    cleared = ok(post(api, f"/workspaces/{space}/brief", dict(goal="", decisions="", remaining="",
        expected_revision=saved["revision"], request_id="review-clear-brief")))
    assert [cleared[k] for k in ("goal", "decisions", "remaining")] == ["", "", ""]
    api.cookies.clear()
    ok(post(api, "/session"))
    assert api.get(P + f"/workspaces/{space}/brief").status_code == 404
    assert post(api, f"/workspaces/{space}/brief", args).status_code == 404


def test_context_exact_historical_revision_not_current_content(api):
    space = wid(api)
    output = artifact(api, space, "# VERSION_ONE\n\nNumber 000731 and 17.625.")
    aid = output.get("id", output.get("artifact_id"))
    ok(post(api, f"/artifacts/{aid}/revisions", dict(expected_version=1,
        content="# VERSION_TWO\n\nNumber 000731 and 91.875.", request_id="review-revise-output")))
    value = ok(preview(api, space, [{"kind": "artifact", "id": aid, "version": 1}]))
    encoded = json.dumps(value)
    assert "VERSION_ONE" in encoded and "VERSION_TWO" not in encoded
    assert preview(api, space, [{"kind": "artifact", "id": aid, "version": 999}]).status_code in {400, 404, 409, 422}


def test_same_owner_other_workspace_context_and_search_never_leak(api):
    first, second = wid(api), wid(api, "Unrelated synthetic work")
    foreign = upload(api, second, content="PRIVATE_REVIEW_CANARY_69317")
    result = preview(api, first, [{"kind": "file", "id": foreign["id"]}])
    assert result.status_code == 404
    assert "PRIVATE_REVIEW_CANARY_69317" not in result.text
    matches = ok(api.get(P + f"/workspaces/{first}/search?q=PRIVATE_REVIEW_CANARY_69317"))
    assert "PRIVATE_REVIEW_CANARY_69317" not in json.dumps(matches)
    api.cookies.clear()
    ok(post(api, "/session"))
    assert api.get(P + f"/workspaces/{second}/search?q=PRIVATE").status_code == 404
    assert preview(api, second).status_code == 404


def test_duplicate_reference_and_invalid_version_are_not_ambiguous(api):
    space = wid(api)
    file = upload(api, space)
    ref = {"kind": "file", "id": file["id"]}
    result = preview(api, space, [ref, ref])
    assert result.status_code in {200, 400, 422}
    # A file is immutable, not an arbitrary version or filesystem path handle.
    assert preview(api, space, [ref | {"version": 2}]).status_code in {400, 404, 422}
    assert preview(api, space, [{"kind": "file", "id": "/etc/passwd"}]).status_code == 404
    assert preview(api, space, [{"kind": "system", "id": file["id"]}]).status_code in {400, 422}


def test_replacement_idempotency_cycle_ambiguity_and_immutable_original(api):
    space = wid(api)
    a = upload(api, space, "first.txt", "LOT_A original 000731: 17.625")
    b = upload(api, space, "second.txt", "LOT_B replacement 000731: 18.125")
    c = upload(api, space, "third.txt", "LOT_C divergent 000731: 19.625")
    args = dict(old_file_id=a["id"], new_file_id=b["id"], request_id="review-replacement")
    path = f"/workspaces/{space}/source-replacements"
    ok(post(api, path, args))
    ok(post(api, path, args))
    assert post(api, path, args | {"new_file_id": c["id"]}).status_code == 409
    assert post(api, path, args | {"new_file_id": c["id"], "request_id": "review-divergent"}).status_code in {400, 409}
    assert post(api, path, dict(old_file_id=b["id"], new_file_id=a["id"], request_id="review-cycle-link")).status_code in {400, 409}
    original = ok(api.get(P + f"/files/{a['id']}"))
    assert original["content"] == "LOT_A original 000731: 17.625"
    assert post(api, path, dict(old_file_id=a["id"], new_file_id=a["id"], request_id="review-self-link")).status_code in {400, 409, 422}


def test_source_replacement_same_owner_other_workspace_rejected(api):
    first, second = wid(api), wid(api, "Separate replacement project")
    old = upload(api, first)
    foreign = upload(api, second)
    assert post(api, f"/workspaces/{first}/source-replacements", dict(
        old_file_id=old["id"], new_file_id=foreign["id"], request_id="review-foreign-link")).status_code == 404


def test_run_request_identity_includes_context_choices(api):
    space = wid(api)
    a = upload(api, space, "a.txt", "A content")
    b = upload(api, space, "b.txt", "B content")
    args = dict(workspace_id=space, message="Synthetic command", client_request_id="review-run-context",
        context={"references": [{"kind": "file", "id": a["id"]}], "target": None})
    one = ok(post(api, "/runs", args))
    two = ok(post(api, "/runs", args))
    assert one["run_id"] == two["run_id"]
    changed = args | {"context": {"references": [{"kind": "file", "id": b["id"]}], "target": None}}
    assert post(api, "/runs", changed).status_code == 409


def test_legacy_manual_output_lineage_is_unknown_not_verified(api):
    space = wid(api)
    output = artifact(api, space)
    aid = output.get("id", output.get("artifact_id"))
    lineage = ok(api.get(P + f"/artifacts/{aid}/dependencies?version=1"))
    text = json.dumps(lineage).lower()
    assert "unknown" in text or "unrecorded" in text
    assert api.get(P + f"/artifacts/{aid}/dependencies?version=99").status_code in {400, 404, 422}
    api.cookies.clear()
    ok(post(api, "/session"))
    assert api.get(P + f"/artifacts/{aid}/dependencies?version=1").status_code == 404


def seeded_run(api, space, key="review-snapshot-run", references=None, target=None, message="Synthetic task"):
    store = api.app.state.store
    owner = store.authenticate(api.cookies.get("workspace_session"))
    run = store.create_run(owner, space, message, key, LIMITS,
        context={"references": references or [], "target": target})
    api.app.state.runtime.workspace_state.bind_run_epoch(owner, run["id"])
    manifest = api.app.state.runtime.continuity.snapshot(owner, run["id"])
    return store, owner, run["id"], manifest


def test_context_snapshot_persists_exact_input_across_reopen_and_later_upload(api):
    space = wid(api)
    source = upload(api, space)
    store, owner, run, snapshot = seeded_run(api, space, references=[{"kind": "file", "id": source["id"]}])
    upload(api, space, "later.txt", "LATE_UPLOAD_MUST_NOT_ENTER_SNAPSHOT")
    current = api.app.state.runtime.continuity.snapshot(owner, run)
    assert current == snapshot
    from agent_workspace.continuity import Continuity
    reopened = Continuity(Store(store.path))
    assert reopened.snapshot(owner, run) == snapshot
    assert "LATE_UPLOAD_MUST_NOT_ENTER_SNAPSHOT" not in json.dumps(ok(api.get(P + f"/runs/{run}/context")))
    api.cookies.clear()
    ok(post(api, "/session"))
    assert api.get(P + f"/runs/{run}/context").status_code == 404


def test_cleared_project_brief_cannot_return_as_recent_model_input(api):
    space = wid(api)
    secret = "DELETED_BRIEF_REVIEW_CANARY_61928"
    ok(post(api, f"/workspaces/{space}/brief", dict(goal=secret, decisions="", remaining="",
        expected_revision=0, request_id="review-secret-brief")))
    store, owner, run, _ = seeded_run(api, space)
    store.finish(owner, run, "completed", content="Prior assistant repeated " + secret,
                 history=json.dumps([{"secret": secret}]))
    before = ok(preview(api, space))
    assert secret in json.dumps(before)
    ok(post(api, f"/workspaces/{space}/brief", dict(goal="", decisions="", remaining="",
        expected_revision=1, request_id="review-forget-brief")))
    assert secret not in json.dumps(ok(preview(api, space)))
    assert secret not in json.dumps(ok(api.get(P + f"/runs/{run}/context")))
    # Visible history remains user-owned archival content, not reusable agent input.
    assert secret in json.dumps(ok(api.get(P + f"/workspaces/{space}/messages")))


def test_memory_delete_fences_cached_context_and_never_reintroduces_old_answer(api):
    space = wid(api)
    secret = "DELETED_MEMORY_REVIEW_CANARY_93441"
    memory = ok(post(api, f"/workspaces/{space}/memory", dict(content=secret, request_id="review-memory-save")))
    store, owner, run, _ = seeded_run(api, space)
    store.finish(owner, run, "completed", content="Previous output " + secret, history="old opaque protocol")
    assert secret in json.dumps(ok(preview(api, space)))
    active = store.create_run(owner, space, "still pending", "review-memory-consumer", LIMITS)
    api.app.state.runtime.workspace_state.bind_run_epoch(owner, active["id"])
    api.app.state.runtime.continuity.snapshot(owner, active["id"])
    ok(post(api, f"/workspaces/{space}/memory/{memory['id']}/delete", dict(
        expected_version=memory["version"], request_id="review-memory-drop")))
    assert store.run(owner, active["id"])["cancel_requested"] is True
    with pytest.raises(WorkspaceError):
        api.app.state.runtime.continuity.snapshot(owner, active["id"])
    assert secret not in json.dumps(ok(preview(api, space)))
    assert secret not in json.dumps(ok(api.get(P + f"/runs/{run}/context")))


def test_long_visible_turn_is_omitted_whole_and_original_history_preserved(api):
    space = wid(api)
    store, owner, run, _ = seeded_run(api, space, message="Very long earlier synthetic exchange")
    # Under the existing 256KB output cap, but above the 64KB context cap.
    body = "LONG_ARCHIVED_TURN_" * 6000
    store.finish(owner, run, "completed", content=body, history="SDK_HISTORY_SENTINEL_" * 30000)
    manifest = ok(preview(api, space))
    assert len(json.dumps(manifest).encode()) < 70000
    assert body not in json.dumps(manifest)
    assert manifest["omissions"]
    assert not any(m["content"].startswith("LONG_ARCHIVED_TURN_") for m in manifest["recent_messages"])
    with store.tx() as db:
        assert len(db.execute("SELECT history FROM runs WHERE id=?", (run,)).fetchone()[0]) > 512000
    assert len(ok(api.get(P + f"/workspaces/{space}/messages"))["items"][-1]["content"]) == len(body)


def test_exact_pinned_read_stale_target_and_cancel_preserve_manual_revision(api):
    space = wid(api)
    output = artifact(api, space, "# ORIGINAL_PINNED_VERSION\n\n17.625.")
    aid = output.get("id", output.get("artifact_id"))
    target = {"kind": "artifact", "id": aid, "version": 1}
    store, owner, run, _ = seeded_run(api, space, target=target)
    ok(post(api, f"/artifacts/{aid}/revisions", dict(expected_version=1,
        content="# MANUAL_LATEST_VERSION\n\n18.625.", request_id="review-manual-while-run")))
    assert "ORIGINAL_PINNED_VERSION" in store.read_artifact(owner, run, aid)["content"]
    with pytest.raises(WorkspaceError, match="stale_artifact_version"):
        store.publish(owner, run, "review-agent-write", "Synthetic", "draft.md", "Late model version", aid, 1)
    with pytest.raises(WorkspaceError, match="stale_artifact_version"):
        store.publish(owner, run, "review-new-bypass", "Synthetic", "new.md", "Bypass target")
    store.cancel(owner, run)
    with pytest.raises(WorkspaceError):
        store.publish(owner, run, "review-cancelled", "Synthetic", "draft.md", "After cancellation", aid, 2)
    assert "MANUAL_LATEST_VERSION" in store.artifact(owner, aid)["content"]
    assert len(store.versions(owner, aid)) == 2


def test_replacement_stales_only_recorded_dependency_and_keeps_versions(api):
    space = wid(api)
    a = upload(api, space, "used.txt", "USED_REVIEW_SOURCE 17.625")
    b = upload(api, space, "replacement.txt", "NEW_REVIEW_SOURCE 18.125")
    c = upload(api, space, "unrelated.txt", "UNRELATED_REVIEW_SOURCE 91.125")
    store, owner, first, _ = seeded_run(api, space, references=[{"kind": "file", "id": a["id"]}])
    used = store.publish(owner, first, "review-used-output", "Used source output", "used.md", "Output from 17.625")
    store.finish(owner, first, "completed")
    _, _, second, _ = seeded_run(api, space, key="review-unrelated-run", references=[{"kind": "file", "id": c["id"]}])
    unrelated = store.publish(owner, second, "review-unrelated-output", "Unrelated source output", "unrelated.md", "Output from 91.125")
    store.finish(owner, second, "completed")
    ok(post(api, f"/workspaces/{space}/source-replacements", dict(
        old_file_id=a["id"], new_file_id=b["id"], request_id="review-affect-only-used")))
    stale = ok(api.get(P + f"/artifacts/{used['artifact_id']}/dependencies?version=1"))
    fresh = ok(api.get(P + f"/artifacts/{unrelated['artifact_id']}/dependencies?version=1"))
    assert stale["stale"] is True and stale["status"] == "known"
    assert fresh["stale"] is False
    assert "NEW_REVIEW_SOURCE" not in store.artifact(owner, used["artifact_id"])["content"]
    assert store.source(owner, a["id"])["content"] == "USED_REVIEW_SOURCE 17.625"


def test_brief_parallel_cas_has_one_winner_and_restart_replay_returns_current(api):
    space = wid(api)
    runtime = api.app.state.runtime
    store = api.app.state.store
    owner = store.authenticate(api.cookies.get("workspace_session"))
    def attempt(n):
        try:
            return runtime.continuity.save_brief(owner, space, 0, f"Synthetic goal {n}", "", "", f"review-race-brief-{n}")
        except WorkspaceError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    winners = [r for r in results if isinstance(r, dict)]
    assert len(winners) == 1 and "stale_brief_revision" in results
    winner = winners[0]
    ok(post(api, f"/workspaces/{space}/brief", dict(goal="Current explicit goal", decisions="", remaining="",
        expected_revision=winner["revision"], request_id="review-brief-newer")))
    from agent_workspace.continuity import Continuity
    reopened = Continuity(Store(store.path))
    number = int(winner["goal"].rsplit(" ", 1)[1])
    replay = reopened.save_brief(owner, space, 0, winner["goal"], "", "", f"review-race-brief-{number}")
    assert replay["goal"] == "Current explicit goal"


def test_snapshot_brief_links_preserved_but_archived_claims_not_live_authority(api):
    space = wid(api)
    a = upload(api, space, "before.txt", "Synthetic 17.625")
    b = upload(api, space, "after.txt", "Synthetic 18.125")
    ok(post(api, f"/workspaces/{space}/brief", dict(goal="Compare arboretum counts",
        decisions="Retain 000731 identifier", remaining="Review next sample", expected_revision=0,
        request_id="review-export-brief")))
    store, owner, run, _ = seeded_run(api, space, references=[{"kind": "file", "id": a["id"]}])
    output = store.publish(owner, run, "review-export-output", "Count comparison", "counts.md", "Count is 17.625")
    store.finish(owner, run, "completed", content="ARCHIVED_DIALOGUE_REVIEW_CANARY_18327")
    ok(post(api, f"/workspaces/{space}/source-replacements", dict(old_file_id=a["id"], new_file_id=b["id"],
        request_id="review-export-link")))
    raw = DataLifecycle(store).export(owner, space)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        extension = json.loads(z.read("continuity.json"))
    assert extension["brief"]["goal"] == "Compare arboretum counts"
    assert len(extension["artifact_dependencies"]) == 1
    importer = SnapshotImporter(store)
    encoded = base64.b64encode(raw).decode()
    pre = importer.preview(owner, encoded, "Restored independent project", False)
    result = importer.commit(owner, encoded, "Restored independent project", False,
        pre["confirmation_token"], "review-restore-context")
    restored = result["workspace"]["id"]
    assert restored != space
    assert ok(api.get(P + f"/workspaces/{restored}/brief"))["goal"] == extension["brief"]["goal"]
    maps = importer.lineage(owner, restored)["id_map"]
    with store.tx() as db:
        link = db.execute("SELECT old_file_id,new_file_id FROM source_replacements WHERE workspace_id=?", (restored,)).fetchone()
        assert tuple(link) == (maps["files"][a["id"]], maps["files"][b["id"]])
        assert not db.execute("SELECT 1 FROM runs WHERE workspace_id=?", (restored,)).fetchone()
    copied_aid = maps["artifacts"][output["artifact_id"]]
    copied = store.artifact(owner, copied_aid)
    archived = copied["import_lineage"]["archived_dependency_claims"]
    assert archived and archived[0]["id"] == a["id"]
    assert "untrusted" in copied["import_lineage"]["authority"]
    assert ok(api.get(P + f"/artifacts/{copied_aid}/dependencies"))["status"] == "unknown"
    manifest = ok(preview(api, restored))
    assert manifest["recent_messages"] == []
    assert "ARCHIVED_DIALOGUE_REVIEW_CANARY_18327" not in json.dumps(manifest)


def test_delete_preview_invalidates_on_brief_change_and_purges_new_content(api):
    space = wid(api)
    source = upload(api, space)
    store, owner, run, _ = seeded_run(api, space, references=[{"kind": "file", "id": source["id"]}])
    output = store.publish(owner, run, "review-delete-output", "Disposable", "delete.md", "Temporary draft")
    store.finish(owner, run, "completed")
    lifecycle = DataLifecycle(store)
    stale = lifecycle.preview(owner, space)
    ok(post(api, f"/workspaces/{space}/brief", dict(goal="DELETE_REVIEW_CONTENT_91329", decisions="", remaining="",
        expected_revision=0, request_id="review-before-delete")))
    with pytest.raises(WorkspaceError, match="delete_confirmation_stale"):
        lifecycle.delete(owner, space, stale["confirmation_token"], stale["name"], "review-stale-delete")
    fresh = lifecycle.preview(owner, space)
    assert lifecycle.delete(owner, space, fresh["confirmation_token"], fresh["name"], "review-delete-final")["deleted"]
    with store.tx() as db:
        for table in ("project_briefs", "continuity_requests", "source_replacements", "run_contexts", "context_reads", "artifact_dependencies"):
            assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE workspace_id=?", (space,)).fetchone()[0] == 0
    for path in (f"/workspaces/{space}/brief", f"/runs/{run}/context", f"/artifacts/{output['artifact_id']}/dependencies"):
        assert api.get(P + path).status_code == 404
    assert preview(api, space).status_code == 404


def test_transitive_source_freshness_is_not_lost_when_reading_a_derived_output(api):
    space = wid(api)
    a = upload(api, space, "basis.txt", "Synthetic basis 17.625")
    b = upload(api, space, "new-basis.txt", "Synthetic new basis 18.125")
    store, owner, first, _ = seeded_run(api, space, references=[{"kind": "file", "id": a["id"]}])
    parent = store.publish(owner, first, "review-parent-output", "Parent", "parent.md", "Parent draft from basis")
    store.finish(owner, first, "completed")
    _, _, second, _ = seeded_run(api, space, key="review-derived-run", references=[{
        "kind": "artifact", "id": parent["artifact_id"], "version": 1}])
    child = store.publish(owner, second, "review-child-output", "Child", "child.md", "Derived draft")
    store.finish(owner, second, "completed")
    ok(post(api, f"/workspaces/{space}/source-replacements", dict(
        old_file_id=a["id"], new_file_id=b["id"], request_id="review-transitive-link")))
    assert ok(api.get(P + f"/artifacts/{child['artifact_id']}/dependencies"))["stale"] is True


def test_final_compact_context_respects_its_advertised_byte_cap(api):
    from agent_workspace.continuity import encode, render_prompt
    space = wid(api)
    refs = [{"kind": "file", "id": upload(api, space, f"budget{i}.txt", "x" * 4000)["id"]} for i in range(8)]
    store = api.app.state.store
    owner = store.authenticate(api.cookies.get("workspace_session"))
    service = api.app.state.runtime.continuity
    # Binary search the exact accepted UTF-8 boundary, not one convenient input.
    low, high, accepted = 0, 4000, None
    revision = 0
    while low <= high:
        middle = (low + high) // 2
        revision = service.save_brief(owner, space, revision, "β" * middle + "b" * (4000 - middle),
            "c" * 4000, "d" * 4000, f"review-byte-budget-{middle}")["revision"]
        response = preview(api, space, refs, message="m" * 16000)
        if response.status_code == 413:
            high = middle - 1
        else:
            value = ok(response)
            accepted = value
            assert len(encode(value)) + 16000 <= value["limit_bytes"]
            assert len(render_prompt("m" * 16000, value).encode()) == value["context_bytes"]
            assert value["context_bytes"] <= value["limit_bytes"]
            low = middle + 1
    assert accepted is not None


def test_actual_simulation_continues_without_deserializing_oversized_old_protocol(tmp_path):
    app = create_app(Settings(tmp_path, test_mode=True))
    with TestClient(app, base_url="http://localhost") as client:
        ok(post(client, "/session"))
        space = wid(client)
        first = ok(post(client, "/runs", dict(workspace_id=space, message="fixture:chat",
            client_request_id="review-real-first")))["run_id"]
        for _ in range(250):
            state = ok(client.get(P + f"/runs/{first}"))
            if state["state"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(.02)
        assert state["state"] == "completed", state
        with app.state.store.tx() as db:
            db.execute("UPDATE runs SET history=? WHERE id=?", ("OVERSIZED_UNPARSEABLE_OLD_PROTOCOL" * 19000, first))
        second = ok(post(client, "/runs", dict(workspace_id=space, message="fixture:chat",
            client_request_id="review-real-second")))["run_id"]
        for _ in range(250):
            state = ok(client.get(P + f"/runs/{second}"))
            if state["state"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(.02)
        assert state["state"] == "completed", state
        context = ok(client.get(P + f"/runs/{second}/context"))
        assert "OVERSIZED_UNPARSEABLE_OLD_PROTOCOL" not in json.dumps(context)
        assert len(context["recent_messages"]) == 2
        assert len(ok(client.get(P + f"/workspaces/{space}/messages"))["items"]) == 4


def test_same_run_target_progression_reads_own_revision_without_changing_original_pin(api):
    space = wid(api)
    output = artifact(api, space, "# Baseline\n\nCount 17.625.")
    aid = output.get("id", output.get("artifact_id"))
    store, owner, run, initial = seeded_run(api, space, target={"kind": "artifact", "id": aid, "version": 1})
    one = store.publish(owner, run, "review-own-first", "Revised count", "counts.md", "# First update\n\nCount 18.125.", aid, 1)
    assert one["version"] == 2
    read = store.read_artifact(owner, run, aid)
    assert read["version"] == 2 and "18.125" in read["content"]
    repaired = store.patch(owner, run, "review-own-repair", aid, 2, "18.125", "18.625")
    assert repaired["version"] == 3
    assert store.read_artifact(owner, run, aid)["version"] == 3
    assert store.artifact(owner, aid, 1)["content"] == "# Baseline\n\nCount 17.625."
    actual = ok(api.get(P + f"/runs/{run}/context"))
    assert actual["target"]["version"] == initial["target"]["version"] == 1
    assert any(r["id"] == aid and r["version"] == 2 for r in actual["read_ledger"])
    assert len(store.versions(owner, aid)) == 3


def test_manual_interleave_after_own_target_update_cannot_be_adopted_as_own_progress(api):
    space = wid(api)
    output = artifact(api, space, "# Baseline\n\nOriginal.")
    aid = output.get("id", output.get("artifact_id"))
    store, owner, run, _ = seeded_run(api, space, target={"kind": "artifact", "id": aid, "version": 1})
    store.publish(owner, run, "review-progress-first", "Agent update", "counts.md", "# Agent version two", aid, 1)
    ok(post(api, f"/artifacts/{aid}/revisions", dict(expected_version=2,
        content="# Manual interleave version three", request_id="review-manual-interleave")))
    # A model cannot simply read the manual head and use that version to
    # authorize an overwrite outside the contiguous versions it owns.
    with pytest.raises(WorkspaceError, match="stale_artifact_version"):
        store.publish(owner, run, "review-wrongly-adopt-manual", "Agent overwrite", "counts.md", "Overwrite manual", aid, 3)
    assert store.artifact(owner, aid)["content"] == "# Manual interleave version three"
    assert len(store.versions(owner, aid)) == 3


def test_changed_artifact_version_is_detected_beyond_one_dependency_hop(api):
    space = wid(api)
    first = artifact(api, space, "# Root input version one")
    first_id = first.get("id", first.get("artifact_id"))
    store, owner, parent_run, _ = seeded_run(api, space, references=[{"kind": "artifact", "id": first_id, "version": 1}])
    parent = store.publish(owner, parent_run, "review-grandparent-parent", "Parent draft", "parent.md", "Parent from root")
    store.finish(owner, parent_run, "completed")
    _, _, child_run, _ = seeded_run(api, space, key="review-grandchild-run", references=[{
        "kind": "artifact", "id": parent["artifact_id"], "version": 1}])
    child = store.publish(owner, child_run, "review-parent-child", "Child draft", "child.md", "Child from parent")
    store.finish(owner, child_run, "completed")
    ok(post(api, f"/artifacts/{first_id}/revisions", dict(expected_version=1,
        content="# Root input version two", request_id="review-change-grandparent")))
    deps = ok(api.get(P + f"/artifacts/{child['artifact_id']}/dependencies"))
    assert deps["stale"] is True


def test_exhausted_edit_quota_still_allows_bounded_forgetting_of_brief(api):
    space = wid(api)
    service = api.app.state.runtime.continuity
    store = api.app.state.store
    owner = store.authenticate(api.cookies.get("workspace_session"))
    service.save_brief(owner, space, 0, "QUOTA_ERASURE_REVIEW_CANARY_71638", "", "", "review-quota-seed")
    with store.tx() as db:
        db.executemany("INSERT INTO continuity_requests VALUES(?,?,?,?)", [
            (owner, f"review-quota-fill-{i}", space, "0" * 64) for i in range(1999)])
    cleared = service.save_brief(owner, space, 1, "", "", "", "review-quota-forget")
    assert cleared["goal"] == ""
    assert "QUOTA_ERASURE_REVIEW_CANARY_71638" not in json.dumps(ok(preview(api, space)))
    for i in range(3):
        cleared = service.save_brief(owner, space, cleared["revision"], "", "", "", f"review-already-clear-{i}")
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM continuity_requests WHERE workspace_id=?", (space,)).fetchone()[0] <= 2001
