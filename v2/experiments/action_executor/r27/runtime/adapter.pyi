"""Precise interface of the genuinely imported, source-bound reference codec."""

from pathlib import Path
from struct import Struct
from typing import BinaryIO, TypedDict

Record = tuple[str, int, int, bytes]
Rules = dict[tuple[int, int], tuple[int, int]]

class RecoveryResult(TypedDict):
    prototype_complete: bool
    records: list[Record]
    stored_bytes: int
    actual_capture_admission: str
    power_loss_proved: bool

CAP: int
HEADER: Struct
CLOSE: Struct
FINAL: Struct
OWNER: Struct
SEAL: Struct
TERMINAL: int
CONTROLS: int
IDS: tuple[str, ...]

class PacketError(ValueError): ...

def need(ok: bool, message: str) -> None: ...
def safe(path: Path) -> Path: ...
def limits(contract: object) -> Rules: ...
def parse(data: bytes, rules: Rules) -> list[Record]: ...
def recover(
    path: Path, contract: object, contract_bytes: bytes, epoch: bytes
) -> RecoveryResult: ...

class Writer:
    path: Path
    rules: Rules
    closed: bool
    finished: bool
    flags: int
    normal: int
    counts: list[int]
    sizes: list[int]
    packet: BinaryIO
    def __init__(
        self,
        path: Path,
        contract: object,
        contract_bytes: bytes,
        epoch: bytes,
        faults: dict[str, str] | None = ...,
    ) -> None: ...
    def emit(
        self, family: str, variant: str, payload: bytes, sequence: int | None = ...
    ) -> int: ...
    def close_family(self, family: str) -> None: ...
    def finish(self) -> None: ...
    def abandon(self) -> None: ...
