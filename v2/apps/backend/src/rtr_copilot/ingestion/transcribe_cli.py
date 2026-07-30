"""Offline Vosk child process. Stdout is schema data; stderr is never client-facing."""

import argparse
import json
import wave
from pathlib import Path
from typing import Any

from vosk import KaldiRecognizer, Model, SetLogLevel  # type: ignore[import-untyped]


def transcribe(model_path: Path, audio_path: Path) -> dict[str, Any]:
    SetLogLevel(-1)
    with wave.open(str(audio_path), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getframerate() != 16_000
        ):
            raise ValueError("audio_shape_invalid")
        recognizer = KaldiRecognizer(Model(str(model_path)), 16_000)
        recognizer.SetWords(True)
        results: list[dict[str, Any]] = []
        while payload := source.readframes(4_000):
            if recognizer.AcceptWaveform(payload):
                results.append(json.loads(recognizer.Result()))
        results.append(json.loads(recognizer.FinalResult()))
    segments = []
    for result in results:
        words = list(result.get("result", []))
        text_value = str(result.get("text", "")).strip()
        if not words or not text_value:
            continue
        segments.append({
            "start_ms": round(float(words[0]["start"]) * 1000),
            "end_ms": round(float(words[-1]["end"]) * 1000),
            "text": text_value,
            "confidence": round(
                sum(float(word.get("conf", 0.0)) for word in words) / len(words),
                6,
            ),
            "origin": "transcript",
        })
    return {"schema_version": 1, "segments": segments}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(
        transcribe(arguments.model, arguments.audio),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
