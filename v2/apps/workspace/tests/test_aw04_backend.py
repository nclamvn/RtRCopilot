"""AW-04 synthetic HTTP/configuration and actual SQLite lifecycle boundaries.

No provider socket, real credential, production data or legacy runtime is used.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import warnings
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic_ai import Agent

from agent_workspace.api import create_app
from agent_workspace.cli import child_environments, doctor, launch, main
from agent_workspace.config import Settings
from agent_workspace.connections import Connections
from agent_workspace.data_lifecycle import DataLifecycle
from agent_workspace.provider_config import ENDPOINT, build_model, load_profile, write_profile
from agent_workspace.runtime import Runtime, VERSION
from agent_workspace.store import Store, WorkspaceError
from agent_workspace.workspace_state import WorkspaceState

P = "/api/workspace"
ORIGIN = {"origin": "http://localhost:3110"}
CANARY = "synthetic-PRIVATE-key-never-export"
LIMITS = dict(deadline_seconds=60, request_limit=4, tool_limit=8, token_limit=8000, output_bytes_limit=32000)


def profile(**changes):
    return dict(version=1, model="openai-responses:gpt-6.1-sol", base_url=ENDPOINT,
                api_key=CANARY, external_processing=True, fixture_tools_enabled=False) | changes


def populated(tmp_path):
    store = Store(tmp_path / "catalogue.sqlite")
    _, owner = store.session(None)
    wid = store.workspaces(owner, "Synthetic lifecycle")['id']
    state = WorkspaceState(store)
    connections = Connections(store, tmp_path, True)
    file = store.upload(owner, wid, "source.txt", "Public source 24750\nViệt Nam", "text/plain")
    artifact = store.create_artifact(owner, wid, "Draft", "document", "# First\n24750", "artifact-create-01")
    store.revise(owner, artifact['id'], 1, "# Second\n24751", "artifact-revise-01")
    state.save_memory(owner, wid, "Explicit remembered 24752", "memory-save-001")
    run = store.create_run(owner, wid, "Synthetic question 24753", "run-create-0001", LIMITS)['id']
    store.finish(owner, run, "completed", content="Synthetic answer 24754", history="PRIVATE model history excluded")
    return store, owner, wid, file['id'], artifact['id'], run, state, connections


def test_private_profile_roundtrip_permissions_optin_and_redaction(tmp_path, monkeypatch, capsys):
    config = tmp_path / "private" / "provider.json"
    write_profile(config, profile())
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert load_profile(config) == profile()
    monkeypatch.setenv("WORKSPACE_CONFIG", str(config))
    settings = Settings.from_env()
    assert settings.api_key == CANARY and settings.external_processing
    assert CANARY not in repr(settings)
    assert CANARY not in json.dumps(doctor(settings))
    config.chmod(0o644)
    assert Settings.from_env().configuration_error == "private_configuration_invalid"
    with pytest.raises(ValueError):
        load_profile(config)
    config.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(config)
    with pytest.raises(OSError):
        load_profile(link)
    with pytest.raises(OSError):
        write_profile(link, profile())
    config.unlink()
    monkeypatch.setattr("agent_workspace.cli.getpass.getpass", lambda prompt: CANARY)
    assert main(["configure", "--config", str(config), "--allow-external-processing"]) == 0
    assert CANARY not in capsys.readouterr().out
    assert not list(config.parent.glob(".workspace-profile-*"))


def test_profile_invalid_and_legacy_never_discovered(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKSPACE_CONFIG", raising=False)
    monkeypatch.delenv("WORKSPACE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", CANARY)
    assert Settings.from_env().api_key is None
    for bad in [profile(base_url="http://localhost:8888/v1"), profile(api_key="bad\nkey"), profile(version=2), profile(extra="no")]:
        with pytest.raises(ValueError):
            write_profile(tmp_path / "bad.json", bad)
    assert not (tmp_path / "bad.json").exists()


def test_private_cli_rejects_echo_fallback(tmp_path, monkeypatch, capsys):
    def unsafe(prompt):
        import getpass
        warnings.warn('TTY unavailable', getpass.GetPassWarning)
        raise AssertionError('Must not reach echoed input')
    monkeypatch.setattr('agent_workspace.cli.getpass.getpass', unsafe)
    config = tmp_path / 'provider.json'
    assert main(['configure', '--config', str(config), '--allow-external-processing']) == 1
    assert not config.exists()
    assert 'No network call made' in capsys.readouterr().err


def test_private_config_no_hot_rebind_and_child_env_isolation(tmp_path, monkeypatch):
    config = tmp_path / "provider.json"
    write_profile(config, profile())
    monkeypatch.setenv("WORKSPACE_CONFIG", str(config))
    frozen = Settings.from_env()
    write_profile(config, profile(api_key="different-synthetic-private-key"))
    assert frozen.api_key == CANARY
    assert Settings.from_env().api_key != CANARY
    monkeypatch.setenv("WORKSPACE_API_KEY", CANARY)
    monkeypatch.setenv("OPENAI_API_KEY", CANARY)
    args = argparse.Namespace(config=config, data_dir=tmp_path, simulation=False)
    server, web = child_environments(args)
    assert server['WORKSPACE_CONFIG'] == str(config)
    assert "WORKSPACE_CONFIG" not in web and "WORKSPACE_API_KEY" not in server
    assert "OPENAI_API_KEY" not in server and "OPENAI_API_KEY" not in web
    assert web['WORKSPACE_API_INTERNAL_URL'] == "http://127.0.0.1:8110"
    assert web['WORKSPACE_UI_ENABLED'] == "1"
    assert CANARY not in json.dumps([server, web])


def test_one_command_launcher_child_contract_and_own_group_cleanup(tmp_path, monkeypatch):
    launched, killed = [], []
    class FakeProcess:
        def __init__(self, cmd, **kwargs):
            self.pid = 100000 + len(launched)
            launched.append((cmd, kwargs))
        def poll(self):
            return 1  # synthetic early startup failure
        def wait(self, timeout=None):
            return 1
    monkeypatch.setattr('agent_workspace.cli.subprocess.Popen', FakeProcess)
    monkeypatch.setattr('agent_workspace.cli.os.killpg', lambda pid, sig: killed.append(pid))
    monkeypatch.setenv('WORKSPACE_API_KEY', CANARY)
    assert launch(argparse.Namespace(config=None, data_dir=tmp_path, simulation=True)) == 1
    api, web = launched
    assert api[0][1:3] == ['-m', 'uvicorn'] and api[1]['start_new_session']
    assert api[1]['env']['WORKSPACE_TEST_MODE'] == '1'
    assert web[0][0] == 'node' and 'next/dist/bin/next' in web[0][1]
    assert web[0][-4:] == ['--hostname', '127.0.0.1', '--port', '3110']
    assert web[1]['env']['WORKSPACE_UI_ENABLED'] == '1'
    assert web[1]['env']['WORKSPACE_API_INTERNAL_URL'] == 'http://127.0.0.1:8110'
    assert CANARY not in str(launched) and len(killed) == 2


def test_no_key_readiness_is_truthful_no_socket(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No network expected")
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    with TestClient(create_app(Settings(tmp_path)), base_url="http://localhost") as client:
        client.post(P + '/session', headers=ORIGIN, json={})
        status = client.get(P + '/readiness').json()
        assert not status['available'] and status['reason'] == 'model_not_configured'
        assert status['provider']['storage'] is False
        assert status['setup_command'].startswith('.venv/bin/workspace configure ')
        assert status['setup_directory'] == 'v2/apps/workspace'
        assert 'API_KEY' not in json.dumps(status)
    for settings, reason in [
        (Settings(tmp_path, model='openai:gpt-6.1-sol'), 'workspace_api_key_not_configured'),
        (Settings(tmp_path, model='openai:gpt-6.1-sol', api_key=CANARY), 'external_processing_not_approved'),
        (Settings(tmp_path, model='openai:gpt-6.1-sol', api_key=CANARY, external_processing=True, base_url='https://private.example/v1'), 'unsupported_provider_endpoint')]:
        runtime = Runtime(settings, Store(tmp_path / (reason + '.sqlite')))
        assert runtime._model() is None and runtime.reason == reason


@pytest.mark.asyncio
async def test_official_responses_adapter_tools_storage_and_usage_synthetic_http(tmp_path):
    requests = []
    def handler(request):
        assert request.url == 'https://api.openai.com/v1/responses'
        body = json.loads(request.content)
        requests.append(body)
        assert body['store'] is False and body['max_output_tokens'] == 2048
        assert body['reasoning']['effort'] == 'low'
        assert all(tool['type'] == 'function' for tool in body.get('tools', []))
        output = ([dict(type='function_call', id='fc1', call_id='call1', name='scoped_read', arguments='{}', status='completed')]
                  if len(requests) == 1 else
                  [dict(type='message', id='msg1', role='assistant', status='completed', content=[dict(type='output_text', text='Synthetic public fact 24750', annotations=[])])])
        return httpx.Response(200, json=dict(id='resp'+str(len(requests)), object='response', created_at=1, status='completed',
            model='gpt-6.1-sol', output=output, usage=dict(input_tokens=23, output_tokens=17, total_tokens=40,
                input_tokens_details=dict(cached_tokens=0), output_tokens_details=dict(reasoning_tokens=12))))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = build_model(Settings(tmp_path, model='openai-responses:gpt-6.1-sol', api_key=CANARY, external_processing=True), http_client=client)
        assert model.client.max_retries == 0
        async def scoped_read() -> str:
            return 'Public synthetic fact 24750'
        agent = Agent(model, tools=[scoped_read], retries=0)
        result = await agent.run('Read the synthetic fact')
        assert result.output == 'Synthetic public fact 24750'
        assert result.usage.output_tokens == 34  # includes 24 reasoning tokens across two requests
    assert len(requests) == 2 and CANARY not in json.dumps(requests)


@pytest.mark.asyncio
async def test_provider_unknown_has_no_hidden_retry(tmp_path):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout('synthetic transport interruption')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = build_model(Settings(tmp_path, model='openai:gpt-6.1-sol', api_key=CANARY, external_processing=True), http_client=client)
        with pytest.raises(Exception):
            await Agent(model, retries=0).run('synthetic only')
    assert count == 1


def test_export_consistent_originals_all_versions_manifest_no_private_state(tmp_path):
    store, owner, wid, fid, aid, rid, _, _ = populated(tmp_path)
    data = DataLifecycle(store).export(owner, wid)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['format'] == 'agent-workspace-export-v1'
        for entry in manifest['entries']:
            raw = archive.read(entry['path'])
            assert len(raw) == entry['bytes'] and hashlib.sha256(raw).hexdigest() == entry['sha256']
            assert not entry['path'].startswith('/') and '..' not in entry['path'].split('/')
        assert archive.read(f'sources/{fid}/original').decode() == 'Public source 24750\nViệt Nam'
        assert archive.read(f'artifacts/{aid}/v1.txt') == b'# First\n24750'
        assert archive.read(f'artifacts/{aid}/v2.txt') == b'# Second\n24751'
        bodies = b''.join(archive.read(name) for name in archive.namelist())
        assert b'Explicit remembered 24752' in bodies and b'Synthetic answer 24754' in bodies
        for forbidden in [CANARY.encode(), b'token_hash', b'PRIVATE model history excluded', b'api_key', b'OPENAI_API_KEY']:
            assert forbidden not in bodies


def test_delete_confirmation_staleness_loss_ack_scope_and_restart(tmp_path):
    store, owner, wid, fid, aid, rid, state, connections = populated(tmp_path)
    _, other_owner = store.session(None)
    other = store.workspaces(owner, 'Other workspace')['id']
    other_file = store.upload(owner, other, 'other.txt', 'Keep this unrelated content', 'text/plain')['id']
    lifecycle = DataLifecycle(store)
    with pytest.raises(WorkspaceError, match='not_found'):
        lifecycle.preview(other_owner, wid)
    preview = lifecycle.preview(owner, wid)
    assert preview['artifact_ids'] == [aid]
    with pytest.raises(WorkspaceError, match='delete_confirmation_mismatch'):
        lifecycle.delete(owner, wid, preview['confirmation_token'], 'Wrong', 'delete-key-01')
    state.save_memory(owner, wid, 'A later explicit memory', 'memory-save-002')
    with pytest.raises(WorkspaceError, match='delete_confirmation_stale'):
        lifecycle.delete(owner, wid, preview['confirmation_token'], preview['name'], 'delete-key-01')
    preview = lifecycle.preview(owner, wid)
    result = lifecycle.delete(owner, wid, preview['confirmation_token'], preview['name'], 'delete-key-01')
    assert result['deleted'] is True
    assert lifecycle.delete(owner, wid, preview['confirmation_token'], preview['name'], 'delete-key-01') == result
    assert [w['id'] for w in store.workspaces(owner)] == [other]
    assert store.source(owner, other_file)['content'] == 'Keep this unrelated content'
    reopened = Store(store.path)
    WorkspaceState(reopened)
    conn = Connections(reopened, tmp_path, True)
    for action in [lambda: reopened.items(owner, wid, 'messages'), lambda: reopened.source(owner, fid),
        lambda: reopened.artifact(owner, aid), lambda: reopened.run(owner, rid), lambda: reopened.events(owner, rid, 0),
        lambda: conn.approvals(owner, wid), lambda: conn.effects(owner, wid), lambda: conn.connection(owner, wid),
        lambda: DataLifecycle(reopened).export(owner, wid), lambda: state.memories(owner, wid),
        lambda: reopened.create_run(owner, wid, 'no resurrection', 'run-create-0001', LIMITS),
        lambda: reopened.publish(owner, rid, 'tool-replay', 'No', 'draft.md', 'resurrect')]:
        with pytest.raises(WorkspaceError, match='not_found'):
            action()
    with reopened.tx() as db:
        assert db.execute('SELECT COUNT(*) FROM workspace_tombstones WHERE workspace_id=?', (wid,)).fetchone()[0] == 1
        for table in ('files', 'artifacts', 'messages', 'runs', 'workspace_memory', 'approvals', 'effects', 'workspace_state_requests'):
            assert db.execute(f'SELECT COUNT(*) FROM {table} WHERE workspace_id=?', (wid,)).fetchone()[0] == 0
        assert not db.execute('SELECT 1 FROM revisions WHERE result LIKE ?', ('%' + aid + '%',)).fetchone()


def test_delete_blocks_busy_active_callback_and_unsettled_effect(tmp_path):
    store, owner, wid, _, _, _, _, connections = populated(tmp_path)
    rid = store.create_run(owner, wid, 'pending', 'pending-run-01', LIMITS)['id']
    active = set()
    lifecycle = DataLifecycle(store, active_runs=active)
    preview = lifecycle.preview(owner, wid)
    assert preview['blocked_reason'] == 'workspace_busy'
    with pytest.raises(WorkspaceError, match='workspace_busy'):
        lifecycle.delete(owner, wid, preview['confirmation_token'], preview['name'], 'delete-key-01')
    connections.set_connection(owner, wid, True, 0, 'grant-key-0001')
    approval = connections.prepare(owner, rid, 'call1', 'Synthetic retained outbox')
    with store.tx() as db:
        db.execute("INSERT INTO effects VALUES('effect1',?,?,?,?, 'uncertain',NULL,NULL,1)", (approval['id'], owner, wid, rid))
    store.finish(owner, rid, 'cancelled')
    preview = lifecycle.preview(owner, wid)
    assert preview['blocked_reason'] == 'workspace_unsettled_effects'
    with pytest.raises(WorkspaceError, match='workspace_unsettled_effects'):
        lifecycle.delete(owner, wid, preview['confirmation_token'], preview['name'], 'delete-key-01')
    connections.complete(owner, 'effect1', dict(fixture=True, delivered=True, note='Synthetic retained outbox'))
    active.add(rid)
    assert lifecycle.preview(owner, wid)['blocked_reason'] == 'workspace_busy'
    active.clear()
    preview = lifecycle.preview(owner, wid)
    lifecycle.delete(owner, wid, preview['confirmation_token'], preview['name'], 'delete-key-01')
    for operation in (lambda: connections.resolve(owner, approval['id'], 'approve', 'replayed-approval'),
        lambda: connections.complete(owner, 'effect1', {})):
        with pytest.raises(WorkspaceError, match='not_found'):
            operation()


def test_export_limit_does_not_prevent_confirmed_delete(tmp_path, monkeypatch):
    store, owner, wid, *_ = populated(tmp_path)
    monkeypatch.setattr('agent_workspace.data_lifecycle.MAX_EXPORT_BYTES', 20)
    lifecycle = DataLifecycle(store)
    with pytest.raises(WorkspaceError, match='workspace_export_limit'):
        lifecycle.export(owner, wid)
    preview = lifecycle.preview(owner, wid)
    assert lifecycle.delete(owner, wid, preview['confirmation_token'], preview['name'], 'delete-large-01')['deleted']


def test_api_export_delete_contract_strict_inputs_and_ownership(tmp_path):
    with TestClient(create_app(Settings(tmp_path)), base_url='http://localhost') as client:
        client.post(P + '/session', headers=ORIGIN, json={})
        wid = client.post(P + '/workspaces', headers=ORIGIN, json={'name': 'API synthetic'}).json()['id']
        exported = client.get(P + f'/workspaces/{wid}/export')
        assert exported.status_code == 200 and exported.content.startswith(b'PK')
        preview = client.get(P + f'/workspaces/{wid}/delete-preview').json()
        args = dict(request_id='api-delete-01', confirmation_token=preview['confirmation_token'], confirm_name=preview['name'])
        assert client.post(P + f'/workspaces/{wid}/delete', headers=ORIGIN, json=args | {'approved': True}).status_code == 422
        deleted = client.post(P + f'/workspaces/{wid}/delete', headers=ORIGIN, json=args)
        assert deleted.status_code == 200 and deleted.json()['deleted']
        assert client.post(P + f'/workspaces/{wid}/delete', headers=ORIGIN, json=args).json() == deleted.json()
        assert client.get(P + f'/workspaces/{wid}/export').status_code == 404
        client.cookies.clear()
        client.post(P + '/session', headers=ORIGIN, json={})
        assert client.post(P + f'/workspaces/{wid}/delete', headers=ORIGIN, json=args).status_code == 404


def test_runtime_build_version_binding_fails_prior_live_runs(tmp_path):
    store = Store(tmp_path / 'catalogue.sqlite')
    _, owner = store.session(None)
    wid = store.workspaces(owner, 'Upgrade synthetic')['id']
    rid = store.create_run(owner, wid, 'old pending', 'old-run-001', LIMITS)['id']
    with store.tx() as db:
        db.execute("UPDATE runs SET workflow_version='workspace-aw03-v1' WHERE id=?", (rid,))
    store.fail_incompatible_runs(VERSION)
    assert store.run(owner, rid)['error'] == 'workflow_version_incompatible'


def test_tombstoned_stale_pending_restore_cannot_break_or_restart_runtime(tmp_path):
    store, owner, wid, _, _, rid, _, conn = populated(tmp_path)
    with store.tx() as db:
        old_run = dict(db.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone())
    lifecycle = DataLifecycle(store)
    preview = lifecycle.preview(owner, wid)
    lifecycle.delete(owner, wid, preview['confirmation_token'], preview['name'], 'delete-stale-01')
    old_run.update(state='queued', workflow_version='workspace-aw03-v1', cancel_requested=1, dispatch_pending=1)
    with store.tx() as db:
        columns, values = ','.join(old_run), ','.join('?' for _ in old_run)
        db.execute(f'INSERT INTO runs({columns}) VALUES({values})', tuple(old_run.values()))
    assert store.pending() == []
    store.fail_incompatible_runs(VERSION)
    assert conn.wakeups() == []
    with pytest.raises(WorkspaceError, match='not_found'):
        store.run(owner, rid)
