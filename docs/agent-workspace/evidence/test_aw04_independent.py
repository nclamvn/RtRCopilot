"""Independent AW-04 adversarial probes; disposable SQLite and synthetic HTTP.

Authored by a reviewer separate from the backend/web/evaluation builders. These
checks prove selected local boundaries, not model quality or product acceptance.
"""
import argparse
import asyncio
import hashlib
import io
import json
import time
from types import SimpleNamespace
import warnings
import zipfile

import httpx
import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from agent_workspace.cli import child_environments, doctor, main
from agent_workspace.config import Settings
from agent_workspace.data_lifecycle import DataLifecycle
from agent_workspace.evaluation.budget import CampaignBudget, ENDPOINT, MODEL
from agent_workspace.evaluation.baseline import BudgetModel, DirectToolAgent
from agent_workspace.model_guard import DispatchGuard, run_scope
from agent_workspace.provider_config import build_model, load_profile, write_profile
from agent_workspace.store import Store, WorkspaceError
from agent_workspace.workspace_state import WorkspaceState

LIMITS = dict(deadline_seconds=30, request_limit=4, tool_limit=4,
              token_limit=8000, output_bytes_limit=32000)
SENTINEL = "synthetic-key-private-IND-0427"


def seeded(tmp_path):
    store = Store(tmp_path / "independent.sqlite")
    _, owner = store.session(None)
    wid = store.workspaces(owner, "Disposable reviewer α")['id']
    fid = store.upload(owner, wid, 'facts.csv', 'id,qty\n000710,7.125\n', 'text/csv')['id']
    aid = store.create_artifact(owner, wid, 'Draft', 'document', '# First\n000710', 'ind-artifact-create')['id']
    store.revise(owner, aid, 1, '# Second\n000710', 'ind-artifact-revise')
    state = WorkspaceState(store)
    state.save_memory(owner, wid, 'Synthetic preferred language: Việt', 'ind-memory-save')
    rid = store.create_run(owner, wid, 'Synthetic only', 'ind-run-create', LIMITS)['id']
    store.finish(owner, rid, 'completed', content='Synthetic result', history='PRIVATE_CHECKPOINT_' + SENTINEL)
    return store, owner, wid, fid, aid, rid


def authority(**changes):
    return dict(approved=True, data_scope='synthetic-public-non-rtr', endpoint=ENDPOINT,
        model=MODEL, manifest_digest='a' * 64, case_ids=['IND-A', 'IND-B'],
        limit_usd=.5, max_calls=8, max_input_tokens=20000, max_output_tokens=256,
        concurrency=1, repair_rounds=0, approval_reference='synthetic offline test authority',
        expires_at=time.time() + 3600) | changes


def ledger(tmp_path, **changes):
    return CampaignBudget(tmp_path / 'ind-ledger.sqlite', authority(**changes), 'a' * 64)


def test_profile_private_no_hot_rebind_and_symlink(tmp_path, monkeypatch):
    profile = dict(version=1, model=MODEL, base_url=ENDPOINT, api_key=SENTINEL,
                   external_processing=True, fixture_tools_enabled=False)
    path = tmp_path / 'private' / 'profile.json'
    write_profile(path, profile)
    monkeypatch.setenv('WORKSPACE_CONFIG', str(path))
    monkeypatch.delenv('WORKSPACE_API_KEY', raising=False)
    frozen = Settings.from_env()
    write_profile(path, profile | {'api_key': SENTINEL + '-changed'})
    assert frozen.api_key == SENTINEL
    assert SENTINEL not in repr(frozen)
    assert SENTINEL not in json.dumps(doctor(frozen))
    assert path.stat().st_mode & 0o777 == 0o600
    link = tmp_path / 'linked.json'
    link.symlink_to(path)
    with pytest.raises(OSError):
        load_profile(link)
    path.chmod(0o640)
    with pytest.raises(ValueError, match='permissions'):
        load_profile(path)


