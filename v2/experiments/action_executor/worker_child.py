"""Real product worker with narrow supervised pauses at actual commit seams.

Only pauses are injected; authorization, SQL, source services and results remain
the product implementation. Parent verifies persisted rows before process kill.
"""
import asyncio
import json
import os
from pathlib import Path

from rtr_copilot.actions import runtime
from rtr_copilot.actions.execution import ExecutionService

mode = os.environ.get('TIP054_NATIVE_PAUSE', 'none')
marker = Path(os.environ['TIP054_NATIVE_MARKER'])
run_id = os.environ['TIP054_NATIVE_RUN_ID']
fired = False

async def pause(seam: str):
    global fired
    if not fired:
        fired = True
        marker.write_text(json.dumps({'pid': os.getpid(), 'seam': seam, 'run_id': run_id}))
        await asyncio.Event().wait()

if mode == 'before_dispatch':
    original_dispatch = runtime.dispatch_pending
    async def dispatch(service):
        await pause('persisted_intent_before_sdk_dispatch')
        return await original_dispatch(service)
    runtime.dispatch_pending = dispatch
elif mode == 'during_draft':
    original_draft = ExecutionService._draft
    async def draft(self, claim, plan, step, attempt, actor):
        if str(claim.run_id) == run_id:
            await pause('charged_attempt_before_canonical_source_call')
        return await original_draft(self, claim, plan, step, attempt, actor)
    ExecutionService._draft = draft
elif mode == 'after_draft_commit':
    original_advance = ExecutionService.advance
    async def advance(self, identity):
        result = await original_advance(self, identity)
        if str(identity) == run_id:
            from sqlalchemy import text
            async with self.uow.factory() as session:
                committed = await session.scalar(text("SELECT EXISTS(SELECT 1 FROM action_execution_receipts WHERE run_id=:r AND kind='job_accepted')"), {'r': identity})
            if committed:
                await pause('canonical_job_receipt_committed_before_dbos_step_ack')
        return result
    ExecutionService.advance = advance

asyncio.run(runtime.worker())
