"""Offline local operations. No provider, environment dump or legacy discovery."""
from contextlib import contextmanager
import ctypes
import errno
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib

from .store import WorkspaceError

APP_VERSION = "0.1.0-aw07"
DATA_CONTRACT = "workspace-data-aw06-v1"
FORMAT_FILE = "workspace-format.json"
FORMAT = {"format": "agent-workspace-data-v1", "version": 1, "data_contract": DATA_CONTRACT}
DATABASES = ("catalogue.sqlite", "dbos.sqlite", "fixture-outbox.sqlite")
MAX_BYTES = 256 * 1024 * 1024
MIN_DISK = 10 * 1024 ** 3
TABLES = set("sessions workspaces files runs messages events artifacts versions receipts revisions workspace_tombstones workspace_delete_previews workspace_deletions workspace_metadata_requests workspace_memory_meta workspace_memory workspace_memory_reads workspace_clocks workspace_schedules workspace_state_requests connection_grants approvals effects connection_requests connection_reads project_briefs continuity_requests source_replacements run_contexts context_reads artifact_dependencies workspace_import_previews workspace_import_receipts workspace_import_lineage".split())
REQUIRED = {"sessions": {"token_hash", "owner", "expires"}, "workspaces": {"id", "owner", "name"}, "files": {"id", "workspace_id", "content"}, "runs": {"id", "workspace_id", "state", "workflow_version", "context_options"}, "messages": {"id", "workspace_id", "role", "content"}, "artifacts": {"id", "workspace_id", "version"}, "versions": {"artifact_id", "version", "content"}}
DIRECT = {"pydantic-ai-slim": "2.62.0", "dbos": "3.2.0", "fastapi": "0.162.0", "uvicorn": "0.54.0", "httpx": "0.28.1", "python-docx": "1.2.0", "openpyxl": "3.1.5", "reportlab": "4.4.3", "pypdf": "6.14.2", "defusedxml": "0.7.1", "psutil": "7.0.0", "mcp": "1.26.0", "openai": "3.31.0"}
HINTS = {
    "runtime_locked": "Stop the existing runtime before offline operations. Do not delete its lock file.",
    "unsafe_data_path": "Choose an owned local directory with no symbolic-link components.",
    "data_version_incompatible": "Keep this data unchanged and use a compatible application version or restore a compatible backup into a new directory.",
    "data_schema_unrecognized": "Keep the original data and inspect a private backup; this application does not recognize its schema.",
    "data_corrupt": "Keep the original data unchanged and recover a verified private backup into a new directory.",
    "data_busy": "Drain active runs and reconcile uncertain effects before backup or upgrade.",
    "data_upgrade_required": "Stop the runtime, make a private backup, then run workspace upgrade-data --data-dir PATH explicitly.",
    "backup_invalid": "Use a complete verified private runtime backup, not a workspace content export.",
    "destination_exists": "Choose a new nonexistent destination. Existing files are never overwritten.",
    "backup_limit": "This private backup exceeds the supported 256MiB bound. Preserve the data and use an independently reviewed backup method.",
    "low_disk": "Free disk space until at least10GiB is available, then check again.",
    "port_busy": "Choose different local ports or stop their owning runtime; do not kill an unrelated process.",
    "frontend_build_missing": "Build the independent frontend locally using the pinned dependencies before optimized launch.",
    "node_unavailable": "Provide an installed supported Node.js22 or24 runtime. This command does not download it.",
    "dependency_unavailable": "Use the pinned Python environment. Missing dependencies are not downloaded automatically.",
    "filesystem_operation_failed": "The local operation could not complete safely. Preserve the original data and check permissions and free space.",
}


def failure(code, status=409):
    raise WorkspaceError(code, status)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                failure("backup_invalid")
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: failure("backup_invalid"))
    except (ValueError, UnicodeError, RecursionError):
        failure("backup_invalid")


