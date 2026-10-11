"""Actual source/service/SDK process proofs, finite and synthetic-only."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, '/workspace/v2/apps/backend/tests')
import psycopg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_action_contracts_integration import principal
from test_context_memory_integration import publish
from test_documents_integration import approved_template

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.models import BudgetRequest, PlanRequest, StepRequest
from rtr_copilot.actions.service import ActionService
from rtr_copilot.auth.models import Role
from rtr_copilot.db.uow import UnitOfWork

root = Path(sys.argv[2])
assert str(root).startswith('/evidence/')
root.mkdir(exist_ok=True)
domain = os.environ['POSTGRES_DSN']
engine_dsn = os.environ['ACTION_WORKFLOW_DSN']
assert '/rtr_tip054_' in domain and '/rtr_tip054_' in engine_dsn

async def seed():
    engine = create_async_engine(domain.replace('postgresql://', 'postgresql+asyncpg://', 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        admin = await principal(factory, Role.ADMIN)
        _, owner, template = await approved_template(factory)
        with tempfile.TemporaryDirectory(prefix='tip054-native-source-') as temporary:
            refs = await publish(Path(temporary), factory, owner, 'tip054.native.' + uuid.uuid4().hex, 'TIP054.NATIVE.' + uuid.uuid4().hex)
        actions = ActionService(UnitOfWork(factory))
        for capability in ('sot.read', 'documents.create_draft'):
            await actions.admit_capability(admin, capability, '2', request_id='native-capability-admit')
        plan = await actions.create_plan(owner, PlanRequest(idempotency_key='native-' + uuid.uuid4().hex,
            objective='Synthetic native process recovery proof', source_refs=refs,
            requested_internal_draft=True, budget=BudgetRequest(tool_calls=8, wall_seconds=120),
            steps=(StepRequest(step_key='read', capability_id='sot.read', capability_version='2', arguments={'record_key': refs[0].record_key}),
                   StepRequest(step_key='draft', capability_id='documents.create_draft', capability_version='2', dependencies=('read',), arguments={'template_version_id': str(template), 'parameters': {'customer_name': 'Synthetic native fixture'}}))), request_id='native-plan')
        view = await ExecutionService(UnitOfWork(factory), actions=actions).submit(owner, plan.plan_id, plan.plan_digest, request_id='native-submit')
        result = {'run_id': str(view.run_id), 'plan_id': str(plan.plan_id), 'workflow_id': view.workflow_id, 'actor_id': owner.user_id, 'plan_digest': plan.plan_digest, 'state': view.state, 'deadline_at': view.deadline_at.isoformat(), 'source_refs': [r.model_dump(mode='json') for r in refs]}
        (root / 'seed.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        await engine.dispose()

def snapshot(identity):
    with psycopg.connect(domain) as db:
        row = db.execute('SELECT state,spent_tool_calls,tool_call_limit,deadline_at,epoch,dispatch_pending FROM action_executions WHERE run_id=%s', (identity,)).fetchone()
        receipts = db.execute('SELECT kind,count(*) FROM action_execution_receipts WHERE run_id=%s GROUP BY kind ORDER BY kind', (identity,)).fetchall()
        attempts = db.execute('SELECT step_key,attempt,charged_calls FROM action_step_attempts WHERE run_id=%s ORDER BY step_key,attempt', (identity,)).fetchall()
        jobs = db.execute('SELECT count(*) FROM action_source_links WHERE run_id=%s', (identity,)).fetchone()[0]
    native = None
    native_outputs = 0
    with psycopg.connect(engine_dsn) as db:
        exists = db.execute("SELECT to_regclass('dbos.workflow_status')").fetchone()[0]
        if exists:
            native = db.execute('SELECT workflow_uuid,status,application_version FROM dbos.workflow_status WHERE workflow_uuid=%s', ('action-' + identity,)).fetchone()
            native_outputs = db.execute('SELECT count(*) FROM dbos.operation_outputs WHERE workflow_uuid=%s', ('action-' + identity,)).fetchone()[0]
    return {'execution': dict(zip(('state','spent','limit','deadline','epoch','dispatch_pending'), row)), 'receipts': dict(receipts), 'attempts': attempts, 'canonical_links': jobs, 'native_workflow': native, 'native_outputs': native_outputs}

def cancel_remaining():
    seed_data = json.loads((root / 'seed.json').read_text())
    identity = seed_data['run_id']
    env = dict(os.environ, TIP054_NATIVE_PAUSE='none', TIP054_NATIVE_MARKER='/tmp/' + root.name + '-unused-marker', TIP054_NATIVE_RUN_ID=identity)
    out = (root / 'worker.stdout.txt').open('w'); err = (root / 'worker.stderr.txt').open('w')
    command = [sys.executable, '/work/worker_child.py']
    child = subprocess.Popen(command, env=env, stdout=out, stderr=err)
    out.close(); err.close()
    record = {'pid': child.pid, 'command': command}
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            before = snapshot(identity)
            if before['execution']['state'] == 'waiting' and before['receipts'].get('job_accepted') == 1 and before['native_outputs'] >= 3:
                break
            if child.poll() is not None:
                raise RuntimeError('cancel_worker_exited')
            time.sleep(0.1)
        else:
            raise AssertionError('cancel_partial_fixture_not_reached')
        async def acknowledge():
            from httpx import ASGITransport, AsyncClient
            from rtr_copilot.api.main import app
            from rtr_copilot.ingestion.api import file_subject
            from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository
            db_engine = create_async_engine(domain.replace('postgresql://', 'postgresql+asyncpg://', 1))
            factory = async_sessionmaker(db_engine, expire_on_commit=False)
            actor = await PostgresSubjectRepository(factory).get_by_user_id(uuid.UUID(seed_data['actor_id']))
            assert actor is not None
            async def synthetic_auth():
                return actor
            app.dependency_overrides[file_subject] = synthetic_auth
            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url='http://synthetic.test') as client:
                    started = time.perf_counter_ns()
                    response = await asyncio.wait_for(client.post(f'/api/v1/actions/runs/{identity}/cancel'), timeout=1.5)
                    elapsed = (time.perf_counter_ns() - started) / 1_000_000
                    body = response.json()
                    assert response.status_code == 202 and elapsed <= 1000
                    assert body['state'] == 'partial' and body['cancel_requested'] and body['cancel_acknowledged']
                    return {'http_status': response.status_code, 'elapsed_ms': elapsed, 'business_state': body['state'], 'cancel_requested': body['cancel_requested'], 'receipt_count': len(body['receipts']), 'spent': body['spent_tool_calls']}
            finally:
                app.dependency_overrides.pop(file_subject, None)
                await db_engine.dispose()
        ack = asyncio.run(acknowledge())
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            final = snapshot(identity)
            if final['execution']['state'] == 'partial' and final['native_workflow'][1] == 'SUCCESS':
                break
            time.sleep(0.1)
        else:
            raise AssertionError('truthful_cancel_result_not_native_terminal')
        assert final['receipts'] == before['receipts'] and final['attempts'] == before['attempts']
        assert final['execution']['spent'] == before['execution']['spent']
        assert final['canonical_links'] == before['canonical_links'] == 1
        with psycopg.connect(domain) as db:
            generated = db.execute('SELECT count(*) FROM generated_files g JOIN action_source_links l USING(render_job_id) WHERE l.run_id=%s', (identity,)).fetchone()[0]
        assert generated == 0
        (root / 'native-proof.json').write_text(json.dumps({'status': 'PASS', 'mode': 'cancel_remaining', 'ack': ack, 'before': before, 'after': final, 'generated_files': generated, 'interpretation': 'Native workflow SUCCESS means it returned business partial/cancel_remaining, not completed file success and not SDK CANCELLED.', 'limits': 'Finite real HTTP ack plus current domain/source/actual SDK result; no external irreversible effect undo or prompt synchronous get_result cancellation claim.'}, default=str, indent=2))
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
        try:
            record['exit_code'] = child.wait(timeout=10); record['forced_kill'] = False
        except subprocess.TimeoutExpired:
            child.kill(); record['exit_code'] = child.wait(timeout=5); record['forced_kill'] = True
        (root / 'process-records.json').write_text(json.dumps([record], indent=2))

def supervise():
    if os.environ['TIP054_NATIVE_PAUSE'] == 'cancel_remaining':
        return cancel_remaining()
    seed_data = json.loads((root / 'seed.json').read_text())
    identity = seed_data['run_id']
    mode = os.environ['TIP054_NATIVE_PAUSE']
    render_completion = mode in {'complete_draft', 'renderer_kill'}
    renderer_kill = mode == 'renderer_kill'
    if render_completion:
        mode = 'after_draft_commit'
    marker = Path('/tmp') / (root.parent.name + '-' + root.name + '-marker.json')
    assert not marker.exists()
    records = []
    def start(label, pause):
        env = dict(os.environ, TIP054_NATIVE_PAUSE=pause, TIP054_NATIVE_MARKER=str(marker), TIP054_NATIVE_RUN_ID=identity)
        out = (root / (label + '.stdout.txt')).open('w')
        err = (root / (label + '.stderr.txt')).open('w')
        command = [sys.executable, '/work/worker_child.py']
        child = subprocess.Popen(command, env=env, stdout=out, stderr=err)
        out.close(); err.close()
        records.append({'label': label, 'pid': child.pid, 'command': command, 'pause': pause})
        return child
    def stop(child, label, sig):
        child.send_signal(sig)
        try:
            code = child.wait(timeout=10)
            killed = False
        except subprocess.TimeoutExpired:
            child.kill(); code = child.wait(timeout=5); killed = True
        records.append({'label': label, 'pid': child.pid, 'signal': sig.name, 'returncode': code, 'forced_kill_after_10_seconds': killed})
    child = start('first', mode)
    try:
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError('native_worker_exited_before_marker')
            time.sleep(0.05)
        assert marker.exists(), 'native_pause_not_reached'
        observed_marker = json.loads(marker.read_text())
        assert observed_marker['pid'] == child.pid
        before = snapshot(identity)
        if mode == 'before_dispatch':
            assert before['canonical_links'] == 0 and before['execution']['spent'] == 0 and before['native_workflow'] is None
        elif mode == 'during_draft':
            assert before['canonical_links'] == 0 and len(before['attempts']) == 2
        elif mode == 'after_draft_commit':
            assert before['canonical_links'] == 1 and before['receipts'].get('job_accepted') == 1
        else:
            raise AssertionError('unsupported_native_pause')
        (root / 'before-kill.json').write_text(json.dumps({'marker': observed_marker, 'snapshot': before}, default=str, indent=2))
        stop(child, 'actual-process-kill', signal.SIGKILL)
        restarted = start('restart', 'none')
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                after = snapshot(identity)
                if (after['execution']['state'] == 'waiting' and after['canonical_links'] == 1
                        and after['receipts'].get('job_accepted') == 1
                        and after['execution']['epoch'] > before['execution']['epoch']
                        and after['native_outputs'] > before['native_outputs']):
                    break
                if restarted.poll() is not None:
                    raise RuntimeError('restarted_worker_exited')
                time.sleep(0.1)
            else:
                raise AssertionError('recovery_not_waiting_on_one_canonical_job')
            time.sleep(0.7)
            final = snapshot(identity)
            assert final['canonical_links'] == 1 and final['receipts'].get('job_accepted') == 1
            expected_attempts = 3 if mode == 'during_draft' else 2
            assert final['receipts'].get('read_verified') == 1 and len(final['attempts']) == expected_attempts
            if mode == 'during_draft':
                assert [a[1] for a in final['attempts'] if a[0] == 'draft'] == [1, 2]
                assert final['execution']['spent'] > before['execution']['spent']
            assert final['execution']['spent'] == sum(a[2] for a in final['attempts'])
            assert final['execution']['deadline'].isoformat() == seed_data['deadline_at']
            assert final['native_workflow'][0] == seed_data['workflow_id']
            (root / 'after-restart.json').write_text(json.dumps(final, default=str, indent=2))
            if render_completion:
                from render_probe import render_and_verify
                render_and_verify(root, identity, restarted, kill_profile=renderer_kill)
        finally:
            stop(restarted, 'finite-worker-drain', signal.SIGTERM)
        result_mode = ('renderer_kill' if renderer_kill else 'complete_draft') if render_completion else mode
        (root / 'native-proof.json').write_text(json.dumps({'status': 'PASS', 'mode': result_mode, 'same_workflow_id': seed_data['workflow_id'], 'records': records, 'worker_child_sha256': hashlib.sha256(Path('/work/worker_child.py').read_bytes()).hexdigest(), 'limits': 'Real local product worker/process/domain+SDK source recovery. Generated-file proof only when separately retained real-file-proof.json passes; renderer kill may truthfully yield source failure/partial instead. No production/rolling-upgrade claim.'}, indent=2))
    finally:
        if child.poll() is None:
            stop(child, 'exception-cleanup', signal.SIGKILL)
        (root / 'process-records.json').write_text(json.dumps(records, indent=2))

if __name__ == '__main__':
    if sys.argv[1] == 'seed':
        asyncio.run(seed())
    elif sys.argv[1] == 'supervise':
        supervise()
    else:
        raise ValueError('unsupported_mode')
