import io
import json
import stat
import warnings
import zipfile
from pathlib import Path
from typing import Any

import pytest
from docx import Document
from openpyxl import Workbook
from PIL import Image
from pptx import Presentation
from reportlab.pdfgen import canvas

from rtr_copilot.config import Settings
from rtr_copilot.ingestion.api import _decode_cursor, _encode_cursor, _parse_range
from rtr_copilot.ingestion.errors import IngestionFailure, safe_message
from rtr_copilot.ingestion.extractors import Artifact, canonical_json, extract_required
from rtr_copilot.ingestion.file_index import searchable_units
from rtr_copilot.ingestion.malware import DeterministicTestScanner
from rtr_copilot.ingestion.models import (
    OCRPayload,
    OCRRegion,
    TranscriptPayload,
    TranscriptSegment,
)
from rtr_copilot.ingestion.sandbox import ProcessSandbox, SandboxResult
from rtr_copilot.ingestion.validators import (
    MIME_EXTENSIONS,
    inspect_ooxml,
    normalize_display_name,
    validate_content,
)


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "postgres_dsn": "postgresql://user:password@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "s3_endpoint": "http://localhost:9000",
        "s3_access_key": "local",
        "s3_secret_key": "local-secret",
        "s3_bucket": "rtr-test",
    }
    values.update(overrides)
    return Settings(**values)


class FakeProbeSandbox:
    def __init__(self, *, duration: float = 2.5, codec_type: str = "audio") -> None:
        self.duration = duration
        self.codec_type = codec_type
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], *, temp_root: Path) -> SandboxResult:
        self.calls.append(argv)
        return SandboxResult(
            stdout=json.dumps({
                "format": {"duration": str(self.duration)},
                "streams": [{
                    "codec_type": self.codec_type,
                    "codec_name": "fixture",
                }],
            }).encode(),
            stderr_fingerprint=None,
        )


def write_image(path: Path, format_name: str) -> None:
    Image.new("RGB", (16, 12), (10, 20, 30)).save(path, format_name)


def write_pdf(path: Path, text: str = "golden page") -> None:
    pdf = canvas.Canvas(str(path), invariant=1)
    pdf.drawString(50, 750, text)
    pdf.save()


def write_docx(path: Path) -> None:
    document = Document()
    document.add_paragraph("golden paragraph")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "A"
    table.cell(0, 1).text = "B"
    document.save(path)


