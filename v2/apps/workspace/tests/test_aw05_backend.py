"""Synthetic actual SQLite/HTTP snapshot and project lifecycle, no real model."""
import base64
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import stat
import time
import zipfile

from fastapi.testclient import TestClient
import pytest

from agent_workspace.api import create_app
from agent_workspace.config import Settings
from agent_workspace.connections import Connections
from agent_workspace.data_lifecycle import DataLifecycle
from agent_workspace.portability import SnapshotImporter, inspect_archive, MAX_BASE64
from agent_workspace.store import Store, WorkspaceError
from agent_workspace.workspace_state import WorkspaceState

LIMITS = dict(deadline_seconds=60, request_limit=4, tool_limit=8, token_limit=8000, output_bytes_limit=32000)
P = "/api/workspace"
ORIGIN = {"origin": "http://localhost:3110"}


def populated(tmp_path):
    store = Store(tmp_path / "catalogue.sqlite")
    _, owner = store.session(None)
    state = WorkspaceState(store)
    Connections(store, tmp_path, True)
    wid = store.workspaces(owner, "Synthetic seed project")["id"]
    source = store.upload(owner, wid, "seed.csv", "batch,amount,note\n004173,91.125,Tiếng Việt\n", "text/csv")
    artifact = store.create_artifact(owner, wid, "A seed brief", "document", "# First\n\n004173 and 91.125.\n", "create-artifact-001")
    store.revise(owner, artifact["id"], 1, "# Second\n\n004173 and 91.125 remain.\n", "revise-artifact-001")
    state.save_memory(owner, wid, "Synthetic explicit preference.", "save-memory-001")
    state.create_schedule(owner, wid, "fixture:chat", 7.0, "schedule-create-001")
    run = store.create_run(owner, wid, "Synthetic question.", "synthetic-run-001", LIMITS)
    store.finish(owner, run["id"], "completed", content="Synthetic answer.", history="PRIVATE_UNEXPORTED_MODEL_HISTORY")
    raw = DataLifecycle(store).export(owner, wid)
    return store, owner, wid, source, artifact, raw


def encoded(raw):
    return base64.b64encode(raw).decode()


def rewrite(raw, modify, *, extra=None):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = {n: archive.read(n) for n in archive.namelist()}
    modify(members)
    if extra:
        members.update(extra)
    manifest = json.loads(members["manifest.json"])
    manifest["entries"] = [dict(path=n, bytes=len(body), sha256=hashlib.sha256(body).hexdigest()) for n, body in members.items() if n != "manifest.json"]
    members["manifest.json"] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return output.getvalue()


def alter_json(path, fn):
    def modify(members):
        value = json.loads(members[path])
        fn(value)
        members[path] = json.dumps(value).encode()
    return modify


def commit(importer, owner, raw, name="Restored project", memory=False, key="import-command-001"):
    preview = importer.preview(owner, encoded(raw), name, memory)
    result = importer.commit(owner, encoded(raw), name, memory, preview["confirmation_token"], key)
    return preview, result


