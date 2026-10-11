"""Validated data shapes; no untyped JSON crosses the recovery interface."""

from collections.abc import Mapping
from typing import Literal, Protocol, TypedDict

import adapter

Segment = list[int | str]


class NativeEntry(TypedDict):
    family: str
    segments: list[Segment]


Files = dict[str, NativeEntry]


class RecoveryResult(TypedDict):
    prototype_complete: bool
    records: list[tuple[str, int, int, bytes]]
    stored_bytes: int
    actual_capture_admission: str
    power_loss_proved: bool
    charge: int
    physical_attempt_bytes: int
    all_live_file_bytes: int
    native_files: int
    measurement_admission: str


class OffResult(TypedDict):
    captured: Literal[False]
    measurement_admission: Literal["HOLD"]


class WriteStream(Protocol):
    def write(self, raw: bytes, /) -> int: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(type(k) is not str for k in value):
        raise adapter.PacketError("typed object mapping")
    return {str(k): v for k, v in value.items()}


def integer(value: object) -> int:
    if type(value) is not int:
        raise adapter.PacketError("exact integer")
    return value


def native_files(value: object) -> Files:
    result: Files = {}
    for name, raw in mapping(value).items():
        entry = mapping(raw)
        if set(entry) != {"family", "segments"}:
            raise adapter.PacketError("native entry fields")
        family, segments = entry["family"], entry["segments"]
        if type(family) is not str or family not in adapter.IDS or not isinstance(segments, list):
            raise adapter.PacketError("native entry domain")
        checked: list[Segment] = []
        for segment in segments:
            if not isinstance(segment, list) or len(segment) != 3:
                raise adapter.PacketError("native segment shape")
            start, stop = integer(segment[0]), integer(segment[1])
            mode = segment[2]
            if type(mode) is not str or mode not in ("w", "a") or start < 0 or stop <= start:
                raise adapter.PacketError("native segment domain")
            checked.append([start, stop, mode])
        result[name] = {"family": family, "segments": checked}
    return result
