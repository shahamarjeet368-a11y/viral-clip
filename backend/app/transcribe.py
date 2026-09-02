import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from faster_whisper import WhisperModel

_models: dict[str, WhisperModel] = {}


def get_model(model_size: str) -> WhisperModel:
    if model_size not in _models:
        _models[model_size] = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            cpu_threads=os.cpu_count() or 4,
        )
    return _models[model_size]


def pick_model_size(duration_seconds: float) -> str:
    """Trade accuracy for speed on longer videos so total wait time stays reasonable."""
    if duration_seconds > 25 * 60:
        return "tiny"
    if duration_seconds > 10 * 60:
        return "base"
    return "small"


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word]


def transcribe(
    audio_path: Path,
    duration_seconds: float,
    on_progress: Callable[[float, float], None] | None = None,
) -> list[Segment]:
    model = get_model(pick_model_size(duration_seconds))
    raw_segments, _info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=True,
        beam_size=1,  # greedy decoding: several times faster on CPU, small accuracy cost
    )

    segments: list[Segment] = []
    for seg in raw_segments:
        words = [
            Word(start=w.start, end=w.end, text=w.word.strip())
            for w in (seg.words or [])
            if w.word.strip()
        ]
        segments.append(
            Segment(start=seg.start, end=seg.end, text=seg.text.strip(), words=words)
        )
        if on_progress:
            on_progress(seg.end, duration_seconds)
    return segments