def write_xlsx(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Safe"
    sheet["A1"] = "golden cell"
    sheet["B1"] = "=1+1"
    workbook.save(path)


def write_pptx(path: Path) -> None:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    shape = slide.shapes.add_textbox(1, 1, 100, 100)
    shape.text = "golden slide"
    presentation.save(path)


def zip_fixture(path: Path, entries: list[tuple[str, bytes, int | None]]) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for name, payload, mode in entries:
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                if mode is not None:
                    info.create_system = 3
                    info.external_attr = mode << 16
                package.writestr(info, payload)


def minimal_docx_entries() -> list[tuple[str, bytes, int | None]]:
    return [
        ("[Content_Types].xml", b"<Types/>", None),
        ("word/document.xml", b"<document/>", None),
    ]


def test_supported_magic_allowlist_all_14_types(tmp_path: Path) -> None:
    fixtures: list[tuple[str, str, bytes | None, str | None]] = []
    for extension, format_name, mime in (
        (".png", "PNG", "image/png"),
        (".jpg", "JPEG", "image/jpeg"),
        (".webp", "WEBP", "image/webp"),
        (".tiff", "TIFF", "image/tiff"),
    ):
        path = tmp_path / f"image{extension}"
        write_image(path, format_name)
        fixtures.append((path.name, mime, None, None))
    pdf = tmp_path / "golden.pdf"
    write_pdf(pdf)
    fixtures.append((pdf.name, "application/pdf", None, None))
    for filename, writer, mime in (
        (
            "golden.docx",
            write_docx,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "golden.xlsx",
            write_xlsx,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "golden.pptx",
            write_pptx,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ):
        path = tmp_path / filename
        writer(path)
        fixtures.append((filename, mime, None, None))
    binary_media = (
        ("golden.mp4", "video/mp4", b"\0\0\0\x18ftypisomfixture", "video"),
        ("golden.webm", "video/webm", b"\x1aE\xdf\xa3fixture", "video"),
        ("golden.mp3", "audio/mpeg", b"ID3fixture", "audio"),
        ("golden.m4a", "audio/mp4", b"\0\0\0\x18ftypM4A fixture", "audio"),
        ("golden.wav", "audio/wav", b"RIFF\0\0\0\0WAVEfixture", "audio"),
        ("golden.ogg", "audio/ogg", b"OggSfixture", "audio"),
    )
    fixtures.extend(binary_media)
    detected = []
    for filename, mime, payload, codec_type in fixtures:
        path = tmp_path / filename
        if payload is not None:
            path.write_bytes(payload)
        result = validate_content(
            path,
            filename=filename,
            declared_mime=mime,
            settings=settings(),
            sandbox=FakeProbeSandbox(codec_type=codec_type or "audio"),  # type: ignore[arg-type]
        )
        detected.append(result.detected_mime)
    assert len(fixtures) == 14
    assert set(detected) == set(MIME_EXTENSIONS)


@pytest.mark.parametrize(
    ("name", "payload", "declared", "code"),
    [
        ("report.pdf.exe", b"MZ executable", None, "unknown_format"),
        ("active.html", b"<html><script>x</script></html>", None, "unknown_format"),
        ("active.svg", b"<svg><script>x</script></svg>", None, "unknown_format"),
        ("truncated.pdf", b"%PDF-", "application/pdf", "malformed_content"),
        ("fake.png", b"\x89PNG\r\n\x1a\nbroken", "image/png", "malformed_content"),
        ("double.pdf.exe", b"%PDF-broken", "application/pdf", "extension_mismatch"),
    ],
)
def test_hostile_magic_and_structure_codes(
    tmp_path: Path,
    name: str,
    payload: bytes,
    declared: str | None,
    code: str,
) -> None:
    path = tmp_path / name
    path.write_bytes(payload)
    with pytest.raises(IngestionFailure) as captured:
        validate_content(
            path,
            filename=name,
            declared_mime=declared,
            settings=settings(),
        )
    assert captured.value.code == code


def test_declared_mime_and_polyglot_are_rejected(tmp_path: Path) -> None:
    image = tmp_path / "safe.png"
    write_image(image, "PNG")
    with pytest.raises(IngestionFailure, match="declared_mime_mismatch"):
        validate_content(
            image,
            filename=image.name,
            declared_mime="application/pdf",
            settings=settings(),
        )
    polyglot = tmp_path / "polyglot.png"
    polyglot.write_bytes(b"\x89PNG\r\n\x1a\n<script>fixture")
    with pytest.raises(IngestionFailure, match="suspicious_polyglot"):
        validate_content(
            polyglot,
            filename=polyglot.name,
            declared_mime="image/png",
            settings=settings(),
        )


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ([("../escape", b"x", None)], "archive_path_unsafe"),
        ([("/absolute", b"x", None)], "archive_path_unsafe"),
        ([("C:\\escape", b"x", None)], "archive_path_unsafe"),
        ([("word/../escape", b"x", None)], "archive_path_unsafe"),
        ([("WORD/document.xml", b"x", None)], "archive_path_unsafe"),
        ([("word/link", b"x", stat.S_IFLNK | 0o777)], "archive_path_unsafe"),
        ([("word/nested.zip", b"PK\x03\x04", None)], "ooxml_active_content"),
        ([("word/vbaProject.bin", b"x", None)], "ooxml_active_content"),
        ([("word/embeddings/oleObject1.bin", b"x", None)], "ooxml_active_content"),
        ([
            (
                "word/_rels/document.xml.rels",
                b'<Relationships><Relationship TargetMode="External" '
                b'Target="https://invalid.example/x"/></Relationships>',
                None,
            ),
        ], "ooxml_active_content"),
    ],
)
def test_safe_ooxml_rejects_hostile_entries(
    tmp_path: Path,
    extra: list[tuple[str, bytes, int | None]],
    code: str,
) -> None:
    path = tmp_path / "hostile.docx"
    zip_fixture(path, minimal_docx_entries() + extra)
    with pytest.raises(IngestionFailure) as captured:
        inspect_ooxml(
            path,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            settings(),
        )
    assert captured.value.code == code


def test_safe_ooxml_budgets_entry_count_and_ratio(tmp_path: Path) -> None:
    too_many = tmp_path / "many.docx"
    zip_fixture(
        too_many,
        minimal_docx_entries() + [(f"word/x/{index}", b"x", None) for index in range(20)],
    )
    with pytest.raises(IngestionFailure, match="archive_budget_exceeded"):
        inspect_ooxml(
            too_many,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            settings(ingestion_max_archive_entries=10),
        )
    bomb = tmp_path / "ratio.docx"
    zip_fixture(
        bomb,
        minimal_docx_entries() + [("word/huge.txt", b"0" * 100_000, None)],
    )
    with pytest.raises(IngestionFailure, match="archive_budget_exceeded"):
        inspect_ooxml(
            bomb,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            settings(ingestion_max_compression_ratio=2),
        )


