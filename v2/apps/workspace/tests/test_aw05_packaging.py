"""Independent frontend/launcher contracts; no external network or model calls."""
import argparse
import json
from pathlib import Path
import signal
import subprocess

import pytest
from fastapi.testclient import TestClient

from agent_workspace.api import create_app
from agent_workspace.cli import child_environments, launch, local_port, main
from agent_workspace.config import Settings, local_origins


@pytest.mark.parametrize("value", [0, 1023, 65536, -1, True, "3120.0", "03120", "http://localhost:3120", None])
def test_launcher_rejects_unbounded_or_ambiguous_ports(value):
    with pytest.raises(argparse.ArgumentTypeError):
        local_port(value)


@pytest.mark.parametrize("origin", ["https://example.com:3120", "http://example.com:3120", "http://localhost:80", "http://localhost:3120/path", "http://user@localhost:3120", "http://localhost:3120?key=bad", "http://localhost:3120#bad", "http://localhost:99999", 3120])
def test_origin_configuration_is_only_explicit_loopback(origin):
    with pytest.raises((ValueError, TypeError)):
        local_origins(json.dumps([origin]))


def test_explicit_isolated_ports_no_legacy_environment_discovery(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "WORKSPACE_API_KEY", "WORKSPACE_MODEL", "WORKSPACE_CONFIG", "DATABASE_URL"):
        monkeypatch.setenv(name, "SYNTHETIC-NEVER-FORWARD")
    args = argparse.Namespace(config=None, data_dir=tmp_path, simulation=True,
                              api_port=8120, web_port=3120, production=True)
    api, web = child_environments(args)
    assert web["WORKSPACE_API_INTERNAL_URL"] == "http://127.0.0.1:8120"
    assert web["WORKSPACE_PRODUCTION_BUILD"] == "1"
    assert api["WORKSPACE_TEST_MODE"] == "1"
    assert json.loads(api["WORKSPACE_ORIGINS"]) == ["http://localhost:3120", "http://localhost:8120", "http://127.0.0.1:3120", "http://127.0.0.1:8120"]
    assert "SYNTHETIC-NEVER-FORWARD" not in json.dumps([api, web])
    assert "NEXT_TELEMETRY_DISABLED" in web