def test_roundtrip_new_owner_identity_originals_versions_messages_optional_memory(tmp_path):
    store, source_owner, wid, source, artifact, raw = populated(tmp_path)
    importer = SnapshotImporter(store)
    _, owner = store.session(None)
    preview, result = commit(importer, owner, raw, memory=True)
    target = result["workspace"]["id"]
    assert target != wid and result["workspace"]["revision"] == 1 and not result["workspace"]["archived"]
    assert preview["counts"] == dict(files=1, artifacts=1, versions=2, messages=2, memory=1, memory_selected=1, schedules_omitted=1)
    copied = store.items(owner, target, "files")[0]
    assert copied["id"] != source["id"]
    assert store.source(owner, copied["id"], raw=True)["raw_content"] == store.source(source_owner, source["id"], raw=True)["raw_content"]
    draft = store.items(owner, target, "artifacts")[0]
    assert draft["id"] != artifact["id"]
    for number in (1, 2):
        assert store.artifact(owner, draft["id"], number)["content"] == store.artifact(source_owner, artifact["id"], number)["content"]
    messages = store.items(owner, target, "messages")
    assert [m["content"] for m in messages] == ["Synthetic question.", "Synthetic answer."]
    assert all(m["run_id"] is None for m in messages)
    assert len(WorkspaceState(store).memories(owner, target)["items"]) == 1
    assert WorkspaceState(store).schedules(owner, target)["items"] == []
    assert Connections(store, tmp_path, True).connection(owner, target)["enabled"] is False
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM runs WHERE workspace_id=?", (target,)).fetchone()[0] == 0
    lineage = importer.lineage(owner, target)
    assert lineage["id_map"]["files"][source["id"]] == copied["id"]
    assert lineage["archive_sha256"] == hashlib.sha256(raw).hexdigest()
    with pytest.raises(WorkspaceError, match="not_found"):
        importer.lineage(source_owner, target)
    # Export/restore again after reopen, with unchanged content and fresh IDs.
    second_raw = DataLifecycle(store).export(owner, target)
    imported = inspect_archive(second_raw)
    assert len(imported["versions"]) == 2
    reopened = Store(store.path)
    _, second = commit(SnapshotImporter(reopened), owner, second_raw, key="import-command-002")
    assert second["workspace"]["id"] not in {wid, target}
    assert WorkspaceState(reopened).memories(owner, second["workspace"]["id"])["items"] == []
    assert store.items(source_owner, wid, "files")[0]["id"] == source["id"]


def test_import_lost_ack_changed_choices_expiry_owner_and_deleted_replay(tmp_path):
    store, owner, wid, _, _, raw = populated(tmp_path)
    importer = SnapshotImporter(store)
    preview = importer.preview(owner, encoded(raw), "Copied", False)
    _, foreign = store.session(None)
    token = preview["confirmation_token"]
    for actor, name, memory in [(foreign, "Copied", False), (owner, "Changed", False), (owner, "Copied", True)]:
        with pytest.raises(WorkspaceError, match="snapshot_confirmation_stale"):
            importer.commit(actor, encoded(raw), name, memory, token, "import-command-001")
    first = importer.commit(owner, encoded(raw), "Copied", False, token, "import-command-001")
    assert importer.commit(owner, encoded(raw), "Copied", False, token, "import-command-001") == first
    with pytest.raises(WorkspaceError, match="idempotency_conflict"):
        importer.commit(owner, encoded(raw), "Other", False, token, "import-command-001")
    target = first["workspace"]["id"]
    lifecycle = DataLifecycle(store)
    confirm = lifecycle.preview(owner, target)
    lifecycle.delete(owner, target, confirm["confirmation_token"], "Copied", "delete-command-001")
    with pytest.raises(WorkspaceError, match="not_found"):
        importer.commit(owner, encoded(raw), "Copied", False, token, "import-command-001")
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM workspace_import_lineage WHERE workspace_id=?", (target,)).fetchone()[0] == 0
        assert db.execute("SELECT result FROM workspace_import_receipts WHERE workspace_id=?", (target,)).fetchone()[0] == "{}"
    assert len(store.workspaces(owner)) == 1 and store.workspaces(owner)[0]["id"] == wid
    expired = importer.preview(owner, encoded(raw), "Expired", False)
    with store.tx() as db:
        db.execute("UPDATE workspace_import_previews SET expires_at=0")
    with pytest.raises(WorkspaceError, match="snapshot_confirmation_stale"):
        importer.commit(owner, encoded(raw), "Expired", False, expired["confirmation_token"], "import-expired-001")


def test_simultaneous_same_import_key_creates_one_workspace(tmp_path):
    store, owner, _, _, _, raw = populated(tmp_path)
    importer = SnapshotImporter(store)
    preview = importer.preview(owner, encoded(raw), "Only once", False)
    def execute(_):
        return importer.commit(owner, encoded(raw), "Only once", False, preview["confirmation_token"], "import-concurrent-001")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    assert results[0] == results[1]
    assert len(store.workspaces(owner)) == 2


