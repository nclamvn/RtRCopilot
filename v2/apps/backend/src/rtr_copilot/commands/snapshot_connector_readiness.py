"""Write a secret-free readiness attestation for enterprise connectors."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from rtr_copilot.enterprise_corpus.connectors import (
    KnowledgeScope,
    connector_readiness,
    connector_registry_digest,
    load_connector_registry,
    plan_federation,
)


def snapshot(rtr_root: Path) -> dict[str, object]:
    registry = load_connector_registry()
    readiness = connector_readiness(registry, rtr_root=rtr_root)
    scopes: tuple[KnowledgeScope, ...] = ("company", "research", "federated")
    plans = {
        scope: plan_federation(
            registry,
            scope,
            authenticated=True,
            research_authorized=True,
        ).model_dump(mode="json")
        for scope in scopes
    }
    counts = {
        state: sum(item.readiness == state for item in readiness)
        for state in ("active", "contract_ready", "blocked")
    }
    return {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "registry_digest": connector_registry_digest(registry),
        "connectors": [item.model_dump(mode="json") for item in readiness],
        "counts": counts,
        "federation_plans": plans,
        "production_ready": counts["active"] > 0 and counts["blocked"] == 0,
        "verdict": (
            "contract_ready_not_connected"
            if counts["active"] == 0 else "partially_connected"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rtr-root", type=Path, default=Path("/Users/os/RtR"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = snapshot(args.rtr_root)
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