def safe_path(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink():
            failure("unsafe_data_path")
    if path.exists() and (not path.is_dir() or path.stat().st_uid != os.getuid()):
        failure("unsafe_data_path")
    return path


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        failure("unsafe_data_path")
    return info


class DataLease:
    """OS advisory ownership survives crashes without PID guessing/unlink races."""
    def __init__(self, path, *, create=True):
        self.path, self.create, self.fd = Path(path), create, None

    def __enter__(self):
        self.path = safe_path(self.path)
        if not self.path.exists():
            if not self.create:
                failure("unsafe_data_path")
            self.path.mkdir(parents=True, mode=0o700)
        lock = self.path / ".workspace.lock"
        try:
            self.fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            info = os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                failure("unsafe_data_path")
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.__exit__(None, None, None)
            failure("runtime_locked")
        except OSError:
            self.__exit__(None, None, None)
            failure("unsafe_data_path")
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


@contextmanager
def readonly(path):
    regular(path)
    for suffix in ("-wal", "-shm", "-journal"):
        auxiliary = path.with_name(path.name + suffix)
        if auxiliary.exists() or auxiliary.is_symlink():
            regular(auxiliary)
    db = sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            failure("data_corrupt")
        yield db
    finally:
        db.close()


def inspect_data(path, *, require_quiet=False):
    path = safe_path(path)
    if not path.exists():
        return {"state": "new", "data_contract": DATA_CONTRACT}
    sidecar = path / FORMAT_FILE
    if sidecar.exists() or sidecar.is_symlink():
        regular(sidecar)
        value = strict_json(sidecar.read_bytes()) if sidecar.stat().st_size <= 4096 else {}
        if value != FORMAT or type(value.get("version")) is not int:
            failure("data_version_incompatible")
    catalogue = path / "catalogue.sqlite"
    try:
        if catalogue.exists() or catalogue.is_symlink():
            with readonly(catalogue) as db:
                if db.execute("PRAGMA user_version").fetchone()[0] != 0:
                    failure("data_version_incompatible")
                objects = db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
                tables = {name for name, kind in objects if kind == "table"}
                if not set(REQUIRED).issubset(tables) or tables - TABLES or any(kind in {"trigger", "view"} for _, kind in objects):
                    failure("data_schema_unrecognized")
                for table, columns in REQUIRED.items():
                    if not columns.issubset({row[1] for row in db.execute(f"PRAGMA table_info({table})")}):
                        failure("data_schema_unrecognized")
                if require_quiet:
                    if db.execute("SELECT 1 FROM runs WHERE state NOT IN ('completed','failed','cancelled') OR state IS NULL LIMIT 1").fetchone():
                        failure("data_busy")
                    if "effects" in tables and db.execute("SELECT 1 FROM effects WHERE status<>'completed' OR status IS NULL LIMIT 1").fetchone():
                        failure("data_busy")
        elif (path / "dbos.sqlite").exists():
            failure("data_schema_unrecognized")
        for name in DATABASES[1:]:
            target = path / name
            if target.exists() or target.is_symlink():
                with readonly(target) as db:
                    objects = db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
                    if any(kind in {"trigger", "view"} for _, kind in objects):
                        failure("data_schema_unrecognized")
                    tables = {name for name, kind in objects if kind == "table"}
                    if name == "dbos.sqlite":
                        allowed = {"dbos_migrations", "workflow_status", "notifications", "workflow_events", "streams", "workflow_events_history", "workflow_schedules", "application_versions", "queues", "workflow_input", "workflow_output", "operation_outputs"}
                        if "workflow_status" not in tables or tables - allowed:
                            failure("data_schema_unrecognized")
                        required = {"workflow_uuid", "status", "name", "output", "error", "application_version"}
                        if not required.issubset({row[1] for row in db.execute("PRAGMA table_info(workflow_status)")}):
                            failure("data_schema_unrecognized")
                        if require_quiet and db.execute("SELECT 1 FROM workflow_status WHERE status NOT IN ('SUCCESS','ERROR','CANCELLED','MAX_RECOVERY_ATTEMPTS_EXCEEDED') OR status IS NULL LIMIT 1").fetchone():
                            failure("data_busy")
                        # No physical DBOS scheduler was admitted for this pilot.
                        # Reject forged or future scheduled jobs rather than replay.
                        if "workflow_schedules" in tables and db.execute("SELECT 1 FROM workflow_schedules LIMIT 1").fetchone():
                            failure("data_busy")
                    elif name == "fixture-outbox.sqlite":
                        if tables != {"outbox"} or {row[1] for row in db.execute("PRAGMA table_info(outbox)")} != {"scope", "key", "note"}:
                            failure("data_schema_unrecognized")
        return {"state": "compatible" if catalogue.exists() else "new", "data_contract": DATA_CONTRACT}
    except sqlite3.Error:
        failure("data_corrupt")


def initialize_format(path):
    path = safe_path(path)
    target = path / FORMAT_FILE
    if target.exists():
        inspect_data(path)
        return
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded(FORMAT))
        stream.flush()
        os.fsync(stream.fileno())


