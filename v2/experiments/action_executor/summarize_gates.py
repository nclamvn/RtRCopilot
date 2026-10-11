import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

root = Path(sys.argv[1])
result = {}
for pattern, label in [('unit.xml', 'unit'), ('integration-*.xml', 'integration')]:
    suites = [s for p in root.glob(pattern) for s in ET.parse(p).getroot().iter('testsuite')]
    result[label] = {k: sum(int(s.get(k, '0')) for s in suites) for k in ('tests', 'failures', 'errors', 'skipped')}
result['source_unchanged'] = (root / 'source-before.json').read_bytes() == (root / 'source-after.json').read_bytes()
before = json.loads((root / 'source-before.json').read_text())
after = json.loads((root / 'source-after.json').read_text())
result['product_source_unchanged'] = {k: v for k, v in before.items() if not k.startswith('verification/')} == {k: v for k, v in after.items() if not k.startswith('verification/')}
result['returncodes'] = json.loads((root / 'returncodes.json').read_text())
(root / 'summary.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
