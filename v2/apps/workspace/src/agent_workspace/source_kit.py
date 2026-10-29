"""Allowlisted source pilot kit. Integrity checking is not code authentication."""
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile
import zlib

from .operations import APP_VERSION, MIN_DISK, encoded, failure, publish_new, regular, safe_path, strict_json

LIMIT = 8 * 1024 * 1024
REQUIRED = {"v2/apps/workspace/pyproject.toml", "v2/apps/workspace/uv.lock", "v2/apps/workspace/README.md", "v2/apps/workspace/LOCAL_PILOT.md",
    "v2/apps/workspace/src/agent_workspace/cli.py", "v2/apps/workspace/src/agent_workspace/runtime.py", "v2/apps/workspace/src/agent_workspace/api.py",
    "v2/apps/workspace/src/agent_workspace/simulation_model.py", "v2/apps/workspace/src/agent_workspace/operations.py",
    "v2/apps/workspace/src/agent_workspace/assets/research_fixtures.json", "v2/apps/workspace-web/package.json", "v2/apps/workspace-web/tsconfig.json",
    "v2/apps/workspace-web/next.config.ts", "v2/pnpm-lock.yaml", "v2/pnpm-workspace.yaml", "v2/package.json"}
REQUIRED |= {"v2/apps/workspace/src/agent_workspace/assets/" + name for name in ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "LICENSE-NOTO.txt")}


def admitted(name):
    if any(p.startswith(".") or p in {"node_modules", "__pycache__", "data"} for p in PurePosixPath(name).parts):
        return False
    return (name in REQUIRED or name == "v2/patches/brace-expansion@5.0.8.patch"
        or name == "v2/apps/workspace-web/next-env.d.ts"
        or bool(re.fullmatch(r"v2/apps/workspace/src/agent_workspace/[a-z_]+\.py", name))
        or name == "v2/apps/web/src/app/api/workspace/[[...path]]/route.ts"
        or bool(re.fullmatch(r"v2/apps/(workspace-web/src|web/src/workspace)/[A-Za-z0-9_/\[\].-]+\.(ts|tsx|css)", name)) and ".test." not in name)


