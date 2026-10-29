"""Neutral local launcher and private setup; no model smoke or key discovery."""
import argparse
import getpass
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import warnings

from .config import Settings
from .provider_config import ENDPOINT, readiness, write_profile


def local_port(value):
    try:
        if isinstance(value, bool):
            raise ValueError
        port = int(value)
        if str(port) != str(value) or not 1024 <= port <= 65535:
            raise ValueError
        return port
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("Use a loopback port between1024 and65535") from None


def doctor(settings):
    provider, reason = readiness(settings)
    if settings.test_mode:
        reason = None
    versions = {}
    for name in ("pydantic-ai-slim", "dbos", "openai", "mcp"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return dict(mode="simulation" if settings.test_mode else "configured-model",
        configuration_ready=reason is None, reason=reason, provider=provider,
        dependencies=versions, disk_free_bytes=shutil.disk_usage(Path.cwd()).free,
        network_tested=False, real_ai_accepted=False,
        restart_policy="Stop or cancel active runs, reconcile unknown effects, then restart; profiles never hot-rebind.")


def child_environments(args):
    # Server-only provider configuration. No inherited OPENAI_*/legacy keys and
    # never copy server WORKSPACE_* variables to the browser/Next process.
    common = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT") if key in os.environ}
    common.update(PYTHONNOUSERSITE="1", PYDANTIC_AI_NO_BANNER="1")
    api_port = local_port(getattr(args, "api_port", 8110))
    web_port = local_port(getattr(args, "web_port", 3110))
    if api_port == web_port:
        raise ValueError("API and UI require distinct loopback ports")
    origins = [f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (web_port, api_port)]
    server = common | {"WORKSPACE_DATA_DIR": str(Path(args.data_dir).absolute()), "WORKSPACE_ORIGINS": json.dumps(origins)}
    # The current neutral package source, including an explicitly extracted kit.
    # Never inherit an arbitrary caller PYTHONPATH or legacy environment.
    server["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    if args.config:
        server["WORKSPACE_CONFIG"] = str(Path(args.config).absolute())
    if args.simulation:
        server["WORKSPACE_TEST_MODE"] = "1"
    web = common | {"NEXT_TELEMETRY_DISABLED": "1", "WORKSPACE_UI_ENABLED": "1", "WORKSPACE_API_INTERNAL_URL": f"http://127.0.0.1:{api_port}"}
    if getattr(args, "production", False):
        web["WORKSPACE_PRODUCTION_BUILD"] = "1"
    return server, web


def launch(args):
    server_env, web_env = child_environments(args)
    web_dir = Path(getattr(args, "web_dir", None) or Path(__file__).resolve().parents[3] / "workspace-web").absolute()
    modules = Path(getattr(args, "node_modules", None) or web_dir / "node_modules").absolute()
    api_port = local_port(getattr(args, "api_port", 8110))
    web_port = local_port(getattr(args, "web_port", 3110))
    production = getattr(args, "production", False)
    if production and not (web_dir / ".next-build" / "BUILD_ID").is_file():
        print("The independent UI has no local production build. Run pnpm workspace:build from v2 first.", file=sys.stderr)
        return 1
    processes = []
    try:
        processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "agent_workspace.api:app", "--host", "127.0.0.1", "--port", str(api_port)], env=server_env, start_new_session=True))
        # Execute Next directly, not through npm's extra parent. Each child owns
        # a new process group so descendants are cleaned up even on startup failure.
        processes.append(subprocess.Popen(["node", str(modules / "next/dist/bin/next"), "start" if production else "dev", "--hostname", "127.0.0.1", "--port", str(web_port)], cwd=web_dir, env=web_env, start_new_session=True))
        print(f"Agent Workspace: http://127.0.0.1:{web_port}/workspace (local only)", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(.2)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="workspace")
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("configure", help="Write an explicit 0600 private profile; no network test")
    configure.add_argument("--config", type=Path, required=True)
    configure.add_argument("--model", default="gpt-6.1-sol")
    configure.add_argument("--allow-external-processing", action="store_true")
    configure.add_argument("--fixture-tools", action="store_true", help="Allow local synthetic research/MCP ports, not live connectors")
    commands.add_parser("doctor", help="Sanitized offline readiness, no connectivity/model call")
    commands.add_parser("version", help="Local source/workflow/data identifiers; no network")
    check = commands.add_parser("preflight", help="Offline local runtime prerequisites and safe data check")
    check.add_argument("--data-dir", type=Path, default=Path(".workspace-data"))
    check.add_argument("--web-dir", type=Path)
    check.add_argument("--node-modules", type=Path)
    check.add_argument("--api-port", type=local_port, default=8110)
    check.add_argument("--web-port", type=local_port, default=3110)
    backup = commands.add_parser("backup", help="Private stopped-runtime backup; not shareable diagnostics")
    backup.add_argument("--data-dir", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("restore", help="Verify private backup and restore into a NEW directory only")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    upgrade = commands.add_parser("upgrade-data", help="Explicit offline compatibility marker for drained recognized AW06 data")
    upgrade.add_argument("--data-dir", type=Path, required=True)
    kit = commands.add_parser("source-kit", help="Create an allowlisted neutral source pilot kit, no dependencies or private data")
    kit.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify-kit", help="Verify a source kit integrity manifest; not a signature")
    verify.add_argument("--archive", type=Path, required=True)
    start = commands.add_parser("launch", help="Start loopback API and UI, no legacy services")
    start.add_argument("--config", type=Path)
    start.add_argument("--data-dir", default=".workspace-data")
    start.add_argument("--simulation", action="store_true")
    start.add_argument("--api-port", type=local_port, default=8110)
    start.add_argument("--web-port", type=local_port, default=3110)
    start.add_argument("--production", action="store_true", help="Use the independent UI's existing local .next-build, not deployment")
    start.add_argument("--web-dir", type=Path, help="Explicit trusted neutral frontend directory, e.g. an extracted source kit")
    start.add_argument("--node-modules", type=Path, help="Explicit trusted installed pinned frontend dependencies, not shipped by the source kit")
    args = parser.parse_args(argv)
    if args.command == "configure":
        if not args.allow_external_processing:
            parser.error("configure requires --allow-external-processing; do not enter a key without consent")
        try:
            # getpass otherwise falls back to ECHOED stdin when /dev/tty is
            # unavailable. Fail closed instead of collecting a visible secret.
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                key = getpass.getpass("Workspace API key (hidden; OpenAI HTTPS Responses only): ")
            write_profile(args.config, dict(version=1, model="openai-responses:" + args.model,
                api_key=key, base_url=ENDPOINT, external_processing=True,
                fixture_tools_enabled=args.fixture_tools))
        except (ValueError, OSError, getpass.GetPassWarning, EOFError):
            print("Private configuration could not be saved safely. No network call made.", file=sys.stderr)
            return 1
        print("Private profile saved (0600). Restart/drain required; no AI call or acceptance test was run.")
        return 0
    if args.command == "doctor":
        print(json.dumps(doctor(Settings.from_env()), sort_keys=True))
        return 0
    if args.command in {"version", "preflight", "backup", "restore", "upgrade-data", "source-kit", "verify-kit"}:
        from .operations import APP_VERSION, DATA_CONTRACT, HINTS, backup_data, preflight, restore_data, upgrade_data
        from .store import WorkspaceError
        try:
            if args.command == "version":
                value = dict(application_version=APP_VERSION, workflow_version="workspace-aw06-v1", data_contract=DATA_CONTRACT, real_ai_accepted=False)
            elif args.command == "preflight":
                value = preflight(args.data_dir, args.web_dir or Path(__file__).resolve().parents[3] / "workspace-web", api_port=args.api_port, web_port=args.web_port, node_modules=args.node_modules)
            elif args.command == "backup":
                value = backup_data(args.data_dir, args.output)
            elif args.command == "restore":
                value = restore_data(args.archive, args.destination)
            elif args.command == "upgrade-data":
                value = upgrade_data(args.data_dir)
            else:
                from .source_kit import build_kit, verify_kit
                value = build_kit(args.output) if args.command == "source-kit" else verify_kit(args.archive)
            print(json.dumps(value, sort_keys=True))
            return 1 if value.get("status") == "not_ready" else 0
        except (WorkspaceError, OSError, ValueError) as exc:
            code = exc.code if isinstance(exc, WorkspaceError) else "filesystem_operation_failed"
            print(json.dumps(dict(status="not_ready", code=code, hint=HINTS.get(code, HINTS["filesystem_operation_failed"]), network_tested=False)), file=sys.stderr)
            return 1
    if args.api_port == args.web_port:
        parser.error("API and UI require distinct loopback ports")
    from .operations import HINTS, preflight
    from .store import WorkspaceError
    try:
        report = preflight(args.data_dir, args.web_dir or Path(__file__).resolve().parents[3] / "workspace-web",
                           api_port=args.api_port, web_port=args.web_port, production=args.production, node_modules=args.node_modules)
        if report["status"] != "ready":
            print(json.dumps(report, sort_keys=True), file=sys.stderr)
            return 1
    except (WorkspaceError, OSError, ValueError):
        print(json.dumps(dict(status="not_ready", code="filesystem_operation_failed", hint=HINTS["filesystem_operation_failed"])), file=sys.stderr)
        return 1
    return launch(args)


if __name__ == "__main__":
    raise SystemExit(main())
