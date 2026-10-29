"""Builder-owned AW07 local boundaries; independent reviewer probes are separate."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from agent_workspace.api import create_app
from agent_workspace.config import Settings
from agent_workspace.operations import (
    DataLease, FORMAT, FORMAT_FILE, backup_data, diagnostics, initialize_format,
    inspect_data, restore_data, source_identifier, upgrade_data,
)
from agent_workspace.runtime import Runtime
from agent_workspace.source_kit import build_kit, verify_kit
from agent_workspace.store import Store, WorkspaceError


def seed(path):
    store = Store(path / "catalogue.sqlite")
    runtime = Runtime(Settings(path, test_mode=True), store)
    _, owner = store.session(None)
    wid = store.workspaces(owner, "Private synthetic project")['id']
    store.upload(owner, wid, "source.txt", "Secret synthetic source", "text/plain")
    store.create_artifact(owner, wid, "Private title", "document", "private draft", "aw07-artifact-001")
    return runtime, owner, wid


def test_owner_lease_and_exception_release(tmp_path):
    with pytest.raises(RuntimeError), DataLease(tmp_path):
        with pytest.raises(WorkspaceError, match="runtime_locked"):
            with DataLease(tmp_path):
                pass
        raise RuntimeError("synthetic startup failure")
    with DataLease(tmp_path):
        pass


def test_future_marker_no_catalogue_mutation(tmp_path):
    seed(tmp_path)
    catalogue = tmp_path / "catalogue.sqlite"
    before = catalogue.read_bytes()
    (tmp_path / FORMAT_FILE).write_text(json.dumps(FORMAT | {"version": 999}))
    with pytest.raises(WorkspaceError, match="data_version_incompatible"):
        with TestClient(create_app(Settings(tmp_path))):
            pass
    assert catalogue.read_bytes() == before


def test_environment_symlink_survives_parse_and_is_refused_before_store(tmp_path, monkeypatch):
    import argparse
    from agent_workspace.cli import child_environments
    target = tmp_path / "real"
    target.mkdir(mode=0o700)
    seed(target)
    initialize_format(target)
    original = (target / "catalogue.sqlite").read_bytes()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("WORKSPACE_DATA_DIR", str(alias))
    settings = Settings.from_env()
    assert settings.data_dir == alias.absolute()
    server, _ = child_environments(argparse.Namespace(data_dir=alias, simulation=True, config=None))
    assert server["WORKSPACE_DATA_DIR"] == str(alias.absolute())
    with pytest.raises(WorkspaceError, match="unsafe_data_path"):
        with TestClient(create_app(settings), base_url="http://localhost"):
            pass
    assert (target / "catalogue.sqlite").read_bytes() == original
    assert not (target / ".workspace.lock").exists()


def test_unversioned_requires_explicit_upgrade_before_start(tmp_path):
    seed(tmp_path)
    with pytest.raises(WorkspaceError, match="data_upgrade_required"):
        with TestClient(create_app(Settings(tmp_path))):
            pass
    assert upgrade_data(tmp_path)["replay_started"] is False
    assert inspect_data(tmp_path)["state"] == "compatible"
    with TestClient(create_app(Settings(tmp_path)), base_url="http://localhost") as client:
        assert client.get("/api/workspace/status").status_code == 401


def test_private_backup_new_restore_preserves_bytes_and_rejects_live(tmp_path):
    data = tmp_path / "original"
    data.mkdir(mode=0o700)
    runtime, owner, _ = seed(data)
    initialize_format(data)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    archive = private / "backup.zip"
    with DataLease(data), pytest.raises(WorkspaceError, match="runtime_locked"):
        backup_data(data, archive)
    assert not archive.exists()
    assert backup_data(data, archive)["private"]
    restored = tmp_path / "restored"
    assert restore_data(archive, restored)["replay_started"] is False
    saved = sqlite3.connect(restored / "catalogue.sqlite")
    assert saved.execute("SELECT content FROM files").fetchone()[0] == "Secret synthetic source"
    saved.close()
    with pytest.raises(WorkspaceError, match="destination_exists"):
        restore_data(archive, restored)
    assert owner not in json.dumps(diagnostics(runtime, owner))


def test_diagnostics_scoped_contentfree_stable(tmp_path):
    runtime, owner, _ = seed(tmp_path)
    _, other = runtime.store.session(None)
    runtime.store.workspaces(other, "Other owner private")
    runtime.reason = "private secret failure /Users/never-share"
    first = diagnostics(runtime, owner)
    assert first == diagnostics(runtime, owner)
    assert first["counts"] == dict(workspaces=1, files=1, artifacts=1, runs_active=0)
    assert first["runtime"]["reason_code"] == "runtime_unavailable"
    assert first["application"]["build_id"] == source_identifier()
    serialized = json.dumps(first)
    assert all(value not in serialized for value in (owner, "Private title", "Secret synthetic", "/Users/", "Other owner"))


def test_package_fixture_is_shipped_not_test_path():
    from agent_workspace.simulation_model import build_model
    from agent_workspace.research import OfflineResearch
    assert build_model() is not None
    assert OfflineResearch(True).sources


def test_actual_source_kit_is_neutral_bounded_and_verified(tmp_path):
    archive = tmp_path / "pilot.zip"
    result = build_kit(archive)
    assert result["status"] == "verified" and not result["self_contained"]
    assert verify_kit(archive) == result
    import zipfile
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        assert all(not any(part in Path(n).parts for part in (".venv", "node_modules", ".git", ".workspace-data")) for n in names)
        assert "\n  apps/web:" not in zipped.read("v2/pnpm-lock.yaml").decode()
        assert "assets/research_fixtures.json" in " ".join(names)
        readme = zipped.read("v2/apps/workspace/README.md").decode()
        assert "/Users/" not in readme and "RtR" not in readme
        assert readme == zipped.read("v2/apps/workspace/LOCAL_PILOT.md").decode()
        assert readme.startswith("# Local pilot operator guide (AW-07)")
        assert "docs/agent-workspace" not in readme
        extracted = tmp_path / "pilot"
        zipped.extractall(extracted)
    source = extracted / "v2/apps/workspace/src"
    # The original editable Python environment is deliberately reused. Both the
    # extracted CLI and its independently spawned server must import KIT source,
    # not the checkout installed by that environment.
    script = """import argparse,subprocess,sys
from agent_workspace.cli import child_environments
args=argparse.Namespace(data_dir='synthetic-data',simulation=True,config=None)
server,_=child_environments(args)
print(subprocess.check_output([sys.executable,'-c','import agent_workspace.api; print(agent_workspace.api.__file__)'],env=server,text=True).strip())
"""
    imported = subprocess.check_output([sys.executable, "-c", script], env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(source)}, text=True).strip()
    assert imported == str(source / "agent_workspace/api.py")
