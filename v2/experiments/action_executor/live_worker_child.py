"""Real SDK worker with only a pre-canonical-call pause/release observation."""
import asyncio
import json
import os
from pathlib import Path

from rtr_copilot.actions import runtime
from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.execution_models import ExecutionLeaseLost

identity = os.environ['TIP054_NATIVE_RUN_ID']
marker = Path(os.environ['TIP054_LIVE_MARKER'])
release = Path(os.environ['TIP054_LIVE_RELEASE'])
guard_marker = Path(os.environ['TIP054_LIVE_GUARD'])
original = ExecutionService._draft
fired = False

async def draft(self, claim, plan, step, attempt, actor):
    global fired
    if str(claim.run_id) == identity and not fired:
        fired = True
        marker.write_text(json.dumps({'pid': os.getpid(), 'epoch': claim.epoch,
            'attempt_id': str(attempt['attempt_id']), 'attempt': attempt['attempt'],
            'seam': 'charged_real_R1_attempt_before_canonical_source_guard'}))
        while not release.exists():
            await asyncio.sleep(.05)
        try:
            result = await original(self, claim, plan, step, attempt, actor)
        except ExecutionLeaseLost as exc:
            guard_marker.write_text(json.dumps({'pid': os.getpid(), 'exception_type': type(exc).__name__,
                'old_epoch': claim.epoch, 'attempt_id': str(attempt['attempt_id']),
                'newer_receipt_returned': False, 'actual_source_guard_rejected': True}))
            raise
        else:
            guard_marker.write_text(json.dumps({'pid': os.getpid(), 'actual_source_guard_rejected': False,
                'returned_type': type(result).__name__}))
            return result
    return await original(self, claim, plan, step, attempt, actor)

ExecutionService._draft = draft
asyncio.run(runtime.worker())
