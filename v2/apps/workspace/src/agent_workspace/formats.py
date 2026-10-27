"""Bounded, offline source extraction and honest subset exports.

Canonical document = Markdown; canonical table = rectangular UTF-8 CSV.
No model, renderer, hyperlink resolver, formula evaluator or host shell is used.
Binary operations run in disposable spawned processes with wall/CPU limits.
"""
from __future__ import annotations

import csv
import io
import multiprocessing
import re
import socket
import sys
import time
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from xml.sax.saxutils import escape

MAX_RAW_BYTES = 256_000
MAX_TEXT_BYTES = 1_000_000
MAX_ROWS, MAX_COLS, MAX_CELLS = 2000, 40, 20_000
MAX_PAGES = 100
WORKER_SECONDS = 15
_WORKERS = threading.BoundedSemaphore(2)
MIMES = {"txt": "text/plain", "md": "text/markdown", "csv": "text/csv",
         "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "pdf": "application/pdf"}


class FormatError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass
class Extraction:
    text: str
    media_type: str
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Export:
    data: bytes
    media_type: str
    extension: str
    warnings: list[str] = field(default_factory=list)


def _text(value: str) -> str:
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise FormatError("invalid_text", "Invalid Unicode text.") from exc
    if size > MAX_TEXT_BYTES:
        raise FormatError("extracted_text_limit", "Text exceeds the 1 MB extraction/export limit.")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise FormatError("invalid_text", "Control characters are not supported.")
    return value


def _csv_rows(content: str) -> list[list[str]]:
    _text(content)
    try:
        rows = list(csv.reader(io.StringIO(content, newline=""), strict=True))
    except (csv.Error, OverflowError) as exc:
        raise FormatError("invalid_csv", "CSV quoting or field size is invalid.") from exc
    if not rows or not rows[0] or not any(rows[0]):
        raise FormatError("invalid_csv", "CSV requires a non-empty header row.")
    width = len(rows[0])
    if len(rows) > MAX_ROWS or width > MAX_COLS or len(rows) * width > MAX_CELLS:
        raise FormatError("table_limit", "Table exceeds 2000 rows, 40 columns or 20000 cells.")
    if any(len(row) != width for row in rows):
        raise FormatError("ragged_csv", "CSV rows must all have the same number of cells; no rows were repaired.")
    if any(len(cell) > 32000 for row in rows for cell in row):
        raise FormatError("cell_limit", "A cell exceeds the supported 32000-character limit.")
    return rows


def _csv_text(rows) -> str:
    out = io.StringIO(newline="")
    csv.writer(out, lineterminator="\n").writerows(rows)
    return _text(out.getvalue())


def _safe_zip(data: bytes) -> zipfile.ZipFile:
    from defusedxml import ElementTree as ET
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
        if len(infos) > 256 or sum(i.file_size for i in infos) > 20_000_000:
            raise FormatError("archive_limit", "Office archive exceeds expanded size or member limits.")
        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            raise FormatError("unsafe_archive", "Duplicate archive members are unsupported.")
        for info in infos:
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename or info.flag_bits & 1:
                raise FormatError("unsafe_archive", "Unsafe or encrypted Office archive member.")
            if info.file_size > max(100_000, info.compress_size * 200):
                raise FormatError("archive_limit", "Office archive compression ratio exceeds the limit.")
            if "vbaproject" in info.filename.lower() or "embeddings/" in info.filename.lower():
                raise FormatError("unsupported_office", "Macros and embedded objects are unsupported.")
            if info.filename.endswith((".xml", ".rels")):
                root = ET.fromstring(archive.read(info))
                if info.filename.endswith(".rels"):
                    for rel in root:
                        target = rel.attrib.get("Target", "")
                        is_hyperlink = rel.attrib.get("Type", "").endswith("/hyperlink")
                        safe_url = bool(re.match(r"^(https?://|mailto:)", target, re.I))
                        if is_hyperlink and safe_url:
                            continue  # label/target projection only; never resolve/fetch
                        if rel.attrib.get("TargetMode") == "External" or re.match(r"^[a-zA-Z]+:", target):
                            raise FormatError("external_relationship", "External Office relationships are not supported or fetched.")
        return archive
    except FormatError:
        raise
    except Exception as exc:
        raise FormatError("invalid_office", "Malformed or unsafe Office archive/XML.") from exc


def extract_upload(filename: str, data: bytes) -> Extraction:
    if not filename or Path(filename).name != filename or "\\" in filename or "\x00" in filename:
        raise FormatError("invalid_filename", "Upload name must be a simple filename.")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in MIMES:
        raise FormatError("unsupported_format", "Supported uploads: TXT, MD, CSV, DOCX, XLSX and text PDF.")
    if not data or len(data) > MAX_RAW_BYTES:
        raise FormatError("upload_limit", "Upload must contain 1 to 256000 bytes.")
    if ext in {"txt", "md", "csv"}:
        try:
            text = _text(data.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise FormatError("invalid_encoding", "Text uploads must use UTF-8.") from exc
        meta = {"format": ext, "bytes": len(data), "extraction": "utf8"}
        if ext == "csv":
            rows = _csv_rows(text)
            meta.update(rows=len(rows), columns=len(rows[0]))
        return Extraction(text, MIMES[ext], meta)
    return _isolated("extract", ext, data)


def _extract_binary(ext: str, data: bytes) -> Extraction:
    warnings = []
    meta = {"format": ext, "bytes": len(data), "extraction": "text_only", "coverage": "text_projection_not_full_fidelity"}
    if ext in {"docx", "xlsx"}:
        archive = _safe_zip(data)
    if ext == "docx":
        from defusedxml import ElementTree as ET
        from docx import Document
        xml = ET.fromstring(archive.read("word/document.xml"))
        _validate_docx_structure(xml)
        doc = Document(io.BytesIO(data))
        blocks = []
        relationship_parts = [doc.part]
        if any(el.tag.rsplit("}", 1)[-1] in {"drawing", "pict"} for el in xml.iter()):
            warnings.append("DOCX contains images/drawings: non-text content is not extracted; inspect the immutable original.")
            meta["nontext_omitted"] = True
        if any(el.tag.rsplit("}", 1)[-1] in {"fldChar", "fldSimple", "instrText"} for el in xml.iter()):
            warnings.append("DOCX fields use stored display text only; fields/PAGE values are not evaluated or refreshed.")
        seen_headers = set()
        for si, section in enumerate(doc.sections, 1):
            for label, part in (("header", section.header), ("footer", section.footer), ("first-page header", section.first_page_header), ("first-page footer", section.first_page_footer), ("even-page header", section.even_page_header), ("even-page footer", section.even_page_footer)):
                if str(part.part.partname) in seen_headers:
                    continue
                seen_headers.add(str(part.part.partname))
                relationship_parts.append(part.part)
                _validate_docx_structure(part._element)
                if any(el.tag.rsplit("}", 1)[-1] in {"drawing", "pict"} for el in part._element.iter()):
                    warnings.append("DOCX headers/footers contain images/drawings: non-text content is not extracted; inspect the immutable original.")
                    meta["nontext_omitted"] = True
                values = []
                for block in part.iter_inner_content():
                    if hasattr(block, "text"):
                        text = _paragraph_text(block)
                        if text:
                            values.append(text)
                    else:
                        values.append(_docx_table_text(block))
                if values:
                    blocks.append(f"[Section {si} {label}]\n" + "\n".join(values))
                    warnings.append("DOCX headers/footers projected as labelled text, not page-positioned layout; stored field display only.")
        for block in doc.iter_inner_content():
            if hasattr(block, "text"):
                text = _paragraph_text(block)
                name = block.style.name if block.style else ""
                if text.strip() and name.startswith("Heading ") and name[-1:].isdigit():
                    text = "#" * min(int(name[-1]), 6) + " " + text
                elif text.strip() and name.startswith("List"):
                    text = "- " + text
                blocks.append(text)
            else:
                blocks.append(_docx_table_text(block))
        links = []
        for part in relationship_parts:
            for rel in part.rels.values():
                if rel.reltype.endswith("/hyperlink"):
                    links.append(str(rel.target_ref))
        if links:
            blocks.append("[Hyperlink targets, not fetched]\n" + "\n".join(dict.fromkeys(links)))
            warnings.append("Hyperlink labels and target URLs retained as text; no links are fetched.")
        warnings.append("DOCX text/heading/list/table extraction only; font styling and page layout are not preserved.")
        text = "\n\n".join(blocks)
        meta["blocks"] = len(blocks)
    elif ext == "xlsx":
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(data), data_only=False, read_only=False, keep_links=False)
        blocks, cells, notes = [], 0, []
        for sheet in book:
            if sheet.max_row > MAX_ROWS or sheet.max_column > MAX_COLS:
                raise FormatError("table_limit", "XLSX worksheet dimensions exceed supported limits.")
            if sheet.merged_cells.ranges or sheet._charts or sheet._images:
                raise FormatError("unsupported_xlsx", "XLSX merged cells, charts and images are unsupported.")
            rows = []
            for row in sheet.iter_rows():
                values = []
                for cell in row:
                    cells += 1
                    if cells > MAX_CELLS:
                        raise FormatError("table_limit", "XLSX exceeds 20000 total cells.")
                    if cell.data_type == "f":
                        raise FormatError("xlsx_formula_unsupported", "XLSX formulas are unsupported; export a values-only copy. Cached values are not silently substituted.")
                    if cell.hyperlink:
                        notes.append(f"{sheet.title}!{cell.coordinate} hyperlink (not fetched): {cell.hyperlink.target or cell.hyperlink.location}")
                    if cell.comment:
                        notes.append(f"{sheet.title}!{cell.coordinate} comment: {cell.comment.text}")
                    values.append("" if cell.value is None else str(cell.value))
                rows.append(values)
            _csv_rows(_csv_text(rows))
            blocks.append("## " + sheet.title + "\n\n" + _markdown_table(rows))
        text = "\n\n".join(blocks)
        if notes:
            text += "\n\n[Cell annotations, not evaluated]\n" + "\n".join(notes)
            warnings.append("XLSX hyperlinks/comments preserved as labelled text after sheet data; links are not fetched.")
        meta.update(sheets=book.sheetnames, cells=cells)
        warnings.append("XLSX data-only text extraction; formatting and original cell types are recorded as text, not reproduced.")
    else:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise FormatError("encrypted_pdf", "Encrypted PDF is unsupported.")
        if len(reader.pages) > MAX_PAGES:
            raise FormatError("page_limit", "PDF exceeds 100 pages.")
        pages = []
        for page in reader.pages:
            if page.images or page.get("/Annots"):
                raise FormatError("unsupported_pdf", "PDF images/scans and annotations are unsupported; no OCR is performed.")
            stream = page.get_contents()
            if stream and len(stream.get_data()) > 2_000_000:
                raise FormatError("pdf_stream_limit", "Expanded PDF page stream exceeds limit.")
            text = page.extract_text() or ""
            if not text.strip():
                raise FormatError("scanned_pdf_unsupported", "PDF page has no text layer; OCR is not available.")
            pages.append(text)
        text = "\n\n".join(pages)
        meta["pages"] = len(pages)
        warnings.append("PDF text-layer extraction only; reading order and table/layout fidelity require review.")
    if not text.strip():
        raise FormatError("empty_extraction", "Document has no supported extractable text; no complete source projection was created.")
    return Extraction(_text(text), MIMES[ext], meta, warnings)


def _validate_docx_structure(element) -> None:
    unsupported = {"object", "ins", "del", "sdt", "footnoteReference", "endnoteReference", "oMath", "altChunk", "txbxContent"}
    table_tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl"
    for node in element.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag in unsupported:
            raise FormatError("unsupported_docx", "DOCX tracked changes, notes, equations, text boxes and embedded content are unsupported, including in headers/footers.")
        if tag in {"gridSpan", "vMerge"}:
            raise FormatError("unsupported_docx", "Merged DOCX table cells are unsupported, including in headers/footers.")
        if node.tag == table_tag and sum(1 for _ in node.iter(table_tag)) > 1:
            raise FormatError("unsupported_docx", "Nested DOCX tables are unsupported, including in headers/footers.")


def _docx_table_text(table) -> str:
    rows = [["\n".join(_paragraph_text(p) for p in c.paragraphs) for c in row.cells] for row in table.rows]
    _csv_rows(_csv_text(rows))
    return _markdown_table(rows)


def _paragraph_text(paragraph) -> str:
    """Include stored field displays/hyperlink labels, never field instructions."""
    parts = []
    for node in paragraph._p.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "t":
            parts.append(node.text or "")
        elif tag == "tab":
            parts.append("\t")
        elif tag in {"br", "cr"}:
            parts.append("\n")
    return "".join(parts)


def _markdown_table(rows: list[list[str]]) -> str:
    def line(row):
        return "| " + " | ".join(v.replace("|", "\\|").replace("\n", " ") for v in row) + " |"
    return "\n".join([line(rows[0]), line(["---"] * len(rows[0])), *[line(r) for r in rows[1:]]])


def _blocks(content: str):
    """Deliberately small Markdown block subset; unsupported syntax fails closed."""
    _text(content)
    if re.search(r"```|~~~|!\[|\[[^\]]*\]\(|<[/!a-zA-Z]|^\s*>|\*\*|__|`", content, re.M):
        raise FormatError("unsupported_markdown", "Office/PDF export supports plain prose, headings, flat lists and pipe tables; inline markup, code, links, HTML and images are unsupported. Markdown download remains available.")
    lines, result, i = content.splitlines(), [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*", lines[i + 1]):
            rows = []
            separator_index = i + 1
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                if i != separator_index:
                    rows.append([c.strip() for c in re.split(r"(?<!\\)\|", lines[i].strip().strip("|"))])
                i += 1
            _csv_rows(_csv_text(rows))
            if len(rows[0]) > 8:
                raise FormatError("document_table_limit", "Document export tables support at most 8 columns.")
            result.append(("table", rows))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        item = re.match(r"^([-*+] |\d+\. )(.*)$", line)
        if heading:
            result.append(("h" + str(len(heading[1])), heading[2]))
        elif item:
            result.append(("list", line))
        else:
            result.append(("p", line))
        i += 1
    return result


def validate_artifact(kind: str, content: str) -> None:
    if kind not in {"document", "table"}:
        raise FormatError("invalid_kind", "Artifact kind must be document or table.")
    _text(content)
    if not content.strip():
        raise FormatError("empty_artifact", "Artifact content must not be empty.")
    if kind == "table":
        _csv_rows(content)


def render_artifact(kind: str, content: str, format: str, title: str = "Document") -> Export:
    validate_artifact(kind, content)
    fmt = format.lower()
    if fmt not in ({"md", "docx", "pdf"} if kind == "document" else {"csv", "xlsx"}):
        raise FormatError("unsupported_export", "Format is not supported for this artifact kind.")
    if fmt == "md":
        return Export(content.encode("utf-8"), MIMES[fmt], fmt)
    if fmt == "csv":
        rows = _csv_rows(content)
        count = 0
        for row in rows:
            for i, value in enumerate(row):
                if _formula_like(value):
                    row[i] = "'" + value
                    count += 1
        return Export(_csv_text(rows).encode("utf-8"), MIMES[fmt], fmt,
                      [f"{count} formula-like text cells prefixed with an apostrophe for spreadsheet safety; canonical content is unchanged."] if count else [])
    return _isolated("render", kind, content, fmt, _text(title))


_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?\Z")


def _formula_like(value: str) -> bool:
    return bool(value and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) and not _NUMBER.fullmatch(value))


def _render(kind: str, content: str, fmt: str, title: str) -> Export:
    out = io.BytesIO()
    warnings = []
    if fmt == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        book = Workbook()
        sheet = book.active
        sheet.title = "Data"
        for row in _csv_rows(content):
            sheet.append(row)
        for row in sheet:
            for cell in row:
                value = cell.value
                # Only convert exact, lossless small integers. Decimals/IDs remain text.
                if _NUMBER.fullmatch(value or "") and re.fullmatch(r"-?(?:0|[1-9]\d*)", value) and len(value.lstrip("-")) <= 15:
                    cell.value = int(value)
                else:
                    cell.data_type = "s"
                    if _formula_like(value or ""):
                        warnings.append("Formula-like text is stored as literal text, never an executable formula.")
                cell.font = Font(name="Arial", size=11, color="000000", bold=cell.row == 1)
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                if cell.row == 1:
                    cell.fill = PatternFill("solid", fgColor="E6E6E6")
        for column in sheet.columns:
            width = min(60, max(12, max(len(str(c.value or "")) for c in column) + 2))
            sheet.column_dimensions[get_column_letter(column[0].column)].width = width
        sheet.freeze_panes = "A2"
        sheet.print_title_rows = "1:1"
        book.save(out)
    elif fmt == "docx":
        from docx import Document
        from docx.shared import Mm, Pt, RGBColor
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        doc = Document()
        section = doc.sections[0]
        section.page_width, section.page_height = Mm(210), Mm(297)
        section.top_margin = section.bottom_margin = Mm(20)
        section.left_margin = section.right_margin = Mm(22)
        for style in doc.styles:
            if hasattr(style, "font"):
                style.font.name = "Noto Sans"
                style.font.color.rgb = RGBColor(0, 0, 0)
        doc.styles["Normal"].font.size = Pt(11)
        doc.styles["Normal"].paragraph_format.space_after = Pt(6)
        for typ, value in _blocks(content):
            if typ == "table":
                table = doc.add_table(rows=0, cols=len(value[0]))
                table.style = "Table Grid"
                table.autofit = False
                widths = _column_widths(value, 166)
                for col, width in zip(table.columns, widths):
                    col.width = Mm(width)
                for ri, row in enumerate(value):
                    cells = table.add_row().cells
                    if max(map(len, row)) < 1000:
                        table.rows[-1]._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
                    for cell, text, width in zip(cells, row, widths):
                        cell.width = Mm(width)
                        cell.text = text.replace("\\|", "|")
                        borders = OxmlElement("w:tcBorders")
                        for side in ("top", "left", "bottom", "right"):
                            border = OxmlElement("w:" + side)
                            for attr, setting in (("val", "single"), ("sz", "4"), ("color", "D9D9D9")):
                                border.set(qn("w:" + attr), setting)
                            borders.append(border)
                        cell._tc.get_or_add_tcPr().append(borders)
                    if ri == 0:
                        header = OxmlElement("w:tblHeader")
                        table.rows[0]._tr.get_or_add_trPr().append(header)
                        for cell in cells:
                            shade = OxmlElement("w:shd")
                            shade.set(qn("w:fill"), "E6E6E6")
                            cell._tc.get_or_add_tcPr().append(shade)
                            for run in cell.paragraphs[0].runs:
                                run.bold = True
            else:
                paragraph = doc.add_paragraph(value, "Heading " + typ[1:] if typ.startswith("h") else "Normal")
                paragraph.paragraph_format.widow_control = True
                if typ == "list":
                    paragraph.paragraph_format.left_indent = Mm(5)
        doc.core_properties.author = ""
        doc.core_properties.title = title
        doc.save(out)
    else:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
        assets = Path(__file__).with_name("assets")
        for name, file in (("Workspace", "NotoSans-Regular.ttf"), ("WorkspaceBold", "NotoSans-Bold.ttf")):
            pdfmetrics.registerFont(TTFont(name, str(assets / file)))
        for char in content:
            if not char.isspace() and ord(char) not in pdfmetrics.getFont("Workspace").face.charToGlyph:
                raise FormatError("unsupported_glyph", f"PDF font does not support U+{ord(char):04X}; export Markdown/DOCX instead.")
        style = ParagraphStyle("body", fontName="Workspace", fontSize=11, leading=15, spaceAfter=7, splitLongWords=True)
        story = []
        def para(text, selected=style):
            return Paragraph(escape(text.replace("\\|", "|")).replace("\n", "<br/>"), selected)
        for typ, value in _blocks(content):
            if typ == "table":
                widths = _column_widths(value, A4[0] - 90)
                tab = Table([[para(c) for c in row] for row in value], colWidths=widths, repeatRows=1, hAlign="LEFT", splitInRow=1)
                tab.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#D9D9D9")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6E6E6")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
                story.extend([tab, Spacer(1, 8)])
            elif typ.startswith("h"):
                level = int(typ[1:])
                selected = ParagraphStyle(typ, parent=style, fontName="WorkspaceBold", fontSize=max(12, 20-level*2), leading=max(17, 25-level*2), spaceBefore=10, keepWithNext=True)
                story.append(para(value, selected))
            else:
                story.append(para(value))
        SimpleDocTemplate(out, pagesize=A4, leftMargin=45, rightMargin=45, topMargin=45, bottomMargin=45, title=title, author="").build(story)
    return Export(out.getvalue(), MIMES[fmt], fmt, list(dict.fromkeys(warnings)))


def _column_widths(rows, total):
    weights = [max(5, min(40, max(len(str(row[i])) for row in rows))) for i in range(len(rows[0]))]
    return [total * w / sum(weights) for w in weights]


def _worker(connection, operation, arguments):
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        # Darwin rejects memory rlimits; parent monitors RSS on every platform.
        if sys.platform != "darwin":
            resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
        def denied(*args, **kwargs):
            raise RuntimeError("Network disabled in format worker")
        class OfflineSocket(socket.socket):
            connect = denied
            connect_ex = denied
            bind = denied
            sendto = denied
        socket.socket = OfflineSocket
        socket.create_connection = denied
        socket.getaddrinfo = denied
        socket.gethostbyname = denied
        result = _extract_binary(*arguments) if operation == "extract" else _render(*arguments)
        if isinstance(result, Export) and len(result.data) > 5_000_000:
            raise FormatError("export_limit", "Export exceeds 5 MB limit.")
        connection.send((True, result))
    except FormatError as exc:
        connection.send((False, exc.code, str(exc)))
    except Exception:
        connection.send((False, "format_failed", "Malformed or unsupported document; original/draft remains available."))
    finally:
        connection.close()


def _isolated(operation, *arguments):
    if not _WORKERS.acquire(timeout=.5):
        raise FormatError("format_busy", "Two format workers are busy; retry after the current operation completes.")
    try:
        return _run_isolated(operation, *arguments)
    finally:
        _WORKERS.release()


def _run_isolated(operation, *arguments):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sender, operation, arguments), daemon=True)
    process.start()
    sender.close()
    try:
        import psutil
        monitored = psutil.Process(process.pid)
        deadline = time.monotonic() + WORKER_SECONDS
        while not receiver.poll(.025):
            if time.monotonic() > deadline:
                raise FormatError("format_timeout", "Format operation exceeded its 15-second deadline.")
            try:
                if monitored.memory_info().rss > 512_000_000:
                    raise FormatError("format_memory_limit", "Format worker exceeded its 512 MB memory limit.")
            except psutil.NoSuchProcess:
                break
        try:
            response = receiver.recv()
        except EOFError as exc:
            raise FormatError("format_failed", "Format worker ended before completion.") from exc
        if not response[0]:
            raise FormatError(response[1], response[2])
        return response[1]
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
