"""Live-computed governance queue views over TIP-006 record metadata.

Queue membership is always recomputed from live SOT metadata at read time;
`review_tasks` rows only record assignment and completion (REQ-034, D-010-05).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from rtr_copilot.governance.models import (
    Classification,
    QueueKind,
    ReviewTask,
    StrictModel,
)

QueueStatus = Literal["expiring", "expired", "due", "overdue", "disputed",
                      "superseded_ambiguous"]


class QueueConflictSide(StrictModel):
    """One side of a disputed or superseded-ambiguous record."""

    version_id: uuid.UUID
    record_id: uuid.UUID
    package_revision: int
    provenance_level: str
    verification_state: str
    content_sha256: str
    evidence_refs: list[str] = Field(default_factory=list)
    effective_from: datetime
    external: bool = False


class QueueEntry(StrictModel):
    queue_kind: QueueKind
    record_id: uuid.UUID
    record_key: str
    record_version_id: uuid.UUID
    owner_subject_id: uuid.UUID
    classification: Classification
    status: QueueStatus
    sort_at: datetime
    effective_to: datetime | None = None
    review_due_at: datetime | None = None
    sides: list[QueueConflictSide] = Field(default_factory=list)
    task: ReviewTask | None = None


class QueueAggregates(StrictModel):
    total: int
    by_status: dict[str, int]
    assigned: int
    unassigned: int


class QueuePage(StrictModel):
    queue_kind: QueueKind
    computed_at: datetime
    entries: list[QueueEntry]
    aggregates: QueueAggregates
    next_cursor: str | None = None


def freshness_status(effective_to: datetime, *, now: datetime) -> QueueStatus:
    """A fact at or past its expiry instant is expired, not merely expiring."""
    return "expired" if effective_to <= now else "expiring"


def review_status(review_due_at: datetime, *, now: datetime) -> QueueStatus:
    return "overdue" if review_due_at <= now else "due"


def conflict_status(active_count: int, superseded_by_other: bool) -> QueueStatus:
    if active_count > 1:
        return "disputed"
    if superseded_by_other:
        return "superseded_ambiguous"
    raise ValueError("not_a_conflict")


def aggregate_entries(entries: list[QueueEntry]) -> QueueAggregates:
    """Aggregates over the caller-visible entries only; hidden rows never count."""
    by_status: dict[str, int] = {}
    assigned = 0
    for entry in entries:
        by_status[entry.status] = by_status.get(entry.status, 0) + 1
        if entry.task is not None and entry.task.state in {"assigned", "reopened"}:
            assigned += 1
    return QueueAggregates(
        total=len(entries),
        by_status=by_status,
        assigned=assigned,
        unassigned=len(entries) - assigned,
    )
