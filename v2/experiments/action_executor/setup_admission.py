"""Public DBOS admission setup: preserve every cached serving package pin."""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request
import zipfile
from email.parser import Parser

ROOT = Path('/qa')
EVIDENCE = Path('/evidence')
baseline = {d.metadata['Name']: d.version for d in metadata.distributions()}
constraints = ROOT / 'serving-constraints.txt'
constraints.write_text('\n'.join(f'{name}=={version}' for name, version in sorted(baseline.items())) + '\n')
EVIDENCE.joinpath('baseline-packages.json').write_text(json.dumps(baseline, indent=2))
EVIDENCE.joinpath('serving-constraints.txt').write_text(constraints.read_text())
public = json.loads(urllib.request.urlopen('https://pypi.org/pypi/dbos/3.2.0/json', timeout=30).read())
EVIDENCE.joinpath('dbos-pypi-3.2.0.json').write_text(json.dumps(public, indent=2))
subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-cache-dir', '--dest', str(ROOT / 'wheels'), '-c', str(constraints), 'dbos==3.2.0'], check=True)
subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--find-links', str(ROOT / 'wheels'), '--target', str(ROOT / 'packages'), '-c', str(constraints), 'dbos==3.2.0'], check=True)
packages = []
for wheel in sorted(ROOT.joinpath('wheels').glob('*.whl')):
    with zipfile.ZipFile(wheel) as archive:
        name = next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
        detail = Parser().parsestr(archive.read(name).decode())
        licenses = {n: hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist() if 'license' in n.lower()}
    sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    package_public = json.loads(urllib.request.urlopen(f"https://pypi.org/pypi/{detail['Name']}/{detail['Version']}/json", timeout=30).read())
    published = next(p for p in package_public['urls'] if p['filename'] == wheel.name)
    assert sha == published['digests']['sha256']
    packages.append({'name': detail['Name'], 'version': detail['Version'], 'filename': wheel.name, 'sha256': sha, 'public_url': published['url'], 'published_sha256': published['digests']['sha256'], 'requires_dist': detail.get_all('Requires-Dist', []), 'license': detail.get('License'), 'license_expression': detail.get('License-Expression'), 'license_classifiers': [c for c in detail.get_all('Classifier', []) if c.startswith('License ::')], 'license_sha256': licenses})
provenance = {'python': platform.python_version(), 'platform': platform.platform(), 'packages': packages, 'security': {'status': 'NOT_CERTIFIED'}}
try:
    queries = [{'package': {'name': p['name'], 'ecosystem': 'PyPI'}, 'version': p['version']} for p in packages]
    request = urllib.request.Request('https://api.osv.dev/v1/querybatch', json.dumps({'queries': queries}).encode(), {'Content-Type': 'application/json'})
    response = json.loads(urllib.request.urlopen(request, timeout=30).read())
    provenance['security'] = {'tool': 'OSV querybatch', 'queries': queries, 'response': response, 'limitations': 'Point-in-time public package query only; not image/OS/app transitive or production security certification.'}
except Exception as exc:
    provenance['security'] = {'status': 'unavailable', 'error': repr(exc), 'limitations': 'No refreshed vulnerability certification.'}
EVIDENCE.joinpath('setup-provenance.json').write_text(json.dumps(provenance, indent=2))
