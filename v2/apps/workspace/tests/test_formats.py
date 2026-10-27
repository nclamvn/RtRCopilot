"""Synthetic structural/round-trip evidence, not semantic model evaluation."""
import csv
import io
import zipfile

import pytest
from docx import Document
from openpyxl import Workbook, load_workbook
from pypdf import PdfReader, PdfWriter

from agent_workspace.formats import FormatError, extract_upload, render_artifact, validate_artifact

VI = "Tiếng Việt đầy đủ: Nguyễn, cộng đồng, chất lượng, 1.250 và -42."
DOCUMENT = "# Báo cáo\n\n" + VI + "\n\n## Dữ liệu\n\n- Mục thứ nhất\n- Mục thứ hai\n\n| Tên | Số lượng |\n| --- | --- |\n| Cảng Đà Nẵng | -42 |\n| Hải Phòng | 1250 |\n"


def bytes_of(obj):
    out = io.BytesIO()
    obj.save(out)
    return out.getvalue()


def test_utf8_csv_and_limits():
    assert extract_upload("notes.md", VI.encode()).text == VI
    result = extract_upload("data.csv", "Tên,Số\nĐà Nẵng,-42\n".encode())
    assert result.metadata["rows"] == 2
    for filename, data, code in [("a.xlsm", b"x", "unsupported_format"), ("../a.txt", b"x", "invalid_filename"), ("a.txt", b"\xff", "invalid_encoding"), ("a.csv", b"a,b\n1\n", "ragged_csv"), ("a.csv", b'a,b\n"bad', "invalid_csv"), ("a.txt", b"x" * 256001, "upload_limit")]:
        with pytest.raises(FormatError) as error:
            extract_upload(filename, data)
        assert error.value.code == code


def test_document_docx_roundtrip():
    export = render_artifact("document", DOCUMENT, "docx")
    doc = Document(io.BytesIO(export.data))
    assert doc.paragraphs[0].style.name == "Heading 1"
    assert VI in "\n".join(p.text for p in doc.paragraphs)
    assert doc.tables[0].cell(1, 1).text == "-42"
    result = extract_upload("report.docx", export.data)
    assert VI in result.text and "1250" in result.text
    assert result.warnings


def test_common_docx_headers_cached_fields_hyperlinks():
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    doc = Document()
    doc.add_paragraph(VI)
    doc.sections[0].header.paragraphs[0].text = "Tiêu đề đầu trang"
    footer = doc.sections[0].footer.paragraphs[0]
    footer.add_run("Trang ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    field.append(run)
    footer._p.append(field)
    relationship = doc.part.relate_to("https://example.test/reference", RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), relationship)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "Tài liệu tham khảo"
    run.append(text)
    link.append(run)
    doc.add_paragraph()._p.append(link)
    result = extract_upload("common.docx", bytes_of(doc))
    assert "Tiêu đề đầu trang" in result.text and "Tài liệu tham khảo" in result.text
    assert "https://example.test/reference" in result.text
    assert "Trang 1" in result.text
    assert result.metadata["coverage"] == "text_projection_not_full_fidelity"
    assert result.warnings


def test_xlsx_comments_and_links_are_labelled_not_fetched():
    from openpyxl.comments import Comment
    book = Workbook()
    book.active.append(["Tên", "Số"])
    book.active.append(["Đà Nẵng", -42])
    book.active["A2"].hyperlink = "https://example.test/source"
    book.active["B2"].comment = Comment("Số âm cần giữ", "Reader")
    result = extract_upload("common.xlsx", bytes_of(book))
    assert "Số âm cần giữ" in result.text and "https://example.test/source" in result.text
    assert "-42" in result.text and result.warnings


def test_pdf_unicode_long_and_multiple_pages():
    text = DOCUMENT + "\n\n" + "\n\n".join(f"Đoạn {i}: {VI} " + "nội dung kiểm chứng " * 15 for i in range(28)) + "\n\nKẾT THÚC 987654"
    export = render_artifact("document", text, "pdf")
    reader = PdfReader(io.BytesIO(export.data))
    assert len(reader.pages) >= 3
    recovered = "\n".join(p.extract_text() for p in reader.pages)
    assert "KẾT THÚC 987654" in recovered and "Nguyễn" in recovered
    for i in range(28):
        assert f"Đoạn {i}:" in recovered
    assert extract_upload("report.pdf", export.data).metadata["pages"] == len(reader.pages)


def test_table_roundtrip_and_formula_safety():
    content = 'Tên,Số,Ghi chú\nĐà Nẵng,-42,=HYPERLINK("https://evil")\nMã,001,@SUM(A1)\n'
    # Formula-like commas must be properly quoted as with any CSV field.
    export = render_artifact("table", content, "xlsx")
    book = load_workbook(io.BytesIO(export.data), data_only=False)
    sheet = book.active
    assert sheet["B2"].value == -42 and sheet["B2"].data_type == "n"
    assert sheet["B3"].value == "001" and sheet["B3"].data_type == "s"
    assert sheet["C2"].data_type == "s" and sheet["C2"].value.startswith("=")
    assert export.warnings
    extracted = extract_upload("data.xlsx", export.data)
    assert "Đà Nẵng" in extracted.text and "-42" in extracted.text
    safe = render_artifact("table", content, "csv")
    rows = list(csv.reader(io.StringIO(safe.data.decode())))
    assert rows[1][1] == "-42" and rows[1][2].startswith("'=")
    assert rows[2][1] == "001" and safe.warnings


