"""Finite host registry and explicitly bounded JSON Schema subset.

Supported: object/properties/required/closed or typed additionalProperties,
array/items, scalar type unions, enum, string length/pattern/UUID format,
numeric bounds, item/property bounds. Patterns use explicitly anchored
full-match host patterns, not general JSON Schema search semantics.
Everything else is rejected, including
remote refs/composition/executable extensions. This is not full JSON Schema.
"""

import hashlib
import json
import math
import re
import uuid
from typing import Any

from rtr_copilot.actions.models import CapabilitySpec


class ActionError(Exception):
    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def canonical(value: Any) -> bytes:
    def check(item: Any, depth: int = 0) -> None:
        if depth > 12:
            raise ActionError("input_invalid", 422)
        if item is None or type(item) in {str, bool, int}:
            return
        if type(item) is float and math.isfinite(item):
            return
        if isinstance(item, dict) and all(type(key) is str for key in item):
            for child in item.values():
                check(child, depth + 1)
            return
        if isinstance(item, list | tuple):
            for child in item:
                check(child, depth + 1)
            return
        raise ActionError("input_invalid", 422)

    check(value)
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    if len(encoded) > 65_536:
        raise ActionError("input_too_large", 422)
    return encoded


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_schema(schema: dict[str, Any], depth: int = 0) -> None:
    if depth > 6 or type(schema) is not dict:
        raise ActionError("schema_unsupported", 422)
    allowed = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
    }
    if set(schema) - allowed:
        raise ActionError("schema_unsupported", 422)
    types = schema.get("type")
    choices = [types] if isinstance(types, str) else types
    if (
        not isinstance(choices, list)
        or not choices
        or any(
            t not in {"object", "array", "string", "integer", "number", "boolean", "null"}
            for t in choices
        )
    ):
        raise ActionError("schema_unsupported", 422)
    applicable = {"type", "enum"}
    if "object" in choices:
        applicable |= {
            "properties",
            "required",
            "additionalProperties",
            "minProperties",
            "maxProperties",
        }
    if "array" in choices:
        applicable |= {"items", "minItems", "maxItems"}
    if "string" in choices:
        applicable |= {"minLength", "maxLength", "pattern", "format"}
    if "integer" in choices or "number" in choices:
        applicable |= {"minimum", "maximum"}
    if set(schema) - applicable:
        raise ActionError("schema_unsupported", 422)
    if "object" in choices:
        if len(choices) != 1 or "maxProperties" not in schema:
            raise ActionError("schema_unsupported", 422)
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        extra = schema.get("additionalProperties")
        if (
            type(properties) is not dict
            or type(required) is not list
            or any(type(key) is not str or key not in properties for key in required)
            or (extra is not False and not isinstance(extra, dict))
        ):
            raise ActionError("schema_unsupported", 422)
        for child in properties.values():
            validate_schema(child, depth + 1)
        if isinstance(extra, dict):
            validate_schema(extra, depth + 1)
    if "array" in choices:
        if len(choices) != 1 or "maxItems" not in schema or "items" not in schema:
            raise ActionError("schema_unsupported", 422)
        validate_schema(schema["items"], depth + 1)
    if "string" in choices and "maxLength" not in schema:
        raise ActionError("schema_unsupported", 422)
    if ("integer" in choices or "number" in choices) and (
        "minimum" not in schema or "maximum" not in schema
    ):
        raise ActionError("schema_unsupported", 422)
    for key in ("minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"):
        if key in schema and (type(schema[key]) is not int or not 0 <= schema[key] <= 4_096):
            raise ActionError("schema_unsupported", 422)
    for key in ("minimum", "maximum"):
        if key in schema and (
            type(schema[key]) not in {int, float} or not math.isfinite(schema[key])
        ):
            raise ActionError("schema_unsupported", 422)
    for minimum, maximum in (
        ("minLength", "maxLength"),
        ("minItems", "maxItems"),
        ("minProperties", "maxProperties"),
        ("minimum", "maximum"),
    ):
        if minimum in schema and maximum in schema and schema[minimum] > schema[maximum]:
            raise ActionError("schema_unsupported", 422)
    if "format" in schema and schema["format"] != "uuid":
        raise ActionError("schema_unsupported", 422)
    if "pattern" in schema:
        # Patterns are host-admitted constants, not arbitrary model/client regex.
        if (
            type(schema["pattern"]) is not str
            or len(schema["pattern"]) > 128
            or not schema["pattern"].startswith("^")
            or not schema["pattern"].endswith("$")
        ):
            raise ActionError("schema_unsupported", 422)
        try:
            re.compile(schema["pattern"])
        except re.error as error:
            raise ActionError("schema_unsupported", 422) from error
    if "enum" in schema and (
        type(schema["enum"]) is not list or not schema["enum"] or len(schema["enum"]) > 100
    ):
        raise ActionError("schema_unsupported", 422)
    canonical(schema)


