"""AW08 builder verification. Synthetic deterministic storage/ASGI, not real AI."""
import io
import json
import subprocess
import sys
import os
import zipfile

import pytest
from fastapi.testclient import TestClient

from agent_workspace.api import create_app
from agent_workspace.config import Settings
from agent_workspace.operations import (FORMAT, FORMAT_FILE, LEGACY_FORMAT, backup_data,
                                        inspect_data, restore_data, upgrade_data)
from agent_workspace.runtime import Runtime
from agent_workspace.data_lifecycle import DataLifecycle
from agent_workspace.source_kit import build_kit
from agent_workspace.store import Store, WorkspaceError

LIMITS = dict(deadline_seconds=120, request_limit=8, tool_limit=16, token_limit=32000, output_bytes_limit=256000)


def seed(path):
    store = Store(path / "catalogue.sqlite")
    runtime = Runtime(Settings(path, test_mode=True), store)
    _, owner = store.session(None)
    wid = store.workspaces(owner, "Synthetic co-editing")['id']
    artifact = store.create_artifact(owner, wid, "Draft", "document", "# Original\n\nFirst 001.\n\nLast 14.50 kg.\n", "aw08-manual-original")
    return runtime, store, owner, wid, artifact


def propose(runtime, owner, wid, artifact, content=None, *, finish=True, command="write", request="aw08-producer-01"):
    store = runtime.store
    run = store.create_run(owner, wid, "fixture:review", request, LIMITS,
                           context=dict(target=dict(kind="artifact", id=artifact["id"], version=artifact["version"]), review_edits=True))
    rid = run['id']
    runtime.workspace_state.bind_run_epoch(owner, rid)
    runtime.connections.bind_run(owner, rid)
    runtime.continuity.snapshot(owner, rid)
    if command == "patch":
        result = store.patch(owner, rid, "aw08-write", artifact["id"], artifact["version"], "First 001.", "Changed 001.")
    else:
        result = store.publish(owner, rid, "aw08-write", artifact["title"], artifact["filename"], content or "Intro\n\n" + artifact["content"] + "\nClosing\n", artifact["id"], artifact["version"])
    if finish:
        store.finish(owner, rid, "completed", content="Synthetic proposed result")
    return result["candidate_id"], rid


def test_proposal_subset_ack_loss_and_original_saved_state(tmp_path):
    runtime, store, owner, wid, artifact = seed(tmp_path)
    pid, rid = propose(runtime, owner, wid, artifact)
    value = runtime.reviews.get(owner, pid)
    assert len(value["changes"]) == 2 and value["can_decide"]
    assert store.artifact(owner, artifact['id'])['version'] == 1
    selected = [value["changes"][0]["id"]]
    result = runtime.reviews.decide(owner, pid, "accept", selected, "aw08-accept-0001")
    assert result['version'] == 2
    saved = store.artifact(owner, artifact['id'])
    assert saved['content'] == "Intro\n\n" + artifact['content']
    store.revise(owner, artifact['id'], 2, saved['content'] + "Manual\n", "aw08-later-manual")
    assert runtime.reviews.decide(owner, pid, "accept", selected, "aw08-accept-0001") == result
    assert store.artifact(owner, artifact['id'], 2)['content'] == saved['content']
    with pytest.raises(WorkspaceError, match="idempotency_conflict"):
        runtime.reviews.decide(owner, pid, "reject", [], "aw08-accept-0001")
    with store.tx() as db:
        receipt = db.execute("SELECT result FROM receipts WHERE run_id=? AND kind='artifact.proposal'", (rid,)).fetchone()[0]
        assert "Closing" not in receipt and "Intro" not in receipt


@pytest.mark.parametrize("command", ["write", "patch"])
def test_existing_tools_intercept_only_optin(tmp_path, command):
    runtime, store, owner, wid, artifact = seed(tmp_path)
    pid, _ = propose(runtime, owner, wid, artifact, command=command)
    assert store.artifact(owner, artifact['id'])['version'] == 1
    result = runtime.reviews.get(owner, pid)
    runtime.reviews.decide(owner, pid, "accept", [c['id'] for c in result['changes']], "aw08-all-accept-01")
    assert store.artifact(owner, artifact['id'])['version'] == 2


