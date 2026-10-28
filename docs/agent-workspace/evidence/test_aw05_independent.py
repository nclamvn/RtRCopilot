"""Separate-author AW-05 boundary probes, local/synthetic only.

Actual SQLite and ASGI boundaries, no provider or live connector. The historical
AW-04 exporter is loaded from the committed repository into memory, not copied
as a project or applied to any user catalogue.
"""
import base64
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import types
import zipfile

from fastapi.testclient import TestClient
import pytest

from agent_workspace.api import create_app
from agent_workspace.config import Settings, local_origins
from agent_workspace.connections import Connections
from agent_workspace.data_lifecycle import DataLifecycle
from agent_workspace.portability import SnapshotImporter, inspect_archive
from agent_workspace.store import Store, WorkspaceError
from agent_workspace.workspace_state import WorkspaceState

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "v2/apps/workspace"
LIMITS = dict(deadline_seconds=60, request_limit=4, tool_limit=8, token_limit=8000, output_bytes_limit=32000)


def b64(raw):
    return base64.b64encode(raw).decode()


def archive_members(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return {p: z.read(p) for p in z.namelist()}


def repack(raw, mutate):
    entries = archive_members(raw)
    mutate(entries)
    manifest = json.loads(entries["manifest.json"])
    manifest["entries"] = [dict(path=p, bytes=len(v), sha256=hashlib.sha256(v).hexdigest()) for p, v in entries.items() if p != "manifest.json"]
    entries["manifest.json"] = json.dumps(manifest).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, value in entries.items():
            z.writestr(name, value)
    return out.getvalue()


def change_json(path, transform):
    def mutate(entries):
        value = json.loads(entries[path])
        transform(value)
        entries[path] = json.dumps(value).encode()
    return mutate


@pytest.fixture
def seed(tmp_path):
    store = Store(tmp_path / "catalogue.sqlite")
    _, owner = store.session(None)
    state = WorkspaceState(store)
    connections = Connections(store, tmp_path, True)
    wid = store.workspaces(owner, "Independent synthetic observatory")["id"]
    source = store.upload(owner, wid, "observations.csv", "sample,quantity,note\r\n000527,14.625,Tiếng Việt Δ\r\n", "text/csv")
    artifact = store.create_artifact(owner, wid, "Observatory brief", "document", "# Before\n\n000527 and 14.625.\n", "independent-create")
    store.revise(owner, artifact["id"], 1, "# After\n\n000527 and 14.625 stay unchanged.\n", "independent-revise")
    state.save_memory(owner, wid, "Synthetic observatory uses metric units.", "independent-memory")
    state.create_schedule(owner, wid, "fixture:chat", 42.5, "independent-schedule")
    connections.set_connection(owner, wid, True, 0, "independent-grant")
    run = store.create_run(owner, wid, "Synthetic question.", "independent-run", LIMITS)
    store.finish(owner, run["id"], "completed", content="Synthetic displayed answer.", history="PRIVATE_CHECKPOINT_NOT_PORTABLE")
    raw = DataLifecycle(store).export(owner, wid)
    return store, owner, wid, source, artifact, raw


def restore(importer, owner, raw, *, memory=False, name="Independent restored", request="independent-import"):
    preview = importer.preview(owner, b64(raw), name, memory)
    return importer.commit(owner, b64(raw), name, memory, preview["confirmation_token"], request)


def test_independent_new_identity_versions_and_no_restored_power(seed, tmp_path):
    store, old_owner, wid, source, artifact, raw = seed
    _, owner = store.session(None)
    importer = SnapshotImporter(store)
    item = restore(importer, owner, raw, memory=True)
    target = item["workspace"]["id"]
    assert target != wid
    copied_source = store.items(owner, target, "files")[0]
    assert copied_source["id"] != source["id"]
    assert store.source(owner, copied_source["id"], raw=True)["raw_content"] == store.source(old_owner, source["id"], raw=True)["raw_content"]
    copied = store.items(owner, target, "artifacts")[0]
    for n in (1, 2):
        assert store.artifact(owner, copied["id"], n)["content"] == store.artifact(old_owner, artifact["id"], n)["content"]
    assert copied["id"] != artifact["id"]
    messages = store.items(owner, target, "messages")
    assert [m["content"] for m in messages] == ["Synthetic question.", "Synthetic displayed answer."]
    assert all(m["run_id"] is None for m in messages)
    assert WorkspaceState(store).schedules(owner, target)["items"] == []
    assert Connections(store, tmp_path, True).connection(owner, target)["enabled"] is False
    with store.tx() as db:
        assert not db.execute("SELECT 1 FROM runs WHERE workspace_id=?", (target,)).fetchone()
        assert not db.execute("SELECT 1 FROM approvals WHERE workspace_id=?", (target,)).fetchone()
    assert len(WorkspaceState(store).memories(owner, target)["items"]) == 1
    no_memory = restore(importer, owner, raw, name="No memory copy", request="independent-nomemory")["workspace"]["id"]
    assert WorkspaceState(store).memories(owner, no_memory)["items"] == []
    assert importer.lineage(owner, target)["id_map"]["files"][source["id"]] == copied_source["id"]
    with pytest.raises(WorkspaceError, match="not_found"):
        importer.lineage(old_owner, target)


def test_committed_aw04_exporter_and_binary_original_are_compatible(seed):
    store, owner, wid, _, _, _ = seed
    raw_docx = (PACKAGE / "tests/fixtures/formats/harbor.docx").read_bytes()
    binary = store.upload_bytes(owner, wid, "synthetic.docx", raw_docx)
    old_code = subprocess.check_output(["git", "show", "12d924c:v2/apps/workspace/src/agent_workspace/data_lifecycle.py"], cwd=ROOT).decode()
    module = types.ModuleType("agent_workspace._aw04_review_export")
    exec(compile(old_code, "committed-aw04-exporter", "exec"), module.__dict__)
    raw = module.DataLifecycle(store).export(owner, wid)
    imported = restore(SnapshotImporter(store), owner, raw)
    files = store.items(owner, imported["workspace"]["id"], "files")
    copied = next(f for f in files if f["filename"] == "synthetic.docx")
    assert copied["id"] != binary["id"]
    assert store.source(owner, copied["id"], raw=True)["raw_content"] == raw_docx


@pytest.mark.parametrize("mutate", [
    change_json("manifest.json", lambda v: v["workspace"].update(owner="forged-owner")),
    change_json("sources/index.json", lambda v: v[0].update(workspace_id="foreign-workspace")),
    change_json("messages.json", lambda v: v[0].update(role="system")),
    change_json("artifacts.json", lambda v: v[0].update(version=3)),
    lambda entries: entries.update({"permissions.json": b'{"approved":true}'}),
    lambda entries: entries.update({"../outside.txt": b"not allowed"}),
])
def test_hash_valid_untrusted_archive_cannot_create_authority_or_partial_data(seed, mutate):
    store, owner, _, _, _, raw = seed
    before = store.workspaces(owner)
    with pytest.raises(WorkspaceError):
        SnapshotImporter(store).preview(owner, b64(repack(raw, mutate)), "Invalid clone", False)
    assert store.workspaces(owner) == before


@pytest.mark.parametrize("payload", [b'[{"x":1,"x":2}]', b'[NaN]', b'[' * 21 + b'0' + b']' * 21])
def test_malformed_json_is_typed_rejection_not_server_crash(seed, payload):
    store, owner, _, _, _, raw = seed
    with pytest.raises(WorkspaceError):
        SnapshotImporter(store).preview(owner, b64(repack(raw, lambda e: e.update({"memory.json": payload}))), "Reject JSON", False)
    assert len(store.workspaces(owner)) == 1


def test_unpaired_surrogates_in_complete_memory_or_provenance_records_reject(seed):
    store, owner, _, _, _, raw = seed
    for mutate in [
        change_json("memory.json", lambda v: v[0].update(content="bad\ud800memory")),
        change_json("sources/index.json", lambda v: v[0].update(provenance={"untrusted": "bad\ud800claim"})),
    ]:
        with pytest.raises(WorkspaceError):
            SnapshotImporter(store).preview(owner, b64(repack(raw, mutate)), "Reject Unicode", False)
    assert len(store.workspaces(owner)) == 1


def test_corrupt_deflate_is_typed_and_api_rejects_without_writes(tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", b"{}" * 100)
    raw = bytearray(output.getvalue())
    offset = 30 + int.from_bytes(raw[26:28], "little") + int.from_bytes(raw[28:30], "little")
    raw[offset] = 255
    with pytest.raises(WorkspaceError):
        inspect_archive(bytes(raw))
    class NoDispatch:
        def __init__(self, settings, store):
            self.active_runs = set()
        async def start(self):
            pass
        async def close(self):
            pass
    app = create_app(Settings(data_dir=tmp_path, test_mode=True), runtime_factory=NoDispatch)
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
        headers = {"origin": "http://localhost:3110"}
        assert client.post("/api/workspace/session", headers=headers).status_code == 200
        response = client.post("/api/workspace/imports/preview", headers=headers, json=dict(archive_base64=b64(bytes(raw)), name="Invalid compressed data", include_memory=False))
        assert response.status_code == 400
        assert client.get("/api/workspace/workspaces").json()["items"] == []


def test_confirmation_binding_concurrent_consumption_and_atomic_rollback(seed):
    store, owner, _, _, _, raw = seed
    importer = SnapshotImporter(store)
    preview = importer.preview(owner, b64(raw), "Concurrent copy", False)
    _, foreign = store.session(None)
    for actor, name, memory in [(foreign, "Concurrent copy", False), (owner, "Changed", False), (owner, "Concurrent copy", True)]:
        with pytest.raises(WorkspaceError, match="snapshot_confirmation_stale"):
            importer.commit(actor, b64(raw), name, memory, preview["confirmation_token"], "independent-rejected")
    def attempt(i):
        try:
            return importer.commit(owner, b64(raw), "Concurrent copy", False, preview["confirmation_token"], f"independent-compete-{i}")
        except WorkspaceError as exc:
            return exc.code
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert "snapshot_confirmation_stale" in results
    assert len(store.workspaces(owner)) == 2
    preview = importer.preview(owner, b64(raw), "Rollback copy", True)
    with store.tx() as db:
        db.execute("CREATE TRIGGER independent_fault BEFORE INSERT ON workspace_import_lineage BEGIN SELECT RAISE(ABORT,'synthetic rollback'); END")
    with pytest.raises(WorkspaceError, match="snapshot_import_failed"):
        importer.commit(owner, b64(raw), "Rollback copy", True, preview["confirmation_token"], "independent-rollback")
    assert len(store.workspaces(owner)) == 2
    with store.tx() as db:
        db.execute("DROP TRIGGER independent_fault")
    assert importer.commit(owner, b64(raw), "Rollback copy", True, preview["confirmation_token"], "independent-rollback")["imported"]


def test_replay_current_metadata_deletion_and_restart_fence(seed):
    store, owner, _, _, _, raw = seed
    importer = SnapshotImporter(store)
    preview = importer.preview(owner, b64(raw), "First title", False)
    args = owner, b64(raw), "First title", False, preview["confirmation_token"], "independent-current"
    item = importer.commit(*args)
    wid = item["workspace"]["id"]
    renamed = store.update_workspace(owner, wid, "independent-rename", 1, name="Current title")
    replay = importer.commit(*args)
    assert replay["workspace"] == renamed
    reopened = Store(store.path)
    assert SnapshotImporter(reopened).commit(*args)["workspace"] == renamed
    lifecycle = DataLifecycle(store)
    preview = lifecycle.preview(owner, wid)
    lifecycle.delete(owner, wid, preview["confirmation_token"], "Current title", "independent-delete")
    with pytest.raises(WorkspaceError, match="not_found"):
        SnapshotImporter(reopened).commit(*args)
    with store.tx() as db:
        assert db.execute("SELECT result FROM workspace_import_receipts WHERE workspace_id=?", (wid,)).fetchone()[0] == "{}"
        assert not db.execute("SELECT 1 FROM workspace_import_lineage WHERE workspace_id=?", (wid,)).fetchone()
        assert not db.execute("SELECT 1 FROM workspace_metadata_requests WHERE workspace_id=?", (wid,)).fetchone()


def test_archive_visibility_busy_and_revision_are_not_permissions(seed):
    store, owner, wid, _, artifact, _ = seed
    run = store.create_run(owner, wid, "Synthetic active task", "independent-active", LIMITS)
    with pytest.raises(WorkspaceError, match="workspace_busy"):
        store.update_workspace(owner, wid, "independent-archive", 1, archived=True)
    store.finish(owner, run["id"], "cancelled")
    archived = store.update_workspace(owner, wid, "independent-archive", 1, archived=True)
    assert archived["archived"] and not store.workspaces(owner)
    assert store.workspaces(owner, include_archived=True)[0]["id"] == wid
    assert store.artifact(owner, artifact["id"])["version"] == 2
    with pytest.raises(WorkspaceError, match="workspace_archived"):
        store.create_run(owner, wid, "Blocked", "independent-blocked", LIMITS)
    with pytest.raises(WorkspaceError, match="stale_workspace_revision"):
        store.update_workspace(owner, wid, "independent-stale", 1, archived=False)
    assert store.update_workspace(owner, wid, "independent-unarchive", archived["revision"], archived=False)["archived"] is False


@pytest.mark.parametrize("origin", ['["https://localhost:3120"]', '["http://evil.example:3120"]', '["http://localhost:3120/path"]', '["http://user:password@localhost:3120"]'])
def test_standalone_origin_config_rejects_remote_or_credential_paths(origin):
    with pytest.raises(ValueError):
        local_origins(origin)


def test_standalone_graph_has_only_neutral_routes_and_source():
    result = subprocess.run(["node", "scripts/audit-graph.mjs"], cwd=ROOT / "v2/apps/workspace-web", capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    assert report["status"] == "PASS"
    assert report["built_routes"] is not None
    assert "/workspace/page" in report["built_routes"]
    assert not any("ask" in route or "knowledge-ops" in route for route in report["built_routes"])
    paths = [r["path"] for r in report["source_files"]]
    assert "web/src/app/layout.tsx" not in paths
    assert not any("app/styles" in p or "auth" in p or "proxy.ts" in p for p in paths)


def test_actual_composer_helper_scope_blank_tombstone_and_storage_recovery():
    script = r"""
const fs = require('node:fs'); const vm = require('node:vm'); const assert = require('node:assert/strict');
const ts = require('typescript');
const values = new Map(); let removeFails = false; let writeFails = false;
const storage = {getItem: key => values.get(key) ?? null,
  setItem: (key, value) => {if (writeFails) throw new Error('synthetic unavailable'); values.set(key, value);},
  removeItem: key => {if (removeFails) throw new Error('synthetic unavailable'); values.delete(key);}};
const context = {exports: {}, localStorage: storage};
const source = fs.readFileSync('src/workspace/composerDrafts.ts', 'utf8');
vm.runInNewContext(ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText, context);
const {ComposerDrafts, composerKey} = context.exports; const drafts = new ComposerDrafts();
assert.equal(drafts.write('synthetic-a', 'Already sent command').stored, true);
assert.equal(drafts.write('synthetic-b', 'Keep independent draft').stored, true);
removeFails = true;
assert.equal(drafts.write('synthetic-a', '').stored, true);
assert.equal(JSON.parse(values.get(composerKey('synthetic-a'))).content, '');
assert.equal(new ComposerDrafts().load('synthetic-a').draft.content, '');
assert.equal(new ComposerDrafts().load('synthetic-b').draft.content, 'Keep independent draft');
removeFails = false;
drafts.write('synthetic-a', 'Second sent command');
removeFails = writeFails = true;
assert.equal(drafts.write('synthetic-a', '').stored, false);
assert.equal(drafts.load('synthetic-a').draft.content, '');
removeFails = writeFails = false;
assert.equal(drafts.load('synthetic-a').stored, true);
assert.equal(new ComposerDrafts().load('synthetic-a').draft.content, '');
assert.equal(new ComposerDrafts().load('synthetic-b').draft.content, 'Keep independent draft');
drafts.write('synthetic-a', 'Disposable deleted draft'); drafts.forget('synthetic-a');
assert.equal(new ComposerDrafts().load('synthetic-a').draft.content, '');
console.log('actual ComposerDrafts scope/clear/recovery PASS');
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT / "v2/apps/web", capture_output=True, text=True, check=True)
    assert "scope/clear/recovery PASS" in result.stdout
