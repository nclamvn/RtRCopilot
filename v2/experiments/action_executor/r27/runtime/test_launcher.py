"""Actual safe launcher/metadata controls and finite native-ownership counterexample."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest
from adapter import PacketError
from envelope import Capture, recover
from launcher import (
    DOMAIN,
    ENGINE,
    EPOCH,
    HERE,
    ROOT,
    RoutedLauncher,
    commands,
    digest,
    literal_controls,
    literal_scope,
    mapping,
)
from preflight import candidate, canonical, preflight, validate_grant
from routing_manifest import routing_manifest
from supervisor import SourceSupervisor, fixed_control, preserve_primary


@pytest.fixture
def local_root() -> Iterator[Path]:
    # Adapter safe-root ownership requires this small named test-only runtime directory.
    with tempfile.TemporaryDirectory(
        prefix="codex-tmp-r27-launcher-20261010-", dir=HERE
    ) as temporary:
        yield Path(temporary)


def test_actual_source_copies_literals_and_returncode_routes(local_root: Path) -> None:
    capture = Capture(local_root / "capture", enabled=True)
    launcher = RoutedLauncher(capture)
    scope, controls = literal_scope(), literal_controls()
    initial = capture.charge
    with capture:
        hashes = launcher.safe_outputs()
        launcher.review_pin("vibecode_v2/R27_RETENTION_REVIEW_REPORT.md", "a" * 64)
        launcher.returncode("local-control", 0)
        launcher.returncode("cleanup", 1)
        assert launcher.scope.read_bytes() == scope
        assert launcher.controls.read_bytes() == controls
        assert launcher.returncodes.read_bytes() == b"local-control 0\ncleanup 1\n"
    assert len(hashes) == 2 and capture.charge > initial
    capture.finish()
    result = recover(capture.root)
    assert result["native_files"] == 6 and recover(capture.root)["charge"] == result["charge"]
    assert all(record[3] for record in result["records"])


def test_fixed_child_and_actual_r19_metadata_cleanup_subset(local_root: Path) -> None:
    capture = Capture(local_root / "capture", enabled=True)
    supervisor = SourceSupervisor(capture)
    result = asyncio.run(fixed_control(capture))
    assert result["outputs"]["summary_stdout"] == b"actual raw stdout\x00\xff\nsecond line\n"
    assert result["outputs"]["load_stderr"] == b"actual raw stderr\xff\n"
    with capture:
        observed = supervisor.metadata_subset(result)
        owner = json.loads(supervisor.owner_path.read_bytes())
        process = json.loads(supervisor.process_path.read_bytes())
        assert owner["cleanup_deadline"] == observed.cleanup_deadline
        assert process["group_drained"] and process["original_exit_code"] == 0
        assert owner["supervisor_start"] == "LOCAL_SUBSET_NOT_LINUX_GROUP_AUTHORITY"
    assert observed.joined and observed.cleanup_not_renewed and not observed.linux_group_authority
    capture.finish()
    assert recover(capture.root)["native_files"] == 3


def test_preparation_and_write_faults_sticky_primary_cleanup(local_root: Path) -> None:
    capture = Capture(local_root / "source-fault", enabled=True)
    primary = ValueError("original source pin failure")
    with patch("launcher.source", side_effect=primary), pytest.raises(ValueError) as caught:
        RoutedLauncher(capture)
    assert caught.value is primary and capture.writer.flags
    with pytest.raises(PacketError):
        capture.finish()
    capture.abandon()
    capture = Capture(local_root / "supervisor-source-fault", enabled=True)
    with patch("supervisor.source", side_effect=primary), pytest.raises(ValueError) as caught:
        SourceSupervisor(capture)
    assert caught.value is primary and capture.writer.flags
    capture.abandon()
    capture = Capture(local_root / "review-outside-context", enabled=True)
    launcher = RoutedLauncher(capture)
    with pytest.raises(PacketError):
        launcher.review_pin("vibecode_v2/R27_RETENTION_REVIEW_REPORT.md", "a" * 64)
    assert capture.writer.flags and not launcher.review.exists()
    capture.abandon()
    capture = Capture(local_root / "metadata-eval-fault", enabled=True)
    supervisor = SourceSupervisor(capture)
    supervisor.expressions["owner"] = compile("1/0", "negative-owner-expression", "eval")
    with capture, pytest.raises(ZeroDivisionError):
        supervisor.metadata_subset({"outputs": {}, "joined": True, "full_class": True})
    assert capture.writer.flags
    with pytest.raises(PacketError):
        capture.finish()
    capture.abandon()
    capture = Capture(local_root / "write-fault", enabled=True, faults={"packet_write": "raise"})
    launcher = RoutedLauncher(capture)
    original = RuntimeError("known original failure")
    with capture:
        try:
            raise original
        except RuntimeError as error:
            try:
                launcher.returncode("cleanup", 1)
            except OSError as cleanup:
                with pytest.raises(RuntimeError) as preserved:
                    preserve_primary(error, cleanup)
                assert preserved.value is original and preserved.value.__cause__ is cleanup
    assert capture.writer.flags and not (capture.root / "packet/seal.bin").exists()
    capture.abandon()


def test_fixed_excess_and_cancel_join_no_complete_retry(local_root: Path) -> None:
    modes: tuple[Literal["excess", "delay"], ...] = ("excess", "delay")
    for mode in modes:
        capture = Capture(local_root / mode, enabled=True)

        async def exercise(selected: Literal["excess", "delay"], active: Capture) -> None:
            if selected == "excess":
                with pytest.raises(ValueError):
                    await fixed_control(active, selected)
            else:
                started = asyncio.Event()
                task = asyncio.create_task(fixed_control(active, selected, started))
                await asyncio.wait_for(started.wait(), 2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

        asyncio.run(exercise(mode, capture))
        assert capture.writer.flags and not (capture.root / "packet/seal.bin").exists()
        with pytest.raises(PacketError):
            capture.finish()
        capture.abandon()


def test_native_cached_fd_prewrite_ownership_counterexample(local_root: Path) -> None:
    capture = Capture(local_root / "capture", enabled=True)
    target = capture.native / "native-bypass.bin"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    before = capture.charge
    try:
        with capture:
            assert os.write(descriptor, b"R27-NATIVE-BYPASS") == 17
            assert capture.charge == before
    finally:
        os.close(descriptor)
    assert target.read_bytes() == b"R27-NATIVE-BYPASS"
    with pytest.raises(PacketError):
        capture.finish()
    assert not (capture.root / "packet/seal.bin").exists()
    capture.abandon()


def test_exact_commands_twenty_routes_and_no_dispatch() -> None:
    planned = commands()
    load = next(command for command in planned if command.label == "load")
    assert load.seconds == 190 and load.argv[-1] == "off"
    assert "/evidence/r19/" + EPOCH in load.argv
    assert any(token.endswith("/" + DOMAIN) for token in load.argv)
    assert any(token.endswith("/" + ENGINE) for token in load.argv)
    assert "OPENAI_API_KEY=" in load.argv and "ANTHROPIC_API_KEY=" in load.argv
    assert "ACTION_EXECUTOR_OPERATION_TIMEOUT_SECONDS=0.9" in load.argv
    routes = routing_manifest()
    families = routes["families"]
    assert isinstance(families, list) and len(families) == 20
    assert all(mapping(row)["full_original_family"] == "HOLD" for row in families)
    assert routes["effects"] == "DENY"


def test_readonly_source_bound_preflight_and_untrusted_grant(local_root: Path) -> None:
    frozen = local_root / "candidate.json"
    payload = candidate()
    frozen.write_bytes(canonical(payload))
    marker = (
        ROOT
        / ("v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1")
        / "r19/r27-runtime-campaign-launch.json"
    )
    before = marker.exists()
    default = preflight(frozen, marker)
    assert default.source_matches and not default.effect_dispatch_allowed
    assert not default.ready_to_request_measurement and default.runtime_prerequisites.startswith(
        "NOT_EXECUTED"
    )
    grant = {
        "schema": "r27-single-measurement-grant-v1",
        "candidate_sha256": digest(frozen.read_bytes()),
        "plan_sha256": digest(canonical(payload["plan"])),
        "epoch": EPOCH,
        "one_shot": True,
        "load_seconds": 190,
        "shared_cleanup_seconds": 10,
        "retained_cap_bytes": 10485760,
        "authority": "Homeowner separately authorizes measurement",
    }
    grant_path = local_root / "untrusted-grant.json"
    grant_path.write_bytes(canonical(grant))
    with_grant = preflight(frozen, marker, grant_path)
    assert with_grant.grant_status.startswith("UNTRUSTED_SCHEMA_VALIDATED")
    assert not with_grant.effect_dispatch_allowed and marker.exists() == before
    bad = dict(grant, load_seconds=191)
    with pytest.raises(ValueError):
        validate_grant(bad, default.candidate_sha256, mapping(payload["plan"]))
    frozen.write_bytes(canonical(dict(payload, HEAD="bad")))
    with pytest.raises(ValueError):
        preflight(frozen, marker)


def test_preflight_rejects_marker_parent_symlink_without_creation(local_root: Path) -> None:
    frozen = local_root / "candidate.json"
    frozen.write_bytes(canonical(candidate()))
    link = local_root / "link"
    link.symlink_to(local_root, target_is_directory=True)
    with pytest.raises(ValueError):
        preflight(frozen, link / "marker.json")
    assert not (local_root / "marker.json").exists()
