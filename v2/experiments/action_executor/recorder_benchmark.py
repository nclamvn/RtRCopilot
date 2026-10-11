"""Offline blocking recorder cost on retained synthetic observations only.

Wall/CPU timings include runner serialization and host-backed evidence I/O.
This does not reconstruct original concurrent scheduling or attribute failures.
"""
import hashlib
import json
import math
from pathlib import Path
import sys
import time

source = Path(sys.argv[1])
root = Path(sys.argv[2])
assert str(source).startswith('/evidence/') and str(root).startswith('/evidence/')
root.mkdir()  # Fresh immutable benchmark namespace.
samples = json.loads(source.read_text())
source_binding = json.loads((source.parent / 'source-before.json').read_text())
assert len(samples) == 1206
old_sha = source_binding['verification/latency_probe.py']
new_sha = hashlib.sha256(Path('/work/latency_probe.py').read_bytes()).hexdigest()
assert old_sha != new_sha
timings = []
rewrite = root / 'rewrite-scratch.json'
append = (root / 'append-scratch.jsonl').open('x')
try:
    for count in (100, 400, 800, 1206):
        for repetition in range(50):
            for mechanism in ('growing_array_rewrite', 'one_observation_append_flush'):
                wall = time.perf_counter_ns(); cpu = time.process_time_ns()
                if mechanism == 'growing_array_rewrite':
                    rewrite.write_text(json.dumps(samples[:count], indent=2))
                else:
                    append.write(json.dumps(samples[count - 1], separators=(',', ':')) + '\n')
                    append.flush()
                timings.append({'mechanism': mechanism, 'array_size': count,
                    'repetition': repetition, 'wall_ms': (time.perf_counter_ns()-wall)/1_000_000,
                    'cpu_ms': (time.process_time_ns()-cpu)/1_000_000})
finally:
    append.close()
def percentile(values, q):
    return sorted(values)[math.ceil(len(values)*q)-1]
cells = []
for count in (100, 400, 800, 1206):
    for mechanism in ('growing_array_rewrite', 'one_observation_append_flush'):
        rows = [r for r in timings if r['array_size'] == count and r['mechanism'] == mechanism]
        cells.append({'array_size': count, 'mechanism': mechanism, 'samples': len(rows),
            'wall_p50_ms': percentile([r['wall_ms'] for r in rows], .5),
            'wall_p95_ms': percentile([r['wall_ms'] for r in rows], .95),
            'cpu_p95_ms': percentile([r['cpu_ms'] for r in rows], .95)})
original_bytes = sum(len(json.dumps(samples[:n], indent=2).encode()) for n in range(1, len(samples)+1))
result = {'status': 'MEASURED_OFFLINE', 'old_helper_sha256': old_sha,
    'new_helper_sha256': new_sha, 'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'observer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'original_full_rewrite_total_bytes': original_bytes,
    'original_final_array_bytes': len(json.dumps(samples, indent=2).encode()),
    'cells': cells, 'limits': 'Offline same capped runner and host evidence filesystem,50 repeats at each retained dataset prefix. Measures blocking recorder implementation cost only; not the original live timeline, causal attribution of timeout/admission misses, or a substitute for same-profile corrected load.'}
(root / 'raw-timings.json').write_text(json.dumps(timings, indent=2))
(root / 'recorder-benchmark.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
