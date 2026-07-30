import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import fitz  # type: ignore[import-untyped]
from defusedxml import ElementTree  # type: ignore[import-untyped]
from docx import Document
from openpyxl import load_workbook  # type: ignore[import-untyped]
from PIL import Image
from pptx import Presentation
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

from rtr_copilot.config import Settings
from rtr_copilot.ingestion.errors import IngestionFailure
from rtr_copilot.ingestion.sandbox import ProcessSandbox


@dataclass(frozen=True)
class Artifact:
    kind: str
    mime_type: str
    payload: bytes
    origin: Literal["native", "ocr", "transcript", "render"]
    quality_state: Literal["complete", "partial", "low_confidence"]
    quality: dict[str, Any]
    warnings: tuple[str, ...] = ()
    truncated: bool = False

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


class OCRAdapter(Protocol):
    def extract(self, path: Path, *, language: str) -> Artifact | None: ...


class TranscriptAdapter(Protocol):
    def transcribe(self, path: Path, *, duration_ms: int) -> list[Artifact]: ...


class DisabledOCR:
    def extract(self, path: Path, *, language: str) -> Artifact | None:
        return None


class DisabledTranscript:
    def transcribe(self, path: Path, *, duration_ms: int) -> list[Artifact]:
        return []


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _text_pdf(lines: list[str]) -> bytes:
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4, invariant=1, pageCompression=1)
    text = pdf.beginText(40, A4[1] - 40)
    for raw_line in lines or [""]:
        for line in raw_line.splitlines() or [""]:
            text.textLine(line[:160])
            if text.getY() < 40:
                pdf.drawText(text)
                pdf.showPage()
                text = pdf.beginText(40, A4[1] - 40)
    pdf.drawText(text)
    pdf.save()
    return output.getvalue()


def _pdf_thumbnail(payload: bytes) -> bytes:
    document = fitz.open(stream=payload, filetype="pdf")
    try:
        if not document.page_count:
            raise IngestionFailure("malformed_content", stage="render")
        pixmap = document[0].get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False)
        return bytes(pixmap.tobytes("png"))
    finally:
        document.close()


def _image_artifacts(path: Path) -> list[Artifact]:
    with Image.open(path) as source:
        normalized = source.convert("RGB")
        preview_buffer = io.BytesIO()
        normalized.save(preview_buffer, "PNG", optimize=True)
        thumbnail = normalized.copy()
        thumbnail.thumbnail((512, 512))
        thumbnail_buffer = io.BytesIO()
        thumbnail.save(thumbnail_buffer, "PNG", optimize=True)
        quality = {
            "expected_units": 1,
            "extracted_units": 1,
            "native_coverage": 1.0,
            "failed_units": 0,
            "skipped_units": 0,
        }
    return [
        Artifact(
            "safe_image_preview",
            "image/png",
            preview_buffer.getvalue(),
            "render",
            "complete",
            quality,
        ),
        Artifact(
            "thumbnail",
            "image/png",
            thumbnail_buffer.getvalue(),
            "render",
            "complete",
            quality,
        ),
    ]


def _pdf_artifacts(path: Path) -> list[Artifact]:
    source = path.read_bytes()
    reader = PdfReader(io.BytesIO(source), strict=True)
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        media_box = page.mediabox
        pages.append({
            "page": index + 1,
            "origin": "native",
            "text": text,
            "character_count": len(text),
            "reading_order": index,
            "width": float(media_box.width),
            "height": float(media_box.height),
            "coordinate_system": "pdf-points-bottom-left",
        })
    quality = {
        "expected_units": len(pages),
        "extracted_units": len(pages),
        "native_coverage": (
            sum(bool(str(page["text"]).strip()) for page in pages)
            / max(len(pages), 1)
        ),
        "failed_units": 0,
        "skipped_units": 0,
    }
    return [
        Artifact("preview_pdf", "application/pdf", source, "render", "complete", quality),
        Artifact(
            "page_text_json",
            "application/json",
            canonical_json({"schema_version": 1, "pages": pages}),
            "native",
            "complete",
            quality,
        ),
        Artifact(
            "thumbnail",
            "image/png",
            _pdf_thumbnail(source),
            "render",
            "complete",
            quality,
        ),
    ]


