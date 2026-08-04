import io
import uuid
import zipfile
from copy import copy
from datetime import date
from decimal import Decimal

import fitz
import pytest
from docx import Document
from openpyxl import Workbook, load_workbook
from pptx import Presentation
from pptx.util import Inches
from pydantic import ValidationError
from reportlab.pdfgen import canvas

from rtr_copilot.documents.models import (
    BindingDefinition,
    FieldRules,
    TemplateSchema,
)
from rtr_copilot.documents.renderers import render
from rtr_copilot.documents.service import (
    changed_keys,
    decode_cursor,
    encode_cursor,
    locked_fact_value,
    manifest_views,
)
from rtr_copilot.documents.validation import validate_schema, validate_template


def docx_template() -> bytes:
    document = Document()
    paragraph = document.add_paragraph()
    first = paragraph.add_run("Tên: {{cus")
    first.bold = True
    paragraph.add_run("tomer_name}}")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "{{report_date}}"
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def xlsx_template() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "{{customer_name}}"
    sheet["B1"] = "=1+1"
    font = copy(sheet["A1"].font)
    font.bold = True
    sheet["A1"].font = font
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def pptx_template() -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(2))
    box.text_frame.paragraphs[0].add_run().text = "Khách hàng: {{customer_name}}"
    output = io.BytesIO()
    presentation.save(output)
    return output.getvalue()


def pdf_template() -> bytes:
    output = io.BytesIO()
    page = canvas.Canvas(output, invariant=1)
    page.drawString(20, 800, "template")
    page.save()
    return output.getvalue()


@pytest.mark.parametrize(
    ("format_name", "factory"),
    [
        ("docx", docx_template),
        ("xlsx", xlsx_template),
        ("pptx", pptx_template),
        ("pdf", pdf_template),
    ],
)
def test_four_formats_are_structurally_valid_and_byte_deterministic(
    format_name: str,
    factory: object,
) -> None:
    template = factory()  # type: ignore[operator]
    validate_template(template, format_name)
    values = {"customer_name": "Công ty Cổ phần RtR", "report_date": date(2026, 7, 31)}
    first = render(format_name, template, values)
    second = render(format_name, template, values)
    assert first == second
    validate_template(first, format_name)


def test_docx_preserves_style_and_replaces_split_and_table_placeholders() -> None:
    output = render("docx", docx_template(), {
        "customer_name": "Công ty RtR",
        "report_date": "31/07/2026",
    })
    document = Document(io.BytesIO(output))
    assert document.paragraphs[0].text == "Tên: Công ty RtR"
    assert document.paragraphs[0].runs[0].bold is True
    assert document.tables[0].cell(0, 0).text == "31/07/2026"


def test_xlsx_preserves_formula_style_and_neutralizes_formula_injection() -> None:
    output = render("xlsx", xlsx_template(), {"customer_name": "=HYPERLINK(\"x\")"})
    workbook = load_workbook(io.BytesIO(output), data_only=False)
    sheet = workbook.active
    assert sheet["A1"].value == "'=HYPERLINK(\"x\")"
    assert sheet["A1"].font.bold is True
    assert sheet["B1"].value == "=1+1"


def test_pptx_preserves_relationships_and_replaces_text() -> None:
    output = render("pptx", pptx_template(), {"customer_name": "Công ty RtR"})
    presentation = Presentation(io.BytesIO(output))
    assert presentation.slides[0].shapes[0].text == "Khách hàng: Công ty RtR"
    assert len(presentation.slide_masters) >= 1


def test_pdf_has_stable_metadata_and_extractable_vietnamese() -> None:
    output = render("pdf", pdf_template(), {"customer_name": "Công ty RtR Việt Nam"})
    document = fitz.open(stream=output, filetype="pdf")
    assert "Công ty RtR Việt Nam" in "".join(page.get_text() for page in document)
    assert document.metadata["author"] == "Real-time Robotics"
    document.close()


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("../escape.xml", b"<x/>", "archive_traversal"),
        ("word/vbaProject.bin", b"x", "executable_package_content"),
    ],
)
def test_ooxml_validator_rejects_active_and_traversal_content(
    name: str,
    content: bytes,
    expected: str,
) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr(name, content)
    with pytest.raises(ValueError, match=expected):
        validate_template(output.getvalue(), "docx")


