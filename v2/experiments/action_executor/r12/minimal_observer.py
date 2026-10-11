"""R12 exact outer callback exposure; nested helper cost is not separately measured."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

R11 = Path(__file__).resolve().parent.parent / "r11"
PINS = {
    "overhead_observer.py": "e64795c23bb5ef848c4472ff2e444cbf1628cea5bd44b5d633f1cf2fad4c0cdf",
    "analyze.py": "2f6b1b70584f24c25e4d03f500f3351cbb09c3adaa58486a1da31255b5aa5190",
}
SELECTED = (
    "R9.recording@pinned_callback",
    "phase.finish_phase",
    "phase.serialize",
    "phase.write",
    "phase.flush",
    "audit.emit",
    "audit.serialize",
    "audit.write",
    "audit.flush",
)
OMITTED = ("R9.begin", "R9.finish", "R9.request", "R9.resource", "R9.WeakIds.get")
CONTRACT = {
    "selected": list(SELECTED),
    "omitted_separate_exposure": list(OMITTED),
    "omitted_cost": "UNMEASURED_NOT_ZERO",
    "sampling": False,
}


def pinned(filename, name):
    path = R11 / filename
    if path.is_symlink() or path.resolve() != path or path.stat().st_size > 524288:
        raise ValueError("pinned pure helper path/cap")
    if hashlib.sha256(path.read_bytes()).hexdigest() != PINS[filename]:
        raise ValueError("pinned pure helper source changed")
    existing = sys.modules.get(name)
    if existing is not None:
        if Path(existing.__file__).resolve() != path:
            raise ValueError("ambiguous pure helper import")
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("pure helper loader missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


REFERENCE = pinned("overhead_observer.py", "overhead_observer")
REFERENCE_ANALYSIS = pinned("analyze.py", "_r12_pinned_r11_analysis")
FIELDS = REFERENCE.FIELDS
FAULT_KEYS = REFERENCE.FAULT_KEYS
ORIGINS = REFERENCE.ORIGINS
TaskIds = REFERENCE.TaskIds


class MinimalObserver(REFERENCE.ObserverExposure):
    def attach_boundary(self, boundary):
        if self.boundary is not None:
            raise RuntimeError("one reference boundary required")
        self.boundary = boundary
        original = boundary.recording

        def recording(*args, **kwargs):
            operation = args[0] if args else kwargs.get("operation")
            source = self.safe(lambda: self.line(operation))
            label = "R9.recording@" + str(source) if source is not None else "R9.recording.unknown"
            return self.measure(original, label, args, kwargs, source_line=source)

        self.patch(boundary, "recording", recording)
        # No nested helper/registry patches. No event sampling or callback filtering.

    def snapshot(self):
        packet = super().snapshot()
        packet["namespace"] = "R12-only weak task and local span IDs"
        packet["measurement_contract"] = json.loads(json.dumps(CONTRACT))
        return packet

    def close(self):
        if self.closed:
            return
        output, self.output = self.output, None
        try:
            super().close()  # Restore exactly; base does not write the R11 filename.
        finally:
            self.output = output
        if output is not None and not getattr(self, "r12_written", False):
            raw = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":")).encode()
            if len(raw) > self.MAX_BYTES:
                raise ValueError("NEW minimal output cap")
            with (output / "minimal-exposure.json").open("xb") as stream:
                stream.write(raw)
            self.r12_written = True


def decoded_records(packet):
    if (
        packet["namespace"] != "R12-only weak task and local span IDs"
        or packet["measurement_contract"] != CONTRACT
    ):
        raise ValueError("R12 explicit measurement contract")
    return REFERENCE.decoded_records(packet)
