"""Eight grouped local witnesses; none execute the original effectful campaign."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from unittest.mock import patch

import adapter
import pytest
from broker import Broker, ProducerFile, recover
from integration import HERE, BrokerStream, Producers, RaisingHandler, Record, output_scope, shell_outputs, signed_fixture
from rtr_copilot.auth.audit import audit_logger
from preflight import EPOCH, MARKER, candidate, canonical, preflight
from supervisor import CHILD, owned_child, terminal_join


@pytest.fixture
def owned() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="codex-tmp-r27-broker-integration-20261010-", dir=HERE) as temporary:
        yield Path(temporary)


def incomplete(broker: Broker, root: Path) -> None:
    with pytest.raises((ValueError, OSError)):
        broker.finish()
    assert not (root / "packet/seal.bin").exists()
    broker.abandon()


def samples() -> list[Record]:
    return [dict(profile=profile, operation=operation, case=case, elapsed_ms=1.0, okay=True)
            for profile in (1, 10, 25, 50)
            for operation in ("admission", "submit", "status", "cancel") for case in range(100)]


def test_exact_driver_journal_summary_final_and_known_oracle(owned: Path) -> None:
    for status in ("PASS", "FAIL"):
        root = owned / status
        broker = Broker(root)
        producer = Producers(broker)
        target = broker.path("driver", "summary_stdout")
        target.mkdir()
        # Actual original journal/final/summary use different historical families.
        records: list[Record] = []
        with broker.path("driver/samples.jsonl", "journal").open("x") as observations:
            retain = producer.journal(records, observations)
            source_records = samples()
            if status == "FAIL":
                source_records[0]["okay"] = False
            for row in source_records:
                retain(row)
        with output_scope(broker):
            if status == "FAIL":
                with pytest.raises(SystemExit) as caught:
                    producer.finish(records, target)
                assert caught.value.code == 1
            else:
                producer.finish(records, target)
        assert json.loads(broker.path("driver/latency-summary.json", "summary_stdout").read_text())["status"] == status
        assert len(json.loads(broker.path("driver/samples.json", "final_samples").read_text())) == 1600
        result = broker.finish()
        assert result["prototype_complete"] and recover(root) == result
        assert sum(row[0] == "journal" for row in result["records"]) == 1600
        assert len((root / "files/driver/samples.jsonl").read_bytes().splitlines()) == 1600


def test_full_pure_fixture_copy_temp_and_cached_native_denial(owned: Path) -> None:
    root = owned / "fixture"
    broker = Broker(root)
    package = signed_fixture(broker, broker.path("fixture", "fixture"))
    assert package.name == "package-00000000-0000-0000-0000-000000000002"
    assert (package / "manifest.json").stat().st_size > 0
    temporary = broker.path("temp", "ephemeral")
    temporary.mkdir()
    copied = temporary / "copy"
    copied.write_bytes((package / "manifest.json").read_bytes())
    copied.write_bytes(b"overwritten")
    before = broker.charge
    copied.unlink()
    assert broker.charge == before
    result = broker.finish()
    assert sum(row[0] == "fixture" for row in result["records"]) == 6
    assert result["native_files"] == 5 and recover(root) == result
    denied_root = owned / "cached"
    denied = Broker(denied_root)
    capability = denied.path("cannot-native", "ephemeral")
    cached_open = open
    with pytest.raises(adapter.PacketError):
        cached_open(capability, "wb")
    assert not (denied_root / "files/cannot-native").exists()
    incomplete(denied, denied_root)


def test_original_shell_copy_literals_and_actual_audit_restoration(owned: Path) -> None:
    root = owned / "source"
    broker = Broker(root)
    shell_outputs(broker)
    cache = vars(audit_logger)["_cache"]
    assert isinstance(cache, dict)
    snapshot = dict(cache)
    old = (sys.stdout, audit_logger.handlers, audit_logger.filters, audit_logger.level,
           audit_logger.propagate, audit_logger.disabled)
    producer = Producers(broker)
    with output_scope(broker):
        for _ in range(40):
            producer.audit()
    assert old == (sys.stdout, audit_logger.handlers, audit_logger.filters, audit_logger.level,
                   audit_logger.propagate, audit_logger.disabled)
    assert vars(audit_logger)["_cache"] is cache and cache == snapshot
    result = broker.finish()
    assert sum(row[0] == "frozen_copies" for row in result["records"]) == 2
    assert sum(row[0] == "load_stderr" for row in result["records"]) == 40
    assert result["platform_audit"] == "SEPARATE_DISCLOSED_OUTSIDE_QUALIFYING_PACKET"
    assert recover(root) == result


def test_scoped_fault_stale_foreign_and_close_restore_primary(owned: Path) -> None:
    for fault in ("encode", "type", "stale", "foreign", "source", "close", "emit", "nested"):
        root = owned / fault
        broker = Broker(root)
        stdout, cache = sys.stdout, vars(audit_logger)["_cache"]
        if fault == "source":
            prep_error = OSError("source preparation")
            with patch("integration.source", side_effect=prep_error), pytest.raises(OSError) as prep_caught:
                Producers(broker)
            assert prep_caught.value is prep_error
        elif fault == "close":
            original, cleanup = RuntimeError("primary"), OSError("handler close")
            with patch.object(RaisingHandler, "close", side_effect=cleanup) as closing, pytest.raises(RuntimeError) as caught:
                with output_scope(broker):
                    raise original
            assert caught.value is original and isinstance(original.__cause__, adapter.PacketError)
            closing.assert_called_once()
            close_root = owned / "only-close"
            close_broker = Broker(close_root)
            with patch.object(RaisingHandler, "close", side_effect=cleanup), pytest.raises(OSError) as close_caught:
                with output_scope(close_broker):
                    pass
            assert close_caught.value is cleanup
            incomplete(close_broker, close_root)
            # A failed close must not strand the global lock.
            fresh = Broker(owned / "after-close")
            with output_scope(fresh):
                pass
            fresh.finish()
        elif fault == "emit":
            emit_error = OSError("actual audit emit failed")
            producer = Producers(broker)
            with patch.object(ProducerFile, "write", side_effect=emit_error), pytest.raises(OSError) as emitted:
                with output_scope(broker):
                    producer.audit()
            assert emitted.value is emit_error
        elif fault == "nested":
            with pytest.raises(ValueError, match="nonreentrant"):
                with output_scope(broker):
                    with output_scope(broker):
                        pass
        else:
            stream = BrokerStream(broker, "summary_stdout")
            if fault == "encode":
                with pytest.raises(UnicodeEncodeError):
                    stream.write("\ud800")
            elif fault == "type":
                with pytest.raises(TypeError):
                    stream.write(cast(str, 7))
            elif fault == "stale":
                stream.close_scope()
                with output_scope(broker):
                    stream = cast(BrokerStream, sys.stdout)
                with pytest.raises(ValueError):
                    stream.flush()
            else:
                failures: list[BaseException] = []
                def foreign() -> None:
                    try:
                        stream.write("foreign")
                    except BaseException as error:
                        failures.append(error)
                thread = threading.Thread(target=foreign)
                thread.start()
                thread.join()
                assert len(failures) == 1 and isinstance(failures[0], ValueError)
            if stream.active:
                with pytest.raises(adapter.PacketError, match="sticky"):
                    stream.close_scope()
        assert sys.stdout is stdout and vars(audit_logger)["_cache"] is cache
        incomplete(broker, root)


def test_exact_owned_child_whole_eof_and_no_root_delivery(owned: Path) -> None:
    root = owned / "child"
    broker = Broker(root)
    real = asyncio.create_subprocess_exec
    with patch("supervisor.asyncio.create_subprocess_exec", wraps=real) as spawn:
        result = asyncio.run(owned_child(broker))
    assert result.outputs == {"summary_stdout": b"actual raw stdout\x00\xff\nsecond line\n",
                              "load_stderr": b"actual raw stderr\xff\n"}
    assert result.joined and result.returncode == 0 and result.deadline_attempts == 1
    assert not result.linux_group_authority
    args, keywords = spawn.call_args
    assert args == (sys.executable, "-B", str(CHILD), "ok")
    assert keywords["cwd"] == CHILD.parent and "pass_fds" not in keywords
    assert keywords["env"] == {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    assert str(root) not in repr((args, keywords))
    recovered = broker.finish()
    metadata = json.loads((root / "files/supervisor/process.json").read_bytes())
    assert metadata["group_drained"] is False and metadata["linux_group_authority"] is False
    assert metadata["owned_child_reaped"] and metadata["owned_tasks_joined"] and metadata["whole_streams_eof"]
    for family, raw in result.outputs.items():
        records = [row[3] for row in recovered["records"] if row[0] == family]
        assert records == [raw] and (root / ("files/supervisor/" + family + ".raw")).read_bytes() == raw
    assert recover(root) == recovered
    with pytest.raises(ProcessLookupError):
        os.kill(result.pid, 0)


def test_child_repeated_cancel_one_deadline_and_overflow(owned: Path) -> None:
    root = owned / "cancel"
    broker = Broker(root)
    async def cancel() -> asyncio.CancelledError:
        started = asyncio.Event()
        task = asyncio.create_task(owned_child(broker, "delay", started))
        await started.wait()
        task.cancel("first cancellation")
        await asyncio.sleep(0)
        task.cancel("repeated cancellation")
        try:
            await task
        except asyncio.CancelledError as error:
            return error
        raise AssertionError("cancellation required")
    error = asyncio.run(cancel())
    assert error.args == ("first cancellation",)
    owner = json.loads((root / "files/supervisor/owner.json").read_bytes())
    process = json.loads((root / "files/supervisor/process.json").read_bytes())
    assert owner["cleanup_deadline"] is not None and process["owner"]["cleanup_deadline"] == owner["cleanup_deadline"]
    # Original cleanup writer admits one owner overwrite; no renewed deadline/second write.
    segments = broker._entries["supervisor/owner.json"]["segments"]
    assert sum(cast(int, row[1]) - cast(int, row[0]) for row in segments) == 2
    with pytest.raises(ProcessLookupError):
        os.kill(owner["group"], 0)
    incomplete(broker, root)
    root = owned / "excess"
    broker = Broker(root)
    with pytest.raises(ValueError, match="whole fixed raw stream excess"):
        asyncio.run(owned_child(broker, "excess"))
    assert not (root / "files/supervisor/load_stderr.raw").exists()
    owner = json.loads((root / "files/supervisor/owner.json").read_bytes())
    with pytest.raises(ProcessLookupError):
        os.kill(owner["group"], 0)
    incomplete(broker, root)


def test_spawn_and_postspawn_metadata_faults_retain_primary_and_reap(owned: Path) -> None:
    root = owned / "spawn"
    broker = Broker(root)
    original = OSError("exact spawn failed")
    async def fail_spawn(*_args: object, **_keywords: object) -> asyncio.subprocess.Process:
        raise original
    with patch("supervisor.asyncio.create_subprocess_exec", fail_spawn), pytest.raises(OSError) as caught:
        asyncio.run(owned_child(broker))
    assert caught.value is original and isinstance(original.__cause__, RuntimeError)
    assert not (root / "files/supervisor/process.json").exists()
    incomplete(broker, root)
    root = owned / "metadata"
    broker = Broker(root, {"native_write": "short"})
    real = asyncio.create_subprocess_exec
    children: list[asyncio.subprocess.Process] = []
    async def remember(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        # Fixed call shape; retain exact Process only to assert terminal ownership.
        child = await real(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                           limit=4096, cwd=CHILD.parent,
                           env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
        children.append(child)
        return child
    with patch("supervisor.asyncio.create_subprocess_exec", remember), pytest.raises(OSError):
        asyncio.run(owned_child(broker, "delay"))
    assert len(children) == 1 and children[0].returncode is not None
    incomplete(broker, root)
    for failure in ("cleanup_wait", "cleanup_kill", "readers_join"):
        root = owned / failure
        broker = Broker(root)
        children.clear()
        terminal_error = OSError(failure)
        injected = False
        async def faulty_join(task: asyncio.Task[object], until: float) -> object:
            nonlocal injected
            target = "r27-read-" if failure == "readers_join" else "r27-reap-"
            if not injected and task.get_name().startswith(target):
                injected = True
                if failure == "cleanup_kill":
                    raise TimeoutError("force same-deadline escalation")
                raise terminal_error
            return await terminal_join(task, until)
        original_kill = asyncio.subprocess.Process.kill
        def faulty_kill(child: asyncio.subprocess.Process) -> None:
            original_kill(child)
            if failure == "cleanup_kill":
                raise terminal_error
        def ignored_terminate(_child: asyncio.subprocess.Process) -> None:
            pass
        async def cancel_cleanup() -> asyncio.CancelledError:
            started = asyncio.Event()
            task = asyncio.create_task(owned_child(broker, "delay", started))
            await started.wait()
            task.cancel("known original cancellation")
            await asyncio.sleep(0)
            task.cancel("repeated during cleanup fault")
            try:
                await task
            except asyncio.CancelledError as error:
                return error
            raise AssertionError("primary cancellation required")
        with (patch("supervisor.asyncio.create_subprocess_exec", remember),
              patch("supervisor.terminal_join", faulty_join),
              patch.object(asyncio.subprocess.Process, "terminate", ignored_terminate),
              patch.object(asyncio.subprocess.Process, "kill", faulty_kill)):
            cancelled = asyncio.run(cancel_cleanup())
        assert injected and cancelled.args == ("known original cancellation",)
        assert cancelled.__cause__ is terminal_error
        assert len(children) == 1 and children[0].returncode is not None
        metadata = json.loads((root / "files/supervisor/process.json").read_bytes())
        assert metadata["group_drained"] is False and metadata["linux_group_authority"] is False
        assert metadata["owned_child_reaped"] and metadata["owned_tasks_joined"]
        assert metadata["resource_status"] == "OBSERVED_JOINED"
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
        incomplete(broker, root)


def test_frozen_preflight_readonly_fresh_namespace_untrusted_grant_deny(owned: Path) -> None:
    frozen = candidate()
    plan = canonical(frozen["plan"])
    assert EPOCH.encode() in plan and b"rtr_tip054_r27_broker_local_e1" in plan
    # Old identities are retained ONLY in the explicitly disclosed substitution map.
    commands = dict(cast(dict[str, object], frozen["plan"]))
    commands.pop("broker_identity_substitutions")
    assert b"r27_runtime_http_e1" not in canonical(commands)
    assert frozen["effects"] == "DENY_THIS_BATCH"
    target = owned / "candidate.json"
    target.write_bytes(canonical(frozen))
    marker_before = MARKER.read_bytes() if MARKER.exists() else None
    result = preflight(target, {"approved": True, "one_shot": True})
    assert result["source_match"] and result["boundary_match"]
    assert not result["effect_dispatch_allowed"] and not result["marker_written"]
    assert result["platform_audit"] == "APPROVED_SEPARATE_DISCLOSED"
    assert (MARKER.read_bytes() if MARKER.exists() else None) == marker_before
    assert canonical(json.loads(target.read_bytes())) == canonical(frozen)
    altered = dict(frozen, effects="ALLOW")
    target.write_bytes(canonical(altered))
    with pytest.raises(ValueError, match="frozen"):
        preflight(target)
