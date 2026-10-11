"""Pinned function-code composition; one recorded AST emit delta, no old edits."""

from __future__ import annotations

import ast
import json
import threading
from collections.abc import Callable
from pathlib import Path
from types import FunctionType, SimpleNamespace
from typing import NoReturn, Protocol, cast

import adapter
import bridge
import stage
import writer
from host import HostPort, OwnedBroker


class StageRecovery(writer.Recovery):
    stage: str
    contract_sha256: str
    semantic_records: list[tuple[str, str, int, bytes, str | None]]


class CodecFailure(Protocol):
    def _fail(self, reason: str) -> NoReturn: ...


def bind(function: object, namespace: dict[str, object]) -> Callable[..., object]:
    original = cast(FunctionType, function)
    rebound = FunctionType(original.__code__, namespace, original.__name__, original.__defaults__)
    rebound.__kwdefaults__ = original.__kwdefaults__
    return rebound


def limits(value: object) -> dict[tuple[int, int], tuple[int, int]]:
    if value != stage.wanted():
        raise adapter.PacketError("exact PRE stage codec domain")
    normalized = json.loads(stage.canonical(value))
    normalized["families"][17]["variants"][0]["name"] = "data"
    return adapter.limits(normalized)


def semantic(owner: adapter.Writer, family: str, variant: str) -> int:
    contract, _ = stage.contract()
    for item in contract["families"]:
        if item["id"] == family:
            for sub in item["variants"]:
                if sub["name"] == variant:
                    return sub["code"]
    cast(CodecFailure, owner)._fail("PRE semantic variant mismatch")


def derive_method(
    source: Path, cls: str, name: str, namespace: dict[str, object]
) -> Callable[..., object]:
    tree = ast.parse(bridge.bounded(source))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    method = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == name)
    changes = 0
    if cls == "Writer":
        for item in ast.walk(method):
            if isinstance(item, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "subtype" for t in item.targets
            ):
                item.value = ast.copy_location(
                    ast.parse("semantic(self, family, variant)", mode="eval").body, item.value
                )
                changes += 1
    else:
        for item in ast.walk(method):
            if (
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and item.func.attr == "emit"
                and len(item.args) == 3
                and isinstance(item.args[1], ast.Constant)
                and item.args[1].value == "data"
            ):
                item.args[1] = ast.copy_location(ast.Constant("synthetic_input"), item.args[1])
                changes += 1
    if changes != 1:
        raise adapter.PacketError("exact one approved AST delta")
    local = dict(namespace)
    exec(compile(ast.fix_missing_locations(ast.Module([method], [])), str(source), "exec"), local)
    return cast(Callable[..., object], local[name])


stage.guard()
CODEC_GLOBALS: dict[str, object] = dict(vars(adapter))
CODEC_GLOBALS.update(limits=limits, semantic=semantic)


class CodecWriter(adapter.Writer):
    pass


for method_name, implementation in {
    "__init__": bind(adapter.Writer.__init__, CODEC_GLOBALS),
    "emit": derive_method(stage.REFERENCE / "adapter.py", "Writer", "emit", CODEC_GLOBALS),
}.items():
    setattr(CodecWriter, method_name, implementation)
CODEC = SimpleNamespace(
    **{
        **vars(adapter),
        "Writer": CodecWriter,
        "limits": limits,
        "recover": bind(adapter.recover, CODEC_GLOBALS),
    }
)


def witnesses() -> dict[str, str]:
    return {**writer.witnesses(), **stage.guard()}


BROKER_GLOBALS: dict[str, object] = dict(vars(writer))
BROKER_GLOBALS.update(
    adapter=CODEC,
    BASE=stage.HERE / "contract.json",
    METADATA=stage.METADATA,
    EPOCH=stage.EPOCH,
    witnesses=witnesses,
)
INITIALIZE = bind(writer.Broker.__init__, BROKER_GLOBALS)
METADATA_CHECK = bind(writer.Broker._metadata, BROKER_GLOBALS)
WRITE = derive_method(stage.REFERENCE / "writer.py", "Broker", "_write", BROKER_GLOBALS)


