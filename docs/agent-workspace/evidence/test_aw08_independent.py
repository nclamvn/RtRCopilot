"""AW08 separate-author, synthetic ASGI/SQLite structural probes, not AI evals."""
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from agent_workspace.api import create_app
from agent_workspace.config import Settings
from agent_workspace.runtime import Runtime
from agent_workspace.store import Store, WorkspaceError

PREFIX = "/api/workspace"
ORIGIN = {"origin": "http://localhost:3110"}
PRIVATE = "AW08-PRIVATE-MEMORY-CANARY-073191"
BASE = "# Synthetic field report\n\nAlpha: 101.25 mm.\n\nUnchanged separator: ID 007.\n\nBeta: 91.625 kg.\n"
PROPOSED = BASE.replace("101.25", "102.75").replace("91.625", "92.875")


class NoDispatch(Runtime):
    async def start(self):
        pass

    async def close(self):
        pass

    async def dispatch_pending(self):
        pass

    def status(self):
        return dict(available=True, test_mode=True, model="scripted structural probe", reason=None, recovery="not running")


def request(client, path, payload=None):
    if payload is None:
        return client.get(PREFIX + path)
    return client.post(PREFIX + path, headers=ORIGIN, json=payload)


def okay(response):
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def app_case(tmp_path):
    app = create_app(Settings(tmp_path / "data", test_mode=True), runtime_factory=NoDispatch)
    with TestClient(app, base_url="http://localhost") as client:
        okay(request(client, "/session", {}))
        owner = app.state.store.authenticate(client.cookies.get("workspace_session"))
        workspace = okay(request(client, "/workspaces", {"name": "Independent synthetic AW08"}))
        artifact = okay(request(client, f"/workspaces/{workspace['id']}/artifacts", dict(title="Field report", kind="document", content=BASE, request_id="independent-aw08-create")))
        yield dict(app=app, client=client, owner=owner, workspace=workspace["id"], artifact=artifact, path=tmp_path / "data")


def candidate(case, content=PROPOSED, key="independent-review-1", terminal="completed"):
    client, runtime, store = case["client"], case["app"].state.runtime, case["app"].state.store
    item = store.artifact(case["owner"], case["artifact"]["id"])
    context = {"target": {"kind": "artifact", "id": item["id"], "version": item["version"]}, "review_edits": True}
    result = okay(request(client, "/runs", dict(workspace_id=case["workspace"], message="Review the proposed exact changes", client_request_id=key, context=context)))
    rid = result["run_id"]
    runtime.workspace_state.bind_run_epoch(case["owner"], rid)
    runtime.connections.bind_run(case["owner"], rid)
    runtime.continuity.snapshot(case["owner"], rid)
    output = store.publish(case["owner"], rid, key + "-call", item["title"], item["filename"], content, item["id"], item["version"])
    listing = okay(request(client, f"/workspaces/{case['workspace']}/proposals"))
    entries = listing["items"]
    assert len(entries) >= 1
    entry = next(item for item in entries if item["run_id"] == rid)
    assert store.artifact(case["owner"], item["id"])["version"] == item["version"], "A candidate must not publish the current artifact"
    assert content not in json.dumps(output), "Reusable tool result must not cache the private candidate body"
    if terminal is not None:
        store.finish(case["owner"], rid, terminal, content="Synthetic producer finished" if terminal == "completed" else None, history="[]")
    response = request(client, f"/proposals/{entry['id']}")
    if terminal == "completed":
        proposed = okay(response)
    else:
        assert response.status_code == 409, "Unfinished/failed/cancelled producer body must not be exposed as ready"
        with store.tx() as db:
            row = db.execute("SELECT changes FROM artifact_proposals WHERE id=?", (entry["id"],)).fetchone()
        proposed = dict(entry, changes=json.loads(row[0]))
    return proposed, rid


def decision(case, proposal, change_ids, key="independent-decision-1", action="accept"):
    return request(case["client"], f"/proposals/{proposal['id']}/decision", dict(decision=action, change_ids=change_ids, request_id=key))


