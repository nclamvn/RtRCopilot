"""Actual DBOS import, async workflow, duplicate, and PostgreSQL persistence."""
from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata as metadata
import inspect
import json
import os
from pathlib import Path

import psycopg
import sqlalchemy
from dbos import DBOS, DBOSClient, DBOSConfig, SetWorkflowID

EXPECTED = {'dbos': '3.2.0', 'sqlalchemy': '2.0.43', 'psycopg': '3.2.9'}
WORKFLOW_ID = os.environ.get('TIP054_PROOF_WORKFLOW_ID', 'tip054-4b-serving-pin-admission')
EFFECT_ID = (WORKFLOW_ID + '-effect' if 'TIP054_PROOF_WORKFLOW_ID' in os.environ
             else 'case-one')
OUTPUT_NAME = os.environ.get('TIP054_PROOF_OUTPUT', 'admission-proof.json')
assert OUTPUT_NAME.endswith('.json') and '/' not in OUTPUT_NAME and '..' not in OUTPUT_NAME
observed = {name: metadata.version(name) for name in EXPECTED}
assert observed == EXPECTED, observed
dsn = os.environ['DBOS_SYSTEM_DATABASE_URL']
native_dsn = dsn.replace('postgresql+psycopg://', 'postgresql://')
with psycopg.connect(native_dsn) as connection:
    connection.execute('CREATE TABLE IF NOT EXISTS admission_effects (id text PRIMARY KEY, value integer NOT NULL)')

@DBOS.step(retries_allowed=False)
async def synthetic_effect(identity: str, value: int) -> int:
    # Disposable synthetic effect only; this is not a product adapter.
    with psycopg.connect(native_dsn) as connection:
        connection.execute('INSERT INTO admission_effects VALUES (%s,%s) ON CONFLICT (id) DO NOTHING', (identity, value))
        return connection.execute('SELECT value FROM admission_effects WHERE id=%s', (identity,)).fetchone()[0]

@DBOS.workflow()
async def serving_pin_workflow(identity: str, value: int) -> int:
    return await synthetic_effect(identity, value)

async def prove() -> dict:
    with SetWorkflowID(WORKFLOW_ID):
        handle = await DBOS.start_workflow_async(serving_pin_workflow, EFFECT_ID, 54)
    result = await asyncio.wait_for(handle.get_result(), timeout=10)
    with SetWorkflowID(WORKFLOW_ID):
        duplicate = await DBOS.start_workflow_async(serving_pin_workflow, EFFECT_ID, 54)
    duplicate_result = await asyncio.wait_for(duplicate.get_result(), timeout=10)
    status = await DBOS.get_workflow_status_async(handle.workflow_id)
    steps = await DBOS.list_workflow_steps_async(handle.workflow_id)
    with psycopg.connect(native_dsn) as connection:
        effect_count = connection.execute('SELECT count(*) FROM admission_effects WHERE id=%s', (EFFECT_ID,)).fetchone()[0]
        persisted = connection.execute('SELECT status FROM dbos.workflow_status WHERE workflow_uuid=%s', (handle.workflow_id,)).fetchone()[0]
        engine_rows = connection.execute('SELECT count(*) FROM dbos.operation_outputs WHERE workflow_uuid=%s', (handle.workflow_id,)).fetchone()[0]
    assert (result, duplicate_result, effect_count, persisted) == (54, 54, 1, 'SUCCESS')
    assert status.status == 'SUCCESS' and len(steps) >= 1 and engine_rows >= 1
    return {'result': result, 'duplicate_result': duplicate_result, 'effect_count': effect_count, 'persisted_status': persisted, 'engine_step_rows': engine_rows, 'api_status': status.status, 'workflow_id': handle.workflow_id}

DBOS(config=DBOSConfig(name='tip054-4b-admission', system_database_url=dsn, application_version='tip054-4b-admission-v1'))
DBOS.launch()
try:
    proof = asyncio.run(prove())
    report = {'status': 'PASS', 'actual_versions': observed, 'actual_module_paths': {'sqlalchemy': sqlalchemy.__file__, 'psycopg': psycopg.__file__}, 'apis': {name: str(inspect.signature(getattr(DBOS, name))) for name in ('start_workflow_async', 'get_workflow_status_async', 'list_workflow_steps_async', 'cancel_workflow_async', 'register_queue')}, 'proof': proof, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'limits': 'Serving-pin import and one disposable PG async workflow/duplicate proof only; not product admission, cancellation responsiveness, replay migration, security or production certification.'}
    Path('/evidence').joinpath(OUTPUT_NAME).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
finally:
    DBOS.destroy()
