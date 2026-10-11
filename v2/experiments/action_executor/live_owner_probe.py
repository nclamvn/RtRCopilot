"""Two simultaneously live actual SDK workers, natural lease expiry, real fence."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import psycopg
from native_probe import snapshot

root = Path(sys.argv[2])
assert str(root).startswith('/evidence/')
seed = json.loads((root / 'seed.json').read_text())
identity = seed['run_id']
marker = Path('/tmp/' + root.name + '-live-old.json')
release = Path('/tmp/' + root.name + '-live-release')
guard = Path('/tmp/' + root.name + '-live-guard.json')
assert not any(p.exists() for p in (marker, release, guard))
records = []
children = []

def launch(label, old):
    env = dict(os.environ, TIP054_NATIVE_RUN_ID=identity, TIP054_NATIVE_PAUSE='none',
        TIP054_NATIVE_MARKER='/tmp/' + root.name + '-unused', TIP054_LIVE_MARKER=str(marker),
        TIP054_LIVE_RELEASE=str(release), TIP054_LIVE_GUARD=str(guard))
    command = [sys.executable, '/work/live_worker_child.py' if old else '/work/worker_child.py']
    out = (root / (label + '.stdout.txt')).open('w')
    err = (root / (label + '.stderr.txt')).open('w')
    child = subprocess.Popen(command, env=env, stdout=out, stderr=err)
    out.close(); err.close()
    records.append({'label': label, 'pid': child.pid, 'command': command,
        'executor_identity': 'same configured local-action-worker deliberately', 'old_claim_pause': old})
    children.append(child)
    return child

def source_rows():
    with psycopg.connect(os.environ['POSTGRES_DSN']) as db:
        return {
            'objects': db.execute('SELECT count(*) FROM object_blobs').fetchone()[0],
            'jobs': db.execute('SELECT count(*) FROM render_jobs').fetchone()[0],
            'generated_files': db.execute('SELECT count(*) FROM generated_files').fetchone()[0],
            'links': db.execute('SELECT render_job_id,attempt_id,canonical_input_hash FROM action_source_links WHERE run_id=%s', (identity,)).fetchall(),
            'receipts': db.execute('SELECT attempt_id,kind,source_id FROM action_execution_receipts WHERE run_id=%s ORDER BY occurred_at', (identity,)).fetchall(),
        }

last = None
try:
    objects_before = source_rows()['objects']
    old = launch('old-live-worker', True)
    until = time.monotonic() + 25
    while not marker.exists() and time.monotonic() < until:
        assert old.poll() is None, 'old_actual_worker_exited_before_claim_pause'
        time.sleep(.05)
    assert marker.exists()
    old_claim = json.loads(marker.read_text())
    before = snapshot(identity)
    assert old_claim['pid'] == old.pid and before['execution']['epoch'] == old_claim['epoch']
    assert before['canonical_links'] == 0 and len(before['attempts']) == 2
    assert before['native_workflow'][1] == 'PENDING'
    newer = launch('new-compatible-live-worker', False)
    until = time.monotonic() + 35
    while time.monotonic() < until:
        last = snapshot(identity)
        assert old.poll() is None and newer.poll() is None, 'both_workers_must_stay_alive'
        if (last['canonical_links'] == 1 and last['receipts'].get('job_accepted') == 1
                and last['execution']['epoch'] > old_claim['epoch']
                and last['native_outputs'] > before['native_outputs']):
            break
        time.sleep(.1)
    else:
        raise AssertionError('new_live_worker_did_not_recover_after_natural_lease_expiry')
    accepted = source_rows()
    assert accepted['jobs'] == 1 and len(accepted['links']) == 1
    assert str(accepted['links'][0][1]) != old_claim['attempt_id']
    assert not any(str(r[0]) == old_claim['attempt_id'] for r in accepted['receipts'])
    assert accepted['objects'] == objects_before and accepted['generated_files'] == 0
    release.write_text('release actual old claim; no authority or outcome override')
    until = time.monotonic() + 10
    while not guard.exists() and time.monotonic() < until:
        assert old.poll() is None and newer.poll() is None
        time.sleep(.05)
    assert guard.exists()
    observed_guard = json.loads(guard.read_text())
    assert observed_guard['pid'] == old.pid
    assert observed_guard['actual_source_guard_rejected'] and not observed_guard['newer_receipt_returned']
    assert observed_guard['exception_type'] == 'ExecutionLeaseLost'
    time.sleep(.7)
    final = snapshot(identity)
    final_sources = source_rows()
    assert old.poll() is None and newer.poll() is None
    assert final_sources == accepted
    assert final['canonical_links'] == 1 and final['receipts'] == last['receipts']
    assert final['attempts'] == last['attempts'] and len(final['attempts']) == 3
    assert final['execution']['spent'] == sum(a[2] for a in final['attempts']) == 3
    assert final['execution']['deadline'].isoformat() == seed['deadline_at']
    assert final['native_workflow'][0] == seed['workflow_id'] and final['native_workflow'][1] == 'PENDING'
    (root / 'two-live-owner-proof.json').write_text(json.dumps({'status': 'PASS',
        'old_pid': old.pid, 'new_pid': newer.pid, 'both_alive_at_guard_observation': True,
        'old_claim': old_claim, 'actual_stale_guard': observed_guard,
        'before': before, 'new_owner_before_release': last, 'after_old_rejection': final,
        'source_rows': final_sources,
        'limits': 'Deliberate duplicate local executor identity with two real SDK processes; natural15s lease expiry, real domain/source guard, no effect mock. Not multi-host/HA or arbitrary rolling upgrade certification.'}, default=str, indent=2))
except Exception as exc:
    (root / 'two-live-owner-failure.json').write_text(json.dumps({'exception_type': type(exc).__name__,
        'message': str(exc), 'last_snapshot': last}, default=str, indent=2))
    raise
finally:
    for child in reversed(children):
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
        try:
            code = child.wait(timeout=10); forced = False
        except subprocess.TimeoutExpired:
            child.kill(); code = child.wait(timeout=5); forced = True
        records.append({'label': 'finite-live-worker-drain', 'pid': child.pid,
            'exit_code': code, 'forced_kill_after_10_seconds': forced})
    (root / 'two-live-owner-process-records.json').write_text(json.dumps(records, indent=2))