def test_independent_partial_exact_save_and_ack_replay(app_case):
    case = app_case
    proposal, _ = candidate(case)
    ids = [change["id"] for change in proposal["changes"]]
    assert len(ids) == 2
    first = okay(decision(case, proposal, ids[:1]))
    second = okay(decision(case, proposal, ids[:1]))
    assert first == second
    saved = case["app"].state.store.artifact(case["owner"], case["artifact"]["id"])
    assert saved["version"] == 2
    assert saved["content"] == BASE.replace("101.25", "102.75")
    assert case["app"].state.store.artifact(case["owner"], saved["id"], 1)["content"] == BASE
    changed = decision(case, proposal, ids, key="independent-decision-1")
    assert changed.status_code == 409
    assert case["app"].state.store.artifact(case["owner"], saved["id"])["version"] == 2


@pytest.mark.parametrize("selection", ["duplicate", "foreign", "empty"])
def test_independent_bad_change_ids_cannot_mutate(app_case, selection):
    proposal, _ = candidate(app_case)
    valid = proposal["changes"][0]["id"]
    ids = [valid, valid] if selection == "duplicate" else ["unowned-change-073191"] if selection == "foreign" else []
    assert decision(app_case, proposal, ids).status_code in {400, 409, 422}
    assert app_case["app"].state.store.artifact(app_case["owner"], app_case["artifact"]["id"])["content"] == BASE


@pytest.mark.parametrize("state", [None, "failed", "cancelled"])
def test_independent_noncompleted_producer_cannot_publish(app_case, state):
    proposal, _ = candidate(app_case, terminal=state)
    assert decision(app_case, proposal, [c["id"] for c in proposal["changes"]]).status_code == 409
    assert app_case["app"].state.store.artifact(app_case["owner"], app_case["artifact"]["id"])["version"] == 1


def test_independent_review_interception_replay_changed_args_and_new_artifact_fence(app_case):
    proposal, rid = candidate(app_case, terminal=None)
    store = app_case["app"].state.store
    item = store.artifact(app_case["owner"], app_case["artifact"]["id"])
    replay = store.publish(app_case["owner"], rid, "independent-review-1-call", item["title"], item["filename"], PROPOSED, item["id"], 1)
    assert PROPOSED not in json.dumps(replay)
    assert len(okay(request(app_case["client"], f"/workspaces/{app_case['workspace']}/proposals"))["items"]) == 1
    with pytest.raises(WorkspaceError):
        store.publish(app_case["owner"], rid, "independent-review-1-call", item["title"], item["filename"], PROPOSED + "changed", item["id"], 1)
    with pytest.raises(WorkspaceError):
        store.publish(app_case["owner"], rid, "independent-rogue-create", "Rogue output", "draft.md", "Must not create an unrelated artifact")
    assert len(store.items(app_case["owner"], app_case["workspace"], "artifacts")) == 1
    assert store.artifact(app_case["owner"], item["id"])["version"] == 1


def test_independent_reject_and_replay_do_not_publish(app_case):
    proposal, _ = candidate(app_case)
    first = okay(decision(app_case, proposal, [], action="reject"))
    assert okay(decision(app_case, proposal, [], action="reject")) == first
    assert decision(app_case, proposal, [c["id"] for c in proposal["changes"]], key="independent-after-reject").status_code == 409
    assert app_case["app"].state.store.artifact(app_case["owner"], app_case["artifact"]["id"])["version"] == 1


def test_independent_stale_base_preserves_candidate_and_existing_edit(app_case):
    proposal, _ = candidate(app_case)
    store = app_case["app"].state.store
    store.revise(app_case["owner"], app_case["artifact"]["id"], 1, BASE + "Manual concurrent edit.\n", "independent-manual-concurrent")
    assert decision(app_case, proposal, [c["id"] for c in proposal["changes"]]).status_code == 409
    saved = store.artifact(app_case["owner"], app_case["artifact"]["id"])
    assert saved["version"] == 2 and saved["content"].endswith("Manual concurrent edit.\n")
    assert request(app_case["client"], f"/proposals/{proposal['id']}").status_code == 200


