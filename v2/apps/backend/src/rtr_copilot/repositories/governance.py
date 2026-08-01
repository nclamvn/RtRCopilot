import json
import re
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.governance.models import (
    Classification,
    Gap,
    GapOrigin,
    GapPage,
    GapPriority,
    GapReasonCategory,
    GapState,
    GapTransition,
    GovernanceSetting,
    GraduationProposal,
    PackageImportState,
    PackageIntake,
    ProposalDecision,
    QueueKind,
    ResearchPackage,
    ResearchRecord,
    ResearchSource,
    ResearchSourceLifecycle,
    ReviewTask,
    SettingValue,
    SettingValueType,
)

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

ALLOWED_PACKAGE_TRANSITIONS: frozenset[tuple[PackageImportState, PackageImportState]] = (
    frozenset({
        ("received", "validating"),
        ("received", "rejected"),
        ("validating", "imported"),
        ("validating", "rejected"),
    })
)

ALLOWED_GAP_TRANSITIONS: frozenset[tuple[GapState, GapState]] = frozenset({
    ("open", "triaged"),
    ("triaged", "assigned"),
    ("assigned", "answered"),
    ("answered", "published"),
    ("open", "declined"),
    ("triaged", "declined"),
    ("assigned", "declined"),
    ("answered", "declined"),
})

SOURCE_COLUMNS = """
    source_id, stable_key, display_name, description, origin,
    owner_subject_id, classification, lifecycle, created_at, updated_at
"""
PACKAGE_COLUMNS = """
    package_id, source_id, fingerprint, payload_sha256, snapshot_manifest,
    captured_at, snapshot_scope, adapter_version, tier_composition,
    import_state, rejection_code, record_count, importer_subject_id,
    received_at, imported_at
"""
RECORD_COLUMNS = """
    research_record_id, package_id, record_key, version_ordinal, tier,
    zone_label, content, searchable_text, evidence_spans,
    corroboration_state, content_sha256, created_at
"""
GAP_COLUMNS = """
    gap_id, question_fingerprint, sanitized_question, sanitized_summary,
    reason_category, classification, requester_id, owner_subject_id,
    routing_key, occurrence_count, lifecycle, answer_run_id,
    resolving_record_id, origin, priority, first_seen_at, last_seen_at,
    triaged_at, assigned_at, due_at, answered_at, closed_at,
    resolving_version_id, decline_reason
"""
REVIEW_TASK_COLUMNS = """
    task_id, queue_kind, record_version_id, assignee_subject_id, assigned_by,
    state, due_at, note, created_at, updated_at, completed_at
"""
PROPOSAL_COLUMNS = """
    proposal_id, research_record_ids, claim_draft, target_record_key,
    proposer_subject_id, rationale, state, decided_by, decision_reason,
    attestation_hash, publish_package_id, supersedes_proposal_id,
    proposed_at, decided_at
"""
SETTING_COLUMNS = """
    setting_id, setting_key, version, value_type, value, updated_by, reason,
    created_at
"""


class GovernanceError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def encode_gap_cursor(first_seen_at: datetime, gap_id: uuid.UUID) -> str:
    return f"{first_seen_at.isoformat()}~{gap_id}"


def decode_gap_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw_at, raw_id = cursor.split("~", 1)
        return datetime.fromisoformat(raw_at), uuid.UUID(raw_id)
    except ValueError as error:
        raise GovernanceError("invalid_cursor") from error


def validate_setting_value(value_type: SettingValueType, value: SettingValue) -> None:
    if value_type == "boolean":
        valid = isinstance(value, bool)
    elif value_type == "string":
        valid = isinstance(value, str)
    elif value_type == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif value_type == "decimal":
        valid = isinstance(value, int | float) and not isinstance(value, bool)
    else:
        valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if not valid:
        raise GovernanceError("setting_value_type_mismatch")


