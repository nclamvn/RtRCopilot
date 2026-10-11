"""Finite actual ASGI Action API measurements; no provider/engine effect calls."""
import asyncio
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

sys.path.insert(0, '/workspace/v2/apps/backend/tests')
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_action_contracts_integration import principal
from test_context_memory_integration import publish

from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.service import ActionService
from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.ingestion.api import file_subject

root = Path(sys.argv[1])
assert str(root).startswith('/evidence/')
root.mkdir(exist_ok=True)
dsn = os.environ['POSTGRES_DSN']
assert '/rtr_tip054_' in dsn

def quantile(values, q):
    return sorted(values)[math.ceil(len(values) * q) - 1]

async def main():
    engine = create_async_engine(dsn.replace('postgresql://', 'postgresql+asyncpg://', 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    records = []
    observations = (root / 'samples.jsonl').open('x')
    def retain(record):
        records.append(record)
        observations.write(json.dumps(record, separators=(',', ':')) + '\n')
        observations.flush()  # Every completed observation is host-backed now.
    try:
        admin = await principal(factory, Role.ADMIN)
        owner = await principal(factory)
        with tempfile.TemporaryDirectory(prefix='tip054-latency-source-') as temporary:
            refs = await publish(Path(temporary), factory, owner, 'tip054.latency.' + uuid.uuid4().hex, 'TIP054.LATENCY.' + uuid.uuid4().hex)
        actions = ActionService(UnitOfWork(factory))
        await actions.admit_capability(admin, 'sot.read', '2', request_id='latency-capability-admit')
        async def synthetic_auth(_=None):
            return owner
        app.dependency_overrides[file_subject] = synthetic_auth
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://synthetic.test') as client:
            async def request(profile, case, operation, method, path, payload=None):
                started = time.perf_counter_ns()
                try:
                    response = await client.request(method, path, json=payload, headers={'X-Request-ID': f'tip054-latency-{profile}-{case}-{operation}'})
                    elapsed = (time.perf_counter_ns() - started) / 1_000_000
                    body = response.json()
                    okay = response.status_code in {'admission': (201,), 'submit': (202,), 'status': (200,), 'cancel': (202,)}[operation]
                    record = {'profile': profile, 'case': case, 'operation': operation, 'elapsed_ms': elapsed, 'http_status': response.status_code, 'okay': okay, 'state': body.get('state'), 'error_code': body.get('error', {}).get('code')}
                    retain(record)
                    return body if okay else None
                except Exception as exc:
                    retain({'profile': profile, 'case': case, 'operation': operation, 'elapsed_ms': (time.perf_counter_ns() - started) / 1_000_000, 'okay': False, 'exception_type': type(exc).__name__})
                    return None
            for concurrency in (1, 10, 25, 50):
                semaphore = asyncio.Semaphore(concurrency)
                async def case(number):
                    async with semaphore:
                        payload = PlanRequest(idempotency_key=f'latency-{concurrency}-{number:04}-{uuid.uuid4().hex}', objective='Synthetic bounded HTTP source-read action', source_refs=refs,
                            steps=(StepRequest(step_key='read', capability_id='sot.read', capability_version='2', arguments={'record_key': refs[0].record_key}),)).model_dump(mode='json')
                        plan = await request(concurrency, number, 'admission', 'POST', '/api/v1/actions/plans', payload)
                        if plan is None:
                            return
                        execution = await request(concurrency, number, 'submit', 'POST', f"/api/v1/actions/plans/{plan['plan_id']}/execute", {'expected_plan_digest': plan['plan_digest']})
                        if execution is None:
                            return
                        assert execution['state'] == 'queued' and execution['spent_tool_calls'] == 0
                        status = await request(concurrency, number, 'status', 'GET', f"/api/v1/actions/runs/{execution['run_id']}")
                        if status is not None:
                            assert status['state'] == 'queued'
                        cancelled = await request(concurrency, number, 'cancel', 'POST', f"/api/v1/actions/runs/{execution['run_id']}/cancel")
                        if cancelled is not None:
                            assert cancelled['cancel_requested'] and cancelled['state'] == 'cancelled'
                await asyncio.gather(*(case(number) for number in range(100)))
        cells = []
        for concurrency in (1, 10, 25, 50):
            for operation in ('admission', 'submit', 'status', 'cancel'):
                samples = [s for s in records if s['profile'] == concurrency and s['operation'] == operation]
                values = [s['elapsed_ms'] for s in samples]
                limit = 500 if operation == 'admission' else 1000
                cell = {'concurrency': concurrency, 'operation': operation, 'samples': len(samples), 'failures': sum(not s['okay'] for s in samples), 'p50_ms': quantile(values, .5) if values else None, 'p95_ms': quantile(values, .95) if values else None, 'p99_ms': quantile(values, .99) if values else None, 'p95_limit_ms': limit}
                cell['pass'] = len(samples) == 100 and cell['failures'] == 0 and cell['p95_ms'] <= limit
                cells.append(cell)
        report = {'status': 'PASS' if all(c['pass'] for c in cells) else 'FAIL', 'cells': cells, 'profile': {'runner_cpus': 4, 'runner_memory_gib': 4, 'postgres_cpus': 2, 'postgres_memory_mib': 4096, 'postgres_data_tmpfs_gib': 3, 'samples_per_operation_load': 100, 'corpus': 'one permitted signed synthetic SOT reference', 'auth': 'synthetic current subject dependency only; real API middleware/router/policy/domain paths', 'rate_limits_enabled': True, 'finite_test_window_render_quota': 5000, 'finite_test_window_read_quota': 5000, 'rate_window_seconds': 60, 'no_worker': True, 'no_provider': True, 'recorder': 'per_observation_host_backed_JSONL_append_flush_final_JSON'}, 'limits': 'Request service time includes pool contention while an acquired case slot is held; semaphore queue excluded. Declared finite synthetic rate quotas cover burst samples, not serving default30 writes/120reads per minute certification. Local ASGI not network/UI/mobile/OIDC latency, provider/render time or production load certification.'}
        (root / 'latency-summary.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        if report['status'] != 'PASS':
            raise SystemExit(1)
    finally:
        observations.close()
        (root / 'samples.json').write_text(json.dumps(records, indent=2))
        app.dependency_overrides.pop(file_subject, None)
        await engine.dispose()

asyncio.run(main())
