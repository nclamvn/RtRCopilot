import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Literal

import fitz  # type: ignore[import-untyped]
from PIL import Image

from rtr_copilot.config import Settings
from rtr_copilot.ingestion.errors import IngestionFailure
from rtr_copilot.ingestion.extractors import Artifact, canonical_json
from rtr_copilot.ingestion.models import (
    OCRPayload,
    OCRRegion,
    TranscriptPayload,
    TranscriptSegment,
)
from rtr_copilot.ingestion.sandbox import ProcessSandbox


class LocalTesseractOCR:
    def __init__(self, settings: Settings, sandbox: ProcessSandbox) -> None:
        self.settings = settings
        self.sandbox = sandbox
        self.languages = {
            language.strip()
            for language in settings.ingestion_ocr_languages.split(",")
            if language.strip()
        }

    def _one_rotation(
        self,
        source: Image.Image,
        *,
        rotation: int,
        page: int,
        language: str,
        directory: Path,
    ) -> tuple[list[OCRRegion], float]:
        rotated = source.rotate(rotation, expand=True)
        input_path = directory / f"ocr-page-{page}-rotation-{rotation}.png"
        rotated.save(input_path, "PNG")
        result = self.sandbox.run([
            "tesseract",
            str(input_path.resolve()),
            "stdout",
            "-l",
            language,
            "--psm",
            "6",
            "tsv",
        ], temp_root=directory)
        rows = csv.DictReader(
            io.StringIO(result.stdout.decode("utf-8", "replace")),
            delimiter="\t",
        )
        regions = []
        confidences = []
        for index, row in enumerate(rows):
            text_value = str(row.get("text", "")).strip()
            try:
                confidence = float(row.get("conf", "-1")) / 100
                left = float(row.get("left", "0"))
                top = float(row.get("top", "0"))
                width = float(row.get("width", "0"))
                height = float(row.get("height", "0"))
            except (TypeError, ValueError):
                continue
            if not text_value or confidence < 0 or width <= 0 or height <= 0:
                continue
            confidences.append(confidence)
            regions.append(OCRRegion(
                page=page,
                region=f"p{page}-r{index}",
                bounding_box=(left, top, left + width, top + height),
                coordinate_system="pixel-top-left",
                page_width=float(rotated.width),
                page_height=float(rotated.height),
                rotation_degrees=rotation,
                language=language,
                text=text_value,
                confidence=max(0.0, min(1.0, confidence)),
            ))
        aggregate = sum(confidences) / len(confidences) if confidences else 0.0
        return regions, aggregate

    def extract_image(
        self,
        path: Path,
        *,
        page: int = 1,
        language: str = "eng",
    ) -> tuple[list[OCRRegion], float]:
        if not self.settings.ingestion_ocr_enabled:
            raise IngestionFailure("ocr_unavailable", stage="ocr")
        if language not in self.languages:
            raise IngestionFailure("ocr_language_unavailable", stage="ocr")
        try:
            with Image.open(path) as image:
                source = image.convert("RGB")
                candidates = [
                    self._one_rotation(
                        source,
                        rotation=rotation,
                        page=page,
                        language=language,
                        directory=path.parent,
                    )
                    for rotation in (0, 90, 180, 270)
                ]
        except IngestionFailure:
            raise
        except Exception as exc:
            raise IngestionFailure("ocr_failed", stage="ocr") from exc
        return max(candidates, key=lambda candidate: candidate[1])

    def artifact_for_input(self, path: Path, *, mime: str) -> Artifact:
        regions: list[OCRRegion] = []
        confidence_values: list[float] = []
        if mime.startswith("image/"):
            page_regions, confidence = self.extract_image(path)
            regions.extend(page_regions)
            confidence_values.append(confidence)
        elif mime == "application/pdf":
            document = fitz.open(path)
            try:
                for page_index, page in enumerate(document, start=1):
                    if page.get_text().strip():
                        continue
                    pixmap = page.get_pixmap(
                        matrix=fitz.Matrix(2, 2),
                        alpha=False,
                    )
                    page_path = path.parent / f"ocr-source-page-{page_index}.png"
                    pixmap.save(page_path)
                    page_regions, confidence = self.extract_image(
                        page_path,
                        page=page_index,
                    )
                    regions.extend(page_regions)
                    confidence_values.append(confidence)
            finally:
                document.close()
        else:
            raise IngestionFailure("ocr_not_applicable", stage="ocr")
        if not confidence_values:
            raise IngestionFailure("ocr_not_applicable", stage="ocr")
        aggregate = (
            sum(confidence_values) / len(confidence_values)
            if confidence_values
            else 0.0
        )
        warnings = []
        if aggregate < 0.6:
            warnings.append("ocr_low_confidence")
        payload = OCRPayload(
            regions=regions,
            aggregate_confidence=aggregate,
            warnings=warnings,
        )
        quality_state: Literal["complete", "partial", "low_confidence"] = (
            "low_confidence" if warnings else "complete"
        )
        return Artifact(
            kind="ocr_json",
            mime_type="application/json",
            payload=canonical_json(payload.model_dump(mode="json")),
            origin="ocr",
            quality_state=quality_state,
            quality={
                "expected_units": 1 if mime.startswith("image/") else len(confidence_values),
                "extracted_units": len({region.page for region in regions}),
                "ocr_coverage": 1.0 if regions else 0.0,
                "aggregate_confidence": aggregate,
                "failed_units": 0 if regions else 1,
                "skipped_units": 0,
            },
            warnings=tuple(warnings),
            truncated=False,
        )