def test_import_replay_returns_current_metadata_not_old_title_or_archive_state(tmp_path):
    store, owner, _, _, _, raw = populated(tmp_path)
    importer = SnapshotImporter(store)
    preview, result = commit(importer, owner, raw)
    wid = result["workspace"]["id"]
    current = store.update_workspace(owner, wid, "rename-after-import", 1, name="Current title", archived=True)
    replay = importer.commit(owner, encoded(raw), "Restored project", False, preview["confirmation_token"], "import-command-001")
    assert replay["workspace"] == current
    assert replay["lineage"] == result["lineage"] and len(store.workspaces(owner, include_archived=True)) == 2


def test_transaction_failure_leaves_no_half_workspace_or_consumed_preview(tmp_path):
    store, owner, _, _, _, raw = populated(tmp_path)
    importer = SnapshotImporter(store)
    preview = importer.preview(owner, encoded(raw), "Must roll back", True)
    before = store.workspaces(owner)
    with store.tx() as db:
        db.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON versions BEGIN SELECT RAISE(ABORT,'synthetic import failure'); END")
    with pytest.raises(WorkspaceError, match="snapshot_import_failed"):
        importer.commit(owner, encoded(raw), "Must roll back", True, preview["confirmation_token"], "import-rollback-001")
    assert store.workspaces(owner) == before
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM workspace_import_receipts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM workspace_import_previews").fetchone()[0] == 1
        db.execute("DROP TRIGGER synthetic_failure")
    assert importer.commit(owner, encoded(raw), "Must roll back", True, preview["confirmation_token"], "import-rollback-001")["imported"]


@pytest.mark.parametrize("operation", [
    lambda m: m.update({"../escape": b"bad"}),
    lambda m: m.update({"credentials.json": b'{"api_key":"synthetic-only"}'}),
    alter_json("sources/index.json", lambda x: x[0].update(workspace_id="foreign-workspace")),
    alter_json("sources/index.json", lambda x: x[0].update(owner="forged-owner")),
    alter_json("artifacts.json", lambda x: x[0].update(kind=["document"])),
    alter_json("messages.json", lambda x: x[0].update(role="system")),
    alter_json("memory.json", lambda x: x[0].update(content="bad\x00memory")),
    alter_json("manifest.json", lambda x: x.update(format="unsupported-v99")),
])
def test_hash_valid_but_untrusted_invalid_records_rejected(tmp_path, operation):
    store, owner, _, _, _, raw = populated(tmp_path)
    importer = SnapshotImporter(store)
    before = store.workspaces(owner)
    with pytest.raises(WorkspaceError):
        importer.preview(owner, encoded(rewrite(raw, operation)), "Rejected", False)
    assert store.workspaces(owner) == before
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM workspace_import_previews").fetchone()[0] == 0


def test_member_digest_extracted_text_and_version_metadata_are_not_authority(tmp_path):
    store, owner, _, source, artifact, raw = populated(tmp_path)
    importer = SnapshotImporter(store)
    def tamper(m):
        m[f"sources/{source['id']}/extracted.txt"] = b"Fabricated extracted text."
    with pytest.raises(WorkspaceError, match="snapshot_extraction_mismatch"):
        importer.preview(owner, encoded(rewrite(raw, tamper)), "Bad text", False)
    path = f"artifacts/{artifact['id']}/v1.json"
    def forged(m):
        entry = json.loads(m[path])
        metadata = json.loads(entry["metadata"])
        metadata["id"] = "different-live-artifact"
        entry["metadata"] = json.dumps(metadata)
        m[path] = json.dumps(entry).encode()
    with pytest.raises(WorkspaceError):
        importer.preview(owner, encoded(rewrite(raw, forged)), "Bad metadata", False)
    def remove_version(m):
        del m[f"artifacts/{artifact['id']}/v1.txt"]
    with pytest.raises(WorkspaceError):
        importer.preview(owner, encoded(rewrite(raw, remove_version)), "Missing version", False)