def _docx_artifacts(path: Path) -> list[Artifact]:
    document = Document(str(path))
    paragraphs: list[dict[str, Any]] = [
        {
            "paragraph": index,
            "origin": "native",
            "text": paragraph.text,
        }
        for index, paragraph in enumerate(document.paragraphs)
    ]
    tables: list[dict[str, Any]] = [
        {
            "table": table_index,
            "rows": [
                [cell.text for cell in row.cells]
                for row in table.rows
            ],
        }
        for table_index, table in enumerate(document.tables)
    ]
    headers = [
        {
            "section": section_index,
            "paragraph": paragraph_index,
            "origin": "native",
            "text": paragraph.text,
        }
        for section_index, section in enumerate(document.sections)
        for paragraph_index, paragraph in enumerate(section.header.paragraphs)
        if paragraph.text
    ]
    footers = [
        {
            "section": section_index,
            "paragraph": paragraph_index,
            "origin": "native",
            "text": paragraph.text,
        }
        for section_index, section in enumerate(document.sections)
        for paragraph_index, paragraph in enumerate(section.footer.paragraphs)
        if paragraph.text
    ]
    footnotes: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as package:
        if "word/footnotes.xml" in package.namelist():
            root = ElementTree.fromstring(package.read("word/footnotes.xml"))
            for note_index, note in enumerate(root):
                text = "".join(
                    str(node.text or "")
                    for node in note.iter()
                    if node.tag.endswith("}t") or node.tag == "t"
                )
                if text:
                    footnotes.append({
                        "footnote": note_index,
                        "origin": "native",
                        "text": text,
                    })
    lines = [str(item["text"]) for item in paragraphs]
    lines.extend(
        " | ".join(str(cell) for cell in row)
        for table in tables
        for row in list(table["rows"])
    )
    lines.extend(str(item["text"]) for item in headers)
    lines.extend(str(item["text"]) for item in footers)
    lines.extend(str(item["text"]) for item in footnotes)
    pdf = _text_pdf(lines)
    unit_count = (
        len(paragraphs)
        + len(tables)
        + len(headers)
        + len(footers)
        + len(footnotes)
    )
    quality = {
        "expected_units": unit_count,
        "extracted_units": unit_count,
        "native_coverage": 1.0,
        "failed_units": 0,
        "skipped_units": 0,
    }
    return [
        Artifact(
            "structured_text_json",
            "application/json",
            canonical_json({
                "schema_version": 1,
                "paragraphs": paragraphs,
                "tables": tables,
                "headers": headers,
                "footers": footers,
                "footnotes": footnotes,
            }),
            "native",
            "complete",
            quality,
        ),
        Artifact("preview_pdf", "application/pdf", pdf, "render", "complete", quality),
        Artifact(
            "thumbnail",
            "image/png",
            _pdf_thumbnail(pdf),
            "render",
            "complete",
            quality,
        ),
    ]


