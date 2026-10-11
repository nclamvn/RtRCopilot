"""Source/boundary candidate freeze and read-only default-DENY broker preflight."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import FunctionType
from typing import cast

from broker import BOUNDARY_SHA, SCOPE_SHA
from integration import BASE, BASE_SHA, HERE, ROOT, mapping, pins
from routing import ledger

EPOCH = "r27_broker_http_e1"
MARKER = (
    ROOT
    / "v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1/r19/r27-broker-launch.json"
)
HEAD = "0e88f48588dc3228f1ae9eca7a7597d96589af8b"
HEAD_WARNING = (
    b"git: warning: confstr() failed with code 5: couldn't get path of "
    b"DARWIN_USER_TEMP_DIR; using /tmp instead\n"
)
LAUNCHER_SHA = "d7d1ff030bafa22b58227e4648c63cae0a7dbd242af508432fea44a185781773"


def bounded_read(path: Path, ceiling: int = 262144) -> bytes:
    if not path.is_file() or any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("regular nonsymlink source/control")
    if path.stat().st_size > ceiling:
        raise ValueError("source/control finite ceiling")
    with path.open("rb") as stream:
        raw = stream.read(ceiling + 1)
    if len(raw) > ceiling:
        raise ValueError("source/control grew past finite ceiling")
    return raw


def live_head() -> str:
    result = subprocess.run(
        ("/usr/bin/git", "rev-parse", "HEAD"),
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "GIT_OPTIONAL_LOCKS": "0"},
        capture_output=True,
        timeout=2,
        check=True,
    )
    if result.stderr not in (b"", HEAD_WARNING) or result.stdout.strip() != HEAD.encode():
        raise ValueError("fixed read-only HEAD baseline/diagnostic mismatch")
    return HEAD


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def prepared_commands() -> dict[str, object]:
    """Reuse sealed pure planning function; explicit namespace substitutions, NO dispatch."""
    path = ROOT / "v2/experiments/action_executor/r27/runtime/launcher.py"
    if digest(bounded_read(path)) != LAUNCHER_SHA:
        raise ValueError("sealed planning source pin before import")
    spec = importlib.util.spec_from_file_location("r27_broker_sealed_launcher", path)
    if spec is None or spec.loader is None:
        raise ValueError("sealed planning function loader")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    function: object = module.prepared_manifest
    if (
        not isinstance(function, FunctionType)
        or Path(function.__code__.co_filename).resolve() != path
    ):
        raise ValueError("source planning function identity")
    plan = cast(Callable[[], dict[str, object]], function)()
    substitutions = {
        "r27_runtime_http_e1": EPOCH,
        "r27-runtime-campaign-launch.json": "r27-broker-launch.json",
        "rtr_tip054_r27_local_e1": "rtr_tip054_r27_broker_local_e1",
        "rtr_tip054_r27_engine_e1": "rtr_tip054_r27_broker_engine_e1",
    }
    encoded = canonical(plan).decode()
    for old, new in substitutions.items():
        encoded = encoded.replace(old, new)
    result = mapping(json.loads(encoded))
    result["broker_identity_substitutions"] = substitutions
    result["dispatch_surface"] = "NONE; namespace/commands not runtime qualified"
    result.pop("native_and_outer_blockers", None)
    result["native_admission"] = "cooperative pinned ports; unknown native writers DENY"
    result["platform_audit"] = "approved separate disclosed audit; not broker-owned or zero"
    return result


def candidate() -> dict[str, object]:
    boundary_raw = bounded_read(HERE / "boundary.json")
    if digest(boundary_raw) != BOUNDARY_SHA or digest(bounded_read(HERE / "SCOPE.md")) != SCOPE_SHA:
        raise ValueError("immutable approved boundary/scope")
    boundary = mapping(json.loads(boundary_raw))
    if (
        boundary["decision"] != "APPROVED_LOCAL_IMPLEMENTATION"
        or mapping(boundary["base_contract"])["sha256"] != BASE_SHA
        or mapping(boundary["qualifying"])["cap_bytes"] != 10485760
        or mapping(boundary["platform_audit"])["controlled_by_broker"] is not False
    ):
        raise ValueError("approved boundary drift")
    files = sorted((*HERE.glob("*.py"), *HERE.glob("*.pyi")))
    if not 5 <= len(files) <= 32:
        raise ValueError("bounded complete authored source inventory")
    sources = {path.relative_to(ROOT).as_posix(): digest(bounded_read(path)) for path in files}
    sources.update(pins())
    for path in (
        BASE,
        HERE / "SCOPE.md",
        HERE / "boundary.json",
        ROOT / "v2/experiments/action_executor/r27/runtime/launcher.py",
        ROOT / "v2/experiments/action_executor/r27/runtime/raw_child.py",
    ):
        sources[path.relative_to(ROOT).as_posix()] = digest(bounded_read(path))
    for name, sha in sources.items():
        path = ROOT / name
        if digest(bounded_read(path)) != sha:
            raise ValueError("actual source pin mismatch")
    return {
        "schema": "r27-broker-candidate-v1",
        "HEAD": live_head(),
        "HEAD_witness": (
            "Main baseline plus fixed read-only live HEAD match; dirty source bytes pinned"
        ),
        "HEAD_diagnostic_policy": HEAD_WARNING.decode().rstrip(),
        "sources": sources,
        "boundary_sha256": digest(boundary_raw),
        "plan": prepared_commands(),
        "routing": ledger(),
        "marker": MARKER.relative_to(ROOT).as_posix(),
        "epoch": EPOCH,
        "campaign_authority": False,
        "runtime_prerequisites": "NOT_RUN: live fixture/capacity/DB/SQL/Linux group",
        "effects": "DENY_THIS_BATCH",
    }


def preflight(path: Path, grant: object = None) -> dict[str, object]:
    if not path.is_absolute() or any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("safe source candidate path")
    raw = bounded_read(path, 524288)
    if canonical(json.loads(raw)) != canonical(candidate()):
        raise ValueError("exact frozen source/boundary/commands drift")
    if any(item.is_symlink() for item in (MARKER, *MARKER.parents)):
        raise ValueError("marker parent symlink")
    return {
        "source_match": True,
        "boundary_match": True,
        "candidate_sha256": digest(raw),
        "platform_audit": "APPROVED_SEPARATE_DISCLOSED",
        "grant": "untrusted local data, never authority",
        "grant_supplied": grant is not None,
        "marker": "CONSUMED_OR_UNKNOWN" if MARKER.exists() else "ABSENT",
        "marker_written": False,
        "effect_dispatch_allowed": False,
        "runtime_prerequisites": "NOT_RUN",
        "native_unsupported": "CAPABILITY_DENY",
        "effects": "DENY_THIS_BATCH",
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: preflight.py ABSOLUTE_FROZEN_CANDIDATE")
    print(json.dumps(preflight(Path(sys.argv[1])), sort_keys=True))
    raise SystemExit(2)  # A source match never grants campaign authority.
