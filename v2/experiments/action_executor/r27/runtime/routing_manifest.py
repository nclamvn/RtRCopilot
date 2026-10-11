"""Twenty actual producer-family routes; local proof never implies full campaign coverage."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from launcher import CONTRACT, mapping, sequence, text


@dataclass(frozen=True)
class Route:
    family: str
    real_producer: str
    prepared_endpoint: str
    record_boundary: str
    local_scope: str
    runtime_status: str
    max_records: int
    max_payload_bytes: int
    full_original_family: str = "HOLD"


DETAILS = (
    (
        "R21 shell cp binding/contract at44-45",
        "RoutedLauncher.safe_outputs",
        "each full original file copy",
        (
            "two exact source-pinned copies via precharged native endpoin"
            "ts; shell cp itself not invoked"
        ),
        "LOCAL_CONTROL",
    ),
    (
        "r/run_phase_baseline.py r-controls write",
        "RoutedLauncher.safe_outputs",
        "one original JSON write",
        (
            "actual pure original controls encoder expression with off; e"
            "ngine/asserts/runpy unexecuted"
        ),
        "SOURCE_SUBSET",
    ),
    (
        "R21 shell printf executor-scope",
        "RoutedLauncher.safe_outputs",
        "one fixed complete literal",
        ("exact decoded original literal bytes precharged; no effectful shell launch"),
        "LOCAL_CONTROL",
    ),
    (
        "R21 review-pin printf /qualification.mark",
        "review_pin + readonly preflight marker check",
        "one pin/marker file each",
        ("finite review pin endpoint only; original mark not called or consumed"),
        "PREPARED_HOLD",
    ),
    (
        "latency_probe.main.retain",
        "typed producers.DriverOutputs.journal",
        "each original observation write call",
        ("exact producer block on static controls; full original request loop unexecuted"),
        "SOURCE_SUBSET",
    ),
    (
        "latency_probe.main finally samples.json",
        "typed producers.DriverOutputs.finish",
        "one complete final JSON write",
        ("exact final block; full app/dependency/engine finally remains unexecuted"),
        "SOURCE_SUBSET",
    ),
    (
        ("latency_probe summary/write/print/oracle and R19 child stdout"),
        "DriverOutputs.finish + pipes.finite_child",
        ("each original write/print; fixed child whole stdout, never read chunks"),
        "source block/fixed child only",
        "SOURCE_SUBSET",
    ),
    (
        ("StructuredAuditSink.emit, app/repository logs and R19 child stderr"),
        "typed scoped logger + finite_child",
        "original rendered emit; fixed complete raw child stream",
        "full audit emitter only; arbitrary app stderr HOLD",
        "SOURCE_SUBSET",
    ),
    (
        "R21 checked migration ->R19 native child stdout/stderr",
        "PreparedCommand migration ->future prewrite broker",
        "unknown complete native write/stream",
        "command/argv prepared only; no alembic/Docker/SQL",
        "PREPARED_HOLD",
    ),
    (
        ("R19 supervise owner/process JSON + begin_cleanup owner overwrite"),
        "SourceSupervisor.metadata_subset",
        "actual source JSON expression/whole original overwrite",
        (
            "real source metadata writes after safechild; no Linux group "
            "authority/pre-spawn persistence"
        ),
        "SOURCE_SUBSET",
    ),
    (
        "R21 stop_active stdout/stderr/drained proof, R19 stop/drain",
        "safe fixed pipe join + metadata stop proof",
        "whole stop command streams and proof records",
        ("joined full RequestConnection safechild; original /proc group signal/stop not executed"),
        "SOURCE_SUBSET",
    ),
    (
        "R21 source/cap/child qualification CLI and redirects",
        "preflight.validate_sources + typed recovery",
        "each complete original proof stream",
        ("source hashes read locally; original checked CLI streams only prepared"),
        "PREPARED_HOLD",
    ),
    (
        ("R21 fixture_check Docker inspect and latency publish SOT stage"),
        "PreparedCommand fixture + pure signedfixture producer",
        "whole inspection stream/file; pure fixture write calls",
        ("full pure signedfixture is subset, no Docker inspect or SOT publisher/stager"),
        "PREPARED_HOLD",
    ),
    (
        "R21 pg_sql role/absence/create/grants/postload/drop/closure",
        "PreparedCommand +read-only source ledger",
        "one complete psql stdout/stderr invocation",
        ("exact namespace/timeout/argv prepared; zero SQL/admin execution"),
        "PREPARED_HOLD",
    ),
    (
        "R21 capacity hostdf+PGdf at90-92",
        "PreparedCommand capacity",
        "whole each original df stdout/stderr",
        ("source bound to host>=20GiB PG>=512MiB; current prerequisites unexecuted"),
        "PREPARED_HOLD",
    ),
    (
        "R21 qualification analyze -> reconstructed.json/stderr",
        "PreparedCommand reconstruction +typed recovery",
        "whole reconstructed JSON/error output",
        ("packet recovery locally tested; original analysis CLI not invoked"),
        "PREPARED_HOLD",
    ),
    (
        ("R21 checked/cleanup/finish/postload/analysis printf returncodes"),
        "RoutedLauncher.returncode",
        "one complete original label/code line",
        ("finite exact line endpoint tested, original outer lifecycle not launched"),
        "SOURCE_SUBSET",
    ),
    (
        ("latency TemporaryDirectory ->publish ->SOT staging/tmp/nativewrites"),
        "registered pure fixture subset; finite native bypass proof",
        "each original write including overwritten/deleted copies",
        ("os.open/os.write can bypass hooks/precharge; temp subsystem NOT covered"),
        "BLOCKER",
    ),
    (
        "phase_profiler/pg_monitor branch under mode=on",
        "OFF-only controls/preflight environment",
        "observer records if future separately admitted",
        (
            "original mode off; observer absence prepared/verified in loc"
            "al plan, no runtime activation"
        ),
        "ABSENT_OFF_PLAN",
    ),
    (
        ("R21 inherited shellstdout/stderr + Main tool/raw retained records/platform transcript"),
        "future broker shell pipes; platform copy outsideowner",
        "whole each inherited record/each physical retained copy",
        (
            "shell channels can be brokerprepared; Codex platform-service"
            " copy cannot be precharged by interpreter"
        ),
        "BLOCKER",
    ),
)


def routing_manifest() -> dict[str, object]:
    contract = mapping(json.loads(CONTRACT.read_bytes()))
    families = sequence(contract["families"])
    if len(families) != len(DETAILS) or contract["cap_bytes"] != 10485760:
        raise ValueError("unchanged twenty-family contract required")
    routes = []
    for family, detail in zip(families, DETAILS, strict=True):
        original = mapping(family)
        variant = mapping(sequence(original["variants"])[0])
        count, limit = variant["max_records"], variant["max_payload_bytes"]
        if type(count) is not int or type(limit) is not int:
            raise ValueError("typed fixed family bounds")
        producer, endpoint, boundary, local, status = detail
        routes.append(
            asdict(
                Route(
                    text(original["id"]), producer, endpoint, boundary, local, status, count, limit
                )
            )
        )
    return {
        "schema": "r27-real-path-routing-v1",
        "families": routes,
        "local_control_assertions": (
            "actual tests/health artifact required; authorship alone not PASS"
        ),
        "whole_record_rule": (
            "raw original writes/whole finite child streams; no splitting/truncation"
        ),
        "shared_cap_bytes": 10485760,
        "measurement_admission": "HOLD",
        "effects": "DENY",
        "one_design_recommendation": (
            "one bounded top-level prewrite broker owns all admitted chil"
            "d file/pipe/artifact writes with joined cleanup; platform-se"
            "rvice transcript remains an explicit boundary/authority deci"
            "sion, not broker-controlled or silently excluded"
        ),
    }
