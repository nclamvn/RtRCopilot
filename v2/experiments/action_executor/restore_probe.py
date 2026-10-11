"""Finite cold domain+DBOS restore observer; no live/whole-cluster DR claim."""
import hashlib
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

def fingerprints():
    result = {}
    for label, dsn, schema in [('domain', os.environ['POSTGRES_DSN'], 'public'), ('engine', os.environ['ACTION_WORKFLOW_DSN'], 'dbos')]:
        with psycopg.connect(dsn) as db:
            tables = db.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename', (schema,)).fetchall()
            result[label] = {}
            for (table,) in tables:
                assert table.replace('_', '').isalnum()
                hashes = sorted(x[0] for x in db.execute(f'SELECT md5(to_jsonb(t)::text) FROM "{schema}"."{table}" t'))
                result[label][table] = {'count': len(hashes), 'row_digests': hashes}
    return result

if sys.argv[1] == 'fingerprint':
    target = root / os.environ['TIP054_RESTORE_FINGERPRINT']
    assert target.parent == root
    target.write_text(json.dumps(fingerprints(), indent=2, sort_keys=True))
elif sys.argv[1] in {'resume', 'incompatible'}:
    incompatible = sys.argv[1] == 'incompatible'
    original = Path(os.environ['TIP054_RESTORE_ORIGINAL'])
    seed = json.loads((original / 'seed.json').read_text())
    run = seed['run_id']
    before = snapshot(run)
    label = 'incompatible' if incompatible else 'resume'
    out = (root / (label + '.stdout.txt')).open('w'); err = (root / (label + '.stderr.txt')).open('w')
    env = dict(os.environ, TIP054_NATIVE_PAUSE='none', TIP054_NATIVE_MARKER='/tmp/' + root.name + '-unused-marker', TIP054_NATIVE_RUN_ID=run)
    if incompatible:
        env['RTR_BUILD_SHA'] = 'f' * 64
    command = [sys.executable, '/work/worker_child.py']
    child = subprocess.Popen(command, env=env, stdout=out, stderr=err)
    out.close(); err.close()
    record = {'command': command, 'pid': child.pid}
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            final = snapshot(run)
            compatible_ready = (final['execution']['state'] == 'waiting'
                                and final['execution']['epoch'] > before['execution']['epoch'])
            incompatible_ready = final['execution']['state'] == 'paused'
            if ((incompatible_ready if incompatible else compatible_ready)
                    and final['native_outputs'] > before['native_outputs']):
                break
            if child.poll() is not None:
                raise RuntimeError('restored_worker_exited')
            time.sleep(0.1)
        else:
            raise AssertionError('restored_pending_workflow_not_resumed')
        assert final['canonical_links'] == before['canonical_links'] == 1
        assert final['receipts'] == before['receipts']
        assert final['attempts'] == before['attempts']
        assert final['execution']['spent'] == before['execution']['spent']
        assert final['execution']['deadline'] == before['execution']['deadline']
        assert final['native_workflow'][0] == seed['workflow_id']
        proof_name = 'incompatible-build-proof.json' if incompatible else 'restore-proof.json'
        if incompatible:
            assert final['native_workflow'][1] != 'SUCCESS'
        (root / proof_name).write_text(json.dumps({'status': 'PASS', 'mode': 'incompatible_configured_build' if incompatible else 'compatible_restore', 'workflow_id': seed['workflow_id'], 'before': before, 'after': final,
            'observer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'limits': 'Cold logical engine+domain restore into fresh namespace; immutable synthetic MinIO source objects retained, not whole-cluster/roles/live-safe/production or object-store DR.'}, default=str, indent=2))
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
        try:
            record['exit_code'] = child.wait(timeout=10)
            record['forced_kill'] = False
        except subprocess.TimeoutExpired:
            child.kill(); record['exit_code'] = child.wait(timeout=5); record['forced_kill'] = True
        (root / (label + '-process-record.json')).write_text(json.dumps(record, indent=2))
else:
    raise ValueError('unsupported_mode')