def test_zip_duplicate_symlink_fanout_and_byte_limits(tmp_path):
    store, owner, _, _, _, raw = populated(tmp_path)
    importer = SnapshotImporter(store)
    with pytest.raises(WorkspaceError, match="snapshot_archive_limit"):
        importer.preview(owner, "A" * (MAX_BASE64 + 1), "Oversized", False)
    with pytest.raises(WorkspaceError):
        importer.preview(owner, "notbase64", "Invalid", False)
    output = io.BytesIO(raw)
    with zipfile.ZipFile(output, "a") as archive:
        with pytest.warns(UserWarning):
            archive.writestr("manifest.json", b"{}")
    with pytest.raises(WorkspaceError):
        inspect_archive(output.getvalue())
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        item = zipfile.ZipInfo("manifest.json")
        item.create_system = 3
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(item, "../../no")
    with pytest.raises(WorkspaceError):
        inspect_archive(output.getvalue())
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb", b"0" * (20 * 1024 * 1024 + 1))
    with pytest.raises(WorkspaceError, match="snapshot_archive_limit"):
        inspect_archive(output.getvalue())


def test_corrupt_deflate_stream_is_typed_rejection_without_catalogue_writes(tmp_path):
    store = Store(tmp_path / "corrupt.sqlite")
    _, owner = store.session(None)
    importer = SnapshotImporter(store)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", b"{}" * 100)
    raw = bytearray(output.getvalue())
    start = 30 + int.from_bytes(raw[26:28], "little") + int.from_bytes(raw[28:30], "little")
    raw[start] = 255
    with pytest.raises(WorkspaceError, match="invalid_workspace_snapshot"):
        importer.preview(owner, encoded(bytes(raw)), "Corrupt", False)
    assert store.workspaces(owner) == []
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM workspace_import_previews").fetchone()[0] == 0


def test_rename_archive_cas_visibility_and_no_new_execution(tmp_path):
    store, owner, wid, _, artifact, _ = populated(tmp_path)
    renamed = store.update_workspace(owner, wid, "rename-project-001", 1, name="Renamed synthetic")
    assert renamed["revision"] == 2 and store.workspaces(owner, query="SYNTHETIC")[0]["id"] == wid
    assert store.update_workspace(owner, wid, "rename-project-001", 1, name="Renamed synthetic") == renamed
    with pytest.raises(WorkspaceError, match="stale_workspace_revision"):
        store.update_workspace(owner, wid, "rename-project-002", 1, name="Stale")
    archived = store.update_workspace(owner, wid, "archive-project-001", 2, archived=True)
    assert archived["archived"] and store.workspaces(owner) == []
    assert store.workspaces(owner, include_archived=True)[0]["id"] == wid
    # Archive is visibility/dispatch organisation, not a new read-only ACL.
    store.revise(owner, artifact["id"], 2, "# Editable archived draft", "archived-manual-edit")
    with pytest.raises(WorkspaceError, match="workspace_archived"):
        store.create_run(owner, wid, "fixture:chat", "archived-run-001", LIMITS)
    state = WorkspaceState(store)
    with pytest.raises(WorkspaceError, match="workspace_archived"):
        state.tick(owner, wid, 8.0, "archived-clock-001", LIMITS)
    assert state.schedules(owner, wid)["items"][0]["state"] == "pending"
    restored = store.update_workspace(owner, wid, "unarchive-project-001", 3, archived=False)
    assert not restored["archived"]
    run = store.create_run(owner, wid, "fixture:chat", "after-unarchive-run", LIMITS)
    with pytest.raises(WorkspaceError, match="workspace_busy"):
        store.update_workspace(owner, wid, "archive-busy-001", 4, archived=True)
    store.finish(owner, run["id"], "cancelled")
    _, foreign = store.session(None)
    with pytest.raises(WorkspaceError, match="not_found"):
        store.update_workspace(foreign, wid, "foreign-metadata-001", 4, name="Hijack")