@pytest.mark.parametrize("failure", ["inflight", "failed", "cancelled", "stale", "foreign", "duplicate", "unknown"])
def test_proposal_failure_is_atomic(tmp_path, failure):
    runtime, store, owner, wid, artifact = seed(tmp_path)
    pid, rid = propose(runtime, owner, wid, artifact, finish=failure != "inflight")
    change = runtime.reviews.listing(owner, wid)['items'][0]
    with store.tx() as db:
        ids = [c['id'] for c in json.loads(db.execute("SELECT changes FROM artifact_proposals WHERE id=?", (pid,)).fetchone()[0])]
        if failure in {"failed", "cancelled"}:
            db.execute("UPDATE runs SET state=? WHERE id=?", (failure, rid))
    expected = 1
    if failure == "stale":
        store.revise(owner, artifact['id'], 1, "Manual preserved", "aw08-stale-write-01")
        expected = 2
    if failure == "foreign":
        _, owner = store.session(None)
    if failure == "duplicate":
        ids += [ids[0]]
    if failure == "unknown":
        ids = ["other-proposal:change-1"]
    with pytest.raises(WorkspaceError):
        runtime.reviews.decide(owner, pid, "accept", ids, "aw08-invalid-01")
    if failure == "inflight":
        with pytest.raises(WorkspaceError, match="proposal_producer_not_completed"):
            runtime.reviews.decide(owner, pid, "reject", [], "aw08-inflight-reject")
    with store.tx() as db:
        assert db.execute("SELECT version FROM artifacts WHERE id=?", (artifact['id'],)).fetchone()[0] == expected
        assert db.execute("SELECT COUNT(*) FROM proposal_decisions").fetchone()[0] == 0
    assert change['status'] == 'pending'


@pytest.mark.parametrize("privacy", ["memory", "brief", "connection"])
def test_proposal_scope_revocation_cannot_resurrect(tmp_path, privacy):
    runtime, store, owner, wid, artifact = seed(tmp_path)
    if privacy == "memory":
        memory = runtime.workspace_state.save_memory(owner, wid, "Synthetic forgotten memory", "aw08-memory-01")
    pid, _ = propose(runtime, owner, wid, artifact)
    ids = [c['id'] for c in runtime.reviews.get(owner, pid)['changes']]
    if privacy == "memory":
        runtime.workspace_state.delete_memory(owner, wid, memory['id'], memory['version'], "aw08-memory-delete")
    elif privacy == "brief":
        runtime.continuity.save_brief(owner, wid, 0, "New goal", "", "", "aw08-brief-change")
    else:
        runtime.connections.set_connection(owner, wid, True, 0, "aw08-grant-change")
    with pytest.raises(WorkspaceError):
        runtime.reviews.get(owner, pid)
    with pytest.raises(WorkspaceError):
        runtime.reviews.decide(owner, pid, "accept", ids, "aw08-revoked-accept")
    if privacy != "connection":
        with store.tx() as db:
            assert db.execute("SELECT COUNT(*) FROM artifact_proposals").fetchone()[0] == 0


def test_csv_logical_rows_multiline_and_subset_values(tmp_path):
    runtime, store, owner, wid, _ = seed(tmp_path)
    content = 'id,value\n001,"first\nline"\n002,unchanged\n003,14.50 kg\n'
    artifact = store.create_artifact(owner, wid, "Table", "table", content, "aw08-table-original")
    proposed = content.replace('first\nline', 'edited\nline').replace('14.50 kg', '=TEXT(14.50)')
    pid, _ = propose(runtime, owner, wid, artifact, proposed)
    candidate = runtime.reviews.get(owner, pid)
    assert candidate['diff_unit'] == 'csv_row' and len(candidate['changes']) == 2
    runtime.reviews.decide(owner, pid, 'accept', [candidate['changes'][0]['id']], 'aw08-table-subset')
    assert store.artifact(owner, artifact['id'])['content'] == content.replace('first\nline', 'edited\nline')


def test_reject_and_invalid_review_options(tmp_path):
    runtime, store, owner, wid, artifact = seed(tmp_path)
    for context in ({"review_edits": True}, {"review_edits": "yes"}, {"target": dict(kind="artifact", id=artifact['id'], version=1), "approval": True}):
        with pytest.raises(WorkspaceError):
            store.create_run(owner, wid, 'invalid', 'aw08-invalid-options', LIMITS, context=context)
    pid, _ = propose(runtime, owner, wid, artifact)
    assert runtime.reviews.decide(owner, pid, 'reject', [], 'aw08-reject-01')['status'] == 'rejected'
    assert store.artifact(owner, artifact['id'])['version'] == 1