class StageOwnedBroker(OwnedBroker):
    def __init__(self, root: Path, faults: dict[str, str] | None = None) -> None:
        stage.guard()  # Before adapter.safe/mkdir, descriptor or owner creation.
        self._events: list[list[object]] = []
        self._calls: dict[str, int] = {}
        INITIALIZE(self, root, faults)
        self.first_fault: BaseException | None = None
        self._fault_lock = threading.Lock()

    def fail(self, reason: str) -> NoReturn:
        error = adapter.PacketError(reason)
        if hasattr(self, "first_fault"):
            self.capture_fault(error)
        else:
            self.invalidate()
        raise error

    def _manifest(
        self,
        entries: dict[str, writer.Entry],
        directories: set[str],
        tombstones: list[list[str | int]],
        *,
        ceiling: bool = False,
    ) -> dict[str, object]:
        result = writer.Broker._manifest(self, entries, directories, tombstones, ceiling=ceiling)
        _, raw = stage.contract()
        result.update(
            stage="PRE_LOCAL_CONTROL",
            contract_sha256=writer.digest(raw),
            directory_events=self._events,
        )
        return result

    def _metadata(
        self,
        entries: dict[str, writer.Entry],
        directories: set[str],
        tombstones: list[list[str | int]] | None = None,
    ) -> None:
        if (
            not set(entries) <= {stage.PREFIX + p for p in stage.BOUNDS}
            or not directories <= {"", *stage.DIRECTORIES}
            or len(self._events) > 6
        ):
            self.fail("closed local paths/directories/events")
        METADATA_CHECK(self, entries, directories, tombstones)

    def _write(
        self, path: writer.ProducerPath, raw: bytes, mode: writer.Mode, *, exclusive: bool = False
    ) -> None:
        self._guard(path._token)
        name = path._name
        bound = stage.BOUNDS.get(name.removeprefix(stage.PREFIX))
        if (
            not name.startswith(stage.PREFIX)
            or bound is None
            or path._family != "ephemeral"
            or type(raw) is not bytes
            or len(raw) > bound[1]
            or mode != "w"
            or exclusive
            or self._calls.get(name, 0) >= bound[0]
        ):
            self.fail("closed whole source call/path/role/count")
        self._calls[name] = self._calls.get(name, 0) + 1
        WRITE(self, path, raw, mode, exclusive=exclusive)

    def record(self, family: str, raw: bytes) -> int:
        if not self._sealing or family != "source_cap_child" or len(raw) != 80:
            self.fail("no packet-only synthetic bypass")
        return writer.Broker.record(self, family, raw)

    def _mkdir(self, path: writer.ProducerPath, parents: bool, exist_ok: bool) -> None:
        self._guard(path._token)
        if path._name != stage.DIRECTORIES[-1] or not parents or not exist_ok:
            self.fail("exact original directory call")
        proposed = self._directories | set(stage.DIRECTORIES)
        self._events.append(
            ["mkdir", path._name, sum(self._writer.counts), sorted(proposed - self._directories)]
        )
        self._metadata(self._entries, proposed)
        writer.Broker._mkdir(self, path, parents, exist_ok)

    def remove_directory(self, name: str) -> None:
        self._guard()
        if name not in stage.DIRECTORIES or name not in self._directories:
            self.fail("closed directory removal")
        if any(p.startswith(name + "/") for p in self._directories):
            self.fail("deepest-first directory cleanup")
        proposed = self._directories - {name}
        self._events.append(["rmdir", name, sum(self._writer.counts), []])
        self._metadata(self._entries, proposed)
        self._trip("native_rmdir")
        self._target(name).rmdir()
        self._directories = proposed

    def finish(self) -> StageRecovery:
        self._guard()
        if (
            self._calls != {stage.PREFIX + p: b[0] for p, b in stage.BOUNDS.items()}
            or self._directories != {""}
            or any(e["exists"] for e in self._entries.values())
            or len(self._tombstones) != 9
            or len(self._events) != 6
        ):
            self.fail("complete closed source body and owned cleanup required")
        return cast(StageRecovery, FINISH(self))