def _xlsx_artifacts(path: Path, settings: Settings) -> list[Artifact]:
    merged_by_index: list[list[str]] = []
    with zipfile.ZipFile(path) as package:
        worksheet_names = sorted(
            name
            for name in package.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        for name in worksheet_names:
            root = ElementTree.fromstring(package.read(name))
            merged_by_index.append([
                str(node.attrib["ref"])
                for node in root.iter()
                if node.tag.endswith("mergeCell") and "ref" in node.attrib
            ])
    workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    try:
        sheets = []
        total_cells = 0
        truncated = False
        for sheet_index, sheet in enumerate(workbook.worksheets):
            rows = []
            for row_index, row in enumerate(sheet.iter_rows(), start=1):
                values = []
                for cell in row:
                    total_cells += 1
                    if total_cells > settings.ingestion_max_cells:
                        truncated = True
                        break
                    values.append({
                        "cell": cell.coordinate,
                        "value": cell.value,
                        "formula": (
                            str(cell.value) if cell.data_type == "f" else None
                        ),
                    })
                if values:
                    rows.append({"row": row_index, "cells": values})
                if truncated:
                    break
            sheets.append({
                "sheet": sheet.title,
                "rows": rows,
                "merged_ranges": (
                    merged_by_index[sheet_index]
                    if sheet_index < len(merged_by_index)
                    else []
                ),
                "truncated": truncated,
            })
            if truncated:
                break
    finally:
        workbook.close()
    quality = {
        "expected_units": len(workbook.sheetnames),
        "extracted_units": len(sheets),
        "native_coverage": len(sheets) / max(len(workbook.sheetnames), 1),
        "failed_units": 0,
        "skipped_units": max(0, len(workbook.sheetnames) - len(sheets)),
        "cell_count": total_cells,
    }
    state: Literal["complete", "partial", "low_confidence"] = (
        "partial" if truncated else "complete"
    )
    warnings = ("workbook_truncated",) if truncated else ()
    return [
        Artifact(
            "workbook_manifest",
            "application/json",
            canonical_json({
                "schema_version": 1,
                "sheet_names": workbook.sheetnames,
                "sheet_count": len(workbook.sheetnames),
                "truncated": truncated,
            }),
            "native",
            state,
            quality,
            warnings,
            truncated,
        ),
        Artifact(
            "sheet_preview_json",
            "application/json",
            canonical_json({"schema_version": 1, "sheets": sheets}),
            "native",
            state,
            quality,
            warnings,
            truncated,
        ),
    ]


def _pptx_artifacts(path: Path, settings: Settings) -> list[Artifact]:
    presentation = Presentation(str(path))
    if len(presentation.slides) > settings.ingestion_max_slides:
        raise IngestionFailure("archive_budget_exceeded", stage="extract")
    slides = []
    lines = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        shapes = []
        for shape_index, shape in enumerate(slide.shapes):
            text = str(getattr(shape, "text", ""))
            if text:
                lines.append(text)
            shapes.append({
                "slide": slide_index,
                "shape": shape_index,
                "origin": "native",
                "text": text,
                "left": int(shape.left),
                "top": int(shape.top),
                "width": int(shape.width),
                "height": int(shape.height),
                "reading_order": shape_index,
            })
        notes = ""
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text
            if notes:
                lines.append(notes)
        slides.append({"slide": slide_index, "shapes": shapes, "notes": notes})
    pdf = _text_pdf(lines)
    quality = {
        "expected_units": len(slides),
        "extracted_units": len(slides),
        "native_coverage": 1.0,
        "failed_units": 0,
        "skipped_units": 0,
    }
    return [
        Artifact(
            "structured_text_json",
            "application/json",
            canonical_json({"schema_version": 1, "slides": slides}),
            "native",
            "complete",
            quality,
        ),
        Artifact("preview_pdf", "application/pdf", pdf, "render", "complete", quality),
        Artifact(
            "slide_thumbnail",
            "image/png",
            _pdf_thumbnail(pdf),
            "render",
            "complete",
            quality,
        ),
    ]


def _media_artifacts(
    path: Path,
    mime: str,
    duration_ms: int,
    sandbox: ProcessSandbox,
) -> list[Artifact]:
    quality = {
        "expected_units": 1,
        "extracted_units": 1,
        "duration_ms": duration_ms,
        "duration_drift_ms": 0,
        "failed_units": 0,
        "skipped_units": 0,
    }
    if mime.startswith("video/"):
        normalized = path.parent / "normalized.mp4"
        poster = path.parent / "poster.png"
        sandbox.run([
            "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
            "-i", str(path.resolve()), "-map_metadata", "-1", "-c:v", "libx264",
            "-threads:v", "1", "-preset", "veryfast", "-c:a", "aac",
            "-threads:a", "1", "-movflags", "+faststart",
            "-y", str(normalized.resolve()),
        ], temp_root=path.parent)
        sandbox.run([
            "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
            "-i", str(path.resolve()), "-frames:v", "1", "-map_metadata", "-1",
            "-c:v", "png", "-threads:v", "1", "-y", str(poster.resolve()),
        ], temp_root=path.parent)
        return [
            Artifact(
                "browser_video",
                "video/mp4",
                normalized.read_bytes(),
                "render",
                "complete",
                quality,
            ),
            Artifact(
                "poster",
                "image/png",
                poster.read_bytes(),
                "render",
                "complete",
                quality,
            ),
        ]
    normalized_audio = path.parent / "normalized.m4a"
    waveform = path.parent / "waveform.png"
    sandbox.run([
        "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
        "-i", str(path.resolve()), "-map_metadata", "-1", "-vn", "-c:a", "aac",
        "-threads:a", "1", "-y", str(normalized_audio.resolve()),
    ], temp_root=path.parent)
    sandbox.run([
        "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
        "-i", str(path.resolve()), "-filter_complex", "showwavespic=s=1024x256",
        "-frames:v", "1", "-c:v", "png", "-threads:v", "1",
        "-y", str(waveform.resolve()),
    ], temp_root=path.parent)
    return [
        Artifact(
            "browser_audio",
            "audio/mp4",
            normalized_audio.read_bytes(),
            "render",
            "complete",
            quality,
        ),
        Artifact(
            "waveform",
            "image/png",
            waveform.read_bytes(),
            "render",
            "complete",
            quality,
        ),
    ]


def extract_required(
    path: Path,
    *,
    mime: str,
    structural: dict[str, Any],
    settings: Settings,
    sandbox: ProcessSandbox,
) -> list[Artifact]:
    if mime.startswith("image/"):
        return _image_artifacts(path)
    if mime == "application/pdf":
        return _pdf_artifacts(path)
    if mime.endswith("wordprocessingml.document"):
        return _docx_artifacts(path)
    if mime.endswith("spreadsheetml.sheet"):
        return _xlsx_artifacts(path, settings)
    if mime.endswith("presentationml.presentation"):
        return _pptx_artifacts(path, settings)
    return _media_artifacts(
        path,
        mime,
        int(structural["duration_ms"]),
        sandbox,
    )