def test_ooxml_validator_rejects_external_relationship() -> None:
    output = io.BytesIO()
    relationships = (
        '<Relationships><Relationship Target="https://example.invalid" '
        'TargetMode="External"/></Relationships>'
    )
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("word/_rels/document.xml.rels", relationships)
    with pytest.raises(ValueError, match="external_relationship"):
        validate_template(output.getvalue(), "docx")


def test_schema_rejects_literal_fact_fallback_and_undeclared_derived_logic() -> None:
    fact = BindingDefinition(
        field_path="company.name", field_type="string", source="user",
        record_key="company.name", rules=FieldRules(max_length=100),
    )
    with pytest.raises(ValueError, match="literal_fact_fallback_forbidden"):
        validate_schema(TemplateSchema(bindings=[fact]))
    derived = BindingDefinition(
        field_path="year", field_type="integer", source="derived",
    )
    with pytest.raises(ValueError, match="derived_contract_required"):
        validate_schema(TemplateSchema(bindings=[derived]))


def test_locked_fact_format_is_bounded_and_literal_drift_fails_closed() -> None:
    templated = BindingDefinition(
        field_path="payload", field_type="string", source="locked_fact",
        record_key="SPEC.HERA.PAYLOAD.MAX",
        accepted_provenance=["verified_primary"],
        value_template="{value} {unit}", rules=FieldRules(max_length=100),
    )
    assert locked_fact_value(templated, {"value": 15, "unit": "kg"}) == "15 kg"
    literal = templated.model_copy(update={
        "value_template": None, "value_literal": "IP54",
    })
    assert locked_fact_value(literal, {"statement": "IP54 certified"}) == "IP54"
    with pytest.raises(ValueError, match="fact_literal_drift"):
        locked_fact_value(literal, {"statement": "IP55 certified"})
    with pytest.raises(ValueError, match="locked_fact_format_ambiguous"):
        validate_schema(TemplateSchema(bindings=[templated.model_copy(update={
            "value_literal": "15 kg",
        })]))


def test_date_day_month_year_derivations_are_declared() -> None:
    for operation in ("date_day", "date_month", "date_year"):
        validate_schema(TemplateSchema(bindings=[BindingDefinition(
            field_path=operation, field_type="integer", source="derived",
            derived_operation=operation, derived_fields=["signed_at"],
            rules=FieldRules(minimum=Decimal(1), maximum=Decimal(9999)),
        )]))


def test_schema_is_strict_and_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        BindingDefinition.model_validate({
            "field_path": "name", "field_type": "string", "source": "user",
            "executable": "now()",
        })
    schema = TemplateSchema(bindings=[BindingDefinition(
        field_path="name", field_type="string", source="user",
        rules=FieldRules(min_length=8, max_length=2),
    )])
    with pytest.raises(ValueError, match="field_bounds_invalid"):
        validate_schema(schema)


def test_template_cursor_is_stable_signed_and_tamper_evident() -> None:
    template_id = uuid.uuid4()
    cursor = encode_cursor("báo cáo", template_id, "test-secret")
    assert decode_cursor(cursor, "test-secret") == ("báo cáo", template_id)
    with pytest.raises(ValueError, match="invalid_cursor"):
        decode_cursor(cursor[:-2] + "AA", "test-secret")


def test_unresolved_placeholders_and_pptx_overflow_fail_closed() -> None:
    with pytest.raises(ValueError, match="unresolved_placeholder"):
        render("docx", docx_template(), {"customer_name": "RtR"})
    with pytest.raises(ValueError, match="shape_text_overflow"):
        render("pptx", pptx_template(), {"customer_name": "x" * 2_000})


def test_generated_history_comparison_separates_parameters_and_locked_snapshots() -> None:
    first_parameters, first_locked = manifest_views({"fields": [
        {"field_path": "name", "source": "user", "canonical_value": "A"},
        {
            "field_path": "company", "source": "locked_fact",
            "canonical_value": "RtR", "record_version_id": "v1",
            "record_checksum": "a", "evidence_checksum": "b",
        },
    ]})
    second_parameters, second_locked = manifest_views({"fields": [
        {"field_path": "name", "source": "user", "canonical_value": "B"},
        {
            "field_path": "company", "source": "locked_fact",
            "canonical_value": "RtR", "record_version_id": "v2",
            "record_checksum": "c", "evidence_checksum": "d",
        },
    ]})
    assert changed_keys(first_parameters, second_parameters) == ["name"]
    assert changed_keys(first_locked, second_locked) == ["company"]
