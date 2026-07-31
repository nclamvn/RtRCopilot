import io
import json
import re
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import fitz  # type: ignore[import-untyped]
import reportlab  # type: ignore[import-untyped]
from docx import Document
from openpyxl import load_workbook  # type: ignore[import-untyped]
from pptx import Presentation
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

FIXED_TIME = datetime(2000, 1, 1, tzinfo=UTC)
PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_.]{0,127})\}\}")
FORMULA_ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A")
UNICODE_FONT = "RtR-DejaVu"
MIME_BY_FORMAT = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: str(item) if isinstance(item, Decimal) else item,
    ).encode()


def display(value: Any) -> str:
    if isinstance(value, dict | list):
        return canonical_json(value).decode()
    return "" if value is None else str(value)


def replace_text(text: str, values: dict[str, Any]) -> str:
    return PLACEHOLDER.sub(
        lambda match: display(values.get(match.group(1), match.group(0))),
        text,
    )


def normalize_zip(payload: bytes) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(payload))
    output = io.BytesIO()
    with source, zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9,
    ) as target:
        for name in sorted(source.namelist()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            target.writestr(info, source.read(name))
    return output.getvalue()


def zip_text_members(payload: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return [
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if name.endswith((".xml", ".rels"))
        ]


def render_docx(template: bytes, values: dict[str, Any]) -> bytes:
    document = Document(io.BytesIO(template))
    document.core_properties.created = FIXED_TIME
    document.core_properties.modified = FIXED_TIME
    document.core_properties.last_printed = FIXED_TIME
    containers = [document.paragraphs]
    for section in document.sections:
        containers.extend([section.header.paragraphs, section.footer.paragraphs])
    for paragraphs in containers:
        for paragraph in paragraphs:
            original = "".join(run.text for run in paragraph.runs)
            if PLACEHOLDER.search(original):
                replacement = replace_text(original, values)
                if paragraph.runs:
                    paragraph.runs[0].text = replacement
                    for run in paragraph.runs[1:]:
                        run.text = ""
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    original = "".join(run.text for run in paragraph.runs)
                    if PLACEHOLDER.search(original):
                        replacement = replace_text(original, values)
                        if paragraph.runs:
                            paragraph.runs[0].text = replacement
                            for run in paragraph.runs[1:]:
                                run.text = ""
    output = io.BytesIO()
    document.save(output)
    result = normalize_zip(output.getvalue())
    if any(PLACEHOLDER.search(text) for text in zip_text_members(result)):
        raise ValueError("unresolved_placeholder")
    return result


def safe_cell_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def render_xlsx(template: bytes, values: dict[str, Any]) -> bytes:
    workbook = load_workbook(io.BytesIO(template), data_only=False)
    workbook.properties.created = FIXED_TIME.replace(tzinfo=None)
    workbook.properties.modified = FIXED_TIME.replace(tzinfo=None)
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and PLACEHOLDER.search(cell.value):
                    exact = PLACEHOLDER.fullmatch(cell.value)
                    cell.value = safe_cell_value(
                        values.get(exact.group(1)) if exact else replace_text(cell.value, values),
                    )
    output = io.BytesIO()
    workbook.save(output)
    result = normalize_zip(output.getvalue())
    if any(PLACEHOLDER.search(text) for text in zip_text_members(result)):
        raise ValueError("unresolved_placeholder")
    if any(error in text for text in zip_text_members(result) for error in FORMULA_ERRORS):
        raise ValueError("formula_error")
    return result


def render_pptx(template: bytes, values: dict[str, Any]) -> bytes:
    presentation = Presentation(io.BytesIO(template))
    presentation.core_properties.created = FIXED_TIME
    presentation.core_properties.modified = FIXED_TIME
    for slide in presentation.slides:
        for shape in slide.shapes:
            if not hasattr(shape, "text_frame"):
                continue
            for paragraph in shape.text_frame.paragraphs:
                original = "".join(run.text for run in paragraph.runs)
                if PLACEHOLDER.search(original):
                    replacement = replace_text(original, values)
                    width_inches = max(0.1, int(shape.width) / 914_400)
                    height_inches = max(0.1, int(shape.height) / 914_400)
                    approximate_capacity = max(40, int(width_inches * height_inches * 90))
                    if len(replacement) > min(2_000, approximate_capacity):
                        raise ValueError("shape_text_overflow")
                    paragraph.text = replacement
    output = io.BytesIO()
    presentation.save(output)
    result = normalize_zip(output.getvalue())
    if any(PLACEHOLDER.search(text) for text in zip_text_members(result)):
        raise ValueError("unresolved_placeholder")
    return result


def render_pdf(_: bytes, values: dict[str, Any]) -> bytes:
    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not font_path.exists():
        font_path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
    if UNICODE_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(UNICODE_FONT, str(font_path)))
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4, invariant=1, pageCompression=1)
    pdf.setAuthor("Real-time Robotics")
    pdf.setCreator("RtR Document OS")
    pdf.setTitle("Governed document")
    y = 800
    pdf.setFont(UNICODE_FONT, 14)
    pdf.drawString(48, y, "RtR GOVERNED DOCUMENT")
    pdf.setFont(UNICODE_FONT, 10)
    for key in sorted(values):
        y -= 20
        if y < 48:
            pdf.showPage()
            pdf.setFont(UNICODE_FONT, 10)
            y = 800
        line = f"{key}: {display(values[key])}"
        pdf.drawString(48, y, line[:110])
    pdf.save()
    payload = output.getvalue()
    document = fitz.open(stream=payload, filetype="pdf")
    if document.page_count < 1:
        raise ValueError("pdf_invalid")
    document.close()
    return payload


def render(format_name: str, template: bytes, values: dict[str, Any]) -> bytes:
    if format_name == "docx":
        return render_docx(template, values)
    if format_name == "xlsx":
        return render_xlsx(template, values)
    if format_name == "pptx":
        return render_pptx(template, values)
    if format_name == "pdf":
        return render_pdf(template, values)
    raise ValueError("unsupported_format")