def test_launcher_has_ui_flag_and_never_forwards_keys(tmp_path, monkeypatch):
    for name in ['OPENAI_API_KEY', 'WORKSPACE_API_KEY', 'ANTHROPIC_API_KEY', 'NEXT_PUBLIC_OPENAI_KEY']:
        monkeypatch.setenv(name, SENTINEL)
    args = argparse.Namespace(data_dir=tmp_path, config=None, simulation=True)
    server, web = child_environments(args)
    assert web['WORKSPACE_UI_ENABLED'] == '1'
    assert web['WORKSPACE_API_INTERNAL_URL'] == 'http://127.0.0.1:8110'
    assert SENTINEL not in json.dumps([server, web])
    assert server['WORKSPACE_TEST_MODE'] == '1'
    assert 'WORKSPACE_TEST_MODE' not in web


def test_key_configuration_refuses_getpass_echo_fallback(tmp_path, monkeypatch, capsys):
    import getpass
    def insecure_fallback(_prompt):
        warnings.warn('Synthetic no-tty fallback', getpass.GetPassWarning)
        return SENTINEL
    monkeypatch.setattr('agent_workspace.cli.getpass.getpass', insecure_fallback)
    path = tmp_path / 'must-not-exist.json'
    assert main(['configure', '--config', str(path), '--allow-external-processing']) == 1
    assert not path.exists()
    output = capsys.readouterr()
    assert SENTINEL not in output.out + output.err


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [429, 500])
async def test_provider_error_makes_exactly_one_synthetic_dispatch(tmp_path, code):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url == 'https://api.openai.com/v1/responses'
        body = json.loads(request.content)
        assert body['store'] is False and body['max_output_tokens'] == 2048
        return httpx.Response(code, json={'error': {'message': 'Synthetic provider failure', 'type': 'synthetic'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = build_model(Settings(tmp_path, model=MODEL, api_key=SENTINEL,
            external_processing=True), http_client=client)
        with pytest.raises(Exception):
            await Agent(model, retries=0).run('Synthetic public probe')
    assert len(requests) == 1


def test_export_originals_versions_hashes_and_private_checkpoint_exclusion(tmp_path):
    store, owner, wid, fid, aid, _ = seeded(tmp_path)
    payload = DataLifecycle(store).export(owner, wid)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert archive.read(f'sources/{fid}/original') == b'id,qty\n000710,7.125\n'
        assert archive.read(f'artifacts/{aid}/v1.txt') == b'# First\n000710'
        assert archive.read(f'artifacts/{aid}/v2.txt') == b'# Second\n000710'
        for entry in manifest['entries']:
            raw = archive.read(entry['path'])
            assert entry['bytes'] == len(raw)
            assert entry['sha256'] == hashlib.sha256(raw).hexdigest()
        all_bytes = b''.join(archive.read(p) for p in archive.namelist())
        for forbidden in (SENTINEL.encode(), b'PRIVATE_CHECKPOINT_', b'token_hash', b'api_key'):
            assert forbidden not in all_bytes


def test_export_refuses_oversized_saved_content_before_zip(tmp_path, monkeypatch):
    store, owner, wid, *_ = seeded(tmp_path)
    monkeypatch.setattr('agent_workspace.data_lifecycle.MAX_EXPORT_BYTES', 40)
    with pytest.raises(WorkspaceError, match='workspace_export_limit'):
        DataLifecycle(store).export(owner, wid)


def test_delete_token_expiry_cannot_be_replayed_to_other_workspace(tmp_path):
    store, owner, wid, *_ = seeded(tmp_path)
    other = store.workspaces(owner, 'Disposable reviewer α')['id']
    life = DataLifecycle(store)
    preview = life.preview(owner, wid)
    with pytest.raises(WorkspaceError, match='delete_confirmation_stale'):
        life.delete(owner, other, preview['confirmation_token'], preview['name'], 'ind-delete-foreign')
    with store.tx() as db:
        db.execute('UPDATE workspace_delete_previews SET expires_at=? WHERE workspace_id=?', (time.time() - 1, wid))
    with pytest.raises(WorkspaceError, match='delete_confirmation_stale'):
        life.delete(owner, wid, preview['confirmation_token'], preview['name'], 'ind-delete-expired')
    assert len(store.workspaces(owner)) == 2


def test_tombstone_also_denies_restored_stale_records_and_late_callbacks(tmp_path):
    store, owner, wid, fid, aid, rid = seeded(tmp_path)
    other = store.workspaces(owner, 'Unrelated must survive')['id']
    with store.tx() as db:
        snapshots = {}
        for table, where, value in [('workspaces', 'id', wid), ('files', 'id', fid),
                ('artifacts', 'id', aid), ('runs', 'id', rid)]:
            snapshots[table] = dict(db.execute(f'SELECT * FROM {table} WHERE {where}=?', (value,)).fetchone())
    lifecycle = DataLifecycle(store)
    p = lifecycle.preview(owner, wid)
    result = lifecycle.delete(owner, wid, p['confirmation_token'], p['name'], 'ind-delete-once')
    assert lifecycle.delete(owner, wid, p['confirmation_token'], p['name'], 'ind-delete-once') == result
    # Simulate stale external catalogue restoration; the tombstone must remain an
    # independent fence, rather than relying only on successful body deletion.
    with store.tx() as db:
        for table, row in snapshots.items():
            columns = ','.join(row)
            placeholders = ','.join('?' for _ in row)
            db.execute(f'INSERT INTO {table}({columns}) VALUES({placeholders})', tuple(row.values()))
    restored = Store(store.path)
    assert [w['id'] for w in restored.workspaces(owner)] == [other]
    actions = [lambda: restored.source(owner, fid), lambda: restored.artifact(owner, aid),
        lambda: restored.run(owner, rid), lambda: restored.events(owner, rid, 0),
        lambda: restored.finish(owner, rid, 'completed', content='Must never resurrect'),
        lambda: restored.upload(owner, wid, 'new.txt', 'No', 'text/plain'),
        lambda: restored.publish(owner, rid, 'late-tool', 'Late', 'late.md', 'No')]
    for action in actions:
        with pytest.raises(WorkspaceError, match='not_found'):
            action()


@pytest.mark.asyncio
async def test_campaign_unbound_ui_request_and_scope_change_are_denied(tmp_path):
    budget = ledger(tmp_path)
    params = ModelRequestParameters()
    scope = SimpleNamespace(owner='owner-a', run_id='ordinary-ui-run')
    with pytest.raises(WorkspaceError, match='campaign_run_not_bound'):
        await budget.reserve(scope, [], {'max_tokens': 128}, params)
    budget.bind_run('owner-a', 'approved-run', 'IND-A', 'workspace')
    with pytest.raises(WorkspaceError, match='campaign_run_binding_changed'):
        budget.bind_run('owner-a', 'approved-run', 'IND-B', 'direct-tool-agent')
    with pytest.raises(WorkspaceError, match='campaign_run_out_of_scope'):
        budget.bind_run('owner-a', 'wrong-case', 'NOT-APPROVED', 'workspace')


@pytest.mark.asyncio
async def test_campaign_global_concurrency_unknown_restart_and_binding(tmp_path):
    budget = ledger(tmp_path)
    params = ModelRequestParameters()
    a = SimpleNamespace(owner='same', run_id='workspace-run')
    b = SimpleNamespace(owner='same', run_id='baseline-run')
    budget.bind_run(a.owner, a.run_id, 'IND-A', 'workspace')
    budget.bind_run(b.owner, b.run_id, 'IND-A', 'direct-tool-agent')
    first = await budget.reserve(a, [], {'max_tokens': 128}, params)
    with pytest.raises(WorkspaceError, match='campaign_uncertain_or_concurrent_dispatch'):
        await budget.reserve(b, [], {'max_tokens': 128}, params)
    before = budget.snapshot()['conservative_charged_or_reserved_usd']
    await budget.unknown(first)
    reopened = CampaignBudget(budget.path, budget.authority, 'a' * 64)
    with pytest.raises(WorkspaceError, match='campaign_stopped'):
        await reopened.reserve(b, [], {'max_tokens': 128}, params)
    assert reopened.snapshot()['conservative_charged_or_reserved_usd'] == before
    with pytest.raises(WorkspaceError, match='campaign_ledger_binding_changed'):
        CampaignBudget(budget.path, budget.authority | {'limit_usd': .6}, 'a' * 64)


@pytest.mark.asyncio
async def test_campaign_oversized_usage_is_not_refunded_and_cannot_continue(tmp_path):
    budget = ledger(tmp_path)
    scope = SimpleNamespace(owner='independent', run_id='case-run')
    budget.bind_run(scope.owner, scope.run_id, 'IND-A', 'workspace')
    ticket = await budget.reserve(scope, [], {'max_tokens': 128}, ModelRequestParameters())
    reserved = budget.snapshot()['conservative_charged_or_reserved_usd']
    with pytest.raises(WorkspaceError, match='campaign_usage_unbounded'):
        await budget.settle(ticket, 1, 129)
    assert budget.snapshot()['conservative_charged_or_reserved_usd'] == reserved
    with pytest.raises(WorkspaceError, match='campaign_stopped'):
        await budget.reserve(scope, [], {'max_tokens': 128}, ModelRequestParameters())


@pytest.mark.asyncio
@pytest.mark.parametrize('settings', [{'max_tokens': 257}, {'max_tokens': 128, 'extra_body': {}},
    {'max_tokens': 128, 'openai_builtin_tools': []}, {'max_tokens': 128, 'openai_service_tier': 'priority'}])
async def test_campaign_rejects_unpriced_or_unbounded_dispatch(tmp_path, settings):
    budget = ledger(tmp_path)
    scope = SimpleNamespace(owner='independent', run_id='case-run')
    budget.bind_run(scope.owner, scope.run_id, 'IND-A', 'workspace')
    with pytest.raises(WorkspaceError):
        await budget.reserve(scope, [], settings, ModelRequestParameters())
    assert budget.snapshot()['calls'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('arm', ['workspace', 'direct-tool-agent'])
@pytest.mark.parametrize('settings_source', ['agent', 'model'])
async def test_actual_streamed_tool_parameters_reserve_before_both_arms_io(tmp_path, monkeypatch, arm, settings_source):
    budget = ledger(tmp_path, max_output_tokens=2048)
    scope = SimpleNamespace(owner='independent', run_id='streamed-' + arm)
    budget.bind_run(scope.owner, scope.run_id, 'IND-A', arm)
    requests, tool_calls = [], []

    async def stream(messages, info):
        # Physical mock-model IO cannot begin before the exact shared ledger has
        # a pending reservation; PydanticAI supplies its real parameter dataclass.
        current = budget.snapshot()
        assert current['dispatches'][-1]['status'] == 'reserved'
        requests.append(current['calls'])
        if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            yield 'Synthetic scoped result retained.'
        else:
            yield {0: DeltaToolCall(name='scoped_read', json_args='{}', tool_call_id='ind-read-01')}

    async def scoped_read() -> str:
        tool_calls.append('read')
        return 'Public synthetic source 710'

    model = FunctionModel(stream_function=stream, settings={'max_tokens': 2048} if settings_source == 'model' else None)
    if arm == 'workspace':
        wrapped = DispatchGuard(model, None, simulation=True, budget=budget)
        # DBOS replay ownership is separately integration-tested by runtime
        # proofs. This probe isolates the actual PydanticAI/ledger stream seam.
        monkeypatch.setattr(wrapped, 'reserve', lambda *_: None)
    else:
        wrapped = BudgetModel(model, budget, scope)
    token = run_scope.set(scope)
    try:
        agent = Agent(wrapped, tools=[scoped_read], retries=0,
            model_settings={'max_tokens': 2048} if settings_source == 'agent' else None)
        async with agent.run_stream('Read a synthetic source', deps=scope) as result:
            output = ''.join([piece async for piece in result.stream_text(delta=True)])
        assert 'Synthetic scoped result' in output
    finally:
        run_scope.reset(token)
    assert len(requests) == 2 and tool_calls == ['read']
    assert all(d['status'] == 'settled' for d in budget.snapshot()['dispatches'])


def test_direct_tool_port_fixture_parity_in_non_simulation_mode(tmp_path):
    settings = Settings(tmp_path, fixture_tools_enabled=True, test_mode=False)
    store = Store(tmp_path / 'parity.sqlite')
    baseline = DirectToolAgent(settings, store, FunctionModel(lambda *_: None), ledger(tmp_path))
    from agent_workspace.runtime import Runtime
    product = Runtime(settings, store)
    assert bool(baseline.research.sources) == bool(product.research.sources) is True


@pytest.mark.asyncio
@pytest.mark.parametrize('arm', ['workspace', 'direct-tool-agent'])
async def test_responses_sse_stream_settles_same_ledger_without_network(tmp_path, monkeypatch, arm):
    budget = ledger(tmp_path, max_output_tokens=2048)
    scope = SimpleNamespace(owner='independent', run_id='sse-' + arm)
    budget.bind_run(scope.owner, scope.run_id, 'IND-A', arm)
    calls = []
    text = 'Synthetic SSE output, not real AI.'
    content = dict(type='output_text', text=text, annotations=[])
    item = dict(id='msg_ind_1', type='message', role='assistant', status='completed', content=[content])
    response = dict(id='resp_ind_1', object='response', created_at=1, model='gpt-6.1-sol',
        status='completed', output=[item], usage=dict(input_tokens=100, output_tokens=20, total_tokens=120,
            input_tokens_details=dict(cached_tokens=0), output_tokens_details=dict(reasoning_tokens=5)))
    events = [
        dict(type='response.created', response=response | {'status': 'in_progress', 'output': [], 'usage': None}),
        dict(type='response.output_item.added', output_index=0, item=item | {'status': 'in_progress', 'content': []}),
        dict(type='response.content_part.added', output_index=0, content_index=0, item_id=item['id'], part=content | {'text': ''}),
        dict(type='response.output_text.delta', output_index=0, content_index=0, item_id=item['id'], delta=text),
        dict(type='response.output_text.done', output_index=0, content_index=0, item_id=item['id'], text=text),
        dict(type='response.content_part.done', output_index=0, content_index=0, item_id=item['id'], part=content),
        dict(type='response.output_item.done', output_index=0, item=item),
        dict(type='response.completed', response=response),
    ]
    def handler(request):
        assert budget.snapshot()['dispatches'][-1]['status'] == 'reserved'
        calls.append(request.url.path)
        payload = json.loads(request.content)
        assert payload['stream'] is True and payload['store'] is False and payload['max_output_tokens'] == 2048
        wire = ''.join('event: ' + e['type'] + '\ndata: ' + json.dumps(e) + '\n\n' for e in events)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=wire)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = build_model(Settings(tmp_path, model=MODEL, api_key=SENTINEL,
            external_processing=True), http_client=client)
        if arm == 'workspace':
            wrapped = DispatchGuard(model, None, budget=budget)
            monkeypatch.setattr(wrapped, 'reserve', lambda *_: None)
        else:
            wrapped = BudgetModel(model, budget, scope)
        token = run_scope.set(scope)
        try:
            async with Agent(wrapped, retries=0).run_stream('Synthetic public SSE probe', deps=scope) as result:
                actual = ''.join([part async for part in result.stream_text(delta=True)])
            assert actual == text
        finally:
            run_scope.reset(token)
    assert calls == ['/v1/responses']
    ledger_entry = budget.snapshot()['dispatches'][0]
    assert ledger_entry['status'] == 'settled'
    assert ledger_entry['input_tokens'] == 100 and ledger_entry['output_tokens'] == 20