def validate_input(value: Any, schema: dict[str, Any]) -> None:
    canonical(value)
    types = schema["type"]
    allowed = {types} if isinstance(types, str) else set(types)
    kind = (
        "null"
        if value is None
        else "boolean"
        if type(value) is bool
        else "integer"
        if type(value) is int
        else "number"
        if type(value) is float
        else "string"
        if type(value) is str
        else "object"
        if type(value) is dict
        else "array"
        if type(value) is list
        else "unsupported"
    )
    if kind not in allowed and not (kind == "integer" and "number" in allowed):
        raise ActionError("arguments_invalid", 422)
    if "enum" in schema and not any(type(value) is type(v) and value == v for v in schema["enum"]):
        raise ActionError("arguments_invalid", 422)
    if kind == "object":
        if not schema.get("minProperties", 0) <= len(value) <= schema["maxProperties"]:
            raise ActionError("arguments_invalid", 422)
        if not set(schema.get("required", [])) <= set(value):
            raise ActionError("arguments_invalid", 422)
        for key, item in value.items():
            child = schema.get("properties", {}).get(key, schema["additionalProperties"])
            if child is False:
                raise ActionError("arguments_invalid", 422)
            validate_input(item, child)
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema["maxItems"]:
            raise ActionError("arguments_invalid", 422)
        for item in value:
            validate_input(item, schema["items"])
    elif kind == "string":
        if not schema.get("minLength", 0) <= len(value) <= schema["maxLength"]:
            raise ActionError("arguments_invalid", 422)
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ActionError("arguments_invalid", 422)
        if schema.get("format") == "uuid":
            try:
                uuid.UUID(value)
            except ValueError as error:
                raise ActionError("arguments_invalid", 422) from error
    elif kind in {"integer", "number"} and not schema["minimum"] <= value <= schema["maximum"]:
        raise ActionError("arguments_invalid", 422)


READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "maxProperties": 1,
    "additionalProperties": False,
    "required": ["record_key"],
    "properties": {"record_key": {"type": "string", "minLength": 1, "maxLength": 256}},
}
DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "maxProperties": 2,
    "additionalProperties": False,
    "required": ["template_version_id", "parameters"],
    "properties": {
        "template_version_id": {"type": "string", "format": "uuid", "maxLength": 36},
        "parameters": {
            "type": "object",
            "maxProperties": 200,
            "properties": {},
            "additionalProperties": {
                "type": ["string", "number", "boolean", "null"],
                "maxLength": 2_000,
                "minimum": -1_000_000_000,
                "maximum": 1_000_000_000,
            },
        },
    },
}
CONTRACT_OUTPUT: dict[str, Any] = {
    "type": "object",
    "maxProperties": 1,
    "additionalProperties": False,
    "required": ["execution_available"],
    "properties": {"execution_available": {"type": "boolean", "enum": [False]}},
}

HOST_CONTRACTS = (
    CapabilitySpec(
        capability_id="sot.read",
        version="1",
        effect_class="R0",
        policy_action="view",
        implementation_ref="sot.read",
        input_schema=READ_SCHEMA,
        output_schema=CONTRACT_OUTPUT,
        allowed_destinations=("response",),
        reconciliation="read_only",
        compensation="not_applicable",
    ),
    CapabilitySpec(
        capability_id="documents.create_draft",
        version="1",
        effect_class="R1",
        policy_action="render",
        implementation_ref="documents.create_draft",
        input_schema=DRAFT_SCHEMA,
        output_schema=CONTRACT_OUTPUT,
        allowed_destinations=("internal_files",),
        reconciliation="canonical_job",
        compensation="cancel_remaining",
    ),
)

# New immutable protocol versions; the v1 admission-only digests are untouched.
EXECUTION_OUTPUT: dict[str, Any] = {
    "type": "object", "maxProperties": 2, "additionalProperties": False,
    "required": ["outcome", "output_digest"],
    "properties": {
        "outcome": {"type": "string", "maxLength": 32,
                    "enum": ["read_verified", "job_accepted", "artifact_verified"]},
        "output_digest": {"type": "string", "maxLength": 64,
                          "pattern": "^[0-9a-f]{64}$"},
    },
}
EXECUTION_CONTRACTS = tuple(
    spec.model_copy(update={"version": "2", "output_schema": EXECUTION_OUTPUT,
                            "max_attempts": 2, "execution_available": True})
    for spec in HOST_CONTRACTS
)


class HostRegistry:
    def __init__(self, specs: tuple[CapabilitySpec, ...] | None = None) -> None:
        self._contracts: dict[tuple[str, str], bytes] = {}
        for spec in HOST_CONTRACTS + EXECUTION_CONTRACTS if specs is None else specs:
            validate_schema(spec.input_schema)
            validate_schema(spec.output_schema)
            key = (spec.capability_id, spec.version)
            if key in self._contracts:
                raise ActionError("capability_conflict")
            # Store bytes, not shallow-frozen dicts that callers can mutate.
            self._contracts[key] = canonical(spec.model_dump(mode="json"))

    def contract(self, capability_id: str, version: str) -> CapabilitySpec:
        payload = self._contracts.get((capability_id, version))
        if payload is None:
            raise ActionError("capability_unavailable", 404)
        return CapabilitySpec.model_validate_json(payload)

    def all(self) -> tuple[CapabilitySpec, ...]:
        return tuple(
            CapabilitySpec.model_validate_json(payload)
            for _, payload in sorted(self._contracts.items())
        )


def hashes(spec: CapabilitySpec) -> tuple[str, str]:
    return digest(spec.model_dump(mode="json")), digest(
        {
            "input": spec.input_schema,
            "output": spec.output_schema,
        }
    )