def test_reject_xlsx_formula_not_silent_none():
    book = Workbook()
    book.active.append(["Value"])
    book.active.append(["=1+2"])
    with pytest.raises(FormatError, match="Cached values") as error:
        extract_upload("formula.xlsx", bytes_of(book))
    assert error.value.code == "xlsx_formula_unsupported"


def test_reject_encryption_and_blank_scan():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    writer.write(out)
    with pytest.raises(FormatError) as error:
        extract_upload("scan.pdf", out.getvalue())
    assert error.value.code == "scanned_pdf_unsupported"
    writer.encrypt("secret")
    out = io.BytesIO()
    writer.write(out)
    with pytest.raises(FormatError) as error:
        extract_upload("secret.pdf", out.getvalue())
    assert error.value.code == "encrypted_pdf"


@pytest.mark.parametrize("name,payload", [("../evil.xml", b"x"), ("word/vbaProject.bin", b"x"), ("word/document.xml", b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'), ("word/_rels/document.xml.rels", b'<Relationships><Relationship TargetMode="External" Target="https://example.test"/></Relationships>')])
def test_reject_unsafe_office(name, payload):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(name, payload)
    with pytest.raises(FormatError):
        extract_upload("bad.docx", out.getvalue())


def test_unsupported_export_preserves_markdown_and_glyph_fails():
    text = "# Heading\n\n![image](https://example.test/image.png)"
    assert render_artifact("document", text, "md").data == text.encode()
    with pytest.raises(FormatError) as error:
        render_artifact("document", text, "docx")
    assert error.value.code == "unsupported_markdown"
    with pytest.raises(FormatError) as error:
        render_artifact("document", "Unsupported emoji 🛸", "pdf")
    assert error.value.code == "unsupported_glyph"
    with pytest.raises(FormatError):
        validate_artifact("table", "a,b\n1\n")


def test_worker_timeout_and_table_bounds(monkeypatch):
    from agent_workspace import formats
    monkeypatch.setattr(formats, "WORKER_SECONDS", 0)
    with pytest.raises(FormatError) as error:
        render_artifact("document", DOCUMENT, "pdf")
    assert error.value.code == "format_timeout"
    with pytest.raises(FormatError) as error:
        validate_artifact("table", ",".join("a" for _ in range(41)))
    assert error.value.code == "table_limit"


def test_worker_concurrency_bound():
    from agent_workspace import formats
    formats._WORKERS.acquire()
    formats._WORKERS.acquire()
    try:
        with pytest.raises(FormatError) as error:
            render_artifact("document", DOCUMENT, "pdf")
        assert error.value.code == "format_busy"
    finally:
        formats._WORKERS.release()
        formats._WORKERS.release()


def test_long_table_cell_pdf_not_truncated():
    long_cell = "Nguyễn kiểm chứng nội dung dài " * 130
    content = "# Bảng dài\n\n| Tên | Mô tả |\n| --- | --- |\n| Đà Nẵng | " + long_cell + "KẾT-Ô-12345 |\n"
    output = render_artifact("document", content, "pdf")
    reader = PdfReader(io.BytesIO(output.data))
    assert len(reader.pages) >= 2
    recovered = "\n".join(p.extract_text() for p in reader.pages)
    assert "KẾT-Ô-12345" in recovered


def test_office_zip_bomb_rejected():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"x" * 1_000_000)
    with pytest.raises(FormatError) as error:
        extract_upload("bomb.docx", out.getvalue())
    assert error.value.code == "archive_limit"


def test_pipe_table_hyphen_only_data_row_is_not_separator():
    content = "| First | Second |\n| --- | --- |\n| - | -- |\n| KEEP | 120.50 |\n| : | --- |\n"
    result = render_artifact("document", content, "docx")
    rows = Document(io.BytesIO(result.data)).tables[0].rows
    assert [[c.text for c in row.cells] for row in rows] == [["First", "Second"], ["-", "--"], ["KEEP", "120.50"], [":", "---"]]


def test_blank_docx_fails_loud():
    with pytest.raises(FormatError) as error:
        extract_upload("blank.docx", bytes_of(Document()))
    assert error.value.code == "empty_extraction"


@pytest.mark.parametrize("part_name", ["first_page_header", "first_page_footer", "even_page_header", "even_page_footer"])
def test_all_header_footer_hyperlink_targets(part_name):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    doc = Document()
    doc.add_paragraph(VI)
    part = getattr(doc.sections[0], part_name)
    target = f"https://example.test/{part_name}"
    relationship = part.part.relate_to(target, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), relationship)
    run, text = OxmlElement("w:r"), OxmlElement("w:t")
    text.text = "LIÊN KẾT " + part_name
    run.append(text)
    link.append(run)
    part.paragraphs[0]._p.append(link)
    result = extract_upload("headers.docx", bytes_of(doc))
    assert target in result.text and "LIÊN KẾT " + part_name in result.text


@pytest.mark.parametrize("construct", ["nested", "merged", "textbox"])
def test_unsupported_header_footer_content_rejects(construct):
    from docx.shared import Mm
    from docx.oxml import OxmlElement
    doc = Document()
    doc.add_paragraph(VI)
    header = doc.sections[0].first_page_header
    if construct == "textbox":
        header.paragraphs[0]._p.append(OxmlElement("w:txbxContent"))
    else:
        table = header.add_table(rows=1, cols=2, width=Mm(160))
        if construct == "nested":
            table.cell(0, 0).add_table(rows=1, cols=1).cell(0, 0).text = "DO NOT OMIT"
        else:
            table.cell(0, 0).merge(table.cell(0, 1)).text = "DO NOT OMIT"
    with pytest.raises(FormatError) as error:
        extract_upload("unsupported-header.docx", bytes_of(doc))
    assert error.value.code == "unsupported_docx"