class GovernanceRepository:
    """Storage boundary for TIP-010 governance and research-zone state.

    Methods enforce storage invariants only (immutability, idempotency,
    state-machine legality, separation-of-duties preconditions); policy and
    workflow decisions belong to the service layer.
    """

    async def create_source(
        self,
        session: AsyncSession,
        source: ResearchSource,
    ) -> ResearchSource:
        await session.execute(text(f"""
            INSERT INTO research_sources (
              {SOURCE_COLUMNS}
            ) VALUES (
              :source_id, :stable_key, :display_name, :description, :origin,
              :owner_subject_id, :classification, :lifecycle, :created_at,
              :updated_at
            )
        """), source.model_dump())
        return source

    async def get_source(
        self,
        session: AsyncSession,
        source_id: uuid.UUID,
    ) -> ResearchSource | None:
        row = (await session.execute(text(f"""
            SELECT {SOURCE_COLUMNS} FROM research_sources
            WHERE source_id = :source_id
        """), {"source_id": source_id})).mappings().one_or_none()
        return ResearchSource(**row) if row else None

    async def get_source_by_key(
        self,
        session: AsyncSession,
        stable_key: str,
    ) -> ResearchSource | None:
        row = (await session.execute(text(f"""
            SELECT {SOURCE_COLUMNS} FROM research_sources
            WHERE stable_key = :stable_key
        """), {"stable_key": stable_key})).mappings().one_or_none()
        return ResearchSource(**row) if row else None

    async def list_sources(
        self,
        session: AsyncSession,
        *,
        lifecycle: ResearchSourceLifecycle | None = None,
    ) -> list[ResearchSource]:
        rows = (await session.execute(text(f"""
            SELECT {SOURCE_COLUMNS} FROM research_sources
            WHERE CAST(:lifecycle AS text) IS NULL OR lifecycle = :lifecycle
            ORDER BY stable_key
        """), {"lifecycle": lifecycle})).mappings()
        return [ResearchSource(**row) for row in rows]

    async def register_package(
        self,
        session: AsyncSession,
        package: ResearchPackage,
    ) -> PackageIntake:
        """Insert a package; an identical fingerprint is idempotent."""
        row = (await session.execute(text(f"""
            INSERT INTO research_packages (
              package_id, source_id, fingerprint, payload_sha256,
              snapshot_manifest, captured_at, snapshot_scope, adapter_version,
              tier_composition, import_state, rejection_code, record_count,
              importer_subject_id, received_at, imported_at
            ) VALUES (
              :package_id, :source_id, :fingerprint, :payload_sha256,
              CAST(:snapshot_manifest AS jsonb), :captured_at, :snapshot_scope,
              :adapter_version, CAST(:tier_composition AS jsonb),
              :import_state, :rejection_code, :record_count,
              :importer_subject_id, :received_at, :imported_at
            )
            ON CONFLICT (fingerprint) DO NOTHING
            RETURNING {PACKAGE_COLUMNS}
        """), {
            **package.model_dump(exclude={"snapshot_manifest", "tier_composition"}),
            "snapshot_manifest": json.dumps(package.snapshot_manifest),
            "tier_composition": json.dumps(package.tier_composition),
        })).mappings().one_or_none()
        if row is not None:
            return PackageIntake(package=ResearchPackage(**row), created=True)
        existing = await self.get_package_by_fingerprint(session, package.fingerprint)
        if existing is None:
            raise GovernanceError("package_fingerprint_conflict")
        return PackageIntake(package=existing, created=False)

    async def get_package(
        self,
        session: AsyncSession,
        package_id: uuid.UUID,
    ) -> ResearchPackage | None:
        row = (await session.execute(text(f"""
            SELECT {PACKAGE_COLUMNS} FROM research_packages
            WHERE package_id = :package_id
        """), {"package_id": package_id})).mappings().one_or_none()
        return ResearchPackage(**row) if row else None

    async def get_package_by_fingerprint(
        self,
        session: AsyncSession,
        fingerprint: str,
    ) -> ResearchPackage | None:
        row = (await session.execute(text(f"""
            SELECT {PACKAGE_COLUMNS} FROM research_packages
            WHERE fingerprint = :fingerprint
        """), {"fingerprint": fingerprint})).mappings().one_or_none()
        return ResearchPackage(**row) if row else None

    async def list_packages(
        self,
        session: AsyncSession,
        *,
        source_id: uuid.UUID | None = None,
        import_state: PackageImportState | None = None,
    ) -> list[ResearchPackage]:
        rows = (await session.execute(text(f"""
            SELECT {PACKAGE_COLUMNS} FROM research_packages
            WHERE (CAST(:source_id AS uuid) IS NULL OR source_id = :source_id)
              AND (CAST(:import_state AS text) IS NULL
                   OR import_state = :import_state)
            ORDER BY received_at DESC, package_id DESC
        """), {
            "source_id": source_id,
            "import_state": import_state,
        })).mappings()
        return [ResearchPackage(**row) for row in rows]

    async def set_package_state(
        self,
        session: AsyncSession,
        package_id: uuid.UUID,
        *,
        from_state: PackageImportState,
        to_state: PackageImportState,
        rejection_code: str | None = None,
        record_count: int | None = None,
        tier_composition: dict[str, int] | None = None,
    ) -> ResearchPackage:
        if (from_state, to_state) not in ALLOWED_PACKAGE_TRANSITIONS:
            raise GovernanceError("package_transition_invalid")
        if to_state == "rejected" and rejection_code is None:
            raise GovernanceError("rejection_code_required")
        row = (await session.execute(text(f"""
            UPDATE research_packages SET
              import_state = :to_state,
              rejection_code = CAST(:rejection_code AS text),
              imported_at = CASE WHEN :to_state = 'imported'
                THEN now() ELSE imported_at END,
              record_count = COALESCE(CAST(:record_count AS integer),
                record_count),
              tier_composition = COALESCE(CAST(:tier_composition AS jsonb),
                tier_composition)
            WHERE package_id = :package_id AND import_state = :from_state
            RETURNING {PACKAGE_COLUMNS}
        """), {
            "package_id": package_id,
            "from_state": from_state,
            "to_state": to_state,
            "rejection_code": rejection_code,
            "record_count": record_count,
            "tier_composition": (
                json.dumps(tier_composition) if tier_composition is not None else None
            ),
        })).mappings().one_or_none()
        if row is None:
            raise GovernanceError("package_state_conflict")
        return ResearchPackage(**row)

    async def insert_record(
        self,
        session: AsyncSession,
        record: ResearchRecord,
    ) -> ResearchRecord:
        """Insert one immutable research record version.

        There is intentionally no update or delete path; the database rejects
        any post-insert mutation.
        """
        await session.execute(text("""
            INSERT INTO research_records (
              research_record_id, package_id, record_key, version_ordinal,
              tier, zone_label, content, searchable_text, evidence_spans,
              corroboration_state, content_sha256, created_at
            ) VALUES (
              :research_record_id, :package_id, :record_key, :version_ordinal,
              :tier, :zone_label, CAST(:content AS jsonb), :searchable_text,
              CAST(:evidence_spans AS jsonb), :corroboration_state,
              :content_sha256, :created_at
            )
        """), {
            **record.model_dump(exclude={"content", "evidence_spans"}),
            "content": json.dumps(record.content),
            "evidence_spans": json.dumps([
                span.model_dump() for span in record.evidence_spans
            ]),
        })
        return record

    async def get_record(
        self,
        session: AsyncSession,
        research_record_id: uuid.UUID,
    ) -> ResearchRecord | None:
        row = (await session.execute(text(f"""
            SELECT {RECORD_COLUMNS} FROM research_records
            WHERE research_record_id = :research_record_id
        """), {"research_record_id": research_record_id})).mappings().one_or_none()
        return ResearchRecord(**row) if row else None

    async def list_records(
        self,
        session: AsyncSession,
        package_id: uuid.UUID,
    ) -> list[ResearchRecord]:
        rows = (await session.execute(text(f"""
            SELECT {RECORD_COLUMNS} FROM research_records
            WHERE package_id = :package_id
            ORDER BY record_key, version_ordinal
        """), {"package_id": package_id})).mappings()
        return [ResearchRecord(**row) for row in rows]

    async def create_or_increment_gap(
        self,
        session: AsyncSession,
        *,
        question_digest: str,
        sanitized_question: str,
        sanitized_summary: str,
        requester_id: uuid.UUID,
        routing_key: str,
        origin: GapOrigin = "honest_null",
        reason_category: GapReasonCategory = "no_evidence",
        classification: Classification = "internal",
        priority: GapPriority = "normal",
        answer_run_id: uuid.UUID | None = None,
    ) -> Gap:
        """Create a gap or increment the open occurrence for the same digest."""
        if not SHA256_PATTERN.fullmatch(question_digest):
            raise GovernanceError("invalid_question_digest")
        if origin == "honest_null" and answer_run_id is None:
            raise GovernanceError("answer_run_required")
        row = (await session.execute(text(f"""
            INSERT INTO gaps (
              gap_id, question_fingerprint, sanitized_question,
              sanitized_summary, reason_category, classification,
              requester_id, routing_key, origin, priority, answer_run_id
            ) VALUES (
              :gap_id, :question_digest, :sanitized_question,
              :sanitized_summary, :reason_category, :classification,
              :requester_id, :routing_key, :origin, :priority,
              CAST(:answer_run_id AS uuid)
            )
            ON CONFLICT (question_fingerprint, requester_id, classification)
            DO UPDATE SET occurrence_count = gaps.occurrence_count + 1,
              last_seen_at = now(),
              answer_run_id = COALESCE(excluded.answer_run_id,
                gaps.answer_run_id),
              reason_category = excluded.reason_category
            RETURNING {GAP_COLUMNS}
        """), {
            "gap_id": uuid.uuid4(),
            "question_digest": question_digest,
            "sanitized_question": sanitized_question,
            "sanitized_summary": sanitized_summary,
            "reason_category": reason_category,
            "classification": classification,
            "requester_id": requester_id,
            "routing_key": routing_key,
            "origin": origin,
            "priority": priority,
            "answer_run_id": answer_run_id,
        })).mappings().one()
        return Gap(**row)

    async def get_gap(
        self,
        session: AsyncSession,
        gap_id: uuid.UUID,
    ) -> Gap | None:
        row = (await session.execute(text(f"""
            SELECT {GAP_COLUMNS} FROM gaps WHERE gap_id = :gap_id
        """), {"gap_id": gap_id})).mappings().one_or_none()
        return Gap(**row) if row else None

    async def list_gaps(
        self,
        session: AsyncSession,
        *,
        state: str | None = None,
        owner_subject_id: uuid.UUID | None = None,
        priority: GapPriority | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> GapPage:
        limit = max(1, min(limit, 200))
        boundary = decode_gap_cursor(cursor) if cursor else None
        rows = (await session.execute(text(f"""
            SELECT {GAP_COLUMNS} FROM gaps
            WHERE (CAST(:state AS text) IS NULL OR lifecycle = :state)
              AND (CAST(:owner AS uuid) IS NULL
                   OR owner_subject_id = :owner)
              AND (CAST(:priority AS text) IS NULL OR priority = :priority)
              AND (CAST(:cursor_at AS timestamptz) IS NULL
                   OR (first_seen_at, gap_id)
                      < (CAST(:cursor_at AS timestamptz),
                         CAST(:cursor_id AS uuid)))
            ORDER BY first_seen_at DESC, gap_id DESC
            LIMIT :limit
        """), {
            "state": state,
            "owner": owner_subject_id,
            "priority": priority,
            "cursor_at": boundary[0] if boundary else None,
            "cursor_id": boundary[1] if boundary else None,
            "limit": limit + 1,
        })).mappings().all()
        items = [Gap(**row) for row in rows[:limit]]
        next_cursor = (
            encode_gap_cursor(items[-1].first_seen_at, items[-1].gap_id)
            if len(rows) > limit
            else None
        )
        return GapPage(items=items, next_cursor=next_cursor)

    async def transition_gap(
        self,
        session: AsyncSession,
        gap_id: uuid.UUID,
        *,
        to_state: GapState,
        actor_subject_id: uuid.UUID,
        reason: str,
        owner_subject_id: uuid.UUID | None = None,
        due_at: datetime | None = None,
        resolving_version_id: uuid.UUID | None = None,
        decline_reason: str | None = None,
    ) -> Gap:
        """Apply one legal gap transition and append its immutable history row."""
        current = (await session.execute(text("""
            SELECT lifecycle, resolving_version_id FROM gaps
            WHERE gap_id = :gap_id FOR UPDATE
        """), {"gap_id": gap_id})).mappings().one_or_none()
        if current is None:
            raise GovernanceError("gap_not_found")
        from_state = str(current["lifecycle"])
        if from_state in {"resolved", "dismissed"}:
            raise GovernanceError("gap_state_unsupported")
        if (from_state, to_state) not in ALLOWED_GAP_TRANSITIONS:
            raise GovernanceError("gap_transition_invalid")
        if to_state == "assigned" and owner_subject_id is None:
            raise GovernanceError("gap_owner_required")
        if to_state == "answered":
            if resolving_version_id is None:
                raise GovernanceError("gap_resolution_record_required")
            lifecycle = await session.scalar(text("""
                SELECT lifecycle FROM record_versions
                WHERE version_id = :version_id
            """), {"version_id": resolving_version_id})
            if lifecycle is None:
                raise GovernanceError("record_version_not_found")
            if lifecycle != "active":
                raise GovernanceError("record_version_not_active")
        if to_state == "published" and current["resolving_version_id"] is None:
            raise GovernanceError("gap_resolution_record_required")
        if to_state == "declined" and decline_reason is None:
            raise GovernanceError("gap_decline_reason_required")
        row = (await session.execute(text(f"""
            UPDATE gaps SET
              lifecycle = :to_state,
              owner_subject_id = COALESCE(CAST(:owner AS uuid),
                owner_subject_id),
              triaged_at = CASE WHEN :to_state = 'triaged'
                THEN now() ELSE triaged_at END,
              assigned_at = CASE WHEN :to_state = 'assigned'
                THEN now() ELSE assigned_at END,
              due_at = COALESCE(CAST(:due_at AS timestamptz), due_at),
              answered_at = CASE WHEN :to_state = 'answered'
                THEN now() ELSE answered_at END,
              closed_at = CASE WHEN :to_state IN ('published','declined')
                THEN now() ELSE closed_at END,
              resolving_version_id = COALESCE(CAST(:version_id AS uuid),
                resolving_version_id),
              decline_reason = CASE WHEN :to_state = 'declined'
                THEN CAST(:decline_reason AS text) ELSE decline_reason END
            WHERE gap_id = :gap_id AND lifecycle = :from_state
            RETURNING {GAP_COLUMNS}
        """), {
            "gap_id": gap_id,
            "from_state": from_state,
            "to_state": to_state,
            "owner": owner_subject_id,
            "due_at": due_at,
            "version_id": resolving_version_id,
            "decline_reason": decline_reason,
        })).mappings().one_or_none()
        if row is None:
            raise GovernanceError("gap_transition_conflict")
        await session.execute(text("""
            INSERT INTO gap_transitions (
              transition_id, gap_id, from_state, to_state, actor_subject_id,
              reason
            ) VALUES (
              :transition_id, :gap_id, :from_state, :to_state, :actor, :reason
            )
        """), {
            "transition_id": uuid.uuid4(),
            "gap_id": gap_id,
            "from_state": from_state,
            "to_state": to_state,
            "actor": actor_subject_id,
            "reason": reason,
        })
        return Gap(**row)

    async def list_gap_transitions(
        self,
        session: AsyncSession,
        gap_id: uuid.UUID,
    ) -> list[GapTransition]:
        rows = (await session.execute(text("""
            SELECT sequence, transition_id, gap_id, from_state, to_state,
              actor_subject_id, reason, occurred_at
            FROM gap_transitions WHERE gap_id = :gap_id
            ORDER BY sequence
        """), {"gap_id": gap_id})).mappings()
        return [GapTransition(**row) for row in rows]

    async def upsert_review_task(
        self,
        session: AsyncSession,
        *,
        queue_kind: QueueKind,
        record_version_id: uuid.UUID,
        assignee_subject_id: uuid.UUID,
        assigned_by: uuid.UUID,
        due_at: datetime | None = None,
        note: str = "",
    ) -> ReviewTask:
        """Assign (or reassign) the queue task for one live record version."""
        row = (await session.execute(text(f"""
            INSERT INTO review_tasks (
              task_id, queue_kind, record_version_id, assignee_subject_id,
              assigned_by, due_at, note
            ) VALUES (
              :task_id, :queue_kind, :record_version_id, :assignee,
              :assigned_by, CAST(:due_at AS timestamptz), :note
            )
            ON CONFLICT (queue_kind, record_version_id) DO UPDATE SET
              assignee_subject_id = excluded.assignee_subject_id,
              assigned_by = excluded.assigned_by,
              due_at = excluded.due_at,
              note = excluded.note,
              state = CASE WHEN review_tasks.state = 'completed'
                THEN 'reopened' ELSE review_tasks.state END,
              completed_at = NULL,
              updated_at = now()
            RETURNING {REVIEW_TASK_COLUMNS}
        """), {
            "task_id": uuid.uuid4(),
            "queue_kind": queue_kind,
            "record_version_id": record_version_id,
            "assignee": assignee_subject_id,
            "assigned_by": assigned_by,
            "due_at": due_at,
            "note": note,
        })).mappings().one()
        return ReviewTask(**row)

    async def complete_review_task(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
    ) -> ReviewTask:
        row = (await session.execute(text(f"""
            UPDATE review_tasks SET state = 'completed', completed_at = now(),
              updated_at = now()
            WHERE task_id = :task_id AND state IN ('assigned','reopened')
            RETURNING {REVIEW_TASK_COLUMNS}
        """), {"task_id": task_id})).mappings().one_or_none()
        if row is None:
            raise GovernanceError("review_task_state_conflict")
        return ReviewTask(**row)

    async def list_review_tasks(
        self,
        session: AsyncSession,
        *,
        queue_kind: QueueKind | None = None,
        assignee_subject_id: uuid.UUID | None = None,
        state: str | None = None,
    ) -> list[ReviewTask]:
        rows = (await session.execute(text(f"""
            SELECT {REVIEW_TASK_COLUMNS} FROM review_tasks
            WHERE (CAST(:queue_kind AS text) IS NULL
                   OR queue_kind = :queue_kind)
              AND (CAST(:assignee AS uuid) IS NULL
                   OR assignee_subject_id = :assignee)
              AND (CAST(:state AS text) IS NULL OR state = :state)
            ORDER BY due_at NULLS LAST, task_id
        """), {
            "queue_kind": queue_kind,
            "assignee": assignee_subject_id,
            "state": state,
        })).mappings()
        return [ReviewTask(**row) for row in rows]

    async def create_proposal(
        self,
        session: AsyncSession,
        *,
        research_record_ids: list[uuid.UUID],
        claim_draft: dict[str, object],
        target_record_key: str,
        proposer_subject_id: uuid.UUID,
        rationale: str,
        supersedes_proposal_id: uuid.UUID | None = None,
    ) -> GraduationProposal:
        """Draft a graduation proposal over imported research record versions."""
        unique_ids = list(dict.fromkeys(research_record_ids))
        if not unique_ids:
            raise GovernanceError("research_records_required")
        graduatable = await session.scalar(text("""
            SELECT count(*) FROM research_records r
            JOIN research_packages p USING (package_id)
            WHERE r.research_record_id = ANY(:ids)
              AND p.import_state = 'imported'
        """), {"ids": unique_ids})
        if int(graduatable or 0) != len(unique_ids):
            raise GovernanceError("research_record_not_graduatable")
        if supersedes_proposal_id is not None:
            exists = await session.scalar(text("""
                SELECT EXISTS(SELECT 1 FROM graduation_proposals
                  WHERE proposal_id = :proposal_id)
            """), {"proposal_id": supersedes_proposal_id})
            if not exists:
                raise GovernanceError("superseded_proposal_not_found")
        row = (await session.execute(text(f"""
            INSERT INTO graduation_proposals (
              proposal_id, research_record_ids, claim_draft,
              target_record_key, proposer_subject_id, rationale,
              supersedes_proposal_id
            ) VALUES (
              :proposal_id, :research_record_ids, CAST(:claim_draft AS jsonb),
              :target_record_key, :proposer, :rationale,
              CAST(:supersedes AS uuid)
            )
            RETURNING {PROPOSAL_COLUMNS}
        """), {
            "proposal_id": uuid.uuid4(),
            "research_record_ids": unique_ids,
            "claim_draft": json.dumps(claim_draft),
            "target_record_key": target_record_key,
            "proposer": proposer_subject_id,
            "rationale": rationale,
            "supersedes": supersedes_proposal_id,
        })).mappings().one()
        return GraduationProposal(**row)

    async def get_proposal(
        self,
        session: AsyncSession,
        proposal_id: uuid.UUID,
    ) -> GraduationProposal | None:
        row = (await session.execute(text(f"""
            SELECT {PROPOSAL_COLUMNS} FROM graduation_proposals
            WHERE proposal_id = :proposal_id
        """), {"proposal_id": proposal_id})).mappings().one_or_none()
        return GraduationProposal(**row) if row else None

    async def list_proposals(
        self,
        session: AsyncSession,
        *,
        state: str | None = None,
    ) -> list[GraduationProposal]:
        rows = (await session.execute(text(f"""
            SELECT {PROPOSAL_COLUMNS} FROM graduation_proposals
            WHERE CAST(:state AS text) IS NULL OR state = :state
            ORDER BY proposed_at DESC, proposal_id DESC
        """), {"state": state})).mappings()
        return [GraduationProposal(**row) for row in rows]

    async def decide_proposal(
        self,
        session: AsyncSession,
        proposal_id: uuid.UUID,
        *,
        decider_subject_id: uuid.UUID,
        decision: ProposalDecision,
        decision_reason: str,
        attestation_hash: str,
    ) -> GraduationProposal:
        """Record one immutable decision; the proposer can never decide."""
        current = (await session.execute(text("""
            SELECT proposer_subject_id, state FROM graduation_proposals
            WHERE proposal_id = :proposal_id FOR UPDATE
        """), {"proposal_id": proposal_id})).mappings().one_or_none()
        if current is None:
            raise GovernanceError("proposal_not_found")
        if current["state"] != "proposed":
            raise GovernanceError("proposal_already_decided")
        if current["proposer_subject_id"] == decider_subject_id:
            raise GovernanceError("proposer_cannot_decide")
        if not SHA256_PATTERN.fullmatch(attestation_hash):
            raise GovernanceError("invalid_attestation_hash")
        row = (await session.execute(text(f"""
            UPDATE graduation_proposals SET
              state = :decision, decided_by = :decider,
              decision_reason = :decision_reason,
              attestation_hash = :attestation_hash, decided_at = now()
            WHERE proposal_id = :proposal_id AND state = 'proposed'
            RETURNING {PROPOSAL_COLUMNS}
        """), {
            "proposal_id": proposal_id,
            "decision": decision,
            "decider": decider_subject_id,
            "decision_reason": decision_reason,
            "attestation_hash": attestation_hash,
        })).mappings().one_or_none()
        if row is None:
            raise GovernanceError("proposal_already_decided")
        return GraduationProposal(**row)

    async def attach_publish_submission(
        self,
        session: AsyncSession,
        proposal_id: uuid.UUID,
        *,
        publish_package_id: uuid.UUID,
    ) -> GraduationProposal:
        """Link the approved proposal to its publish-gate submission, once."""
        row = (await session.execute(text(f"""
            UPDATE graduation_proposals SET
              publish_package_id = :publish_package_id
            WHERE proposal_id = :proposal_id AND state = 'approved'
              AND publish_package_id IS NULL
            RETURNING {PROPOSAL_COLUMNS}
        """), {
            "proposal_id": proposal_id,
            "publish_package_id": publish_package_id,
        })).mappings().one_or_none()
        if row is None:
            raise GovernanceError("proposal_submission_conflict")
        return GraduationProposal(**row)

    async def get_setting(
        self,
        session: AsyncSession,
        setting_key: str,
    ) -> GovernanceSetting | None:
        row = (await session.execute(text(f"""
            SELECT {SETTING_COLUMNS} FROM governance_settings
            WHERE setting_key = :setting_key
            ORDER BY version DESC LIMIT 1
        """), {"setting_key": setting_key})).mappings().one_or_none()
        return GovernanceSetting(**row) if row else None

    async def set_setting(
        self,
        session: AsyncSession,
        *,
        setting_key: str,
        value_type: SettingValueType,
        value: SettingValue,
        updated_by: uuid.UUID,
        reason: str,
    ) -> GovernanceSetting:
        """Append a new immutable version of one typed setting."""
        validate_setting_value(value_type, value)
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"governance_setting:{setting_key}"},
        )
        row = (await session.execute(text(f"""
            INSERT INTO governance_settings (
              setting_id, setting_key, version, value_type, value,
              updated_by, reason
            ) VALUES (
              :setting_id, :setting_key,
              (SELECT COALESCE(MAX(version), 0) + 1 FROM governance_settings
               WHERE setting_key = :setting_key),
              :value_type, CAST(:value AS jsonb), :updated_by, :reason
            )
            RETURNING {SETTING_COLUMNS}
        """), {
            "setting_id": uuid.uuid4(),
            "setting_key": setting_key,
            "value_type": value_type,
            "value": json.dumps(value),
            "updated_by": updated_by,
            "reason": reason,
        })).mappings().one()
        return GovernanceSetting(**row)

    async def list_setting_versions(
        self,
        session: AsyncSession,
        setting_key: str,
    ) -> list[GovernanceSetting]:
        rows = (await session.execute(text(f"""
            SELECT {SETTING_COLUMNS} FROM governance_settings
            WHERE setting_key = :setting_key
            ORDER BY version
        """), {"setting_key": setting_key})).mappings()
        return [GovernanceSetting(**row) for row in rows]
