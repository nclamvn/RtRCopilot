"""Generate minimal admitted lock from public metadata, no serving source writes."""
from pathlib import Path
import shutil
import subprocess

work = Path('/qa/metadata')
work.mkdir()
for name in ('pyproject.toml', 'uv.lock'):
    shutil.copyfile(Path('/metadata') / name, work / name)
subprocess.run(['uv', 'lock', '--project', str(work), '--python', '/usr/local/bin/python', '--no-managed-python'], check=True)
shutil.copyfile(work / 'uv.lock', '/evidence/admitted-uv.lock')
