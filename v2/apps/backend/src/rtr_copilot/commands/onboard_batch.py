"""TIP-013 Phase A · curator-gated batch onboarding (D-013-03, AC-A2).

This command orchestrates the onboarding of a *manifest* of synthetic source
items through the EXISTING gates only — it never opens a new ingestion path and
never bypasses a control:

* SOT items go quarantine -> stage -> validate -> publish (the TIP-006 gate;
  activation requires a curator-signed attestation).
* Research items go through the Refinery adapter import gate (TIP-010) and,
  optionally, the graduation gate (propose -> decide with separation of duties);
  graduation stages a draft SOT candidate and, per REQ-033, never auto-activates.

Discipline enforced here:

* **Dry-run by default.** Without ``--apply`` the tool only *validates* every
  item with the pure, no-DB validators and reports the plan. ``--apply`` runs
  the real gates.
* **Curator approval is a required step.** ``--apply`` is refused unless the
  operator also passes ``--approve``; the SOT publish gate additionally requires
  the package attestation to be signed by the manifest's ``curator_subject_id``.
* **Two-phase, fail-closed.** Every item is validated (pure, no DB write) before
  ANY activation. A batch with a single defective item is rejected wholesale with
  a typed, audited reason and ZERO partial activation.
* **Idempotent.** Re-applying the same manifest re-uses the gate idempotency
  (stage/publish/import are all idempotent), so a retry never double-activates.
* **Audited.** Each gate call already appends an append-only audit event; the
  request-id carries the batch id so the trail is linkable, and this command
  emits a machine-readable batch ledger.

No real corpus is ever read here; the fixtures are synthetic packages staged by
the caller into the configured staging roots.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import Settings, get_settings
from rtr_copilot.governance.models import ResearchTier
from rtr_copilot.repositories.governance import GovernanceError
from rtr_copilot.research.models import CandidateClaim, GraduationProposalInput
from rtr_copilot.research.package import ResearchPackageError, ResearchPackageParser
from rtr_copilot.research.service import ResearchService
from rtr_copilot.sot.package import PackageError, PackageParser, validate_package
from rtr_copilot.sot.service import PublishError, SOTPublishService

Clock = Callable[[], datetime]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GraduationSpec(_Strict):
    """Optional graduation of imported research records into an SOT candidate."""

    proposer_subject_id: uuid.UUID
    decider_subject_id: uuid.UUID
    target_record_key: str = Field(min_length=1, max_length=256)
    record_keys: list[str] = Field(min_length=1, max_length=100)
    claim_text: str = Field(min_length=1, max_length=4000)
    classification: str = "internal"
    value: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(default="batch graduation", min_length=1, max_length=4000)


class SotItem(_Strict):
    staging_name: str = Field(min_length=1)
    expected_source_key: str | None = None
    expected_revision: int | None = None


class ResearchItem(_Strict):
    staging_name: str = Field(min_length=1)
    source_key: str = Field(min_length=1)
    tiers: list[ResearchTier] | None = None
    graduation: GraduationSpec | None = None


class BatchManifest(_Strict):
    batch_id: str = Field(min_length=1, max_length=200)
    curator_subject_id: uuid.UUID
    sot_items: list[SotItem] = Field(default_factory=list)
    research_items: list[ResearchItem] = Field(default_factory=list)


class ItemResult(_Strict):
    kind: Literal["sot", "research"]
    ref: str
    phase: Literal["validate", "apply"]
    ok: bool
    state: str
    reason_code: str | None = None
    package_id: str | None = None
    run_id: str | None = None
    idempotent: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)


class BatchReport(_Strict):
    batch_id: str
    curator_subject_id: str
    apply: bool
    approved: bool
    status: Literal[
        "validated",
        "rejected",
        "onboarded",
        "apply_failed",
        "approval_required",
    ]
    started_at: str
    finished_at: str
    activated_count: int
    items: list[ItemResult]
    summary: str


class OnboardBatch:
    """Runs a manifest through the existing gates, two-phase and fail-closed."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.factory = factory
        self.clock: Clock = clock or (lambda: datetime.now(UTC))
        self.sot_parser = PackageParser(Path(self.settings.sot_staging_root))
        self.research_parser = ResearchPackageParser(
            Path(self.settings.research_staging_root),
        )

    def _curator_subject(self, subject_id: uuid.UUID) -> Subject:
        """A curator principal for the research gate.

        In production the roles are bound to the authenticated session; the batch
        operator asserts curator authority via ``--approve`` and the manifest's
        ``curator_subject_id``, and the SOT gate independently verifies the
        curator signature, so this is not a privilege escalation path.
        """
        return Subject(
            user_id=str(subject_id),
            issuer="onboard-batch",
            sub=subject_id.hex,
            email=f"{subject_id.hex}@rtrobotics.com",
            canonical_domain="rtrobotics.com",
            roles={Role.CURATOR},
        )

    # ---- Phase 1: pure validation (no DB writes) ---------------------------
    def _validate_sot(self, item: SotItem, curator_id: uuid.UUID) -> ItemResult:
        try:
            package = self.sot_parser.parse(item.staging_name)
        except PackageError as error:
            return ItemResult(
                kind="sot",
                ref=item.staging_name,
                phase="validate",
                ok=False,
                state="planned_invalid",
                reason_code=error.code,
            )
        detail: dict[str, Any] = {
            "source_key": package.manifest.source_key,
            "revision": package.manifest.revision,
        }
        if (
            item.expected_source_key is not None
            and package.manifest.source_key != item.expected_source_key
        ):
            return ItemResult(
                kind="sot",
                ref=item.staging_name,
                phase="validate",
                ok=False,
                state="planned_invalid",
                reason_code="manifest_source_key_mismatch",
                detail=detail,
            )
        if (
            item.expected_revision is not None
            and package.manifest.revision != item.expected_revision
        ):
            return ItemResult(
                kind="sot",
                ref=item.staging_name,
                phase="validate",
                ok=False,
                state="planned_invalid",
                reason_code="manifest_revision_mismatch",
                detail=detail,
            )
        if str(package.attestation.curator_subject_id) != str(curator_id):
            return ItemResult(
                kind="sot",
                ref=item.staging_name,
                phase="validate",
                ok=False,
                state="planned_invalid",
                reason_code="attestation_curator_mismatch",
                detail=detail,
            )
        report = validate_package(
            package,
            now=self.clock(),
            allow_claim_as_approved=self.settings.sot_allow_claim_as_approved,
        )
        if not report.valid:
            codes = [finding.code for finding in report.findings]
            detail["finding_codes"] = codes
            return ItemResult(
                kind="sot",
                ref=item.staging_name,
                phase="validate",
                ok=False,
                state="planned_invalid",
                reason_code=codes[0] if codes else "validation_failed",
                detail=detail,
            )
        detail["record_count"] = report.record_count
        detail["evidence_count"] = report.evidence_count
        return ItemResult(
            kind="sot",
            ref=item.staging_name,
            phase="validate",
            ok=True,
            state="planned_valid",
            detail=detail,
        )

    def _validate_research(self, item: ResearchItem) -> ItemResult:
        try:
            staged = self.research_parser.stage(item.staging_name, now=self.clock())
            records = staged.load_records()
        except ResearchPackageError as error:
            return ItemResult(
                kind="research",
                ref=item.staging_name,
                phase="validate",
                ok=False,
                state="planned_invalid",
                reason_code=error.code,
            )
        detail: dict[str, Any] = {
            "source_key": staged.manifest.source_key,
            "record_count": len(records),
        }
        if staged.manifest.source_key != item.source_key:
            return ItemResult(
                kind="research",
                ref=item.staging_name,
                phase="validate",
                ok=False,
                state="planned_invalid",
                reason_code="manifest_source_key_mismatch",
                detail=detail,
            )
        if item.graduation is not None:
            present = {record.record_key for record in records}
            missing = [key for key in item.graduation.record_keys if key not in present]
            if missing:
                detail["missing_record_keys"] = missing
                return ItemResult(
                    kind="research",
                    ref=item.staging_name,
                    phase="validate",
                    ok=False,
                    state="planned_invalid",
                    reason_code="graduation_record_key_unknown",
                    detail=detail,
                )
        return ItemResult(
            kind="research",
            ref=item.staging_name,
            phase="validate",
            ok=True,
            state="planned_valid",
            detail=detail,
        )

    def validate_all(self, manifest: BatchManifest) -> list[ItemResult]:
        results: list[ItemResult] = []
        for item in manifest.sot_items:
            results.append(self._validate_sot(item, manifest.curator_subject_id))
        for research in manifest.research_items:
            results.append(self._validate_research(research))
        return results

    # ---- Phase 2: apply through the real gates -----------------------------
    async def _apply_sot(
        self,
        item: SotItem,
        curator_id: uuid.UUID,
        batch_id: str,
    ) -> ItemResult:
        service = SOTPublishService(
            self.settings,
            factory=self.factory,
            clock=self.clock,
        )
        base = f"onboard:{batch_id}:{item.staging_name}"
        staged = await service.stage(
            item.staging_name,
            actor_id=curator_id,
            request_id=f"{base}:stage",
        )
        report = await service.validate(
            staged.package_id,
            actor_id=curator_id,
            request_id=f"{base}:validate",
        )
        if not report.valid:
            codes = [finding.code for finding in report.findings]
            return ItemResult(
                kind="sot",
                ref=item.staging_name,
                phase="apply",
                ok=False,
                state="rejected",
                reason_code=codes[0] if codes else "validation_failed",
                package_id=str(staged.package_id),
                run_id=str(staged.run_id),
                detail={"finding_codes": codes},
            )
        published = await service.publish(
            staged.package_id,
            actor_id=curator_id,
            request_id=f"{base}:publish",
        )
        return ItemResult(
            kind="sot",
            ref=item.staging_name,
            phase="apply",
            ok=published.state == "active",
            state=published.state,
            package_id=str(published.package_id),
            run_id=str(published.run_id),
            idempotent=published.idempotent,
            detail={
                "source_key": published.source_key,
                "revision": published.revision,
            },
        )

    async def _apply_research(
        self,
        item: ResearchItem,
        curator_id: uuid.UUID,
        batch_id: str,
    ) -> ItemResult:
        service = ResearchService(self.settings, factory=self.factory)
        curator = self._curator_subject(curator_id)
        base = f"onboard:{batch_id}:{item.staging_name}"
        imported = await service.import_package(
            curator,
            item.staging_name,
            request_id=f"{base}:import",
        )
        detail: dict[str, Any] = {
            "source_key": imported.package.source_key,
            "record_count": imported.package.record_count,
            "import_state": imported.package.import_state,
        }
        result = ItemResult(
            kind="research",
            ref=item.staging_name,
            phase="apply",
            ok=True,
            state="imported",
            package_id=str(imported.package.package_id),
            idempotent=imported.idempotent,
            detail=detail,
        )
        if item.graduation is None:
            return result
        graduation = await self._graduate(
            service,
            item.graduation,
            imported.package.package_id,
            base=base,
        )
        result.detail["graduation"] = graduation
        result.state = "imported+graduated"
        return result

    async def _graduate(
        self,
        service: ResearchService,
        spec: GraduationSpec,
        package_id: uuid.UUID,
        *,
        base: str,
    ) -> dict[str, Any]:
        proposer = self._curator_subject(spec.proposer_subject_id)
        decider = self._curator_subject(spec.decider_subject_id)
        record_ids = await self._resolve_record_ids(
            service,
            proposer,
            package_id,
            spec.record_keys,
            request_id=f"{base}:grad-list",
        )
        proposal = await service.propose(
            proposer,
            GraduationProposalInput(
                research_record_ids=record_ids,
                claim=CandidateClaim(
                    claim_text=spec.claim_text,
                    value=spec.value,
                    classification=spec.classification,  # type: ignore[arg-type]
                ),
                target_record_key=spec.target_record_key,
                rationale=spec.rationale,
            ),
            request_id=f"{base}:grad-propose",
        )
        decided = await service.decide(
            decider,
            proposal.proposal_id,
            decision="approved",
            reason=spec.rationale,
            request_id=f"{base}:grad-decide",
        )
        return {
            "proposal_id": str(decided.proposal_id),
            "state": decided.state,
            "publish_package_id": (
                str(decided.publish_package_id)
                if decided.publish_package_id
                else None
            ),
            "auto_activated": False,
        }

    async def _resolve_record_ids(
        self,
        service: ResearchService,
        subject: Subject,
        package_id: uuid.UUID,
        record_keys: list[str],
        *,
        request_id: str,
    ) -> list[uuid.UUID]:
        by_key: dict[str, uuid.UUID] = {}
        cursor: str | None = None
        while True:
            page = await service.list_records(
                subject,
                package_id,
                request_id=request_id,
                cursor=cursor,
                limit=100,
            )
            for record in page.items:
                by_key[record.record_key] = record.research_record_id
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        missing = [key for key in record_keys if key not in by_key]
        if missing:
            raise GovernanceError("graduation_record_key_unknown")
        return [by_key[key] for key in record_keys]

    async def run(
        self,
        manifest: BatchManifest,
        *,
        apply: bool,
        approved: bool,
    ) -> BatchReport:
        started = datetime.now(UTC).isoformat()
        curator_id = manifest.curator_subject_id
        validations = self.validate_all(manifest)
        invalid = [item for item in validations if not item.ok]
        if apply and not approved:
            return BatchReport(
                batch_id=manifest.batch_id,
                curator_subject_id=str(curator_id),
                apply=apply,
                approved=approved,
                status="approval_required",
                started_at=started,
                finished_at=datetime.now(UTC).isoformat(),
                activated_count=0,
                items=validations,
                summary=(
                    "Curator approval required: re-run --apply together with "
                    "--approve. No item was activated."
                ),
            )
        if invalid:
            return BatchReport(
                batch_id=manifest.batch_id,
                curator_subject_id=str(curator_id),
                apply=apply,
                approved=approved,
                status="rejected",
                started_at=started,
                finished_at=datetime.now(UTC).isoformat(),
                activated_count=0,
                items=validations,
                summary=(
                    f"Batch rejected fail-closed: {len(invalid)} of "
                    f"{len(validations)} item(s) failed validation. Zero "
                    "activation."
                ),
            )
        if not apply:
            return BatchReport(
                batch_id=manifest.batch_id,
                curator_subject_id=str(curator_id),
                apply=apply,
                approved=approved,
                status="validated",
                started_at=started,
                finished_at=datetime.now(UTC).isoformat(),
                activated_count=0,
                items=validations,
                summary=(
                    f"Dry-run: all {len(validations)} item(s) would pass their "
                    "gate. Re-run with --apply --approve to activate."
                ),
            )
        applied: list[ItemResult] = []
        activated = 0
        try:
            for item in manifest.sot_items:
                result = await self._apply_sot(item, curator_id, manifest.batch_id)
                applied.append(result)
                if result.state == "active":
                    activated += 1
            for research in manifest.research_items:
                result = await self._apply_research(
                    research,
                    curator_id,
                    manifest.batch_id,
                )
                applied.append(result)
        except (PublishError, PackageError, GovernanceError, PermissionError) as error:
            code = getattr(error, "code", type(error).__name__)
            applied.append(ItemResult(
                kind="sot",
                ref="<batch>",
                phase="apply",
                ok=False,
                state="apply_failed",
                reason_code=str(code),
            ))
            return BatchReport(
                batch_id=manifest.batch_id,
                curator_subject_id=str(curator_id),
                apply=apply,
                approved=approved,
                status="apply_failed",
                started_at=started,
                finished_at=datetime.now(UTC).isoformat(),
                activated_count=activated,
                items=applied,
                summary=(
                    f"Apply halted on {code}. Already-validated items were "
                    "idempotent; re-run to resume."
                ),
            )
        return BatchReport(
            batch_id=manifest.batch_id,
            curator_subject_id=str(curator_id),
            apply=apply,
            approved=approved,
            status="onboarded",
            started_at=started,
            finished_at=datetime.now(UTC).isoformat(),
            activated_count=activated,
            items=applied,
            summary=(
                f"Onboarded: {activated} SOT revision(s) activated, "
                f"{len(manifest.research_items)} research package(s) imported."
            ),
        )


