"""Public package setup only. Run before attaching isolated internal network."""
from pathlib import Path
import hashlib
import json
import platform
import subprocess
import tarfile
import urllib.request
from email.parser import Parser

BASE = Path("/bakeoff")
BASE.mkdir(exist_ok=True)
subprocess.run(["python", "-m", "pip", "download", "--no-cache-dir", "--dest", str(BASE / "wheels"),
                "-r", "/work/requirements-lock.txt"], check=True)
subprocess.run(["python", "-m", "pip", "install", "--no-index", "--find-links", str(BASE / "wheels"),
                "--target", str(BASE / "packages"), "-r", "/work/requirements-lock.txt"], check=True)
arch = {"aarch64": "arm64", "x86_64": "amd64"}[platform.machine()]
name = f"temporal_cli_1.9.1_linux_{arch}.tar.gz"
url = "https://github.com/temporalio/cli/releases/download/v1.9.1/"
archive = BASE / name
urllib.request.urlretrieve(url + name, archive)
checksums = urllib.request.urlopen(url + "checksums.txt").read().decode()
sha = hashlib.sha256(archive.read_bytes()).hexdigest()
expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == name)
if sha != expected:
    raise RuntimeError("Temporal CLI published checksum mismatch")
with tarfile.open(archive) as tar:
    tar.extractall(BASE / "bin", filter="data")
provenance = {"python": platform.python_version(), "arch": arch, "cli_version": "1.9.1",
              "cli_url": url + name, "cli_sha256": sha, "published_cli_sha256": expected,
              "packages": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (BASE / "wheels").iterdir()},
              "security_check": "NOT_CERTIFIED: wheel SHA256 integrity is not a vulnerability audit; no refreshed advisory DB checked"}
package_metadata = {}
for dist in (BASE / "packages").glob("*.dist-info"):
    metadata = Parser().parsestr((dist / "METADATA").read_text())
    licenses = {str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in dist.rglob("*") if p.is_file() and "license" in str(p).lower()}
    package_metadata[metadata["Name"]] = {"version": metadata["Version"],
        "license": metadata.get("License"), "license_expression": metadata.get("License-Expression"),
        "license_classifiers": [c for c in metadata.get_all("Classifier", []) if c.startswith("License ::")],
        "license_file_sha256": licenses}
provenance["package_metadata"] = package_metadata
try:
    queries = [{"package": {"name": name, "ecosystem": "PyPI"}, "version": detail["version"]}
               for name, detail in package_metadata.items()]
    request = urllib.request.Request("https://api.osv.dev/v1/querybatch", json.dumps({"queries": queries}).encode(),
                                     {"Content-Type": "application/json"})
    response = json.loads(urllib.request.urlopen(request, timeout=20).read())
    provenance["security_check"] = {"tool": "OSV public querybatch", "queries": queries,
                                    "response": response,
                                    "limitations": "point-in-time public package advisory query only; not image/OS/CLI vulnerability certification"}
except Exception as exc:
    provenance["security_check"] = {"status": "unavailable", "error": repr(exc),
                                    "limitations": "no dependency security certification"}
(BASE / "setup-provenance.json").write_text(json.dumps(provenance, indent=2))