def test_import_api_owner_origin_strict_payload_and_scoped_body_limits(tmp_path):
    class MockRuntime:
        active_runs = set()
        def __init__(self, settings, store):
            self.workspace_state = WorkspaceState(store)
        async def start(self):
            pass
        async def close(self):
            pass
    app = create_app(Settings(data_dir=tmp_path), runtime_factory=MockRuntime)
    with TestClient(app, base_url="http://localhost") as client:
        client.post(P + "/session", json={}, headers=ORIGIN).raise_for_status()
        assert client.post(P + "/imports/preview", json={}, headers={"origin": "https://evil.invalid"}).status_code == 403
        assert client.post(P + "/imports/preview", json=dict(archive_base64="bad", name="Bad", include_memory=False, owner="forged"), headers=ORIGIN).status_code == 422
        created = client.post(P + "/workspaces", json={"name": "Ordinary"}, headers=ORIGIN).json()
        reply = client.post(P + "/workspaces/" + created["id"] + "/metadata", json=dict(name="New", expected_revision=1, request_id="metadata-api-001"), headers=ORIGIN)
        assert reply.status_code == 200 and reply.json()["revision"] == 2
        assert client.post(P + "/workspaces", content=b"0" * 1600001, headers=ORIGIN | {"content-type": "application/json"}).status_code == 413
        # A body above the old generic ceiling reaches import schema validation.
        assert client.post(P + "/imports/preview", json=dict(archive_base64="A" * 1600001, name="Large", include_memory=False), headers=ORIGIN).status_code == 400


def test_supported_binary_originals_reparse_and_remain_byte_exact(tmp_path):
    store = Store(tmp_path / "binary.sqlite")
    _, owner = store.session(None)
    wid = store.workspaces(owner, "Synthetic format continuity")["id"]
    for suffix in ("docx", "xlsx", "pdf"):
        raw = (Path(__file__).parent / "fixtures" / "formats" / ("harbor." + suffix)).read_bytes()
        store.upload_bytes(owner, wid, "harbor." + suffix, raw)
    archive = DataLifecycle(store).export(owner, wid)
    importer = SnapshotImporter(store)
    _, result = commit(importer, owner, archive, name="Formats restored")
    target = result["workspace"]["id"]
    originals = {i["filename"]: store.source(owner, i["id"], raw=True)["raw_content"] for i in store.items(owner, wid, "files")}
    for item in store.items(owner, target, "files"):
        assert store.source(owner, item["id"], raw=True)["raw_content"] == originals[item["filename"]]


def test_preview_quota_and_expired_cleanup_have_no_archive_blob(tmp_path):
    store, owner, _, _, _, raw = populated(tmp_path)
    importer = SnapshotImporter(store)
    for _ in range(10):
        importer.preview(owner, encoded(raw), "Preview", False)
    with pytest.raises(WorkspaceError, match="snapshot_preview_limit"):
        importer.preview(owner, encoded(raw), "One too many", False)
    with store.tx() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(workspace_import_previews)")}
        assert columns == {"token_hash", "owner", "args_digest", "expires_at"}
        db.execute("UPDATE workspace_import_previews SET expires_at=0")
    assert importer.preview(owner, encoded(raw), "After expiry", False)["name"] == "After expiry"


def test_equal_timestamp_messages_order_roundtrips(tmp_path):
    store, owner, wid, _, _, raw = populated(tmp_path)
    def equal_times(members):
        messages = json.loads(members["messages.json"])
        messages[0]["id"], messages[1]["id"] = "z-first", "a-second"
        messages[0]["created_at"] = messages[1]["created_at"] = 123.5
        members["messages.json"] = json.dumps(messages).encode()
    raw = rewrite(raw, equal_times)
    importer = SnapshotImporter(store)
    _, result = commit(importer, owner, raw)
    target = result["workspace"]["id"]
    assert [m["role"] for m in store.items(owner, target, "messages")] == ["user", "assistant"]
    second = inspect_archive(DataLifecycle(store).export(owner, target))
    assert [m["role"] for m in second["messages"]] == ["user", "assistant"]
