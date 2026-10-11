"""Populated 0018→0019→0018→0019 and actual rtr_app invariants.

Run only in a labelled disposable fixture. Existing domain histories survive;
the newly downgraded executor tables intentionally do not restore their data.
"""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import sys
import uuid
from urllib.parse import urlsplit

sys.path.insert(0, '/workspace/v2/apps/backend/tests')
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_action_contracts_integration import principal

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.service import ActionService
from rtr_copilot.auth.models import Role
from rtr_copilot.context.models import SOTReference
from rtr_copilot.db.uow import UnitOfWork

NEW = ('action_executions', 'action_step_attempts', 'action_execution_receipts',
       'action_execution_events', 'action_source_links')

async def main():
    mode, evidence_name = sys.argv[1:]
    evidence = Path(evidence_name)
    dsn = os.environ['INTEGRATION_DATABASE_DSN']
    assert urlsplit(dsn).path.startswith('/rtr_tip054_')
    assert urlsplit(dsn).username == 'rtr_app'
    engine = create_async_engine(dsn.replace('postgresql://', 'postgresql+asyncpg://', 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        if mode == 'seed-execution':
            admin = await principal(factory, Role.ADMIN)
            actions = ActionService(UnitOfWork(factory))
            await actions.admit_capability(admin, 'sot.read', '2', request_id='migration-v2-admit')
            async with factory() as session:
                row = (await session.execute(text('''SELECT r.source_key,r.record_key,v.version_id,v.content_sha256
                    FROM records r JOIN record_versions v ON v.version_id=r.current_version_id
                    WHERE r.record_key='TIP054.MIGRATION.SIGNED' '''))).mappings().one()
            ref = SOTReference(source_key=row['source_key'], record_key=row['record_key'],
                               record_version_id=row['version_id'], content_sha256=row['content_sha256'])
            plan = await actions.create_plan(admin, PlanRequest(
                idempotency_key='tip054-executor-migration-v2', objective='Synthetic populated migration proof',
                source_refs=(ref,), steps=(StepRequest(step_key='read', capability_id='sot.read',
                    capability_version='2', arguments={'record_key': ref.record_key}),)), request_id='migration-v2-plan')
            executor = ExecutionService(UnitOfWork(factory), actions=actions)
            view = await executor.submit(admin, plan.plan_id, plan.plan_digest, request_id='migration-v2-submit')
            first = await executor.advance(view.run_id)
            second = await executor.advance(view.run_id)
            final = await executor.status(admin, view.run_id)
            assert first.state == 'waiting' and second.state == 'succeeded'
            assert len(final.receipts) == 1 and final.receipts[0].kind == 'read_verified'
            assert final.spent_tool_calls == 1
            evidence.write_text(json.dumps({'run_id': str(view.run_id), 'state': final.state,
                'receipt_count': len(final.receipts), 'spent_tool_calls': final.spent_tool_calls,
                'limits': 'Real domain R0 execution, not an engine replay or R1 publication proof'}, indent=2))
            return
        async with factory() as session:
            tables = (await session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).scalars().all()
            snapshot = {}
            for table in tables:
                if table == 'alembic_version' or table in NEW:
                    continue
                assert table.replace('_', '').isalnum()
                snapshot[table] = list((await session.execute(text(f'SELECT md5(to_jsonb(t)::text) FROM "{table}" t'))).scalars())
            if mode == 'snapshot':
                evidence.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
                print('OLD_DOMAIN_SNAPSHOT', len(snapshot), sum(map(len, snapshot.values())))
            elif mode == 'verify':
                previous = json.loads(evidence.read_text())
                changed = [table for table, hashes in previous.items() if Counter(hashes) - Counter(snapshot[table])]
                assert not changed, changed
                print('OLD_DOMAIN_SURVIVORS_PASS', len(previous))
            elif mode == 'grants':
                results = {}
                for table in NEW:
                    rights = (await session.execute(text("SELECT has_table_privilege(current_user,:t,'SELECT'),has_table_privilege(current_user,:t,'INSERT'),has_table_privilege(current_user,:t,'UPDATE'),has_table_privilege(current_user,:t,'DELETE'),has_table_privilege(current_user,:t,'TRUNCATE')"), {'t': table})).one()
                    expected = (True, True, table == 'action_executions', False, False)
                    assert tuple(rights) == expected, (table, rights)
                    results[table] = list(rights)
                role = (await session.execute(text('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user'))).one()
                assert tuple(role) == (False, False, False)
                populated = {table: await session.scalar(text(f'SELECT count(*) FROM {table}')) for table in NEW}
                assert all(populated[table] for table in NEW if table != 'action_source_links')
                evidence.write_text(json.dumps({'runtime': 'rtr_app', 'rights': results, 'role': list(role), 'populated': populated, 'note': 'R0 migration seed does not create DocumentOS action_source_links'}, indent=2))
                statements = [
                    'UPDATE action_executions SET spent_tool_calls=0',
                    'UPDATE action_executions SET tool_call_limit=tool_call_limit+1',
                    "UPDATE action_executions SET deadline_at=deadline_at+interval '1 hour'",
                    'UPDATE action_executions SET epoch=epoch-1',
                    "UPDATE action_executions SET state='queued'",
                    'UPDATE action_step_attempts SET charged_calls=1',
                    'UPDATE action_execution_receipts SET reused_source=true',
                    "UPDATE action_execution_events SET reason_code='tamper_attempt'",
                    'DELETE FROM action_executions',
                ]
                failures = []
                for statement in statements:
                    async with factory() as denied:
                        try:
                            await denied.execute(text(statement))
                        except DBAPIError as exc:
                            failures.append({'statement': statement, 'exception_type': type(exc).__name__})
                        else:
                            raise AssertionError('runtime_mutation_unexpectedly_allowed:' + statement)
                        finally:
                            await denied.rollback()
                result = json.loads(evidence.read_text())
                result['actual_denied_mutations'] = failures
                evidence.write_text(json.dumps(result, indent=2))
            else:
                raise ValueError('unsupported_mode')
    finally:
        await engine.dispose()

asyncio.run(main())
