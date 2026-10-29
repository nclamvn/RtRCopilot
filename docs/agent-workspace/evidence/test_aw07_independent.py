"""Separate-author AW-07 synthetic probes; never a real-model evaluation.

These exercise actual local file/SQLite/ASGI boundaries and an actual second
Python process. They do not certify AI quality, cloud behavior or release rights.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import struct
import subprocess
import sys
from types import SimpleNamespace
import zipfile

from fastapi.testclient import TestClient
import pytest

from agent_workspace.api import create_app
from agent_workspace.config import Settings
from agent_workspace.runtime import Runtime
from agent_workspace.store import Store, WorkspaceError

P = "/api/workspace"
ORIGIN = {"origin": "http://localhost:3110"}
LIMITS = dict(deadline_seconds=120, request_limit=8, tool_limit=16,
              token_limit=32000, output_bytes_limit=256000)
CANARY = "PRIVATE-CANARY-073191-DoNotExport"


class NoDispatch(Runtime):
    async def start(self):
        pass

    async def close(self):
        pass

    async def dispatch_pending(self):
        pass

    def status(self):
        return dict(available=True, test_mode=True, model=CANARY,
                    reason=CANARY, recovery=CANARY)


def operations():
    from agent_workspace import operations as module
    return module


def post(client, path, data=None):
    return client.post(P + path, headers=ORIGIN, json=data or {})


def success(response):
    assert response.status_code == 200, response.text
    return response.json()


def fingerprint(directory):
    # SQLite read-only WAL-mode connections can materialize empty WAL/SHM
    # bookkeeping. Compare durable user bytes, not those documented sidecars.
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file() and not path.is_symlink()
            and path.name != ".workspace.lock" and not path.name.endswith(("-wal", "-shm"))}


@pytest.fixture
def seed(tmp_path):
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    store = Store(data / "catalogue.sqlite")
    runtime = Runtime(Settings(data, test_mode=True), store)
    token, owner = store.session(None)
    wid = store.workspaces(owner, "Synthetic observatory " + CANARY)["id"]
    file = store.upload(owner, wid, "private-" + CANARY + ".txt",
                        "Station 073191, 91.625 mm. " + CANARY, "text/plain")
    artifact = store.create_artifact(owner, wid, "Private " + CANARY, "document",
                                     "# Synthetic 073191\n\n91.625 mm. " + CANARY,
                                     "review-aw07-create")
    store.revise(owner, artifact["id"], 1, "# Revised 073191\n\n91.875 mm. " + CANARY,
                 "review-aw07-revise")
    runtime.continuity.save_brief(owner, wid, 0, "Review " + CANARY,
                                   "Keep numbers exact", "Compare tomorrow",
                                   "review-aw07-brief")
    runtime.workspace_state.save_memory(owner, wid, "User memory " + CANARY,
                                        "review-aw07-memory")
    runtime.workspace_state.create_schedule(owner, wid, "fixture:chat " + CANARY,
                                            120, "review-aw07-schedule")
    operations().initialize_format(data)
    return dict(data=data, store=store, runtime=runtime, owner=owner,
                token=token, workspace=wid, source=file, artifact=artifact)


def archive_members(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def save_archive(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    path.chmod(0o600)
    return path


def test_independent_lease_blocks_second_process_and_releases_without_pid_tricks(tmp_path):
    op = operations()
    data = tmp_path / "lease-test"
    code = "from pathlib import Path; from agent_workspace.operations import DataLease; import sys;\nwith DataLease(Path(sys.argv[1])): print('ACQUIRED')"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[3] / "v2/apps/workspace/src"))
    with op.DataLease(data):
        second = subprocess.run([sys.executable, "-c", code, str(data)], env=env,
                                text=True, capture_output=True, timeout=10)
        assert second.returncode != 0
        assert "ACQUIRED" not in second.stdout
    third = subprocess.run([sys.executable, "-c", code, str(data)], env=env,
                           text=True, capture_output=True, timeout=10)
    assert third.returncode == 0 and "ACQUIRED" in third.stdout


def test_independent_backup_restore_preserves_original_and_no_overwrite(seed, tmp_path):
    op = operations()
    archive = tmp_path / "private" / "snapshot.zip"
    original = fingerprint(seed["data"])
    op.backup_data(seed["data"], archive)
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(archive.parent.stat().st_mode) == 0o700
    assert fingerprint(seed["data"]) == original
    restored = tmp_path / "restored"
    op.restore_data(archive, restored)
    copied = Store(restored / "catalogue.sqlite")
    assert copied.authenticate(seed["token"]) == seed["owner"]
    assert copied.artifact(seed["owner"], seed["artifact"]["id"], 1)["content"].endswith(CANARY)
    assert copied.artifact(seed["owner"], seed["artifact"]["id"])["version"] == 2
    assert copied.source(seed["owner"], seed["source"]["id"], raw=True)["raw_content"] == seed["store"].source(seed["owner"], seed["source"]["id"], raw=True)["raw_content"]
    for table in ("workspace_memory", "workspace_schedules", "project_briefs", "versions", "revisions"):
        with sqlite3.connect(seed["data"] / "catalogue.sqlite") as original_db, sqlite3.connect(restored / "catalogue.sqlite") as restored_db:
            assert restored_db.execute(f"SELECT * FROM {table}").fetchall() == original_db.execute(f"SELECT * FROM {table}").fetchall()
    after = fingerprint(restored)
    with pytest.raises((WorkspaceError, ValueError, FileExistsError)):
        op.restore_data(archive, restored)
    assert fingerprint(restored) == after


def test_independent_backup_refuses_held_lease_and_nonterminal_run(seed, tmp_path):
    op = operations()
    output = tmp_path / "private" / "busy.zip"
    with op.DataLease(seed["data"]):
        with pytest.raises((WorkspaceError, ValueError)):
            op.backup_data(seed["data"], output)
    assert not output.exists()
    seed["store"].create_run(seed["owner"], seed["workspace"], "fixture:slow", "review-aw07-active", LIMITS)
    with pytest.raises((WorkspaceError, ValueError)):
        op.backup_data(seed["data"], output)
    assert not output.exists()


@pytest.mark.parametrize("extra", ["../escape", "/tmp/escape", "nested/unexpected", "provider.json"])
def test_independent_restore_rejects_extra_and_traversal_members_without_destination(seed, tmp_path, extra):
    op = operations()
    archive = tmp_path / "private" / "base.zip"
    op.backup_data(seed["data"], archive)
    members = archive_members(archive.read_bytes())
    members[extra] = CANARY.encode()
    altered = save_archive(tmp_path / "tampered.zip", members)
    destination = tmp_path / "destination"
    with pytest.raises((WorkspaceError, ValueError)):
        op.restore_data(altered, destination)
    assert not destination.exists() and not (tmp_path / "escape").exists()


def test_independent_restore_corruption_hash_mismatch_and_duplicate_members(seed, tmp_path):
    op = operations()
    archive = tmp_path / "private" / "base.zip"
    op.backup_data(seed["data"], archive)
    members = archive_members(archive.read_bytes())
    target = next(name for name in members if name.endswith(".sqlite"))
    members[target] += b"CORRUPTED-CONTENT"
    altered = save_archive(tmp_path / "bad-hash.zip", members)
    with pytest.raises((WorkspaceError, ValueError)):
        op.restore_data(altered, tmp_path / "bad-hash-destination")
    assert not (tmp_path / "bad-hash-destination").exists()
    duplicate = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(duplicate, "w") as writer:
        for name, body in archive_members(archive.read_bytes()).items():
            writer.writestr(name, body)
        writer.writestr(target, b"DUPLICATE")
    with pytest.raises((WorkspaceError, ValueError)):
        op.restore_data(duplicate, tmp_path / "duplicate-destination")
    assert not (tmp_path / "duplicate-destination").exists()


def test_independent_diagnostics_is_authenticated_allowlist_and_owner_scoped(tmp_path):
    app = create_app(Settings(tmp_path / "api", test_mode=True), runtime_factory=NoDispatch)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get(P + "/diagnostics").status_code == 401
        success(post(client, "/session"))
        owner = success(post(client, "/workspaces", {"name": CANARY}))
        success(post(client, f"/workspaces/{owner['id']}/files", dict(filename="file.txt", content=CANARY)))
        first = success(client.get(P + "/diagnostics"))
        raw = json.dumps(first)
        assert CANARY not in raw and owner["id"] not in raw
        assert str(tmp_path) not in raw and "workspace_session" not in raw
        assert first["format"] == "agent-workspace-diagnostics-v1"
        client.cookies.clear()
        success(post(client, "/session"))
        other = success(client.get(P + "/diagnostics"))
        assert CANARY not in json.dumps(other)
        assert first != other, "Owner-scoped aggregate counts should differ for populated versus empty owner"


@pytest.mark.parametrize("kind", ["future_sidecar", "future_pragma", "corrupt", "unknown_table", "trigger"])
def test_independent_startup_refuses_unknown_or_corrupt_before_store_mutation(seed, kind):
    op = operations()
    data = seed["data"]
    if kind == "future_sidecar":
        (data / op.FORMAT_FILE).write_text(json.dumps(dict(op.FORMAT, version=999)))
    elif kind == "corrupt":
        (data / "catalogue.sqlite").write_bytes(b"synthetic damaged catalogue")
    else:
        with sqlite3.connect(data / "catalogue.sqlite") as db:
            if kind == "future_pragma":
                db.execute("PRAGMA user_version=99")
            elif kind == "unknown_table":
                db.execute("CREATE TABLE future_secret (content TEXT)")
            else:
                db.execute("CREATE TRIGGER malicious AFTER INSERT ON sessions BEGIN DELETE FROM workspaces; END")
    before = fingerprint(data)
    app = create_app(Settings(data, test_mode=True), runtime_factory=NoDispatch)
    with pytest.raises(WorkspaceError):
        with TestClient(app, base_url="http://localhost"):
            pytest.fail("Unknown state must not start")
    assert fingerprint(data) == before


@pytest.mark.parametrize("name", [".workspace.lock", "catalogue.sqlite"])
def test_independent_lease_and_catalogue_symlinks_are_refused(tmp_path, name):
    op = operations()
    data = tmp_path / "alias"
    data.mkdir(mode=0o700)
    target = tmp_path / "private-target"
    target.write_bytes(b"CANARYDO NOT CHANGE")
    (data / name).symlink_to(target)
    with pytest.raises(WorkspaceError):
        if name == ".workspace.lock":
            with op.DataLease(data):
                pytest.fail("Symlink lock admitted")
        else:
            op.inspect_data(data)
    assert target.read_bytes() == b"CANARYDO NOT CHANGE"


@pytest.mark.parametrize("rewrite", ["nan", "duplicate", "boolean_version"])
def test_independent_restore_strict_manifest_json(seed, tmp_path, rewrite):
    op = operations()
    archive = tmp_path / "private" / "base.zip"
    op.backup_data(seed["data"], archive)
    members = archive_members(archive.read_bytes())
    manifest = json.loads(members["manifest.json"])
    if rewrite == "nan":
        manifest["created_at"] = float("nan")
        members["manifest.json"] = json.dumps(manifest).encode()
    elif rewrite == "duplicate":
        members["manifest.json"] = b'{"version":1,' + members["manifest.json"][1:]
    else:
        manifest["version"] = True
        members["manifest.json"] = json.dumps(manifest).encode()
    bad = save_archive(tmp_path / "bad.zip", members)
    with pytest.raises(WorkspaceError):
        op.restore_data(bad, tmp_path / "destination")
    assert not (tmp_path / "destination").exists()


def test_independent_restore_bounds_declared_expansion_before_reading(seed, tmp_path):
    op = operations()
    archive = tmp_path / "private" / "base.zip"
    op.backup_data(seed["data"], archive)
    raw = bytearray(archive.read_bytes())
    offset = raw.index(b"PK\x01\x02")
    struct.pack_into("<I", raw, offset + 24, op.MAX_BYTES + 1)
    bomb = tmp_path / "declared-bomb.zip"
    bomb.write_bytes(raw)
    with pytest.raises(WorkspaceError):
        op.restore_data(bomb, tmp_path / "destination")
    assert not (tmp_path / "destination").exists()


def test_independent_failed_atomic_publication_cleans_staging(seed, tmp_path, monkeypatch):
    op = operations()
    archive = tmp_path / "private" / "base.zip"
    op.backup_data(seed["data"], archive)
    def interrupted(*args, **kwargs):
        raise WorkspaceError("filesystem_operation_failed", 409)
    monkeypatch.setattr(op, "publish_new", interrupted)
    with pytest.raises(WorkspaceError):
        op.restore_data(archive, tmp_path / "destination")
    assert not (tmp_path / "destination").exists()
    assert not list(tmp_path.glob(".workspace-restore-*"))


def test_independent_auxiliary_dbos_requires_recognized_quiescent_schema(seed, tmp_path):
    op = operations()
    with sqlite3.connect(seed["data"] / "dbos.sqlite") as db:
        db.execute("CREATE TABLE disguised_pending_work (payload TEXT)")
        db.execute("INSERT INTO disguised_pending_work VALUES ('do not dispatch')")
    with pytest.raises(WorkspaceError):
        op.backup_data(seed["data"], tmp_path / "private" / "bad-dbos.zip")


@pytest.mark.parametrize("database", ["dbos.sqlite", "fixture-outbox.sqlite"])
def test_independent_auxiliary_sql_triggers_are_not_trusted(seed, tmp_path, database):
    op = operations()
    with sqlite3.connect(seed["data"] / database) as db:
        if database == "dbos.sqlite":
            db.execute("CREATE TABLE workflow_status (status TEXT)")
            db.execute("CREATE TRIGGER forged AFTER INSERT ON workflow_status BEGIN DELETE FROM workflow_status; END")
        else:
            db.execute("CREATE TABLE outbox (scope TEXT,key TEXT,note TEXT,PRIMARY KEY(scope,key))")
            db.execute("CREATE TRIGGER forged AFTER INSERT ON outbox BEGIN DELETE FROM outbox; END")
    with pytest.raises(WorkspaceError):
        op.backup_data(seed["data"], tmp_path / "private" / "forged.zip")


def test_independent_rehashed_backup_with_queued_work_is_still_refused(seed, tmp_path):
    op = operations()
    run = seed["store"].create_run(seed["owner"], seed["workspace"], "fixture:chat", "review-aw07-terminal", LIMITS)
    seed["store"].finish(seed["owner"], run["id"], "completed", content="Synthetic retained result", history="[]")
    original = tmp_path / "private" / "base.zip"
    op.backup_data(seed["data"], original)
    members = archive_members(original.read_bytes())
    database = tmp_path / "altered.sqlite"
    database.write_bytes(members["catalogue.sqlite"])
    with sqlite3.connect(database) as db:
        db.execute("UPDATE runs SET state='queued'")
    db.close()
    members["catalogue.sqlite"] = database.read_bytes()
    manifest = json.loads(members["manifest.json"])
    entry = next(e for e in manifest["entries"] if e["path"] == "catalogue.sqlite")
    entry["bytes"] = len(members["catalogue.sqlite"])
    entry["sha256"] = hashlib.sha256(members["catalogue.sqlite"]).hexdigest()
    members["manifest.json"] = json.dumps(manifest).encode()
    altered = save_archive(tmp_path / "rehashed.zip", members)
    with pytest.raises(WorkspaceError) as caught:
        op.restore_data(altered, tmp_path / "destination")
    assert caught.value.code == "data_busy"
    assert not (tmp_path / "destination").exists()


def test_independent_preflight_reports_low_disk_busy_and_future_without_private_paths(seed, tmp_path, monkeypatch):
    op = operations()
    web = tmp_path / CANARY
    web.mkdir()
    (seed["data"] / op.FORMAT_FILE).write_text(json.dumps(dict(op.FORMAT, version=911)))
    monkeypatch.setattr(op.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    report = op.preflight(seed["data"], web)
    codes = {entry["code"] for entry in report["checks"]}
    assert "low_disk" in codes and "data_version_incompatible" in codes
    assert report["status"] == "not_ready"
    assert report["network_tested"] is False and report["real_ai_accepted"] is False
    assert str(tmp_path) not in json.dumps(report) and CANARY not in json.dumps(report)
    (seed["data"] / op.FORMAT_FILE).write_text(json.dumps(op.FORMAT))
    with op.DataLease(seed["data"]):
        busy = op.preflight(seed["data"], web)
        assert "runtime_locked" in {entry["code"] for entry in busy["checks"]}


def test_independent_unversioned_aw06_requires_explicit_offline_upgrade(seed):
    op = operations()
    (seed["data"] / op.FORMAT_FILE).unlink()
    before = fingerprint(seed["data"])
    app = create_app(Settings(seed["data"], test_mode=True), runtime_factory=NoDispatch)
    with pytest.raises(WorkspaceError) as caught:
        with TestClient(app, base_url="http://localhost"):
            pytest.fail("Legacy data requires explicit upgrade before startup")
    assert caught.value.code == "data_upgrade_required"
    assert fingerprint(seed["data"]) == before
    result = op.upgrade_data(seed["data"])
    assert not result["replay_started"]
    assert (seed["data"] / op.FORMAT_FILE).exists()
    assert op.inspect_data(seed["data"])["state"] == "compatible"


def test_independent_wrong_frontend_versions_do_not_pass_preflight(tmp_path):
    op = operations()
    web = tmp_path / "web"
    modules = web / "node_modules"
    for package in ("next", "react", "react-dom"):
        directory = modules / package
        directory.mkdir(parents=True)
        (directory / "package.json").write_text(json.dumps(dict(name=package, version="0.0.1")))
    binary = modules / "next/dist/bin/next"
    binary.parent.mkdir(parents=True)
    binary.write_text("// synthetic; must never be executed")
    result = op.preflight(tmp_path / "new-data", web, production=False)
    frontend = next(check for check in result["checks"] if check["check"] == "frontend_dependencies")
    assert not frontend["passed"], "Existence of a launcher is not pinned dependency compatibility"


def test_independent_source_kit_actual_scope_and_byte_tamper(tmp_path):
    from agent_workspace.source_kit import build_kit, verify_kit
    archive = tmp_path / "kit.zip"
    result = build_kit(archive)
    assert result["integrity_only"] and not result["self_contained"]
    assert not result["network_tested"] and not result["real_ai_accepted"]
    members = archive_members(archive.read_bytes())
    required = {"v2/apps/workspace/pyproject.toml", "v2/apps/workspace/uv.lock",
                "v2/apps/workspace/LOCAL_PILOT.md", "v2/apps/workspace/src/agent_workspace/runtime.py",
                "v2/apps/workspace/src/agent_workspace/simulation_model.py",
                "v2/apps/workspace/src/agent_workspace/assets/research_fixtures.json",
                "v2/apps/workspace-web/package.json", "v2/pnpm-lock.yaml"}
    assert required <= members.keys()
    assert all(not any(part in {".git", ".venv", "node_modules", "tests", "__pycache__"}
                       or part.startswith(".env") or part.endswith((".sqlite", ".sqlite-wal"))
                       for part in Path(name).parts) for name in members)
    assert all(not name.startswith(("docs/", "v2/apps/backend/", "v2/knowledge")) for name in members)
    assert not any(CANARY.encode() in body for body in members.values())
    assert b"tests.simulation_model" not in members["v2/apps/workspace/src/agent_workspace/runtime.py"]
    members["v2/apps/workspace/src/agent_workspace/runtime.py"] += b"\n# tamper\n"
    bad = save_archive(tmp_path / "tampered-kit.zip", members)
    with pytest.raises(WorkspaceError):
        verify_kit(bad)


def test_independent_source_kit_requires_scope_and_minimum_runtime_members(tmp_path):
    from agent_workspace.source_kit import verify_kit
    from agent_workspace.operations import APP_VERSION
    manifest = dict(format="agent-workspace-source-kit-v1", version=1,
                    application_version=APP_VERSION, scope="synthetic untrusted manifest", entries=[])
    empty = save_archive(tmp_path / "empty-kit.zip", {"source-kit-manifest.json": json.dumps(manifest).encode()})
    with pytest.raises(WorkspaceError):
        verify_kit(empty)


def test_independent_source_kit_never_follows_symlinked_source_directory(tmp_path, monkeypatch):
    from agent_workspace import source_kit as kit
    fake = tmp_path / "synthetic-source"
    required = kit.REQUIRED | {"v2/apps/workspace-web/next-env.d.ts",
                               "v2/patches/brace-expansion@5.0.8.patch",
                               "v2/apps/web/src/app/api/workspace/[[...path]]/route.ts"}
    for name in required:
        target = fake / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic source, no usable application")
    (fake / "v2/pnpm-lock.yaml").write_text("importers:\n  apps/workspace-web:\n    dependencies: {}\n  apps/web:\n    dependencies: {}\npackages:\n  placeholder: {}\n")
    (fake / "v2/pnpm-workspace.yaml").write_text("packages:\n  - apps/workspace-web\n  - apps/web\n")
    foreign = tmp_path / "outside-source-boundary"
    foreign.mkdir()
    (foreign / "foreign.ts").write_text(CANARY)
    (fake / "v2/apps/workspace-web/src").symlink_to(foreign, target_is_directory=True)
    monkeypatch.setattr(kit, "__file__", str(fake / "v2/apps/workspace/src/agent_workspace/source_kit.py"))
    with pytest.raises(WorkspaceError) as caught:
        kit.build_kit(tmp_path / "must-not-publish.zip")
    assert caught.value.code == "unsafe_data_path"
    assert not (tmp_path / "must-not-publish.zip").exists()


def test_independent_cli_private_failure_is_typed_without_traceback_or_user_path(tmp_path):
    source = Path(__file__).resolve().parents[3] / "v2/apps/workspace/src"
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(source), "PYDANTIC_AI_NO_BANNER": "1"}
    absent = tmp_path / CANARY / "missing-data"
    result = subprocess.run([sys.executable, "-m", "agent_workspace.cli", "backup",
                             "--data-dir", str(absent), "--output", str(tmp_path / "private/backup.zip")],
                            env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 1
    report = json.loads(result.stderr)
    assert report["status"] == "not_ready" and report["network_tested"] is False
    assert report["code"] in {"unsafe_data_path", "filesystem_operation_failed"}
    assert CANARY not in result.stderr + result.stdout
    assert "Traceback" not in result.stderr and str(tmp_path) not in result.stderr


@pytest.mark.parametrize("entry", ["asgi_environment", "launcher_child_environment"])
@pytest.mark.parametrize("alias_kind", ["final_directory", "parent_directory"])
def test_independent_environment_and_launcher_preserve_alias_until_pre_store_refusal(tmp_path, monkeypatch, entry, alias_kind):
    """Exercise supported settings/launcher seams, not just raw DataLease input."""
    from agent_workspace.cli import child_environments
    real = tmp_path / "real-private-data"
    real.mkdir(mode=0o700)
    alias = tmp_path / "symlink-alias"
    alias.symlink_to(real, target_is_directory=True)
    if alias_kind == "parent_directory":
        (real / "nested-data").mkdir(mode=0o700)
        data = alias / "nested-data"
    else:
        data = alias
    (real / "sentinel.txt").write_text(CANARY)
    before = fingerprint(real)
    for name in list(os.environ):
        if name.startswith("WORKSPACE_"):
            monkeypatch.delenv(name)
    if entry == "launcher_child_environment":
        server, web = child_environments(SimpleNamespace(data_dir=data, config=None,
            simulation=True, api_port=8177, web_port=3177, production=False))
        assert server["WORKSPACE_DATA_DIR"] == str(data.absolute()), "Launcher must not erase the alias before the ownership gate"
        assert "WORKSPACE_DATA_DIR" not in web
        for name, value in server.items():
            if name.startswith("WORKSPACE_"):
                monkeypatch.setenv(name, value)
    else:
        monkeypatch.setenv("WORKSPACE_DATA_DIR", str(data))
        monkeypatch.setenv("WORKSPACE_TEST_MODE", "1")
    app = create_app(runtime_factory=NoDispatch)
    with pytest.raises(WorkspaceError) as caught:
        with TestClient(app, base_url="http://localhost"):
            pytest.fail("Environment/launcher path must be refused before opening its target")
    assert caught.value.code == "unsafe_data_path"
    assert fingerprint(real) == before
    assert not list(real.rglob(".workspace.lock"))
    assert not list(real.rglob("catalogue.sqlite"))
