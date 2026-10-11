"""Digest mounted public source only, without payload/log disclosure."""
import hashlib
import json
from pathlib import Path
import sys

root = Path('/workspace/v2/apps/backend')
paths = [p for item in ('src', 'tests', 'migrations') for p in root.joinpath(item).rglob('*.py')]
paths += [root / 'pyproject.toml', root / 'uv.lock', root / 'alembic.ini']
result = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
result.update({'verification/' + p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(Path('/work').glob('*')) if p.suffix in {'.py', '.sh'}})
Path(sys.argv[1]).write_text(json.dumps(result, indent=2, sort_keys=True))
print('SOURCE_FILES', len(result))