def test_independent_memory_erasure_removes_pending_private_candidate_and_receipts(app_case):
    runtime = app_case["app"].state.runtime
    memory = runtime.workspace_state.save_memory(app_case["owner"], app_case["workspace"], PRIVATE, "independent-memory-save")
    proposal, _ = candidate(app_case, PROPOSED + PRIVATE)
    runtime.workspace_state.delete_memory(app_case["owner"], app_case["workspace"], memory["id"], memory["version"], "independent-memory-delete")
    assert request(app_case["client"], f"/proposals/{proposal['id']}").status_code in {404, 409}
    assert decision(app_case, proposal, [c["id"] for c in proposal["changes"]]).status_code in {404, 409}
    with app_case["app"].state.store.tx() as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        leaked = []
        for table in tables:
            for row in db.execute(f'SELECT * FROM "{table}"'):
                if any(isinstance(value, str) and PRIVATE in value for value in row):
                    leaked.append(table)
        assert not leaked, "Deleted private candidate bodies remain in live tables: " + ",".join(sorted(set(leaked)))


def test_independent_foreign_actor_cannot_read_or_decide_candidate(app_case):
    proposal, _ = candidate(app_case)
    client = app_case["client"]
    client.cookies.clear()
    okay(request(client, "/session", {}))
    assert request(client, f"/proposals/{proposal['id']}").status_code == 404
    assert decision(app_case, proposal, [c["id"] for c in proposal["changes"]]).status_code == 404


def test_independent_revoked_bound_connection_blocks_candidate_get_and_decision(app_case):
    runtime = app_case["app"].state.runtime
    runtime.connections.set_connection(app_case["owner"], app_case["workspace"], True, 0, "independent-grant-enable")
    proposal, _ = candidate(app_case)
    runtime.connections.set_connection(app_case["owner"], app_case["workspace"], False, 1, "independent-grant-revoke")
    assert request(app_case["client"], f"/proposals/{proposal['id']}").status_code == 409
    assert decision(app_case, proposal, [c["id"] for c in proposal["changes"]]).status_code == 409
    assert app_case["app"].state.store.artifact(app_case["owner"], app_case["artifact"]["id"])["version"] == 1


def test_independent_reject_revoked_candidate_is_cleanup_not_body_reauthorization(app_case):
    runtime = app_case["app"].state.runtime
    runtime.connections.set_connection(app_case["owner"], app_case["workspace"], True, 0, "independent-cleanup-grant")
    proposal, _ = candidate(app_case)
    runtime.connections.set_connection(app_case["owner"], app_case["workspace"], False, 1, "independent-cleanup-revoke")
    result = okay(decision(app_case, proposal, [], action="reject"))
    assert result["status"] == "rejected" and result["version"] is None
    assert okay(decision(app_case, proposal, [], action="reject")) == result
    assert request(app_case["client"], f"/proposals/{proposal['id']}").status_code == 409
    assert app_case["app"].state.store.artifact(app_case["owner"], app_case["artifact"]["id"])["version"] == 1


def handoff(case, selections):
    return request(case["client"], f"/workspaces/{case['workspace']}/handoff", {"selections": selections})


def test_independent_handoff_exact_old_version_no_unselected_or_private_state(app_case):
    store = app_case["app"].state.store
    wid, owner, aid = app_case["workspace"], app_case["owner"], app_case["artifact"]["id"]
    store.upload(owner, wid, "secret-source.txt", PRIVATE, "text/plain")
    app_case["app"].state.runtime.workspace_state.save_memory(owner, wid, PRIVATE, "independent-handoff-memory")
    store.create_artifact(owner, wid, "Unselected private output", "document", PRIVATE, "independent-unselected-output")
    store.revise(owner, aid, 1, BASE + "Newer saved version.\n", "independent-new-version")
    response = handoff(app_case, [dict(artifact_id=aid, version=1, format="md")])
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    assert all(PRIVATE.encode() not in raw for raw in members.values())
    assert all(not name.endswith((".sqlite", ".db")) and not any(part in name for part in ("memory", "session", "proposal")) for name in members)
    contents = [raw for name, raw in members.items() if name.endswith(".md")]
    assert contents == [BASE.encode()]
    manifest = json.loads(next(raw for name, raw in members.items() if name.endswith(".json")))
    assert "Newer saved version" not in json.dumps(manifest)
    assert hashlib.sha256(BASE.encode()).hexdigest() in json.dumps(manifest)


def test_independent_handoff_invalid_selection_is_atomic(app_case):
    aid = app_case["artifact"]["id"]
    bad = [dict(artifact_id=aid, version=1, format="md"), dict(artifact_id="foreign-073191", version=1, format="md")]
    response = handoff(app_case, bad)
    assert response.status_code in {400, 404, 409, 422}
    assert "application/zip" not in response.headers.get("content-type", "")
    duplicate = handoff(app_case, [dict(artifact_id=aid, version=1, format="md")] * 2)
    assert duplicate.status_code in {400, 409, 422}


