"""Real family coverage: approved platform audit is disclosed, not an unresolved blocker."""

from __future__ import annotations

import json

from integration import BASE, mapping, rows

SCOPES = (
    "exact original frozen copy bytes through producer ports",
    "original pure controls expression; engine/runpy NOT_RUN",
    "exact original scope literal through broker",
    "review line adapted; real campaign marker NOT_CONSUMED",
    "exact retain body, original encoder/append/flush on static control data",
    "exact source finally write expression through logical facade",
    "exact summary/write/print/oracle; fixed raw EOF stream in separate control epoch",
    "actual audit sink scoped rendered writes; fixed raw stderr EOF in separate epoch",
    "migration stdout/stderr QUALIFYING, PREPARED_NOT_RUN; unknown native writers DENY",
    "actual R19 owner/result expressions +cleanup overwrite; no Linux group qualification",
    "exact fixed owned child/drain/reap; original Linux group/descendants NOT_RUN",
    "source/preflight/recovery controlled; original effectful CLI channels NOT_RUN",
    "full pure signedfixture five files/six writes/stat/read; publish/SQL NOT_RUN",
    "SQL/admin stdout/stderr QUALIFYING but PREPARED_NOT_RUN",
    "disk command streams QUALIFYING but PREPARED_NOT_RUN",
    "strict broker recovery; original load analysis CLI PREPARED_NOT_RUN",
    "source-connected exact label/code line; original shell lifecycle PREPARED_NOT_RUN",
    "logical temp namespace copy/overwrite/delete; native unknown path writers DENY",
    "observer OFF; no observer activation or native monitor",
    (
        "shell/host admitted artifact streams QUALIFYING; "
        "Codex/platform transcript separate disclosed audit"
    ),
)


def ledger() -> dict[str, object]:
    families = rows(mapping(json.loads(BASE.read_bytes()))["families"])
    if len(families) != 20:
        raise ValueError("same twenty families required")
    return {
        "schema": "r27-broker-routing-v1",
        "platform_boundary": "APPROVED_AND_PINNED",
        "platform_audit_controlled": False,
        "platform_audit_bytes_claimed_zero": False,
        "families": [
            dict(
                id=mapping(family)["id"],
                code=mapping(family)["code"],
                domain=mapping(family)["variants"],
                local_scope=scope,
                full_original_runtime="NOT_RUN",
                tested="see exact local controls/XML",
            )
            for family, scope in zip(families, SCOPES, strict=True)
        ],
        "effects": "DENY_THIS_BATCH",
        "native_scope": "pinned cooperative ports/exact finite child only",
    }