def test_origin_env_invalid_fails_closed_and_supported_custom_origin_works(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKSPACE_CONFIG", raising=False)
    monkeypatch.setenv("WORKSPACE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_ORIGINS", '["http://127.0.0.1:3120"]')
    settings = Settings.from_env()
    assert settings.origins == ("http://127.0.0.1:3120",)
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.post("/api/workspace/session", json={}, headers={"origin": "http://127.0.0.1:3110"}).status_code == 403
        assert client.post("/api/workspace/session", json={}, headers={"origin": "http://127.0.0.1:3120"}).status_code == 200
    monkeypatch.setenv("WORKSPACE_ORIGINS", '["https://remote.example:3120"]')
    settings = Settings.from_env()
    assert settings.configuration_error == "invalid_loopback_origins" and settings.origins == ()
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.post("/api/workspace/session", json={}, headers={"origin": "http://127.0.0.1:3110"}).status_code == 403
    assert local_origins('["http://localhost:3120/", "http://localhost:3120"]') == ("http://localhost:3120",)


def test_launcher_neutral_package_explicit_ports_and_group_cleanup(tmp_path, monkeypatch):
    launched, killed = [], []
    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.pid = 100001 + len(launched)
            launched.append((command, kwargs))
        def poll(self):
            return 1
        def wait(self, timeout=None):
            return 1
    monkeypatch.setattr("agent_workspace.cli.subprocess.Popen", FakeProcess)
    monkeypatch.setattr("agent_workspace.cli.os.killpg", lambda pid, sig: killed.append((pid, sig)))
    args = argparse.Namespace(config=None, data_dir=tmp_path, simulation=True, api_port=8120, web_port=3120, production=False)
    assert launch(args) == 1
    api, web = launched
    assert api[0][-4:] == ["--host", "127.0.0.1", "--port", "8120"]
    assert web[0][-5:] == ["dev", "--hostname", "127.0.0.1", "--port", "3120"]
    assert Path(web[1]["cwd"]).name == "workspace-web"
    assert web[1]["start_new_session"] is True
    assert killed == [(100001, signal.SIGTERM), (100002, signal.SIGTERM)]


def test_equal_ports_fail_before_process_or_data_creation(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_workspace.cli.subprocess.Popen", lambda *a, **k: pytest.fail("Must not start a process"))
    args = argparse.Namespace(config=None, data_dir=tmp_path, simulation=True, api_port=3120, web_port=3120)
    with pytest.raises(ValueError):
        child_environments(args)
    with pytest.raises(SystemExit) as error:
        main(["launch", "--simulation", "--api-port", "3120", "--web-port", "3120"])
    assert error.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_missing_local_production_build_does_not_start_process(tmp_path, monkeypatch, capsys):
    original = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: False if p.name == "BUILD_ID" else original(p))
    monkeypatch.setattr("agent_workspace.cli.subprocess.Popen", lambda *a, **k: pytest.fail("Must not start a process"))
    args = argparse.Namespace(config=None, data_dir=tmp_path, simulation=True, api_port=8120, web_port=3120, production=True)
    assert launch(args) == 1
    assert "no local production build" in capsys.readouterr().err


def test_child_startup_failure_still_terminates_only_owned_group(tmp_path, monkeypatch):
    killed = []
    class Started:
        pid = 100123
        def wait(self, timeout=None): return 0
    calls = []
    def start(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 2:
            raise OSError("Synthetic missing frontend executable")
        return Started()
    monkeypatch.setattr("agent_workspace.cli.subprocess.Popen", start)
    monkeypatch.setattr("agent_workspace.cli.os.killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(OSError):
        launch(argparse.Namespace(config=None, data_dir=tmp_path, simulation=True, api_port=8120, web_port=3120))
    assert killed == [(100123, signal.SIGTERM)]


def test_interrupt_escalates_stubborn_owned_children_only(tmp_path, monkeypatch):
    children, killed = [], []
    class Stubborn:
        def __init__(self, *args, **kwargs):
            self.pid = 100201 + len(children)
            self.waited = 0
            children.append(self)
        def poll(self):
            raise KeyboardInterrupt
        def wait(self, timeout=None):
            self.waited += 1
            if self.waited == 1:
                raise subprocess.TimeoutExpired("synthetic-child", timeout)
            return 0
    monkeypatch.setattr("agent_workspace.cli.subprocess.Popen", Stubborn)
    monkeypatch.setattr("agent_workspace.cli.os.killpg", lambda pid, sig: killed.append((pid, sig)))
    assert launch(argparse.Namespace(config=None, data_dir=tmp_path, simulation=True, api_port=8120, web_port=3120)) == 0
    assert killed == [(100201, signal.SIGTERM), (100202, signal.SIGTERM), (100201, signal.SIGKILL), (100202, signal.SIGKILL)]
    assert all(child.waited == 2 for child in children)


def test_independent_entry_graph_and_dependency_versions_match_offline_baseline():
    apps = Path(__file__).resolve().parents[2]
    frontend = apps / "workspace-web"
    independent = json.loads((frontend / "package.json").read_text())
    legacy = json.loads((apps / "web/package.json").read_text())
    assert independent["name"] == "@agent-workspace/web"
    assert independent["dependencies"] == legacy["dependencies"]
    for command in ("dev", "start"):
        assert "WORKSPACE_UI_ENABLED=1" in independent["scripts"][command]
        assert "NEXT_TELEMETRY_DISABLED=1" in independent["scripts"][command]
        assert "--hostname 127.0.0.1" in independent["scripts"][command]
    assert "WORKSPACE_PRODUCTION_BUILD=1" in independent["scripts"]["build"]
    result = subprocess.run(["node", "scripts/audit-graph.mjs"], cwd=frontend, capture_output=True, text=True, check=True)
    graph = json.loads(result.stdout)
    assert graph["status"] == "PASS" and graph["external_model_calls"] == 0
    assert graph["source_files"]
    assert all(f["path"].startswith(("workspace-web/src/", "web/src/workspace/")) or f["path"] == "web/src/app/api/workspace/[[...path]]/route.ts" for f in graph["source_files"])
    assert not (frontend / "src/proxy.ts").exists()