@pytest.mark.parametrize("format", ["docx", "pdf"])
def test_independent_handoff_document_binary_readback(app_case, format):
    response = handoff(app_case, [dict(artifact_id=app_case["artifact"]["id"], version=1, format=format)])
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        chosen = [archive.read(name) for name in archive.namelist() if name.endswith("." + format)]
    assert len(chosen) == 1
    if format == "docx":
        from docx import Document
        text = "\n".join(p.text for p in Document(io.BytesIO(chosen[0])).paragraphs)
    else:
        from pypdf import PdfReader
        text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(chosen[0])).pages)
    for retained in ("Synthetic field report", "Alpha: 101.25 mm.", "ID 007.", "Beta: 91.625 kg."):
        assert retained in text


def test_independent_handoff_xlsx_string_values_and_no_formula_execution(app_case):
    content = 'id,metric,note,formula\n007,91.625,"Tiếng Việt\nsecond line",=1+1\n008,102.750,"quoted ""unit""",@SUM(A1)\n'
    item = app_case["app"].state.store.create_artifact(app_case["owner"], app_case["workspace"], "Synthetic string table", "table", content, "independent-table-create")
    response = handoff(app_case, [dict(artifact_id=item["id"], version=1, format="xlsx")])
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        chosen = next(archive.read(name) for name in archive.namelist() if name.endswith(".xlsx"))
    from openpyxl import load_workbook
    sheet = load_workbook(io.BytesIO(chosen), data_only=False).active
    rows = list(sheet.iter_rows(values_only=True))
    assert rows == [tuple(row) for row in csv.reader(io.StringIO(content))]
    assert all(cell.data_type != "f" for row in sheet for cell in row)
    assert app_case["app"].state.store.artifact(app_case["owner"], item["id"])["content"] == content


@pytest.mark.parametrize("extra", [{"approved": True}, {"base_content": "forged"}, {"owner": "foreign"}])
def test_independent_client_authority_fields_are_rejected(app_case, extra):
    proposal, _ = candidate(app_case)
    response = request(app_case["client"], f"/proposals/{proposal['id']}/decision", dict(decision="accept", change_ids=[c["id"] for c in proposal["changes"]], request_id="independent-forged-client", **extra))
    assert response.status_code in {400, 422}
    assert app_case["app"].state.store.artifact(app_case["owner"], app_case["artifact"]["id"])["version"] == 1


def test_independent_logical_csv_row_partial_review_preserves_quoted_cells(app_case):
    store = app_case["app"].state.store
    base = 'id,value,note\r\n007,91.625,"Tiếng Việt\nsecond line"\r\n008,0,separator\r\n009,101.250,"quoted ""unit"""\r\n'
    proposed = base.replace("91.625", "92.875").replace("101.250", "102.750")
    item = store.create_artifact(app_case["owner"], app_case["workspace"], "Logical row test", "table", base, "independent-csv-review")
    app_case["artifact"] = item
    proposal, _ = candidate(app_case, proposed)
    assert proposal["diff_unit"] == "csv_row" and len(proposal["changes"]) == 2
    okay(decision(app_case, proposal, [proposal["changes"][0]["id"]]))
    saved = store.artifact(app_case["owner"], item["id"])
    assert list(csv.reader(io.StringIO(saved["content"], newline=""))) == list(csv.reader(io.StringIO(base.replace("91.625", "92.875"), newline="")))
    assert store.artifact(app_case["owner"], item["id"], 1)["content"] == base


@pytest.mark.parametrize("mutation", ["memory_epoch", "workspace_delete"])
def test_independent_handoff_rechecks_privacy_after_render(app_case, monkeypatch, mutation):
    from agent_workspace import reviews
    original = reviews.render_artifact
    def rendering(*args, **kwargs):
        output = original(*args, **kwargs)
        if mutation == "memory_epoch":
            app_case["app"].state.runtime.workspace_state.save_memory(app_case["owner"], app_case["workspace"], "New private state", "independent-handoff-race-memory")
        else:
            lifecycle = app_case["app"].state.lifecycle
            preview = lifecycle.preview(app_case["owner"], app_case["workspace"])
            lifecycle.delete(app_case["owner"], app_case["workspace"], preview["confirmation_token"], "Independent synthetic AW08", "independent-handoff-race-delete")
        return output
    monkeypatch.setattr(reviews, "render_artifact", rendering)
    response = handoff(app_case, [dict(artifact_id=app_case["artifact"]["id"], version=1, format="md")])
    assert response.status_code in {404, 409}, response.text
    assert "application/zip" not in response.headers.get("content-type", "")


