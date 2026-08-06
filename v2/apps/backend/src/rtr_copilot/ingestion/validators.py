import json
import re
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from defusedxml import ElementTree  # type: ignore[import-untyped]
from PIL import Image
from pypdf import PdfReader
from pypdf.generic import IndirectObject

from rtr_copilot.config import Settings
from rtr_copilot.ingestion.errors import IngestionFailure
from rtr_copilot.ingestion.models import DetectionResult
from rtr_copilot.ingestion.sandbox import ProcessSandbox

MIME_EXTENSIONS = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/webp": {".webp"},
    "image/tiff": {".tif", ".tiff"},
    "application/pdf": {".pdf"},
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
        ".docx",
    },
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {".xlsx"},
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": {
        ".pptx",
    },
    "video/mp4": {".mp4"},
    "video/webm": {".webm"},
    "audio/mpeg": {".mp3"},
    "audio/mp4": {".m4a", ".aac"},
    "audio/wav": {".wav"},
    "audio/ogg": {".ogg", ".opus"},
}
VIEWER_KINDS = {
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "image/tiff": "image",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "video/mp4": "video",
    "video/webm": "video",
    "audio/mpeg": "audio",
    "audio/mp4": "audio",
    "audio/wav": "audio",
    "audio/ogg": "audio",
}
OOXML_REQUIRED = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "word/document.xml"
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "xl/workbook.xml"
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "ppt/presentation.xml"
    ),
}
BIDI_CONTROLS = re.compile("[\u202a-\u202e\u2066-\u2069]")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def normalize_display_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = BIDI_CONTROLS.sub("", normalized)
    normalized = CONTROL_CHARACTERS.sub("", normalized)
    normalized = normalized.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not normalized:
        raise IngestionFailure("filename_invalid", stage="receive")
    return normalized[:255]