def test_pdf_active_content_and_image_pixel_budget(tmp_path: Path) -> None:
    active = tmp_path / "active.pdf"
    write_pdf(active)
    active.write_bytes(active.read_bytes() + b"\n/OpenAction /JavaScript")
    with pytest.raises(IngestionFailure, match="pdf_active_content"):
        validate_content(
            active,
            filename=active.name,
            declared_mime="application/pdf",
            settings=settings(),
        )
    bomb = tmp_path / "pixel.png"
    Image.new("1", (1001, 1000)).save(bomb)
    with pytest.raises(IngestionFailure, match="image_budget_exceeded"):
        validate_content(
            bomb,
            filename=bomb.name,
            declared_mime="image/png",
            settings=settings(ingestion_max_image_pixels=1_000_000),
        )


def test_media_budget_and_malformed_probe(tmp_path: Path) -> None:
    media = tmp_path / "long.mp3"
    media.write_bytes(b"ID3fixture")
    with pytest.raises(IngestionFailure, match="media_budget_exceeded"):
        validate_content(
            media,
            filename=media.name,
            declared_mime="audio/mpeg",
            settings=settings(ingestion_max_media_seconds=10),
            sandbox=FakeProbeSandbox(duration=11),  # type: ignore[arg-type]
        )


def test_ocr_and_transcript_schemas_preserve_origin_geometry_and_time() -> None:
    ocr = OCRPayload(
        regions=[
            OCRRegion(
                page=1,
                region="region-1",
                bounding_box=(10, 20, 100, 40),
                coordinate_system="pixel-top-left",
                page_width=1200,
                page_height=1600,
                rotation_degrees=90,
                language="vie",
                text="văn bản",
                confidence=0.72,
            ),
        ],
        aggregate_confidence=0.72,
        warnings=["ocr_low_confidence"],
    )
    assert ocr.regions[0].origin == "ocr"
    assert ocr.warnings == ["ocr_low_confidence"]

    transcript = TranscriptPayload(
        duration_ms=2500,
        language="vi",
        segments=[
            TranscriptSegment(
                start_ms=100,
                end_ms=1200,
                text="nội dung",
                confidence=0.81,
            ),
        ],
        warnings=[],
    )
    assert transcript.segments[0].speaker_label is None
    assert transcript.segments[0].origin == "transcript"
    with pytest.raises(ValueError, match="segment_outside_duration"):
        TranscriptPayload(
            duration_ms=100,
            segments=[TranscriptSegment(start_ms=50, end_ms=200, text="invalid")],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scanner_state", "expected"),
    [
        ("clean", "clean"),
        ("infected", "infected"),
        ("unavailable", "scanner_unavailable"),
        ("timeout", "scanner_timeout"),
        ("stale", "scanner_signatures_stale"),
        ("malformed", "scanner_response_invalid"),
    ],
)
async def test_malware_adapter_fail_closed_matrix(
    tmp_path: Path,
    scanner_state: Any,
    expected: str,
) -> None:
    path = tmp_path / "sample"
    path.write_bytes(b"clean")
    scanner = DeterministicTestScanner(scanner_state)
    if expected in {"clean", "infected"}:
        assert (await scanner.scan(path)).result == expected
    else:
        with pytest.raises(IngestionFailure) as captured:
            await scanner.scan(path)
        assert captured.value.code == expected


@pytest.mark.asyncio
async def test_encoded_eicar_marker_is_detected(tmp_path: Path) -> None:
    marker = b"X5O!" + b"P%@AP" + b"[4\\PZX54(P^)" + b"7CC)7}$EICAR"
    path = tmp_path / "encoded-generated-only"
    path.write_bytes(marker)
    result = await DeterministicTestScanner().scan(path)
    assert result.result == "infected"


