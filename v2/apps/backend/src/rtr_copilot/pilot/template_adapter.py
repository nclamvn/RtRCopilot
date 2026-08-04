"""Read-only adapter from the canonical RtR template registry to Document OS."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from openpyxl import load_workbook  # type: ignore[import-untyped]
from pydantic import Field

from rtr_copilot.documents.models import (
    BindingDefinition,
    FieldRules,
    TemplateImport,
    TemplateSchema,
)
from rtr_copilot.documents.renderers import canonical_json
from rtr_copilot.documents.validation import validate_schema, validate_template
from rtr_copilot.governance.models import StrictModel

EXPECTED_TEMPLATE_IDS = {"congvan", "salesbrief", "factsheet", "slidecard"}
RECORD_REMAP = {
    "CAND.1.005": "SPEC.HERA.PAYLOAD.MAX",
    "CAND.1.006": "SPEC.HERA.FLIGHT.NO_PAYLOAD",
}
LOCKED_FORMATS: dict[str, tuple[Literal["template", "literal"], str]] = {
    "SPEC.HERA.PAYLOAD.MAX": ("template", "{value} {unit}"),
    "SPEC.HERA.FLIGHT.NO_PAYLOAD": ("template", "{value} minutes"),
    "L3R.K.007": ("literal", "15 km"),
    "L3F.1.037": ("literal", "IP54"),
    "L3F.ENT.001": ("literal", "REAL-TIME ROBOTICS VIỆT NAM"),
    "L3F.RES.002": ("literal", "Lương Việt Quốc"),
}
FIXED_TIME = datetime(2026, 8, 4, tzinfo=UTC)
CORE_TIME = re.compile(
    rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)",
)


class RegistryField(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")
    label: str = ""
    kind: Literal["user", "locked", "derived"] = Field(alias="type")
    required: bool = False
    multiline: bool = False
    format: str | None = None
    cell: str | None = None
    record: str | None = None
    extract: str | None = None
    value: str | None = None
    source_field: str | None = Field(default=None, alias="from")
    part: Literal["day", "month", "year"] | None = None
    hint: str | None = None
    default: str | None = None
    note: str | None = None


class RegistryTemplate(StrictModel):
    id: str
    name: str
    desc: str
    file: str
    kind: Literal["docx", "xlsx"]
    category: str
    version: str
    sheet: str | None = None
    fields: list[RegistryField]


class Registry(StrictModel):
    schema_version: str
    last_updated: str
    templates: list[RegistryTemplate]


class AdaptedTemplate(StrictModel):
    template_id: str
    source_path: str
    source_sha256: str
    adapted_sha256: str
    fingerprint: str
    payload: TemplateImport


class TemplateAdapterResult(StrictModel):
    registry_sha256: str
    templates: list[AdaptedTemplate]


def _load_registry(path: Path) -> Registry:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover - runtime dependency probe
        raise RuntimeError("yaml_dependency_unavailable") from error
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    registry = Registry.model_validate(payload)
    ids = {item.id for item in registry.templates}
    if ids != EXPECTED_TEMPLATE_IDS or len(registry.templates) != 4:
        raise ValueError("pilot_template_registry_incomplete")
    return registry


def _field_rules(field: RegistryField, field_type: str) -> FieldRules:
    if field_type in {"string", "multiline"}:
        return FieldRules(max_length=10_000 if field.multiline else 500)
    if field_type == "integer":
        maximum = {"day": 31, "month": 12, "year": 9999}[str(field.part)]
        return FieldRules(minimum=Decimal(1), maximum=Decimal(maximum))
    return FieldRules()


def _binding(field: RegistryField) -> BindingDefinition:
    if field.kind == "user":
        field_type = "date" if field.format == "date" else (
            "multiline" if field.multiline else "string"
        )
        return BindingDefinition(
            field_path=field.key,
            field_type=field_type,  # type: ignore[arg-type]
            source="user",
            required=field.required,
            rules=_field_rules(field, field_type),
        )
    if field.kind == "derived":
        if field.source_field is None or field.part is None:
            raise ValueError("pilot_template_derived_invalid")
        return BindingDefinition(
            field_path=field.key,
            field_type="integer",
            source="derived",
            required=field.required,
            rules=_field_rules(field, "integer"),
            derived_operation=f"date_{field.part}",  # type: ignore[arg-type]
            derived_fields=[field.source_field],
        )
    if field.record is None:
        raise ValueError("pilot_template_locked_record_missing")
    record_key = RECORD_REMAP.get(field.record, field.record)
    format_spec = LOCKED_FORMATS.get(record_key)
    if format_spec is None:
        raise ValueError("pilot_template_locked_format_unknown")
    format_kind, format_value = format_spec
    return BindingDefinition(
        field_path=field.key,
        field_type="string",
        source="locked_fact",
        required=True,
        rules=FieldRules(max_length=1_000),
        record_key=record_key,
        accepted_provenance=[
            "verified_primary", "verified_secondary", "approved_internal",
        ],
        require_fresh=True,
        value_template=format_value if format_kind == "template" else None,
        value_literal=format_value if format_kind == "literal" else None,
    )


def _canonical_zip(payload: bytes) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(payload))
    output = io.BytesIO()
    with source, zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9,
    ) as target:
        for member in sorted(source.infolist(), key=lambda item: item.filename):
            info = zipfile.ZipInfo(member.filename, (2026, 8, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = member.external_attr
            info.create_system = member.create_system
            content = source.read(member.filename)
            if member.filename == "docProps/core.xml":
                content = CORE_TIME.sub(
                    rb"\g<1>2026-08-04T00:00:00Z\g<2>", content,
                )
            target.writestr(info, content)
    return output.getvalue()


def _adapt_xlsx(source: bytes, template: RegistryTemplate) -> bytes:
    workbook = load_workbook(io.BytesIO(source))
    try:
        if template.sheet is None or template.sheet not in workbook.sheetnames:
            raise ValueError("pilot_template_sheet_missing")
        sheet = workbook[template.sheet]
        for field in template.fields:
            if field.cell is None:
                raise ValueError("pilot_template_cell_missing")
            sheet[field.cell] = "{{" + field.key + "}}"
        workbook.properties.created = FIXED_TIME.replace(tzinfo=None)
        workbook.properties.modified = FIXED_TIME.replace(tzinfo=None)
        output = io.BytesIO()
        workbook.save(output)
    finally:
        workbook.close()
    return _canonical_zip(output.getvalue())


def adapt_templates(template_root: Path) -> TemplateAdapterResult:
    """Build four deterministic imports without mutating canonical sources."""
    root = template_root.resolve(strict=True)
    registry_path = (root / "registry.yaml").resolve(strict=True)
    if registry_path.parent != root:
        raise ValueError("pilot_template_path_escape")
    registry_bytes = registry_path.read_bytes()
    registry = _load_registry(registry_path)
    adapted: list[AdaptedTemplate] = []
    for item in sorted(registry.templates, key=lambda entry: entry.id):
        source_path = (root / item.file).resolve(strict=True)
        if source_path.parent != root or source_path.is_symlink():
            raise ValueError("pilot_template_path_escape")
        source = source_path.read_bytes()
        schema = TemplateSchema(bindings=[_binding(field) for field in item.fields])
        validate_schema(schema)
        binary = _adapt_xlsx(source, item) if item.kind == "xlsx" else source
        validate_template(binary, item.kind)
        source_sha = hashlib.sha256(source).hexdigest()
        adapted_sha = hashlib.sha256(binary).hexdigest()
        fingerprint = hashlib.sha256(canonical_json({
            "template_id": item.id,
            "source_sha256": source_sha,
            "adapted_sha256": adapted_sha,
            "schema": schema.model_dump(mode="json"),
        })).hexdigest()
        adapted.append(AdaptedTemplate(
            template_id=item.id,
            source_path=item.file,
            source_sha256=source_sha,
            adapted_sha256=adapted_sha,
            fingerprint=fingerprint,
            payload=TemplateImport(
                stable_key=f"pilot.{item.id}",
                display_name=item.name,
                description=f"TIP-024 local pilot · {item.desc}",
                category=item.category,
                classification="internal",
                document_class="internal",
                format=item.kind,
                schema=schema,
                source_base64=base64.b64encode(binary).decode("ascii"),
            ),
        ))
    return TemplateAdapterResult(
        registry_sha256=hashlib.sha256(registry_bytes).hexdigest(),
        templates=adapted,
    )


def write_template_staging(result: TemplateAdapterResult, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for item in result.templates:
        path = output / f"{item.template_id}.json"
        path.write_text(
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False, indent=2,
                       sort_keys=True) + "\n",
            encoding="utf-8",
        )
    ledger = result.model_dump(mode="json", exclude={"templates": {"__all__": {"payload"}}})
    (output / "ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "AdaptedTemplate", "TemplateAdapterResult", "adapt_templates",
    "write_template_staging",
]