class LocalVoskTranscript:
    def __init__(self, settings: Settings, sandbox: ProcessSandbox) -> None:
        self.settings = settings
        self.sandbox = sandbox
        self.model_path = Path(settings.ingestion_vosk_model_path)

    def _validated_model(self) -> Path:
        if not self.settings.ingestion_transcript_enabled:
            raise IngestionFailure("transcript_unavailable", stage="transcribe")
        marker = self.model_path / ".archive-sha256"
        try:
            actual = marker.read_text(encoding="ascii").strip()
        except OSError as exc:
            raise IngestionFailure(
                "transcript_model_unavailable",
                stage="transcribe",
            ) from exc
        if actual != self.settings.ingestion_vosk_model_sha256:
            raise IngestionFailure("transcript_model_invalid", stage="transcribe")
        return self.model_path

    @staticmethod
    def _vtt_time(milliseconds: int) -> str:
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, millis = divmod(remainder, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"

    def transcribe(self, path: Path, *, duration_ms: int) -> list[Artifact]:
        model_path = self._validated_model()
        audio_path = path.parent / "transcript-source.wav"
        self.sandbox.run([
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-threads",
            "1",
            "-i",
            str(path.resolve()),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            "-threads:a",
            "1",
            "-y",
            str(audio_path.resolve()),
        ], temp_root=path.parent)
        try:
            result = self.sandbox.run([
                sys.executable,
                "-m",
                "rtr_copilot.ingestion.transcribe_cli",
                "--model",
                str(model_path.resolve()),
                "--audio",
                str(audio_path.resolve()),
            ], temp_root=path.parent)
            decoded = json.loads(result.stdout)
            segments = []
            for item in decoded["segments"]:
                normalized = dict(item)
                normalized["start_ms"] = min(
                    int(normalized["start_ms"]),
                    max(0, duration_ms - 1),
                )
                normalized["end_ms"] = min(
                    max(
                        int(normalized["end_ms"]),
                        normalized["start_ms"] + 1,
                    ),
                    duration_ms,
                )
                segments.append(TranscriptSegment(**normalized))
            payload = TranscriptPayload(
                duration_ms=duration_ms,
                language="en",
                segments=segments,
                warnings=[] if segments else ["transcript_empty"],
            )
        except IngestionFailure as exc:
            if exc.code.startswith("tool_exit_"):
                raise IngestionFailure(
                    "transcript_model_invalid",
                    stage="transcribe",
                ) from exc
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise IngestionFailure("transcript_failed", stage="transcribe") from exc
        confidences = [
            segment.confidence
            for segment in payload.segments
            if segment.confidence is not None
        ]
        aggregate = sum(confidences) / len(confidences) if confidences else 0.0
        warnings = tuple(payload.warnings)
        quality_state: Literal["complete", "partial", "low_confidence"] = (
            "partial" if warnings else "complete"
        )
        vtt_lines = ["WEBVTT", ""]
        for index, segment in enumerate(payload.segments, start=1):
            vtt_lines.extend([
                str(index),
                (
                    f"{self._vtt_time(segment.start_ms)} --> "
                    f"{self._vtt_time(segment.end_ms)}"
                ),
                segment.text,
                "",
            ])
        quality: dict[str, Any] = {
            "expected_units": 1,
            "extracted_units": len(payload.segments),
            "aggregate_confidence": aggregate,
            "duration_ms": duration_ms,
            "failed_units": 0 if payload.segments else 1,
            "skipped_units": 0,
        }
        return [
            Artifact(
                "transcript_json",
                "application/json",
                canonical_json(payload.model_dump(mode="json")),
                "transcript",
                quality_state,
                quality,
                warnings,
            ),
            Artifact(
                "transcript_vtt",
                "text/vtt",
                "\n".join(vtt_lines).encode("utf-8"),
                "transcript",
                quality_state,
                quality,
                warnings,
            ),
        ]