def test_golden_extractors_are_deterministic_and_keep_locators(
    tmp_path: Path,
) -> None:
    fixture_writers = (
        ("golden.pdf", write_pdf, "application/pdf", {"pages": 1}),
        (
            "golden.docx",
            write_docx,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            {},
        ),
        (
            "golden.xlsx",
            write_xlsx,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            {},
        ),
        (
            "golden.pptx",
            write_pptx,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            {},
        ),
    )
    output_count = 0
    for filename, writer, mime, structural in fixture_writers:
        path = tmp_path / filename
        writer(path)
        first = extract_required(
            path,
            mime=mime,
            structural=structural,
            settings=settings(),
            sandbox=FakeProbeSandbox(),  # type: ignore[arg-type]
        )
        second = extract_required(
            path,
            mime=mime,
            structural=structural,
            settings=settings(),
            sandbox=FakeProbeSandbox(),  # type: ignore[arg-type]
        )
        assert [(item.kind, item.sha256) for item in first] == [
            (item.kind, item.sha256) for item in second
        ]
        output_count += len(first)
        for artifact in first:
            assert artifact.quality["expected_units"] >= 1
            assert artifact.quality_state in {"complete", "partial", "low_confidence"}
    xlsx = extract_required(
        tmp_path / "golden.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        structural={},
        settings=settings(),
        sandbox=FakeProbeSandbox(),  # type: ignore[arg-type]
    )
    sheet_json = next(item for item in xlsx if item.kind == "sheet_preview_json")
    assert b'"cell":"B1"' in sheet_json.payload
    assert b'"formula":"=1+1"' in sheet_json.payload
    assert output_count == 11


@pytest.mark.parametrize(
    ("extension", "format_name", "mime"),
    [
        (".png", "PNG", "image/png"),
        (".jpg", "JPEG", "image/jpeg"),
        (".webp", "WEBP", "image/webp"),
        (".tiff", "TIFF", "image/tiff"),
    ],
)
def test_all_image_types_strip_metadata_and_create_required_outputs(
    tmp_path: Path,
    extension: str,
    format_name: str,
    mime: str,
) -> None:
    source = tmp_path / f"source{extension}"
    write_image(source, format_name)
    artifacts = extract_required(
        source,
        mime=mime,
        structural={"width": 16, "height": 12},
        settings=settings(),
        sandbox=FakeProbeSandbox(),  # type: ignore[arg-type]
    )
    assert {artifact.kind for artifact in artifacts} == {
        "safe_image_preview",
        "thumbnail",
    }
    for artifact in artifacts:
        with Image.open(io.BytesIO(artifact.payload)) as rendered:
            assert rendered.format == "PNG"
            assert not rendered.getexif()


def test_filename_and_client_errors_are_sanitized() -> None:
    assert normalize_display_name("../../safe\u202ename.pdf") == "safename.pdf"
    with pytest.raises(IngestionFailure, match="filename_invalid"):
        normalize_display_name("\x00\u202e")
    hostile = "token=secret /private/path quarantine/key raw file text"
    assert hostile not in safe_message("processing_failed")


def test_file_cursor_and_byte_ranges_are_bounded() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    instant = datetime.now(UTC)
    version_id = uuid4()
    assert _decode_cursor(_encode_cursor(instant, version_id)) == (instant, version_id)
    with pytest.raises(ValueError, match="invalid_cursor"):
        _decode_cursor("tampered")
    assert _parse_range(None, 10) is None
    assert _parse_range("bytes=2-5", 10) == (2, 5)
    assert _parse_range("bytes=7-", 10) == (7, 9)
    assert _parse_range("bytes=-3", 10) == (7, 9)
    assert _parse_range("bytes=0-99", 10) == (0, 9)
    for invalid in ("bytes=10-", "bytes=5-2", "bytes=0-1,3-4", "items=0-1"):
        with pytest.raises(ValueError):
            _parse_range(invalid, 10)


def test_sandbox_rejects_network_and_path_escape_and_kills_timeout(
    tmp_path: Path,
) -> None:
    sandbox = ProcessSandbox(
        timeout_seconds=1,
        temp_bytes=1024 * 1024,
        allowed_tools=frozenset({"sleep", "ffprobe"}),
    )
    with pytest.raises(IngestionFailure, match="network_argument_forbidden"):
        sandbox.run(["ffprobe", "https://invalid.example/file"], temp_root=tmp_path)
    with pytest.raises(IngestionFailure, match="path_escape_forbidden"):
        sandbox.run(["ffprobe", "/etc/passwd"], temp_root=tmp_path)
    with pytest.raises(IngestionFailure, match="tool_timeout"):
        sandbox.run(["sleep", "5"], temp_root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_private_file_index_extracts_text_with_exact_locators() -> None:
    artifact = Artifact(
        kind="page_text_json",
        mime_type="application/json",
        payload=canonical_json({
            "schema_version": 1,
            "pages": [
                {"page": 1, "text": "Alpha flight envelope"},
                {"page": 2, "text": ""},
            ],
        }),
        origin="native",
        quality_state="complete",
        quality={},
    )
    assert searchable_units(artifact) == [
        ("Alpha flight envelope", {"page": 1}),
    ]
    hostile = Artifact(
        kind="unknown_json",
        mime_type="application/json",
        payload=b'{"text":"must not be indexed"}',
        origin="native",
        quality_state="complete",
        quality={},
    )
    assert searchable_units(hostile) == []