def upgrade_data(path):
    with DataLease(path, create=False):
        inspect_data(path, require_quiet=True)
        initialize_format(path)
    return {"status": "compatible", "data_contract": DATA_CONTRACT, "migration": "metadata-only additive marker", "replay_started": False}


def publish_new(source, destination, *, directory=False):
    """No-replace atomic publication on supported macOS/Linux local filesystems."""
    destination = Path(destination)
    if directory:
        if sys.platform == "darwin":
            libc = ctypes.CDLL(None, use_errno=True)
            result = libc.renamex_np(os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
        elif sys.platform.startswith("linux"):
            libc = ctypes.CDLL(None, use_errno=True)
            result = libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
        else:
            failure("filesystem_operation_failed")
        if result:
            code = ctypes.get_errno()
            failure("destination_exists" if code in {errno.EEXIST, errno.ENOTEMPTY} else "filesystem_operation_failed")
    else:
        try:
            os.link(source, destination, follow_symlinks=False)
        except FileExistsError:
            failure("destination_exists")


def backup_data(data_dir, output):
    output = Path(output).absolute()
    safe_path(output.parent)
    if output.exists() or output.is_symlink():
        failure("destination_exists")
    output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if stat.S_IMODE(output.parent.stat().st_mode) & 0o077:
        failure("unsafe_data_path")
    with DataLease(data_dir, create=False):
        data_dir = safe_path(data_dir)
        inspect_data(data_dir, require_quiet=True)
        if not (data_dir / "catalogue.sqlite").exists():
            failure("data_schema_unrecognized")
        if shutil.disk_usage(output.parent).free < MIN_DISK:
            failure("low_disk")
        with tempfile.TemporaryDirectory(prefix=".workspace-backup-", dir=output.parent) as scratch:
            scratch = Path(scratch)
            files = {}
            total = 0
            for name in DATABASES:
                source = data_dir / name
                if source.exists():
                    total += regular(source).st_size
                    if total > MAX_BYTES:
                        failure("backup_limit", 413)
                    with readonly(source) as db:
                        target = sqlite3.connect(scratch / name)
                        try:
                            db.backup(target)
                        finally:
                            target.close()
                    os.chmod(scratch / name, 0o600)
                    files[name] = (scratch / name).read_bytes()
            files[FORMAT_FILE] = encoded(FORMAT)
            total = sum(map(len, files.values()))
            if total > MAX_BYTES:
                failure("backup_limit", 413)
            manifest = dict(format="agent-workspace-private-backup-v1", version=1, data_contract=DATA_CONTRACT,
                application_version=APP_VERSION, created_at=time.time(), entries=[dict(path=name, bytes=len(body), sha256=hashlib.sha256(body).hexdigest()) for name, body in sorted(files.items())],
                privacy="PRIVATE: includes application content, session hashes, grants and DBOS audit; no provider profiles. Not shareable diagnostics.")
            archive = scratch / "backup.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
                for name, body in files.items():
                    zipped.writestr(name, body)
                zipped.writestr("manifest.json", encoded(manifest))
            os.chmod(archive, 0o600)
            publish_new(archive, output)
    return {"status": "backed_up", "format": manifest["format"], "members": len(files), "bytes": output.stat().st_size, "private": True, "replay_started": False}


def restore_data(archive, destination):
    archive, destination = Path(archive).absolute(), Path(destination).absolute()
    regular(archive)
    safe_path(destination.parent)
    if destination.exists() or destination.is_symlink():
        failure("destination_exists")
    if archive.stat().st_size > MAX_BYTES:
        failure("backup_limit", 413)
    try:
        with zipfile.ZipFile(archive) as zipped:
            infos = zipped.infolist()
            names = [item.filename for item in infos]
            allowed = set(DATABASES) | {FORMAT_FILE, "manifest.json"}
            if (len(names) != len(set(names)) or not {"manifest.json", "catalogue.sqlite", FORMAT_FILE}.issubset(names)
                    or set(names) - allowed or len(names) > 5 or sum(item.file_size for item in infos) > MAX_BYTES
                    or any(item.flag_bits & 1 or stat.S_ISLNK(item.external_attr >> 16) or item.is_dir() for item in infos)):
                failure("backup_invalid")
            if zipped.getinfo("manifest.json").file_size > 16384:
                failure("backup_invalid")
            manifest_raw = zipped.read("manifest.json")
            manifest = strict_json(manifest_raw)
            if (not isinstance(manifest, dict) or set(manifest) != {"format", "version", "data_contract", "application_version", "created_at", "entries", "privacy"}
                    or manifest.get("format") != "agent-workspace-private-backup-v1" or type(manifest.get("version")) is not int or manifest.get("version") != 1
                    or manifest.get("data_contract") != DATA_CONTRACT or manifest.get("application_version") != APP_VERSION
                    or not isinstance(manifest.get("entries"), list)):
                failure("data_version_incompatible")
            entries = manifest["entries"]
            if (any(not isinstance(e, dict) or set(e) != {"path", "bytes", "sha256"} for e in entries)
                    or len({e["path"] for e in entries}) != len(entries)
                    or {e["path"] for e in entries} != set(names) - {"manifest.json"}):
                failure("backup_invalid")
            if any(type(e["bytes"]) is not int or e["bytes"] < 0 or not isinstance(e["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", e["sha256"]) for e in entries):
                failure("backup_invalid")
            if shutil.disk_usage(destination.parent).free < MIN_DISK:
                failure("low_disk")
            with tempfile.TemporaryDirectory(prefix=".workspace-restore-", dir=destination.parent) as parent:
                stage = Path(parent) / "data"
                stage.mkdir(mode=0o700)
                for entry in entries:
                    body = zipped.read(entry["path"])
                    if type(entry["bytes"]) is not int or entry["bytes"] != len(body) or not isinstance(entry["sha256"], str) or hashlib.sha256(body).hexdigest() != entry["sha256"]:
                        failure("backup_invalid")
                    target = stage / entry["path"]
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(body)
                        stream.flush()
                        os.fsync(stream.fileno())
                inspect_data(stage, require_quiet=True)
                publish_new(stage, destination, directory=True)
    except (zipfile.BadZipFile, zlib.error, RuntimeError, EOFError, KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        failure("backup_invalid")
    return {"status": "restored", "data_contract": DATA_CONTRACT, "destination_new": True, "replay_started": False,
        "retained": "Session hashes and private audit retained. Browser drafts are not in this backup. Permissions and manual schedules remain stored; no scheduler or execution started."}


def dependency_versions():
    result = {}
    for name in DIRECT:
        try:
            value = importlib.metadata.version(name)
            result[name] = value if re.fullmatch(r"[A-Za-z0-9.+_-]{1,80}", value) else None
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def preflight(data_dir, web_dir, *, api_port=8110, web_port=3110, production=True, node_modules=None):
    checks = []
    def check(name, okay, code, hint):
        checks.append(dict(check=name, passed=bool(okay), code=None if okay else code, hint=None if okay else hint))
    check("python", sys.version_info[:2] == (3, 12), "dependency_unavailable", "Use the pinned Python3.12 environment.")
    versions = dependency_versions()
    check("dependencies", all(versions[k] == v for k, v in DIRECT.items()), "dependency_unavailable", HINTS["dependency_unavailable"])
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=3)
        okay = result.returncode == 0 and re.fullmatch(r"v(?:22|24)\.\d+\.\d+\n?", result.stdout) is not None
    except (OSError, subprocess.TimeoutExpired):
        okay = False
    check("node", okay, "node_unavailable", HINTS["node_unavailable"])
    web_dir = Path(web_dir)
    modules = Path(node_modules) if node_modules else web_dir / "node_modules"
    try:
        web_dependencies = all(json.loads((modules / name / "package.json").read_text())["version"] == version for name, version in {"next": "16.2.11", "react": "19.2.3", "react-dom": "19.2.3"}.items())
    except (OSError, ValueError, KeyError):
        web_dependencies = False
    check("frontend_dependencies", web_dependencies and (modules / "next/dist/bin/next").is_file(), "dependency_unavailable", "Provide existing pinned Next16.2.11/React19.2.3 dependencies; no download is attempted.")
    check("frontend_build", not production or (web_dir / ".next-build/BUILD_ID").is_file(), "frontend_build_missing", HINTS["frontend_build_missing"])
    parent = Path(data_dir).absolute()
    while not parent.exists():
        parent = parent.parent
    check("disk", shutil.disk_usage(parent).free >= MIN_DISK, "low_disk", HINTS["low_disk"])
    for name, port in (("api_port", api_port), ("web_port", web_port)):
        available = type(port) is int and 1024 <= port <= 65535 and api_port != web_port
        if available:
            try:
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", port))
            except OSError:
                available = False
        check(name, available, "port_busy", HINTS["port_busy"])
    try:
        result = inspect_data(data_dir)
        if result["state"] == "compatible" and not (Path(data_dir) / FORMAT_FILE).exists():
            failure("data_upgrade_required")
        if Path(data_dir).exists():
            with DataLease(data_dir, create=False):
                pass
        check("data", True, None, None)
    except WorkspaceError as exc:
        check("data", False, exc.code, HINTS.get(exc.code, HINTS["filesystem_operation_failed"]))
    return dict(format="agent-workspace-preflight-v1", application_version=APP_VERSION, status="ready" if all(c["passed"] for c in checks) else "not_ready", checks=checks, network_tested=False, real_ai_accepted=False)


REASONS = {"model_not_configured", "private_configuration_invalid", "unsupported_provider", "unsupported_provider_endpoint", "workspace_api_key_not_configured", "external_processing_not_approved", "provider_dependencies_not_installed", "invalid_loopback_origins", "simulation_fixture_not_installed", "runtime_unavailable"}


def diagnostics(runtime, owner):
    status = runtime.status()
    reason = status.get("reason")
    reason = None if status.get("available") else reason if reason in REASONS else "runtime_unavailable"
    counts = {}
    with runtime.store.tx() as db:
        counts["workspaces"] = db.execute("SELECT COUNT(*) FROM workspaces WHERE owner=? AND id NOT IN (SELECT workspace_id FROM workspace_tombstones)", (owner,)).fetchone()[0]
        for name in ("files", "artifacts"):
            counts[name] = db.execute(f"SELECT COUNT(*) FROM {name} x JOIN workspaces w ON w.id=x.workspace_id WHERE w.owner=? AND w.id NOT IN (SELECT workspace_id FROM workspace_tombstones)", (owner,)).fetchone()[0]
        counts["runs_active"] = db.execute("SELECT COUNT(*) FROM runs WHERE owner=? AND state NOT IN ('completed','failed','cancelled') AND workspace_id NOT IN (SELECT workspace_id FROM workspace_tombstones)", (owner,)).fetchone()[0]
    versions = dependency_versions()
    return dict(format="agent-workspace-diagnostics-v1", application=dict(version=APP_VERSION, workflow_version="workspace-aw06-v1", build_id=source_identifier()),
        runtime=dict(simulation=bool(status.get("test_mode")), available=bool(status.get("available")), reason_code=reason),
        dependencies={name: versions[name] if versions[name] == DIRECT[name] else None for name in ("pydantic-ai-slim", "dbos", "openai", "mcp")}, counts=counts,
        checks=dict(network_tested=False, real_ai_accepted=False),
        recovery=[] if reason is None else [dict(code=reason, hint="Review local setup and configuration. Readiness is offline; no model has been contacted or accepted.")])


def source_identifier():
    """Backend package fingerprint, not a frontend build or authenticity claim."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return "python-source-" + digest.hexdigest()[:20]
