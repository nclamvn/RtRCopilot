"""Execution metadata is distinct from immutable admission-only v1 history."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from rtr_copilot.actions.models import StrictModel

ExecutionState = Literal[
    "queued", "running", "waiting", "paused", "succeeded", "partial", "failed",
    "cancelled", "needs_review",
]
TERMINAL = frozenset({"succeeded", "partial", "failed", "cancelled", "needs_review"})


class ExecutionReceipt(StrictModel):
    receipt_id: uuid.UUID
    run_id: uuid.UUID
    attempt_id: uuid.UUID
    step_key: str
    attempt: int
    input_digest: str
    source_key: str
    charged_tool_calls: int
    build_id: str
    request_correlation_digest: str
    kind: Literal["read_verified", "job_accepted", "artifact_verified", "failed", "needs_review"]
    source_id: uuid.UUID | None
    version_id: uuid.UUID | None
    output_digest: str
    reused_source: bool
    occurred_at: datetime


class ExecutionView(StrictModel):
    run_id: uuid.UUID
    plan_id: uuid.UUID
    state: ExecutionState
    cancel_requested: bool
    cancel_acknowledged: bool
    reason_code: str | None
    workflow_id: str
    executor_version: str
    spent_tool_calls: int
    tool_call_limit: int
    deadline_at: datetime
    epoch: int
    receipts: tuple[ExecutionReceipt, ...] = ()
    execution_available: bool = True


class SubmitExecution(StrictModel):
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExecutionDecision(StrictModel):
    run_id: uuid.UUID
    state: ExecutionState
    terminal: bool


class ExecutionClaim(StrictModel):
    run_id: uuid.UUID
    token: uuid.UUID
    epoch: int


class ExecutionLeaseLost(Exception):
    """An old owner may not perform effects or read a newer owner's result."""