def test_independent_handoff_foreign_validation_precedes_any_renderer(app_case, monkeypatch):
    from agent_workspace import reviews
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("Foreign selection must be rejected before any rendering")
    monkeypatch.setattr(reviews, "render_artifact", forbidden)
    response = handoff(app_case, [dict(artifact_id=app_case["artifact"]["id"], version=1, format="md"),
                                  dict(artifact_id="foreign-independent", version=1, format="docx")])
    assert response.status_code == 404 and not calls


def test_independent_extracted_kit_asgi_pdf_handoff_vietnamese_readback(tmp_path):
    """Bounded source kit, explicit installed runtime reuse; no clean-machine claim."""
    from agent_workspace.source_kit import build_kit, verify_kit
    archive = tmp_path / "pilot.zip"
    build_kit(archive)
    verify_kit(archive)
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        for name in ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "LICENSE-NOTO.txt"):
            member = "v2/apps/workspace/src/agent_workspace/assets/" + name
            assert member in names and len(package.read(member)) > 100
        package.extractall(extracted)
    source = extracted / "v2/apps/workspace/src"
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(source), "PYTHONNOUSERSITE": "1", "PYDANTIC_AI_NO_BANNER": "1"}
    program = '''
import io, json, pathlib, sys, zipfile
from fastapi.testclient import TestClient
from pypdf import PdfReader
from agent_workspace import formats
from agent_workspace.api import create_app
from agent_workspace.config import Settings
from agent_workspace.runtime import Runtime
class NoDispatch(Runtime):
    async def start(self): pass
    async def close(self): pass
    async def dispatch_pending(self): pass
    def status(self): return dict(available=True,test_mode=True,model="fixture",reason=None,recovery="not running")
assert pathlib.Path(formats.__file__).is_relative_to(pathlib.Path(sys.argv[1]))
prefix="/api/workspace"; headers={"origin":"http://localhost:3110"}
app=create_app(Settings(pathlib.Path(sys.argv[1])/"synthetic-data",test_mode=True),runtime_factory=NoDispatch)
with TestClient(app,base_url="http://localhost") as c:
    assert c.post(prefix+"/session",headers=headers,json={}).status_code==200
    w=c.post(prefix+"/workspaces",headers=headers,json={"name":"Extracted synthetic pilot"}).json()
    body={"title":"Phân tích độc lập","kind":"document","content":"# Báo cáo tổng hợp\\n\\nMã 007. Khối lượng 91.625 kg. Độ ẩm 102.750 mm.","request_id":"independent-kit-document"}
    a=c.post(prefix+"/workspaces/"+w["id"]+"/artifacts",headers=headers,json=body)
    assert a.status_code==200,a.text
    response=c.post(prefix+"/workspaces/"+w["id"]+"/handoff",headers=headers,json={"selections":[{"artifact_id":a.json()["id"],"version":1,"format":"pdf"}]})
    assert response.status_code==200,response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        pdf=z.read(next(n for n in z.namelist() if n.endswith(".pdf")))
    text="\\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    for retained in ("Báo cáo tổng hợp","Mã 007","Khối lượng 91.625 kg","Độ ẩm 102.750 mm"):
        assert retained in text,repr(text)
print(json.dumps({"extracted_package":True,"asgi_handoff":True,"vietnamese_readback":True,"real_ai_accepted":False}))
'''
    result = subprocess.run([sys.executable, "-c", program, str(extracted)], cwd=extracted,
                            env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report == dict(extracted_package=True, asgi_handoff=True, vietnamese_readback=True, real_ai_accepted=False)


def test_independent_concurrent_decisions_publish_only_one_version(app_case):
    proposal, _ = candidate(app_case)
    reviews = app_case["app"].state.runtime.reviews
    ids = [change["id"] for change in proposal["changes"]]
    def choose(key):
        try:
            return reviews.decide(app_case["owner"], proposal["id"], "accept", ids, key)["status"]
        except WorkspaceError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(choose, ["independent-concurrent-one", "independent-concurrent-two"]))
    assert results.count("accepted") == 1 and results.count("proposal_already_decided") == 1
    assert app_case["app"].state.store.artifact(app_case["owner"], app_case["artifact"]["id"])["version"] == 2


