"""Twenty-family source routing ledger; preparation is never runtime qualification."""

from __future__ import annotations

import json

from composition import BASE, BASE_SHA, bounded, digest, mapping, rows

SCOPES = (
    "ACTUAL_LOCAL: exact pinned original binding/contract byte copies",
    "PREPARED: complete baseline original controls AST; engine assertions NOT_RUN",
    "ACTUAL_LOCAL: original shell scope literal",
    "PARTIAL_LOCAL: exclusive broker local marker control; real marker NOT_CONSUMED",
    "PREPARED: full unchanged driver original append/flush algorithm; load NOT_RUN",
    "PARTIAL_LOCAL: exact original final JSON writer control; load NOT_RUN",
    "PARTIAL_LOCAL: exact original summary/print/oracle block; not HTTP observations",
    "ACTUAL_LOCAL: whole rendered root/audit/httpx-style LogRecords; HTTP NOT_RUN",
    "UNSUPPORTED_BEFORE_DISPATCH: Alembic fileConfig/native raw stderr boundary",
    "ACTUAL_LOCAL: original begin_cleanup persists one deadline; real process owner NOT_RUN",
    "PREPARED_NOT_RUN: full pinned Linux proc/group/killpg functions; no group claim",
    "UNSUPPORTED_BEFORE_DISPATCH: actual pytest JUnit explicit writer needs endpoint",
    "NOT_RUN: original external fixture-check outputs; seed is ephemeral, not fixture family",
    "PREPARED_NOT_RUN: all original SQL/admin commands remain qualifying",
    "PREPARED_NOT_RUN: original host/PG df whole command streams remain qualifying",
    "PREPARED_NOT_RUN: original analyzer unchanged",
    "ACTUAL_LOCAL: exact checked label/returncode line",
    "ACTUAL_LOCAL: full original signed fixture + genuine parser through logical snapshot",
    "OFF: original observer remains off; no monitor activation",
    "APPROVED_BOUNDARY: shell/admin admitted artifacts qualify; "
    "platform transcript separate disclosed audit",
)


def ledger() -> dict[str, object]:
    raw = bounded(BASE)
    if digest(raw) != BASE_SHA:
        raise ValueError("immutable twenty-family authority")
    families = rows(mapping(json.loads(raw))["families"])
    return {
        "schema": "r27-real-path-routing-v1",
        "effects": "DENY_THIS_BATCH",
        "capacity": {
            "operative_entries": 32,
            "operative_PRE_records": 32,
            "historical_minimum_entries": 69,
            "original_PRE_records": 53,
            "proposed_96_PRE64": "PREPARED_NOT_ADOPTED",
        },
        "platform_boundary": "APPROVED_SEPARATE_DISCLOSED_AUDIT_NOT_ZERO",
        "families": [
            {
                "id": mapping(family)["id"],
                "code": mapping(family)["code"],
                "bounds_unchanged": mapping(family)["variants"],
                "local_scope": scope,
                "full_runtime": "NOT_RUN",
            }
            for family, scope in zip(families, SCOPES, strict=True)
        ],
        "readiness_blockers": [
            "current capacity below full historical paths/PRE",
            "missing httpx/fastapi/redis",
            "pytest explicit XML endpoint",
            "Alembic logger seam",
            "Linux owned-group execution",
            "live fixture/capacity/absent owned databases",
            "human effect authority",
        ],
    }