def build_kit(output):
    repo = Path(__file__).resolve().parents[5]
    payload = {}

    def add(path):
        safe_path(path.parent)
        if not path.resolve().is_relative_to(repo):
            failure("unsafe_data_path")
        regular(path)
        name = path.relative_to(repo).as_posix()
        if not admitted(name) or path.stat().st_size > LIMIT or len(payload) >= 149:
            failure("backup_invalid")
        payload[name] = path.read_bytes()

    for name in ("pyproject.toml", "uv.lock", "LOCAL_PILOT.md"):
        add(repo / "v2/apps/workspace" / name)
    # A portable operator bundle must not expose checkout-specific development
    # paths or point readers to historical documents outside the neutral kit.
    payload["v2/apps/workspace/README.md"] = payload["v2/apps/workspace/LOCAL_PILOT.md"]
    for path in (repo / "v2/apps/workspace/src/agent_workspace").glob("*.py"):
        if path.is_file():
            add(path)
    add(repo / "v2/apps/workspace/src/agent_workspace/assets/research_fixtures.json")
    for name in ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "LICENSE-NOTO.txt"):
        add(repo / "v2/apps/workspace/src/agent_workspace/assets" / name)
    web = repo / "v2/apps/workspace-web"
    for name in ("package.json", "tsconfig.json", "next-env.d.ts", "next.config.ts"):
        add(web / name)
    for path in (web / "src").rglob("*"):
        if path.is_file() and path.suffix in {".ts", ".tsx", ".css"} and ".test." not in path.name:
            add(path)
    for path in (repo / "v2/apps/web/src/workspace").rglob("*"):
        if path.is_file() and path.suffix in {".ts", ".tsx", ".css"} and ".test." not in path.name:
            add(path)
    add(repo / "v2/apps/web/src/app/api/workspace/[[...path]]/route.ts")
    add(repo / "v2/patches/brace-expansion@5.0.8.patch")
    # Only the neutral importer is included. Unused upstream package resolution
    # metadata remains for lock consistency, not a claim of installed runtime SBOM.
    lock = (repo / "v2/pnpm-lock.yaml").read_text()
    lock, count = re.subn(r"\n  apps/web:\n.*?(?=\npackages:)", "\n", lock, flags=re.S)
    if count != 1 or "\n  apps/web:" in lock:
        failure("backup_invalid")
    payload["v2/pnpm-lock.yaml"] = lock.encode()
    payload["v2/package.json"] = encoded({"name": "agent-workspace-pilot", "private": True, "packageManager": "pnpm@11.15.1"})
    payload["v2/pnpm-workspace.yaml"] = ((repo / "v2/pnpm-workspace.yaml").read_text().replace("  - apps/web\n", "")).encode()
    if sum(map(len, payload.values())) > LIMIT:
        failure("backup_limit")
    manifest = {"format": "agent-workspace-source-kit-v1", "version": 1, "application_version": APP_VERSION,
        "scope": "source-only, same-host trusted runtime reuse; not self-contained or fresh-machine certified",
        "entries": [{"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in sorted(payload.items())]}
    output = Path(output).absolute()
    safe_path(output.parent)
    if output.exists() or output.is_symlink():
        failure("destination_exists")
    if shutil.disk_usage(output.parent).free < MIN_DISK:
        failure("low_disk")
    with tempfile.TemporaryDirectory(prefix=".workspace-kit-", dir=output.parent) as scratch:
        staged = Path(scratch) / "kit.zip"
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, raw in sorted(payload.items()):
                archive.writestr(name, raw)
            archive.writestr("source-kit-manifest.json", encoded(manifest))
        staged.chmod(0o600)
        publish_new(staged, output)
    return verify_kit(output)


def verify_kit(archive):
    archive = Path(archive).absolute()
    regular(archive)
    if archive.stat().st_size > LIMIT:
        failure("backup_limit")
    try:
        with zipfile.ZipFile(archive) as zipped:
            infos = zipped.infolist()
            names = [i.filename for i in infos]
            if (len(names) > 150 or len(names) != len(set(names)) or sum(i.file_size for i in infos) > LIMIT
                or any(i.flag_bits & 1 or i.is_dir() or stat.S_ISLNK(i.external_attr >> 16) for i in infos)
                or not REQUIRED.issubset(names)
                or any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts or "\\" in n or n != "source-kit-manifest.json" and not admitted(n) for n in names)):
                failure("backup_invalid")
            manifest = strict_json(zipped.read("source-kit-manifest.json"))
            if (not isinstance(manifest, dict) or set(manifest) != {"format", "version", "application_version", "scope", "entries"} or manifest.get("format") != "agent-workspace-source-kit-v1"
                or type(manifest.get("version")) is not int or manifest["version"] != 1
                or manifest.get("application_version") != APP_VERSION or not isinstance(manifest.get("entries"), list)):
                failure("backup_invalid")
            entries = manifest["entries"]
            if any(not isinstance(e, dict) or set(e) != {"path", "bytes", "sha256"} for e in entries):
                failure("backup_invalid")
            if len({e["path"] for e in entries}) != len(entries) or {e["path"] for e in entries} != set(names) - {"source-kit-manifest.json"}:
                failure("backup_invalid")
            for entry in entries:
                raw = zipped.read(entry["path"])
                if type(entry["bytes"]) is not int or len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                    failure("backup_invalid")
    except (zipfile.BadZipFile, zlib.error, RuntimeError, EOFError, KeyError, TypeError, ValueError, RecursionError):
        failure("backup_invalid")
    return {"status": "verified", "format": "agent-workspace-source-kit-v1", "members": len(entries), "integrity_only": True, "self_contained": False, "network_tested": False, "real_ai_accepted": False}
