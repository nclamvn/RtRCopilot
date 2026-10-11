"""Actual SDK paused history: compatible HTTP resume, then original deadline.

No SQL authority/usage/deadline mutation and no replacement SDK/domain outcome.
This extends the cold-restored pending run only while its admitted deadline lives.
"""
import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from native_probe import snapshot
from rtr_copilot.api.main import app
from rtr_copilot.ingestion.api import file_subject
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository

root = Path(sys.argv[2])
assert str(root).startswith('/evidence/')
seed = json.loads((Path(os.environ['TIP054_RESTORE_ORIGINAL']) / 'seed.json').read_text())
identity = seed['run_id']
initial = snapshot(identity)
assert initial['execution']['state'] == 'paused'
remaining = (initial['execution']['deadline'] - datetime.now(UTC)).total_seconds()
assert 15 < remaining <= 120, 'restored_original_deadline_has_insufficient_window'
records = []

async def resume_http():
    engine = create_async_engine(os.environ['POSTGRES_DSN'].replace('postgresql://', 'postgresql+asyncpg://', 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    actor = await PostgresSubjectRepository(factory).get_by_user_id(uuid.UUID(seed['actor_id']))
    assert actor is not None
    async def synthetic_current_subject():
        return actor
    app.dependency_overrides[file_subject] = synthetic_current_subject
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://synthetic.test') as client:
            started = time.perf_counter_ns()
            response = await asyncio.wait_for(client.post(f'/api/v1/actions/runs/{identity}/resume'), timeout=1.5)
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            assert response.status_code == 202 and elapsed <= 1000
            body = response.json()
            assert body['state'] == 'queued'
            assert body['spent_tool_calls'] == initial['execution']['spent']
            return {'http_status': response.status_code, 'elapsed_ms': elapsed, 'state': body['state']}
    finally:
        app.dependency_overrides.pop(file_subject, None)
        await engine.dispose()

def launch(label, incompatible):
    out = (root / (label + '.stdout.txt')).open('w')
    err = (root / (label + '.stderr.txt')).open('w')
    env = dict(os.environ, TIP054_NATIVE_PAUSE='none', TIP054_NATIVE_RUN_ID=identity,
               TIP054_NATIVE_MARKER='/tmp/' + root.name + '-' + label + '-unused')
    if incompatible:
        env['RTR_BUILD_SHA'] = 'f' * 64
    command = [sys.executable, '/work/worker_child.py']
    child = subprocess.Popen(command, env=env, stdout=out, stderr=err)
    out.close(); err.close()
    records.append({'label': label, 'pid': child.pid, 'command': command, 'incompatible_configured_build': incompatible})
    return child

def stop(child, label):
    if child.poll() is None:
        child.send_signal(signal.SIGTERM)
    try:
        code = child.wait(timeout=10)
        forced = False
    except subprocess.TimeoutExpired:
        child.kill(); code = child.wait(timeout=5); forced = True
    records.append({'label': label, 'pid': child.pid, 'exit_code': code, 'forced_kill_after_10_seconds': forced})

def unchanged_source(current):
    assert current['receipts'] == initial['receipts']
    assert current['attempts'] == initial['attempts']
    assert current['canonical_links'] == initial['canonical_links'] == 1
    assert current['execution']['spent'] == initial['execution']['spent']
    assert current['execution']['deadline'] == initial['execution']['deadline']
    assert current['native_workflow'][0] == seed['workflow_id']

current = initial
try:
    ack = asyncio.run(resume_http())
    compatible = launch('native-compatible-after-pause', False)
    try:
        until = time.monotonic() + 20
        while time.monotonic() < until:
            current = snapshot(identity)
            if (current['execution']['state'] == 'waiting'
                    and current['execution']['epoch'] > initial['execution']['epoch']
                    and current['native_outputs'] > initial['native_outputs']
                    and not current['execution']['dispatch_pending']):
                break
            assert compatible.poll() is None, 'compatible_worker_exited'
            time.sleep(.1)
        else:
            raise AssertionError('compatible_history_not_actually_resumed')
        unchanged_source(current)
        resumed = current
    finally:
        stop(compatible, 'finite-compatible-drain')
    incompatible = launch('native-paused-original-deadline', True)
    try:
        until = time.monotonic() + 20
        while time.monotonic() < until:
            current = snapshot(identity)
            if current['execution']['state'] == 'paused' and current['native_outputs'] > resumed['native_outputs']:
                break
            assert incompatible.poll() is None, 'incompatible_worker_exited'
            time.sleep(.1)
        else:
            raise AssertionError('native_incompatible_pause_not_observed')
        unchanged_source(current)
        paused = current
        assert current['native_workflow'][1] != 'SUCCESS'
        until = time.monotonic() + max(0, (initial['execution']['deadline'] - datetime.now(UTC)).total_seconds()) + 10
        while time.monotonic() < until:
            current = snapshot(identity)
            if current['execution']['state'] == 'partial' and current['native_workflow'][1] == 'SUCCESS':
                break
            assert incompatible.poll() is None, 'paused_worker_exited_before_original_deadline'
            time.sleep(.2)
        else:
            raise AssertionError('paused_history_did_not_finish_at_original_deadline')
        unchanged_source(current)
        assert current['native_outputs'] > paused['native_outputs']
        with __import__('psycopg').connect(os.environ['POSTGRES_DSN']) as db:
            reason = db.execute('SELECT reason_code FROM action_executions WHERE run_id=%s', (identity,)).fetchone()[0]
        assert reason == 'wall_budget_exhausted'
        (root / 'native-pause-resume-deadline-proof.json').write_text(json.dumps({
            'status': 'PASS', 'workflow_id': seed['workflow_id'], 'resume_ack': ack,
            'initial': initial, 'compatible_resumed': resumed, 'incompatible_paused': paused,
            'deadline_terminal': current, 'terminal_reason': reason,
            'interpretation': 'Actual SDK SUCCESS returns business partial at immutable parent deadline, not all-effects success or SDK cancellation.',
            'limits': 'Same SDK application version with incompatible configured RTR build; no arbitrary rolling-code upgrade, external effect undo, or deadline mutation.'
        }, default=str, indent=2))
    finally:
        stop(incompatible, 'finite-deadline-drain')
except Exception as exc:
    (root / 'native-pause-resume-deadline-failure.json').write_text(json.dumps({
        'exception_type': type(exc).__name__, 'message': str(exc), 'last_snapshot': current,
    }, default=str, indent=2))
    raise
finally:
    (root / 'native-pause-resume-deadline-process-records.json').write_text(json.dumps(records, indent=2))