def test_independent_content_snapshot_does_not_export_pending_candidate_authority(app_case):
    candidate(app_case, PROPOSED + PRIVATE)
    response = request(app_case["client"], f"/workspaces/{app_case['workspace']}/export")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert all(PRIVATE.encode() not in archive.read(name) for name in archive.namelist())
        assert all("proposal" not in name for name in archive.namelist())


def test_independent_aw07_private_restore_keeps_old_marker_until_explicit_upgrade(tmp_path):
    from agent_workspace import operations as op
    legacy = tmp_path / "aw07-data"
    legacy.mkdir(mode=0o700)
    store = Store(legacy / "catalogue.sqlite")
    NoDispatch(Settings(legacy, test_mode=True), store)
    token, owner = store.session(None)
    wid = store.workspaces(owner, "Legacy synthetic AW07")["id"]
    item = store.create_artifact(owner, wid, "Retained exact document", "document", BASE, "independent-legacy-artifact")
    with store.tx() as db:
        for table in op.PROPOSAL_TABLES:
            db.execute(f"DROP TABLE {table}")
    (legacy / op.FORMAT_FILE).write_bytes(op.encoded(op.LEGACY_FORMAT))
    assert op.inspect_data(legacy)["upgrade_required"]
    archive = tmp_path / "private" / "aw07.zip"
    op.backup_data(legacy, archive)
    restored = tmp_path / "restored-aw07"
    outcome = op.restore_data(archive, restored)
    assert outcome["upgrade_required"] and not outcome["replay_started"]
    assert json.loads((restored / op.FORMAT_FILE).read_bytes()) == op.LEGACY_FORMAT
    with pytest.raises(WorkspaceError) as refusal:
        with TestClient(create_app(Settings(restored, test_mode=True), runtime_factory=NoDispatch), base_url="http://localhost"):
            pytest.fail("Old metadata must not open the AW08 runtime")
    assert refusal.value.code == "data_upgrade_required"
    op.upgrade_data(restored)
    assert json.loads((restored / op.FORMAT_FILE).read_bytes()) == op.FORMAT
    with TestClient(create_app(Settings(restored, test_mode=True), runtime_factory=NoDispatch), base_url="http://localhost") as client:
        client.cookies.set("workspace_session", token)
        assert okay(request(client, f"/artifacts/{item['id']}"))["content"] == BASE
    assert json.loads((legacy / op.FORMAT_FILE).read_bytes()) == op.LEGACY_FORMAT


def test_independent_decision_ack_replay_after_actual_asgi_restart(tmp_path):
    path = tmp_path / "restart-data"
    app = create_app(Settings(path, test_mode=True), runtime_factory=NoDispatch)
    with TestClient(app, base_url="http://localhost") as client:
        okay(request(client, "/session", {}))
        token = client.cookies.get("workspace_session")
        owner = app.state.store.authenticate(token)
        wid = okay(request(client, "/workspaces", {"name": "Restart synthetic"}))["id"]
        item = okay(request(client, f"/workspaces/{wid}/artifacts", dict(title="Restart report", kind="document", content=BASE, request_id="independent-restart-create")))
        first_case = dict(app=app, client=client, owner=owner, workspace=wid, artifact=item)
        proposal, _ = candidate(first_case)
        ids = [change["id"] for change in proposal["changes"]]
        first = okay(decision(first_case, proposal, ids, key="independent-restart-decision"))
    restarted = create_app(Settings(path, test_mode=True), runtime_factory=NoDispatch)
    with TestClient(restarted, base_url="http://localhost") as client:
        client.cookies.set("workspace_session", token)
        new_case = dict(app=restarted, client=client, owner=owner, workspace=wid, artifact=item)
        replay = okay(decision(new_case, proposal, ids, key="independent-restart-decision"))
        assert replay == first
        assert okay(request(client, f"/artifacts/{item['id']}"))["version"] == 2
        assert decision(new_case, proposal, ids[:1], key="independent-restart-decision").status_code == 409