@pytest.mark.parametrize("state", ["stale", "failed", "cancelled", "revoked"])
def test_reject_disposes_terminal_blocked_proposal_without_publication(tmp_path, state):
    runtime, store, owner, wid, artifact = seed(tmp_path)
    pid, rid = propose(runtime, owner, wid, artifact)
    if state == "stale":
        store.revise(owner, artifact['id'], 1, "New base", "aw08-reject-stale-base")
    elif state == "revoked":
        runtime.connections.set_connection(owner, wid, True, 0, "aw08-reject-revoked")
    else:
        with store.tx() as db:
            db.execute("UPDATE runs SET state=? WHERE id=?", (state, rid))
    before = store.artifact(owner, artifact['id'])
    summary = runtime.reviews.listing(owner, wid)['items'][0]
    assert summary['can_reject'] and not summary['can_decide']
    result = runtime.reviews.decide(owner, pid, 'reject', [], 'aw08-terminal-reject')
    assert result['status'] == 'rejected' and result['version'] is None
    assert runtime.reviews.decide(owner, pid, 'reject', [], 'aw08-terminal-reject') == result
    assert store.artifact(owner, artifact['id']) == before
    if state != "stale":
        with pytest.raises(WorkspaceError):
            runtime.reviews.get(owner, pid)


def test_handoff_exact_old_versions_private_omissions_and_readback(tmp_path):
    runtime, store, owner, wid, artifact = seed(tmp_path)
    store.revise(owner, artifact['id'], 1, 'NEW UNSELECTED VERSION', 'aw08-unselected-version')
    runtime.workspace_state.save_memory(owner, wid, 'PRIVATE MEMORY CANARY', 'aw08-private-memory')
    data = runtime.reviews.handoff(owner, wid, [dict(artifact_id=artifact['id'], version=1, format='docx')])
    with zipfile.ZipFile(io.BytesIO(data)) as zipped:
        manifest = json.loads(zipped.read('manifest.json'))
        assert manifest['entries'][0]['version'] == 1
        assert 'PRIVATE MEMORY CANARY' not in json.dumps(manifest)
        from docx import Document
        document = Document(io.BytesIO(zipped.read(manifest['entries'][0]['member'])))
        text = '\n'.join(p.text for p in document.paragraphs)
        assert 'First 001.' in text and '14.50 kg.' in text and 'NEW UNSELECTED' not in text


