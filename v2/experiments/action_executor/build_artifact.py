"""Build a source wheel only, no serving image/rebuild/deploy."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

work = Path('/qa/project')
work.mkdir()
shutil.copyfile('/metadata/pyproject.toml', work / 'pyproject.toml')
shutil.copytree('/source', work / 'src')
evidence = Path(os.environ.get('TIP054_BUILD_OUTPUT', '/evidence'))
assert str(evidence).startswith('/evidence') and '..' not in str(evidence)
evidence.mkdir(exist_ok=True)
inputs = {str(p.relative_to(work)): hashlib.sha256(p.read_bytes()).hexdigest() for p in work.rglob('*') if p.is_file()}
subprocess.run(['uv', 'build', '--project', str(work), '--wheel', '--out-dir', str(evidence / 'source-wheel')], check=True)
paths = list((evidence / 'source-wheel').glob('*.whl'))
assert len(paths) == 1
result = {'status': 'PASS', 'kind': 'backend_source_wheel_not_serving_image', 'artifact': paths[0].name, 'sha256': hashlib.sha256(paths[0].read_bytes()).hexdigest(), 'input_sha256': inputs, 'limits': 'Source build only; not image/OS rebuild, serving launch, production deploy or full regression.'}
(evidence / 'build-proof.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
