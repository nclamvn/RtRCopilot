"""Old helper binding unchanged; add explicit R-only helpers/config binding."""

import hashlib
import json
import runpy
import sys
from pathlib import Path

runpy.run_path("/work/source_snapshot.py", run_name="__main__")
path = Path(sys.argv[1])
result = json.loads(path.read_text())
for item in sorted(Path("/work/r").rglob("*")):
    if item.is_file() and (item.suffix in {".py", ".sh"} or item.name == "docker"):
        name = str(item.relative_to("/work/r"))
        result["verification_r/" + name] = hashlib.sha256(item.read_bytes()).hexdigest()
result["v2/.env.example"] = hashlib.sha256(
    Path("/workspace/v2/.env.example").read_bytes()
).hexdigest()
path.write_text(json.dumps(result, indent=2, sort_keys=True))
print("R_SOURCE_FILES", len(result))
