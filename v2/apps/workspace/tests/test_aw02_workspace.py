"""AW02 real local API/store I/O. Scripted responses are not semantic AI evidence."""
import base64
import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from agent_workspace.api import create_app
from agent_workspace.config import Settings
from agent_workspace.store import Store, WorkspaceError
from test_workspace import P, post, start, terminal, workspace


@pytest.fixture(scope="module")
def aw02(tmp_path_factory):
    with TestClient(create_app(Settings(tmp_path_factory.mktemp("workspace-aw02"), test_mode=True)), base_url="http://localhost") as client:
        post(client, "/session")
        yield client


def test_batch_partial_preview_chunks_download_and_isolation(aw02):
    c = aw02
    wid = workspace(c)
    text = "Đầu nguồn 120.35 Việt Nam\n" + "x" * 70000 + "\nLAST-TAIL-135000"
    response = post(c, f"/workspaces/{wid}/files/batch", {"files": [
        {"filename": "large.txt", "content_base64": base64.b64encode(text.encode()).decode()},
        {"filename": "../bad.txt", "content": "no"},
        {"filename": "corrupt.docx", "content_base64": "eA=="},
        {"filename": "bad.txt", "content_base64": "not base64"},
        {"filename": "second.md", "content": "Second source: 240 units."},
    ]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["accepted"]) == 2 and len(result["errors"]) == 3
    source = result["accepted"][0]
    assert source["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    offset, chunks = 0, []
    while True:
        part = c.get(P + f"/files/{source['id']}?offset={offset}&limit=16000").json()
        chunks.append(part["content"])
        if not part["has_more"]:
            break
        offset = part["next_offset"]
    assert "".join(chunks) == text
    assert c.get(P + f"/files/{source['id']}/download").content == text.encode()
    assert c.get(P + f"/files/{source['id']}?limit=99999").status_code == 400
    rid = start(c, wid, "fixture:brief", "aw02-chunked-brief")
    final = terminal(c, rid)
    assert final["state"] == "completed", final
    artifact = c.get(P + f"/workspaces/{wid}/artifacts").json()["items"][0]
    content = c.get(P + f"/artifacts/{artifact['id']}").json()["content"]
    assert text in content and "Second source: 240" in content
    token = c.cookies.get("workspace_session")
    c.cookies.clear()
    post(c, "/session")
    assert c.get(P + f"/files/{source['id']}").status_code == 404
    assert c.get(P + f"/files/{source['id']}/download").status_code == 404
    assert post(c, f"/workspaces/{wid}/research/search", {"query": "Harbor"}).status_code == 404
    c.cookies.clear()
    c.cookies.set("workspace_session", token)


def create_draft(c, suffix="draft"):
    wid = workspace(c)
    post(c, f"/workspaces/{wid}/files", {"filename": "source.txt", "content": "Budget: 120.50\nUnicode: Việt Nam\nKeep this source reference."})
    rid = start(c, wid, "fixture:create", "aw02-create-" + suffix)
    assert terminal(c, rid)["state"] == "completed"
    artifact = c.get(P + f"/workspaces/{wid}/artifacts").json()["items"][0]
    return wid, c.get(P + f"/artifacts/{artifact['id']}").json()


def test_manual_versions_diff_duplicate_stale_busy_and_exports(aw02):
    c = aw02
    wid, item = create_draft(c)
    new_content = item["content"].replace("Keep this source reference.", "Updated section. Keep this source reference.")
    body = {"expected_version": 1, "content": new_content, "request_id": "aw02-manual-revision"}
    edited = post(c, f"/artifacts/{item['id']}/revisions", body)
    assert edited.status_code == 200 and edited.json()["version"] == 2
    assert post(c, f"/artifacts/{item['id']}/revisions", body).json()["version"] == 2
    assert post(c, f"/artifacts/{item['id']}/revisions", dict(body, content="other")).status_code == 409
    assert post(c, f"/artifacts/{item['id']}/revisions", dict(body, request_id="aw02-stale-manual")).json()["detail"] == "stale_artifact_version"
    diff = c.get(P + f"/artifacts/{item['id']}/diff?from_version=1&to_version=2").json()["diff"]
    assert "Updated section." in diff
    assert len(c.get(P + f"/artifacts/{item['id']}/versions").json()["items"]) == 2
    assert c.get(P + f"/artifacts/{item['id']}?version=1").json()["content"] == item["content"]
    for format, prefix in [("md", b"#"), ("docx", b"PK"), ("pdf", b"%PDF")]:
        output = c.get(P + f"/artifacts/{item['id']}/download?version=1&format={format}")
        assert output.status_code == 200, output.text
        assert output.content.startswith(prefix)
    failed = c.get(P + f"/artifacts/{item['id']}/download?format=xlsx")
    assert failed.status_code == 422 and failed.json() == {"detail": "artifact_export_failed"}
    assert c.get(P + f"/artifacts/{item['id']}").json()["content"] == new_content
    rid = start(c, wid, "fixture:slow", "aw02-busy-revision")
    # AW-06 deliberately allows manual revisions while a run is active. Exact
    # artifact CAS, not a workspace-wide editing lock, protects both writers.
    concurrent = post(c, f"/artifacts/{item['id']}/revisions", dict(body, expected_version=2, request_id="aw02-busy-manual"))
    assert concurrent.status_code == 200 and concurrent.json()["version"] == 3
    assert c.get(P + f"/artifacts/{item['id']}?version=2").json()["content"] == new_content
    post(c, f"/runs/{rid}/cancel")
    assert terminal(c, rid)["state"] == "cancelled"


def test_agent_localized_edit_preserves_content(aw02):
    c = aw02
    wid, item = create_draft(c, "patch")
    rid = start(c, wid, "fixture:patch", "aw02-local-patch")
    assert terminal(c, rid)["state"] == "completed"
    revised = c.get(P + f"/artifacts/{item['id']}").json()
    assert revised["version"] == 2
    assert revised["content"] == item["content"].replace("Fixture output, not AI analysis.", "Fixture localized revision, not AI analysis.")


def test_table_unicode_numbers_and_xlsx_roundtrip(aw02):
    c = aw02
    wid = workspace(c)
    text = 'Tên,Ngân sách,Mã\n"Việt Nam",120.50,0012\n"A,B",135000,=not_a_formula\n'
    assert post(c, f"/workspaces/{wid}/files", {"filename": "numbers.csv", "content": text}).status_code == 200
    rid = start(c, wid, "fixture:table", "aw02-table-numbers")
    assert terminal(c, rid)["state"] == "completed"
    item = c.get(P + f"/workspaces/{wid}/artifacts").json()["items"][0]
    assert item["kind"] == "table"
    exported = c.get(P + f"/artifacts/{item['id']}/download?format=csv")
    rows = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[1] == ["Việt Nam", "120.50", "0012"]
    assert rows[2] == ["A,B", "135000", "'=not_a_formula"]
    assert "formula" in exported.headers["X-Workspace-Export-Warnings"].lower()
    assert c.get(P + f"/artifacts/{item['id']}").json()["content"] == text
    output = c.get(P + f"/artifacts/{item['id']}/download?format=xlsx")
    assert output.status_code == 200 and output.content.startswith(b"PK")
    response = post(c, f"/workspaces/{wid}/files/batch", {"files": [{"filename": "roundtrip.xlsx", "content_base64": base64.b64encode(output.content).decode()}]})
    assert len(response.json()["accepted"]) == 1, response.text
    preview = c.get(P + "/files/" + response.json()["accepted"][0]["id"]).json()["content"]
    assert "Việt Nam" in preview and "0012" in preview and "120.50" in preview


def test_offline_research_snapshots_and_scripted_agent_no_sockets(aw02, monkeypatch):
    c = aw02
    wid = workspace(c)
    def denied(*args, **kwargs):
        raise AssertionError("offline research attempted network")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    response = post(c, f"/workspaces/{wid}/research/search", {"query": "Harbor"}).json()
    assert response["fixture"] and len(response["results"]) == 2
    source = response["results"][0]
    assert source["url"].startswith("https://harbor-public.test/")
    snapshot = post(c, f"/workspaces/{wid}/research/read", {"source_id": source["id"]}).json()["source"]
    imported = post(c, f"/workspaces/{wid}/research/import", {"source_id": source["id"]}).json()
    again = post(c, f"/workspaces/{wid}/research/import", {"source_id": source["id"]}).json()
    assert imported["id"] == again["id"]
    assert imported["provenance"]["sha256"] == snapshot["sha256"]
    assert post(c, f"/workspaces/{wid}/research/read", {"source_id": "http://169.254.169.254/"}).status_code == 404
    rid = start(c, wid, "fixture:research", "aw02-research-flow")
    final = terminal(c, rid)
    assert final["state"] == "completed", final
    item = c.get(P + f"/workspaces/{wid}/artifacts").json()["items"][0]
    content = c.get(P + f"/artifacts/{item['id']}").json()["content"]
    assert "120000" in content and "135000" in content and "offline_fixture" in content and "as of" in content


def test_patch_receipts_ambiguity_stale_and_atomic_concurrent_revisions(tmp_path):
    s = Store(tmp_path / "catalogue.sqlite")
    _, owner = s.session(None)
    wid = s.workspaces(owner, "Patch")["id"]
    run = s.create_run(owner, wid, "edit", "aw02-patch-run", dict(deadline_seconds=30, output_bytes_limit=256000))["id"]
    item = s.publish(owner, run, "create", "Draft", "draft.md", "120\n\nKeep region\n\nKeep region\n\nTail Việt Nam")
    for region, expected, code in [("absent", 1, "patch_region_not_unique"), ("Keep region", 1, "patch_region_not_unique"), ("Tail Việt Nam", 0, "stale_artifact_version")]:
        with pytest.raises(WorkspaceError, match=code):
            s.patch(owner, run, "bad-" + region, item["artifact_id"], expected, region, "new")
    result = s.patch(owner, run, "patch", item["artifact_id"], 1, "Tail Việt Nam", "New tail Việt Nam")
    assert s.patch(owner, run, "patch", item["artifact_id"], 1, "Tail Việt Nam", "New tail Việt Nam") == result
    s.finish(owner, run, "completed")
    def revise(key):
        try:
            return s.revise(owner, item["artifact_id"], 2, "Concurrent " + key, key)["version"]
        except WorkspaceError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(revise, ["request-one", "request-two"]))
    assert sorted(map(str, results)) == ["3", "stale_artifact_version"]
    assert len(s.versions(owner, item["artifact_id"])) == 3


def test_old_catalogue_source_upgrade_and_workflow_fail_closed(tmp_path):
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE files(id TEXT PRIMARY KEY,workspace_id TEXT,filename TEXT,media_type TEXT,content TEXT,bytes INTEGER,created_at REAL)")
    db.commit()
    db.close()
    s = Store(path)
    _, owner = s.session(None)
    wid = s.workspaces(owner, "Legacy source")["id"]
    with s.tx() as db:
        db.execute("INSERT INTO files(id,workspace_id,filename,media_type,content,bytes,created_at) VALUES('old-source',?,'old.txt','text/plain','Older 120 Việt Nam',20,0)", (wid,))
    assert s.source(owner, "old-source", raw=True)["raw_content"] == "Older 120 Việt Nam".encode()
    run = s.create_run(owner, wid, "old run", "aw02-old-run", dict(deadline_seconds=30, output_bytes_limit=1000))["id"]
    with s.tx() as db:
        db.execute("UPDATE runs SET workflow_version='workspace-aw01-v1' WHERE id=?", (run,))
    s.fail_incompatible_runs("workspace-aw02-v1")
    assert s.run(owner, run)["error"] == "workflow_version_incompatible"


def test_manual_authoring_without_model_does_not_create_fake_run(tmp_path):
    with TestClient(create_app(Settings(tmp_path)), base_url="http://localhost") as c:
        post(c, "/session")
        wid = workspace(c)
        assert c.get(P + "/status").json()["available"] is False
        body = dict(title="Manual Việt Nam", kind="document", content="# Manual\n\nBudget 120.50", request_id="aw02-manual-create")
        created = post(c, f"/workspaces/{wid}/artifacts", body)
        assert created.status_code == 200, created.text
        item = created.json()
        assert item["version"] == 1 and item["filename"] == "draft.md"
        assert post(c, f"/workspaces/{wid}/artifacts", body).json()["id"] == item["id"]
        assert post(c, f"/workspaces/{wid}/artifacts", dict(body, content="changed")).status_code == 409
        for change in [dict(content=""), dict(kind="table", content="A,B\nragged"), dict(title=" ")]:
            assert post(c, f"/workspaces/{wid}/artifacts", dict(body, request_id="invalid-create", **change)).status_code in {400, 413, 422}
        assert len(c.get(P + f"/workspaces/{wid}/artifacts").json()["items"]) == 1
        assert c.get(P + f"/workspaces/{wid}/messages").json()["items"] == []
        with c.app.state.store.tx() as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert c.get(P + f"/artifacts/{item['id']}/download?format=md").text == body["content"]


def test_api_import_and_construction_do_not_create_or_migrate_catalogue(tmp_path):
    default_dir = tmp_path / "default-data"
    env = dict(os.environ, WORKSPACE_DATA_DIR=str(default_dir), PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run([sys.executable, "-c", "import agent_workspace.api"], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert not default_dir.exists()
    explicit = tmp_path / "explicit-data"
    create_app(Settings(explicit))
    assert not explicit.exists()
    old = tmp_path / "old-catalogue"
    old.mkdir()
    path = old / "catalogue.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE files(id TEXT,workspace_id TEXT,filename TEXT,media_type TEXT,content TEXT,bytes INTEGER,created_at REAL)")
    db.commit()
    create_app(Settings(old))
    assert len(db.execute("PRAGMA table_info(files)").fetchall()) == 7
    db.close()
