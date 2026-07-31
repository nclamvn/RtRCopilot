import io
import re
import zipfile
from pathlib import PurePosixPath

import fitz  # type: ignore[import-untyped]
from defusedxml import ElementTree  # type: ignore[import-untyped]

from rtr_copilot.documents.models import TemplateSchema

OOXML_FORMATS = {"docx", "xlsx", "pptx"}
FORBIDDEN_NAMES = (
    "vbaproject.bin", "oleobject", "embeddings/", "activex/", "customui/",
)
REQUIRED_PARTS = {
    "docx": {"[content_types].xml", "word/document.xml"},
    "xlsx": {"[content_types].xml", "xl/workbook.xml"},
    "pptx": {"[content_types].xml", "ppt/presentation.xml"},
}


def validate_schema(schema: TemplateSchema) -> None:
    paths: set[str] = set()
    for binding in schema.bindings:
        if binding.field_path in paths:
            raise ValueError("duplicate_field_path")
        paths.add(binding.field_path)
        if binding.source == "locked_fact":
            if not binding.record_key or not binding.accepted_provenance:
                raise ValueError("locked_fact_contract_required")
        elif binding.record_key is not None:
            raise ValueError("literal_fact_fallback_forbidden")
        if binding.source == "derived":
            if binding.derived_operation is None or not binding.derived_fields:
                raise ValueError("derived_contract_required")
        elif binding.derived_operation is not None or binding.derived_fields:
            raise ValueError("derived_contract_invalid")
        if (
            binding.rules.min_length is not None
            and binding.rules.max_length is not None
            and binding.rules.min_length > binding.rules.max_length
        ):
            raise ValueError("field_bounds_invalid")
        if (
            binding.field_type in {"string", "multiline", "enum"}
            and binding.rules.max_length is None
        ):
            raise ValueError("field_bound_required")
        if binding.field_type == "enum" and not binding.rules.enum:
            raise ValueError("enum_values_required")
        if (
            binding.field_type in {"integer", "decimal"}
            and (
                binding.rules.minimum is None
                or binding.rules.maximum is None
                or binding.rules.minimum > binding.rules.maximum
            )
        ):
            raise ValueError("numeric_bounds_required")
        if binding.field_type == "list" and binding.rules.max_items is None:
            raise ValueError("field_bound_required")
        if binding.field_type == "table" and binding.rules.max_rows is None:
            raise ValueError("field_bound_required")


def validate_template(payload: bytes, format_name: str, *, max_bytes: int = 50_000_000) -> None:
    if not payload or len(payload) > max_bytes:
        raise ValueError("template_size_invalid")
    if format_name == "pdf":
        document = fitz.open(stream=payload, filetype="pdf")
        try:
            if document.page_count < 1 or document.page_count > 500:
                raise ValueError("pdf_page_limit")
        finally:
            document.close()
        return
    if format_name not in OOXML_FORMATS:
        raise ValueError("template_format_invalid")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
        total = 0
        with archive:
            names = {
                member.filename.replace("\\", "/").lower()
                for member in archive.infolist()
            }
            if not REQUIRED_PARTS[format_name].issubset(names):
                raise ValueError("package_part_missing")
            if len(archive.infolist()) > 5_000:
                raise ValueError("archive_member_limit")
            for member in archive.infolist():
                normalized = member.filename.replace("\\", "/").lower()
                path = PurePosixPath(normalized)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("archive_traversal")
                if any(name in normalized for name in FORBIDDEN_NAMES):
                    raise ValueError("executable_package_content")
                total += member.file_size
                if total > max_bytes * 20:
                    raise ValueError("archive_ratio_limit")
                if normalized.endswith((".xml", ".rels")):
                    root = ElementTree.fromstring(archive.read(member))
                    if normalized.endswith(".rels"):
                        for relation in root:
                            target = str(relation.attrib.get("Target", ""))
                            mode = str(relation.attrib.get("TargetMode", ""))
                            if mode.lower() == "external" or re.match(
                                r"^[a-z]+://", target, re.I,
                            ):
                                raise ValueError("external_relationship")
    except (zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise ValueError("malformed_ooxml") from error
