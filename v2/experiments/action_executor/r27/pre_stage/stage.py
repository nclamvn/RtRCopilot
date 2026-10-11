"""Adopted closed LOCAL PRE policy; never original PRE launch authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import NoReturn, TypedDict

import adapter
import bridge

HERE = Path(__file__).absolute().parent
ROOT = bridge.ROOT
REFERENCE = HERE.parent / "real_path"
EPOCH = b"R27PRECONTROL001"
METADATA = 65536
PREFIX = "tmp/control/"
BOUNDS = {
    "r21_http_e1/binding.json": (2, 18),
    "r21_http_e1/contract.json": (2, 2108),
    "r21-campaign-launch.json": (4, 287),
    "r21_http_e1/run/samples.json": (2, 235440),
    "r21_http_e1/run/samples.jsonl": (3, 233840),
    "r21_http_e1/run/latency-summary.json": (6, 3473),
    "r21_http_e1/run/r-controls.json": (6, 263),
    "r21_http_e1/load.owner.json": (4, 60),
    "r21_http_e1/load.process.json": (6, 164),
}
DIRECTORIES = ("tmp", "tmp/control", "tmp/control/r21_http_e1", "tmp/control/r21_http_e1/run")
PINS = {
    "writer.py": "e2b7738807dced6bd7ed20d9f1662de648e09a1317db45ed193bb2db4c6ddeba",
    "adapter.py": "0f2a92fe0574fafc70acedc966b113928676cd78cc4ff7e6a83cb349074f63a2",
    "host.py": "cb390fff74ecfe3cbdb481443cfd76bfc8e90fe11286815ebb0eb3631a31eda8",
}
SCOPE_SHA = "781eb387a7210a1615b476a2284559a3c7d5bf189f95d10e960122c078169a7a"


class Variant(TypedDict):
    name: str
    code: int
    max_records: int
    max_payload_bytes: int


class Family(TypedDict):
    id: str
    code: int
    variants: list[Variant]


class Contract(TypedDict):
    schema: str
    stage: str
    authority: str
    cap_bytes: int
    metadata_bytes: int
    epoch: str
    families: list[Family]
    per_path: dict[str, list[int]]


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def wanted() -> Contract:
    families: list[Family] = []
    for code, name in enumerate(adapter.IDS, 1):
        variants: list[Variant] = [
            {
                "name": "synthetic_input" if name == "ephemeral" else "data",
                "code": 1,
                "max_records": 35 if name == "ephemeral" else 1,
                "max_payload_bytes": 235440
                if name == "ephemeral"
                else 80
                if name == "source_cap_child"
                else 0,
            }
        ]
        if name == "future_observer":
            variants.append(
                {"name": "framing", "code": 2, "max_records": 1, "max_payload_bytes": 0}
            )
        families.append({"id": name, "code": code, "variants": variants})
    return {
        "schema": "r27-local-pre-synthetic-v1",
        "stage": "PRE_LOCAL_CONTROL",
        "authority": "APPROVED_LOCAL_ONLY_ORIGINAL_PRE_DENY",
        "cap_bytes": adapter.CAP,
        "metadata_bytes": METADATA,
        "epoch": EPOCH.decode(),
        "families": families,
        "per_path": {PREFIX + p: list(v) for p, v in BOUNDS.items()},
    }


def contract() -> tuple[Contract, bytes]:
    raw = bridge.bounded(HERE / "contract.json")
    expected = wanted()
    if raw != canonical(expected) + b"\n":
        raise adapter.PacketError("exact canonical adopted LOCAL PRE contract")
    return expected, raw


def guard() -> dict[str, str]:
    bridge.guard()
    result = {}
    for name, expected in PINS.items():
        path = REFERENCE / name
        value = hashlib.sha256(bridge.bounded(path)).hexdigest()
        if value != expected:
            raise adapter.PacketError("frozen source drift: " + name)
        result[path.relative_to(ROOT).as_posix()] = value
    if hashlib.sha256(bridge.bounded(HERE / "SCOPE.md")).hexdigest() != SCOPE_SHA:
        raise adapter.PacketError("approved scope drift")
    contract()
    for path in [*HERE.glob("*.py"), HERE / "SCOPE.md", HERE / "contract.json"]:
        result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(bridge.bounded(path)).hexdigest()
    return result


def dispatch_original_pre(_: object = None) -> NoReturn:
    guard()
    raise PermissionError(
        "Original PRE DENY before root/child/marker: genuine tempfile/probe/rmtree, "
        "pytest basetemp/symlink, shell/native/plugin/failure writers UNQUALIFIED"
    )
