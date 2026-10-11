"""Read final real SQL/SDK states and all PID/raw-error evidence, no mutation."""
import hashlib
import json
from pathlib import Path
import re
import sys

import psycopg

root = Path(sys.argv[1])
assert str(root).startswith('/evidence/') and re.fullmatch(r'[a-z0-9_]{1,24}', root.name)
modes = ['before_dispatch', 'during_draft', 'after_draft_commit', 'cancel_remaining', 'complete_draft', 'renderer_kill']
cases = []
for index, mode in enumerate(modes, 1):
    case = root / mode
    seed = json.loads((case / 'seed.json').read_text())
    with psycopg.connect(f'postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_n_{root.name}_i{index}') as db:
        domain = db.execute('SELECT state,reason_code,spent_tool_calls,deadline_at,dispatch_pending FROM action_executions WHERE run_id=%s', (seed['run_id'],)).fetchone()
        receipts = db.execute('SELECT kind,count(*) FROM action_execution_receipts WHERE run_id=%s GROUP BY kind ORDER BY kind', (seed['run_id'],)).fetchall()
        links = db.execute('SELECT count(*) FROM action_source_links WHERE run_id=%s', (seed['run_id'],)).fetchone()[0]
    with psycopg.connect(f'postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_ne_{root.name}_i{index}') as db:
        native = db.execute('SELECT workflow_uuid,status,application_version FROM dbos.workflow_status WHERE workflow_uuid=%s', (seed['workflow_id'],)).fetchall()
    assert len(native) == links == 1 and not domain[4]
    if mode in {'cancel_remaining', 'complete_draft', 'renderer_kill'}:
        assert native[0][1] == 'SUCCESS'
    else:
        assert native[0][1] == 'PENDING'  # canonical renderer deliberately not run.
    before = json.loads((case / 'source-before.json').read_text())
    after = json.loads((case / 'source-after.json').read_text())
    assert before == after
    raw_errors = {p.name: p.read_text() for p in case.glob('*.stderr.txt')
                  if re.search(r'\[\s*ERROR\]|Traceback|different loop|Future attached', p.read_text())}
    assert not raw_errors, raw_errors
    cases.append({'mode': mode, 'status': 'PASS', 'business': dict(zip(
        ['state', 'reason_code', 'spent', 'deadline', 'dispatch_pending'], domain)),
        'receipts': dict(receipts), 'native_workflow': native[0], 'canonical_links': links,
        'source_and_helper_unchanged': True, 'sdk_error_or_cross_loop_exception': False,
        'process_records': json.loads((case / 'process-records.json').read_text()),
        'renderer_process_records': json.loads((case / 'renderer-process-records.json').read_text()) if (case / 'renderer-process-records.json').exists() else []})
result = {'status': 'PASS', 'cases': cases, 'observer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'limits': 'Read-only final observation. Pending profiles retain source jobs whose renderer is intentionally not run and workers are finitely stopped; no always-on deployment/queue availability claim. SUCCESS returns source-verified success or truthful business partial, never SDK cancellation.'}
(root / 'native-campaign-summary.json').write_text(json.dumps(result, default=str, indent=2))
print(json.dumps(result, default=str, indent=2))
