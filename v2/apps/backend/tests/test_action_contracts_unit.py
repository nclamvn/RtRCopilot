import math
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from rtr_copilot.actions.models import BudgetRequest, PlanRequest, StepRequest
from rtr_copilot.actions.registry import (
    ActionError,
    HostRegistry,
    canonical,
    digest,
    validate_input,
    validate_schema,
)
from rtr_copilot.actions.service import validate_graph


def test_canonical_keys_and_registry_authority_are_stable() -> None:
    assert digest({"b": [2, 1], "a": 1}) == digest({"a": 1, "b": [2, 1]})
    registry = HostRegistry()
    returned = registry.contract("sot.read", "1")
    returned.input_schema["properties"].clear()
    assert registry.contract("sot.read", "1").input_schema["properties"]
    with pytest.raises(ActionError, match="capability_unavailable"):
        registry.contract("model.exec_sql", "1")


@pytest.mark.parametrize(
    "value",
    [math.nan, math.inf, -math.inf, b"secret", {1: "value"}, {"x"}, datetime.now(UTC), object()],
)
def test_non_json_and_non_finite_values_are_rejected(value: object) -> None:
    with pytest.raises(ActionError, match="input_invalid"):
        canonical(value)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "additionalProperties": True, "maxProperties": 1},
        {"type": "string", "maxLength": 30, "$ref": "https://unapproved/schema"},
        {"type": "integer", "minimum": 0, "maximum": 10, "pattern": "^x$"},
        {"type": "array", "items": {"type": "boolean"}, "maxItems": 3, "maxLength": 10},
        {"type": "string", "maxLength": 10, "pattern": "unanchored"},
        {"type": "string", "maxLength": 10, "format": "uri"},
        {"type": "string", "maxLength": 10, "minLength": 11},
        {"type": "integer", "minimum": 0, "maximum": math.inf},
        {"type": "object", "maxProperties": 3, "additionalProperties": False, "required": ["x"]},
        {"type": "number"},
    ],
)
def test_unsupported_schema_constraints_fail_closed(schema: dict[str, object]) -> None:
    with pytest.raises(ActionError, match="schema_unsupported"):
        validate_schema(schema)


@pytest.mark.parametrize("value", [True, "1", 11, -1])
def test_integer_subset_does_not_coerce_bool_string_or_out_of_bounds(value: object) -> None:
    with pytest.raises(ActionError, match="arguments_invalid"):
        validate_input(value, {"type": "integer", "minimum": 0, "maximum": 10})


@pytest.mark.parametrize("dependencies", [("unknown",), ("a",), ("b", "b")])
def test_unknown_self_and_duplicate_dependencies_fail(dependencies: tuple[str, ...]) -> None:
    request = PlanRequest(
        idempotency_key="graph-key",
        objective="read",
        steps=(
            StepRequest(
                step_key="a",
                capability_id="sot.read",
                arguments={"record_key": "A"},
                dependencies=dependencies,
            ),
            StepRequest(step_key="b", capability_id="sot.read", arguments={"record_key": "B"}),
        ),
    )
    with pytest.raises(ActionError, match="dependencies_invalid"):
        validate_graph(request)


def test_cycle_is_not_an_ordering_hint() -> None:
    request = PlanRequest(
        idempotency_key="graph-key",
        objective="read",
        steps=(
            StepRequest(
                step_key="a",
                capability_id="sot.read",
                arguments={"record_key": "A"},
                dependencies=("b",),
            ),
            StepRequest(
                step_key="b",
                capability_id="sot.read",
                arguments={"record_key": "B"},
                dependencies=("a",),
            ),
        ),
    )
    with pytest.raises(ActionError, match="dependencies_invalid"):
        validate_graph(request)


def test_http_boundary_accepts_json_arrays_and_uuid_but_no_authority_fields() -> None:
    actor = str(uuid.uuid4())
    request = {
        "idempotency_key": "http-boundary",
        "objective": "read",
        "workspace_id": actor,
        "reviewers": [actor],
        "steps": [
            {
                "step_key": "read",
                "capability_id": "sot.read",
                "arguments": {"record_key": "A"},
                "dependencies": [],
            }
        ],
    }
    parsed = PlanRequest.model_validate(request)
    assert str(parsed.workspace_id) == actor
    assert str(parsed.reviewers[0]) == actor
    with pytest.raises(ValidationError):
        PlanRequest.model_validate({**request, "actor_id": actor})
    with pytest.raises(ValidationError):
        PlanRequest.model_validate({**request, "effect_class": "R0"})
    with pytest.raises(ValidationError):
        BudgetRequest(tool_calls=True)
