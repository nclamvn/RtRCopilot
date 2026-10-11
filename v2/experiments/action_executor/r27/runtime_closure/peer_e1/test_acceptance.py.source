"""One shared real writer flow plus source-linked capacity/default-DENY assertions."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import readiness
from acceptance import execute_local
from host import HostPort, OwnedBroker
from writer import recover

HERE = Path(__file__).absolute().parent
REFERENCE = HERE.parent / "real_path"


def test_shared_original_producers_recovery_and_honest_capacity_deny() -> None:
    with tempfile.TemporaryDirectory(prefix=".closure-shared-", dir=REFERENCE) as scratch:
        root = Path(scratch) / "capture"
        broker = OwnedBroker(root)
        with HostPort(broker) as port:
            native = execute_local(broker, port, Path(scratch))
            assert native.reaped and native.tasks_joined
            assert port.read("plugins/report.xml").startswith(b"<?xml")
        result = broker.finish()
        assert result["prototype_complete"] and recover(root) == result
        families = {r[0] for r in result["records"]}
        assert {"ephemeral", "source_cap_child", "migration_streams", "disk"} <= families
        assert result["charge"] <= 10485760
    forecast = readiness.topology()
    assert forecast["exhaustive_full_PRE"] is False
    operative = forecast["operative"]
    assert isinstance(operative, str) and operative.startswith("32entries/PRE32")
    assert forecast["pre_single_active_stop_pathwise_files"] == 128
    assert not readiness.dependencies()["httpx"]
    for grant in (None, {"approved": True, "capacity": 192}, "READY"):
        with pytest.raises(PermissionError):
            readiness.dispatch(grant)