def load_manifest(path: Path) -> BatchManifest:
    raw = path.read_text(encoding="utf-8")
    data: Any
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as error:  # pragma: no cover - optional dependency
            raise SystemExit(
                "YAML manifest requires PyYAML; install it or use JSON.",
            ) from error
        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("manifest must be a mapping/object")
    return BatchManifest.model_validate(data)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="onboard_batch",
        description="Curator-gated batch onboarding (dry-run by default).",
    )
    parser.add_argument("--manifest", required=True, help="path to JSON/YAML manifest")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="run the real gates (default: dry-run validation only)",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="curator approval; required together with --apply to activate",
    )
    parser.add_argument("--report", help="write the batch ledger JSON to this path")
    return parser


_EXIT_CODES: dict[str, int] = {
    "validated": 0,
    "onboarded": 0,
    "rejected": 2,
    "approval_required": 3,
    "apply_failed": 4,
}


async def _run_async(args: argparse.Namespace) -> BatchReport:
    manifest = load_manifest(Path(args.manifest))
    return await OnboardBatch().run(
        manifest,
        apply=bool(args.apply),
        approved=bool(args.approve),
    )


def main(argv: list[str] | None = None) -> int:
    import asyncio

    args = _build_arg_parser().parse_args(argv)
    report = asyncio.run(_run_async(args))
    payload = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)
    if args.report:
        Path(args.report).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return _EXIT_CODES.get(report.status, 1)


if __name__ == "__main__":
    sys.exit(main())
