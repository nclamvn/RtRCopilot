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
    server = common | {"WORKSPACE_DATA_DIR": str(Path(args.data_dir).resolve())}
    if args.config:
        server["WORKSPACE_CONFIG"] = str(Path(args.config).absolute())
    if args.simulation:
        server["WORKSPACE_TEST_MODE"] = "1"
    web = common | {"NEXT_TELEMETRY_DISABLED": "1", "WORKSPACE_UI_ENABLED": "1", "WORKSPACE_API_INTERNAL_URL": "http://127.0.0.1:8110"}
    return server, web


def launch(args):
    server_env, web_env = child_environments(args)
    web_dir = Path(__file__).resolve().parents[3] / "web"
    processes = []
    try:
        processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "agent_workspace.api:app", "--host", "127.0.0.1", "--port", "8110"], env=server_env, start_new_session=True))
        # Execute Next directly, not through npm's extra parent. Each child owns
        # a new process group so descendants are cleaned up even on startup failure.
        processes.append(subprocess.Popen(["node", str(web_dir / "node_modules/next/dist/bin/next"), "dev", "--hostname", "127.0.0.1", "--port", "3110"], cwd=web_dir, env=web_env, start_new_session=True))
        print("Agent Workspace: http://127.0.0.1:3110/workspace (local only)", flush=True)
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
    start = commands.add_parser("launch", help="Start loopback API and UI, no legacy services")
    start.add_argument("--config", type=Path)
    start.add_argument("--data-dir", default=".workspace-data")
    start.add_argument("--simulation", action="store_true")
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
    return launch(args)


if __name__ == "__main__":
    raise SystemExit(main())