def _sniff(head: bytes, path: Path) -> str:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"PK\x03\x04"):
        return _ooxml_type(path)
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        return "audio/mp4" if brand in {b"M4A ", b"M4B ", b"M4P "} else "video/mp4"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    if head.startswith(b"ID3") or (
        len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    raise IngestionFailure("unknown_format", stage="validate")


def _ooxml_type(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as package:
            names = set(package.namelist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise IngestionFailure("malformed_content", stage="validate") from exc
    candidates = [
        mime for mime, required in OOXML_REQUIRED.items() if required in names
    ]
    if len(candidates) != 1:
        raise IngestionFailure(
            "suspicious_polyglot" if candidates else "unknown_format",
            stage="validate",
        )
    return candidates[0]


def _validate_entry_name(name: str) -> str:
    if "\x00" in name or "\\" in name or re.match(r"^[A-Za-z]:", name):
        raise IngestionFailure("archive_path_unsafe", stage="validate")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise IngestionFailure("archive_path_unsafe", stage="validate")
    canonical = "/".join(part for part in path.parts if part not in {"", "."})
    if not canonical:
        raise IngestionFailure("archive_path_unsafe", stage="validate")
    return canonical.casefold()


def inspect_ooxml(path: Path, mime: str, settings: Settings) -> dict[str, Any]:
    expanded = 0
    canonical_names: set[str] = set()
    try:
        with zipfile.ZipFile(path) as package:
            entries = package.infolist()
            if len(entries) > settings.ingestion_max_archive_entries:
                raise IngestionFailure("archive_budget_exceeded", stage="validate")
            for entry in entries:
                canonical = _validate_entry_name(entry.filename)
                if canonical in canonical_names:
                    raise IngestionFailure("archive_path_unsafe", stage="validate")
                canonical_names.add(canonical)
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise IngestionFailure("archive_path_unsafe", stage="validate")
                if entry.flag_bits & 0x1:
                    raise IngestionFailure("archive_entry_unsupported", stage="validate")
                expanded += entry.file_size
                ratio = entry.file_size / max(entry.compress_size, 1)
                if (
                    entry.file_size > settings.ingestion_max_archive_entry_bytes
                    or
                    expanded > settings.ingestion_max_expanded_bytes
                    or ratio > settings.ingestion_max_compression_ratio
                ):
                    raise IngestionFailure("archive_budget_exceeded", stage="validate")
                lower = canonical.lower()
                if (
                    lower.endswith((".zip", ".exe", ".dll", ".js", ".html", ".svg"))
                    or "/embeddings/" in f"/{lower}"
                    or "vbaproject.bin" in lower
                    or "/activex/" in f"/{lower}"
                    or "oleobject" in lower
                    or "/connections.xml" in f"/{lower}"
                ):
                    raise IngestionFailure("ooxml_active_content", stage="validate")
                if lower.endswith(".rels"):
                    relationship = package.read(entry)
                    if len(relationship) > 2_000_000:
                        raise IngestionFailure("archive_budget_exceeded", stage="validate")
                    root = ElementTree.fromstring(relationship)
                    for node in root.iter():
                        attributes = {key.lower(): value for key, value in node.attrib.items()}
                        target = attributes.get("target", "")
                        if (
                            attributes.get("targetmode", "").lower() == "external"
                            or "://" in target
                        ):
                            raise IngestionFailure("ooxml_active_content", stage="validate")
            required = OOXML_REQUIRED[mime]
            if "[Content_Types].xml".casefold() not in canonical_names:
                raise IngestionFailure("malformed_content", stage="validate")
            if required.casefold() not in canonical_names:
                raise IngestionFailure("malformed_content", stage="validate")
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise IngestionFailure("malformed_content", stage="validate") from exc
    return {"archive_entries": len(entries), "expanded_bytes": expanded}


def _validate_image(path: Path, settings: Settings) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > settings.ingestion_max_image_pixels:
                raise IngestionFailure("image_budget_exceeded", stage="validate")
            image.verify()
    except IngestionFailure:
        raise
    except Exception as exc:
        raise IngestionFailure("malformed_content", stage="validate") from exc
    return {"width": width, "height": height, "pixels": width * height}


PDF_FORBIDDEN_KEYS = {
    "/AA",
    "/EmbeddedFile",
    "/EmbeddedFiles",
    "/JavaScript",
    "/JS",
    "/Launch",
    "/OpenAction",
    "/RichMedia",
}
PDF_FORBIDDEN_ACTIONS = {
    "/ImportData",
    "/JavaScript",
    "/Launch",
    "/RichMedia",
    "/SubmitForm",
}
PDF_SAFE_URI_SCHEMES = {"http", "https"}


def _pdf_has_active_content(reader: PdfReader) -> bool:
    """Inspect parsed objects instead of byte patterns in compressed media."""

    stack: list[Any] = [reader.trailer]
    for generation, object_ids in reader.xref.items():
        stack.extend(
            IndirectObject(object_id, generation, reader)
            for object_id in object_ids
            if object_id != 0
        )
    seen_indirect: set[tuple[int, int]] = set()
    seen_direct: set[int] = set()
    while stack:
        value = stack.pop()
        if isinstance(value, IndirectObject):
            indirect_identity = (value.idnum, value.generation)
            if indirect_identity in seen_indirect:
                continue
            seen_indirect.add(indirect_identity)
            value = value.get_object()
        elif isinstance(value, dict | list | tuple):
            direct_identity = id(value)
            if direct_identity in seen_direct:
                continue
            seen_direct.add(direct_identity)
        if isinstance(value, dict):
            keys = {str(key) for key in value}
            if keys & PDF_FORBIDDEN_KEYS:
                return True
            action = str(value.get("/S", ""))
            if action in PDF_FORBIDDEN_ACTIONS:
                return True
            if action == "/URI":
                uri = str(value.get("/URI", "")).strip()
                if urlsplit(uri).scheme.lower() not in PDF_SAFE_URI_SCHEMES:
                    return True
            stack.extend(value.values())
        elif isinstance(value, list | tuple):
            stack.extend(value)
    return False


def _validate_pdf(path: Path, settings: Settings) -> dict[str, Any]:
    try:
        reader = PdfReader(str(path), strict=True)
        pages = len(reader.pages)
        objects = sum(len(section) for section in reader.xref.values())
        if pages > settings.ingestion_max_pdf_pages:
            raise IngestionFailure("archive_budget_exceeded", stage="validate")
        if objects > settings.ingestion_max_pdf_objects:
            raise IngestionFailure("archive_budget_exceeded", stage="validate")
        if _pdf_has_active_content(reader):
            raise IngestionFailure("pdf_active_content", stage="validate")
    except IngestionFailure:
        raise
    except Exception as exc:
        raise IngestionFailure("malformed_content", stage="validate") from exc
    return {"pages": pages, "objects": objects}


def _validate_media(
    path: Path,
    mime: str,
    settings: Settings,
    sandbox: ProcessSandbox,
) -> dict[str, Any]:
    result = sandbox.run([
        "ffprobe",
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,sample_rate",
        "-of",
        "json",
        str(path.resolve()),
    ], temp_root=path.parent)
    try:
        payload = json.loads(result.stdout)
        duration = float(payload["format"]["duration"])
        streams = list(payload.get("streams", []))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise IngestionFailure("malformed_content", stage="validate") from exc
    if duration <= 0 or duration > settings.ingestion_max_media_seconds:
        raise IngestionFailure("media_budget_exceeded", stage="validate")
    expected_type = "video" if mime.startswith("video/") else "audio"
    if not any(stream.get("codec_type") == expected_type for stream in streams):
        raise IngestionFailure("malformed_content", stage="validate")
    for stream in streams:
        if stream.get("codec_type") == "video" and (
            int(stream.get("width", 0)) > settings.ingestion_max_media_width
            or int(stream.get("height", 0)) > settings.ingestion_max_media_height
        ):
            raise IngestionFailure("media_budget_exceeded", stage="validate")
        if stream.get("codec_type") == "audio" and (
            int(stream.get("sample_rate", 0)) > settings.ingestion_max_sample_rate
        ):
            raise IngestionFailure("media_budget_exceeded", stage="validate")
    return {"duration_ms": round(duration * 1000), "streams": streams}


def validate_content(
    path: Path,
    *,
    filename: str,
    declared_mime: str | None,
    settings: Settings,
    sandbox: ProcessSandbox | None = None,
) -> DetectionResult:
    with path.open("rb") as source:
        head = source.read(4096)
        source.seek(0, 2)
        size = source.tell()
    if size <= 0:
        raise IngestionFailure("malformed_content", stage="validate")
    mime = _sniff(head, path)
    if b"<script" in head.lower() or b"<svg" in head.lower() or head.startswith(b"MZ"):
        raise IngestionFailure("suspicious_polyglot", stage="validate")
    if declared_mime and declared_mime.split(";", 1)[0].strip().lower() != mime:
        raise IngestionFailure("declared_mime_mismatch", stage="validate")
    suffix = Path(filename).suffix.lower()
    if suffix not in MIME_EXTENSIONS[mime]:
        raise IngestionFailure("extension_mismatch", stage="validate")
    if mime.startswith("image/"):
        structural = _validate_image(path, settings)
    elif mime == "application/pdf":
        structural = _validate_pdf(path, settings)
    elif mime in OOXML_REQUIRED:
        structural = inspect_ooxml(path, mime, settings)
    else:
        structural = _validate_media(
            path,
            mime,
            settings,
            sandbox or ProcessSandbox(
                timeout_seconds=settings.ingestion_tool_timeout_seconds,
                temp_bytes=settings.ingestion_temp_bytes,
            ),
        )
    return DetectionResult(
        detected_mime=mime,
        viewer_kind=VIEWER_KINDS[mime],
        structural=structural,
    )