def roles(manifest: dict[str, object], records: list[adapter.Record]) -> dict[int, str]:
    expected, raw = stage.contract()
    if manifest.get("stage") != expected["stage"] or manifest.get(
        "contract_sha256"
    ) != writer.digest(raw):
        raise adapter.PacketError("manifest semantic stage binding")
    entries = writer.mapping(manifest["files"])
    if set(entries) != {stage.PREFIX + p for p in stage.BOUNDS}:
        raise adapter.PacketError("closed recovery paths")
    assigned: set[int] = set()
    owners: dict[int, str] = {}
    for name, value in entries.items():
        item = writer.mapping(value)
        if item["family"] != "ephemeral":
            raise adapter.PacketError("synthetic role")
        segments = item["segments"]
        if not isinstance(segments, list):
            raise adapter.PacketError("segments")
        count, maximum = stage.BOUNDS[name.removeprefix(stage.PREFIX)]
        calls = 0
        for piece in segments:
            if not isinstance(piece, list) or len(piece) != 3 or piece[2] != "w":
                raise adapter.PacketError("whole overwrite range")
            start, stop = writer.integer(piece[0]), writer.integer(piece[1])
            if stop != start + 1:
                raise adapter.PacketError("one source call per range")
            for seq in range(start, stop):
                candidates = [r for r in records if r[:3] == ("ephemeral", 1, seq)]
                if seq in assigned or len(candidates) != 1 or len(candidates[0][3]) > maximum:
                    raise adapter.PacketError("exact raw frame owner/path ceiling")
                assigned.add(seq)
                owners[seq] = name
                calls += 1
        if calls != count or item["exists"] is not False:
            raise adapter.PacketError("per-path lifetime count")
    synthetic = {seq for fam, variant, seq, _ in records if fam == "ephemeral" and variant == 1}
    if (
        assigned != synthetic
        or synthetic != set(range(35))
        or any(f not in {"ephemeral", "source_cap_child"} for f, _, _, _ in records)
    ):
        raise adapter.PacketError("no unowned/undeclared packet records")
    if len([r for r in records if r[0] == "source_cap_child"]) != 1:
        raise adapter.PacketError("one closure only")
    directories = manifest["directories"]
    events = manifest.get("directory_events")
    if (
        not isinstance(directories, list)
        or not set(directories) <= {"", *stage.DIRECTORIES}
        or not isinstance(events, list)
        or len(events) > 6
    ):
        raise adapter.PacketError("finite directory lifecycle")
    expected_events: list[list[object]] = [
        ["mkdir", stage.DIRECTORIES[-1], 0, sorted(stage.DIRECTORIES)],
        ["mkdir", stage.DIRECTORIES[-1], 26, []],
        *(["rmdir", name, 35, []] for name in reversed(stage.DIRECTORIES)),
    ]
    if events != expected_events or directories != [""]:
        raise adapter.PacketError("exact source mkdir and closed cleanup chronology")
    tombstones = manifest["tombstones"]
    if not isinstance(tombstones, list) or len(tombstones) != 9:
        raise adapter.PacketError("complete retained file deletion history")
    if sorted(tombstones) != sorted([[name, 35] for name in entries]):
        raise adapter.PacketError("all file removals before directory cleanup")
    live = {""}
    previous = 0
    for event in events:
        if not isinstance(event, list) or len(event) != 4:
            raise adapter.PacketError("directory event shape")
        action, name, position, added = event
        if (
            type(name) is not str
            or name not in stage.DIRECTORIES
            or type(position) is not int
            or not previous <= position <= len(synthetic)
        ):
            raise adapter.PacketError("directory event domain/order")
        previous = position
        if action == "mkdir":
            wanted = sorted(set(stage.DIRECTORIES) - live)
            if name != stage.DIRECTORIES[-1] or added != wanted:
                raise adapter.PacketError("original mkdir replay")
            live.update(stage.DIRECTORIES)
        elif action == "rmdir":
            if added != [] or name not in live or any(p.startswith(name + "/") for p in live):
                raise adapter.PacketError("directory removal replay")
            live.remove(name)
        else:
            raise adapter.PacketError("unknown directory action")
    if live != set(directories):
        raise adapter.PacketError("directory event final-state conservation")
    return owners


def recover_pre(root: Path) -> StageRecovery:
    stage.guard()
    manifest = writer.mapping(
        json.loads(writer.bounded_read(root / "manifest.json", stage.METADATA))
    )
    result = cast(writer.Recovery, RECOVER(root))
    owners = roles(manifest, result["records"])
    contract, raw = stage.contract()
    semantics = {
        (f["id"], v["code"]): v["name"] for f in contract["families"] for v in f["variants"]
    }
    return cast(
        StageRecovery,
        {
            **result,
            "stage": contract["stage"],
            "contract_sha256": writer.digest(raw),
            "semantic_records": [
                (
                    family,
                    semantics[(family, variant)],
                    seq,
                    payload,
                    owners.get(seq) if family == "ephemeral" else None,
                )
                for family, variant, seq, payload in result["records"]
            ],
        },
    )


BROKER_GLOBALS["recover"] = recover_pre
FINISH = bind(writer.Broker.finish, BROKER_GLOBALS)
RECOVER = bind(writer.recover, BROKER_GLOBALS)


def create_local_pre(root: Path, faults: dict[str, str] | None = None) -> StageOwnedBroker:
    return StageOwnedBroker(root, faults)


def cleanup(port: HostPort) -> None:
    broker = cast(StageOwnedBroker, port._broker)
    for name, entry in sorted(broker._entries.items()):
        if entry["exists"]:
            port.delete(name)
    for name in reversed(stage.DIRECTORIES):

        def remove(n: str = name) -> None:
            broker.remove_directory(n)

        port._call(remove)