def test_handoff_scope_before_render_and_epoch_after_render(tmp_path, monkeypatch):
    runtime, store, owner, wid, artifact = seed(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('Rendering must follow complete scope validation')
    monkeypatch.setattr('agent_workspace.reviews.render_artifact', forbidden)
    with pytest.raises(WorkspaceError, match='not_found'):
        runtime.reviews.handoff(owner, wid, [dict(artifact_id=artifact['id'], version=1, format='md'), dict(artifact_id='foreign', version=1, format='md')])
    from agent_workspace.formats import render_artifact
    def changed(*args, **kwargs):
        result = render_artifact(*args, **kwargs)
        runtime.continuity.save_brief(owner, wid, 0, 'Changed while rendering', '', '', 'aw08-render-epoch')
        return result
    monkeypatch.setattr('agent_workspace.reviews.render_artifact', changed)
    with pytest.raises(WorkspaceError, match='handoff_scope_changed'):
        runtime.reviews.handoff(owner, wid, [dict(artifact_id=artifact['id'], version=1, format='md')])


def test_aw07_backup_restore_requires_explicit_aw08_upgrade(tmp_path):
    data = tmp_path / 'old'
    data.mkdir(mode=0o700)
    _, store, _, _, _ = seed(data)
    with store.tx() as db:
        db.execute('DROP TABLE artifact_proposals')
        db.execute('DROP TABLE proposal_decisions')
    (data / FORMAT_FILE).write_text(json.dumps(LEGACY_FORMAT))
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    archive = private / 'aw07.zip'
    backup_data(data, archive)
    destination = tmp_path / 'restored'
    result = restore_data(archive, destination)
    assert result['upgrade_required'] and json.loads((destination / FORMAT_FILE).read_text()) == LEGACY_FORMAT
    with pytest.raises(WorkspaceError, match='data_upgrade_required'):
        with TestClient(create_app(Settings(destination)), base_url='http://localhost'):
            pass
    upgrade_data(destination)
    assert json.loads((destination / FORMAT_FILE).read_text()) == FORMAT
    assert inspect_data(destination)['upgrade_required'] is False
    with TestClient(create_app(Settings(destination)), base_url='http://localhost'):
        pass


def test_extracted_source_kit_pdf_uses_bundled_fonts(tmp_path):
    archive = tmp_path / 'pilot.zip'
    build_kit(archive)
    kit = tmp_path / 'kit'
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(kit)
        assert 'v2/apps/workspace/src/agent_workspace/assets/LICENSE-NOTO.txt' in zipped.namelist()
    source = kit / 'v2/apps/workspace/src'
    # render_artifact uses multiprocessing spawn, so execute a real script/module
    # with a main guard instead of python -c and preserve explicit kit PYTHONPATH.
    script = """from agent_workspace.formats import render_artifact
import io
from pypdf import PdfReader
if __name__ == '__main__':
 output=render_artifact('document','Đối chiếu Việt Nam: 001 và 14.50 kg.','pdf','Tài liệu')
 text=''.join(p.extract_text() for p in PdfReader(io.BytesIO(output.data)).pages)
 assert 'Việt Nam' in text and '001' in text and '14.50 kg' in text
 print('kit-pdf-readback-pass')
"""
    path = kit / 'pdf_probe.py'
    path.write_text(script)
    result = subprocess.check_output([sys.executable, str(path)], env={"PATH": os.environ.get('PATH', ''), "PYTHONPATH": str(source)}, text=True)
    assert 'kit-pdf-readback-pass' in result


def test_private_aw08_backup_keeps_unpublished_candidate_without_replay(tmp_path):
    data = tmp_path / 'data'
    data.mkdir(mode=0o700)
    runtime, store, owner, wid, artifact = seed(data)
    pid, _ = propose(runtime, owner, wid, artifact)
    from agent_workspace.operations import initialize_format
    initialize_format(data)
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    archive = private / 'aw08.zip'
    backup_data(data, archive)
    restored = tmp_path / 'restored'
    assert restore_data(archive, restored)['replay_started'] is False
    next_store = Store(restored / 'catalogue.sqlite')
    next_runtime = Runtime(Settings(restored, test_mode=True), next_store)
    assert next_runtime.reviews.get(owner, pid)['status'] == 'pending'
    assert next_store.artifact(owner, artifact['id'])['version'] == 1
    assert not next_runtime.started


def test_workspace_delete_removes_pending_bodies_and_decision_state(tmp_path):
    runtime, store, owner, wid, artifact = seed(tmp_path)
    pid, _ = propose(runtime, owner, wid, artifact)
    lifecycle = DataLifecycle(store)
    preview = lifecycle.preview(owner, wid)
    lifecycle.delete(owner, wid, preview['confirmation_token'], preview['name'], 'aw08-workspace-delete')
    with pytest.raises(WorkspaceError, match='not_found'):
        runtime.reviews.get(owner, pid)
    with store.tx() as db:
        assert db.execute('SELECT COUNT(*) FROM artifact_proposals').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM proposal_decisions').fetchone()[0] == 0


def test_partial_subset_exceeding_save_bound_fails_atomically(tmp_path):
    runtime, store, owner, wid, artifact = seed(tmp_path)
    base = '# Heading\n\n' + 'A' * 140000 + '\n\n' + 'B' * 100000 + '\n'
    artifact = store.revise(owner, artifact['id'], 1, base, 'aw08-large-base')
    proposed = '# Heading\n\n' + 'B' * 100000 + '\n\n' + 'C' * 140000 + '\n'
    pid, _ = propose(runtime, owner, wid, artifact, proposed)
    candidate = runtime.reviews.get(owner, pid)
    insertion = [c['id'] for c in candidate['changes'] if 'C' in c['new_text']]
    with pytest.raises(WorkspaceError, match='invalid_proposal_subset'):
        runtime.reviews.decide(owner, pid, 'accept', insertion, 'aw08-too-large-subset')
    assert store.artifact(owner, artifact['id'])['content'] == base
    assert runtime.reviews.get(owner, pid)['status'] == 'pending'
