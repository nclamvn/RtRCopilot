"""Source-controlled role-labelled questions for the TIP-024 pilot."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Literal

from pydantic import Field, model_validator

from rtr_copilot.governance.models import StrictModel


class PilotQuestion(StrictModel):
    question_id: str = Field(pattern=r"^P024-Q\d{3}$")
    persona: Literal["staff", "leader", "curator", "admin"]
    scope: Literal["sot", "file", "research", "document"]
    expected: Literal["grounded", "honest_null", "denied", "blocked_caveat"]
    prompt: str = Field(min_length=8, max_length=500)
    rationale: str = Field(min_length=8, max_length=500)


class PilotQuestionSet(StrictModel):
    schema_version: Literal[1] = 1
    campaign: Literal["TIP-024"] = "TIP-024"
    questions: list[PilotQuestion] = Field(min_length=25, max_length=40)

    @model_validator(mode="after")
    def unique_and_complete(self) -> PilotQuestionSet:
        ids = [item.question_id for item in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("pilot_question_id_duplicate")
        if set(item.persona for item in self.questions) != {
            "staff", "leader", "curator", "admin",
        }:
            raise ValueError("pilot_question_persona_incomplete")
        if set(item.scope for item in self.questions) != {
            "sot", "file", "research", "document",
        }:
            raise ValueError("pilot_question_scope_incomplete")
        return self


def load_pilot_questions() -> list[PilotQuestion]:
    """Load and fail closed on drift in the packaged pilot contract."""
    resource = files("rtr_copilot.pilot").joinpath("questions.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    return PilotQuestionSet.model_validate(payload).questions


__all__ = ["PilotQuestion", "PilotQuestionSet", "load_pilot_questions"]
