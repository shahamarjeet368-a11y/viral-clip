from dataclasses import dataclass, field
import numpy as np

from .config import MAX_CLIPS_RETURNED, MIN_GAP_BETWEEN_CLIPS


@dataclass
class Candidate:
    start: float
    end: float
    text: str
    segments: list = None
    score: float = 0.0
    breakdown: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start


def _build_candidates(total_duration: float, target_duration_sec: float) -> list[Candidate]:
    candidates: list[Candidate] = []
    if total_duration <= 0:
        return []

    # If the video is shorter than the target duration, the target duration is the total video duration.
    actual_target = min(target_duration_sec, total_duration)

    # We sample candidates starting every 60 seconds (MIN_GAP_BETWEEN_CLIPS).
    # If the video is very short, we use a smaller step size to ensure we get candidates.
    step = min(60.0, max(5.0, actual_target / 4))
    
    start = 0.0
    while start + actual_target <= total_duration:
        end = start + actual_target
        candidates.append(
            Candidate(
                start=start,
                end=end,
                text="",
            )
        )
        start += step

    # If no candidates were built (e.g. video is very short or slightly shorter than actual_target),
    # add at least one candidate representing the full video.
    if not candidates:
        candidates.append(
            Candidate(
                start=0.0,
                end=total_duration,
                text="",
            )
        )
    return candidates


def _score_candidate(
    cand: Candidate,
    rms: np.ndarray,
    rms_window: float,
) -> None:
    start_idx = int(cand.start / rms_window)
    end_idx = max(start_idx + 1, int(cand.end / rms_window))
    
    energy_slice = rms[start_idx:end_idx] if start_idx < len(rms) else np.array([0.0])
    energy_score = float(np.mean(energy_slice)) if len(energy_slice) else 0.0
    energy_peak_score = float(np.max(energy_slice)) if len(energy_slice) else 0.0

    # Calculate final score: 60% average energy + 40% peak energy.
    raw = 0.6 * energy_score + 0.4 * energy_peak_score
    cand.score = round(raw * 100, 1)
    
    cand.breakdown = {
        "energy": round(energy_score * 100, 1),
        "energy_peak": round(energy_peak_score * 100, 1),
    }


def _select_top(candidates: list[Candidate]) -> list[Candidate]:
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    selected: list[Candidate] = []
    for cand in ranked:
        overlaps = any(
            cand.start < s.end + MIN_GAP_BETWEEN_CLIPS
            and s.start < cand.end + MIN_GAP_BETWEEN_CLIPS
            for s in selected
        )
        if not overlaps:
            selected.append(cand)
        if len(selected) >= MAX_CLIPS_RETURNED:
            break
    return sorted(selected, key=lambda c: c.score, reverse=True)


def _attach_transcript(cand: Candidate, segments: list, index: int) -> None:
    """Fill cand.text/cand.segments from whisper segments overlapping [cand.start, cand.end)."""
    overlapping = [s for s in segments if s.start < cand.end and s.end > cand.start]
    cand.segments = overlapping
    text = " ".join(s.text.strip() for s in overlapping if s.text.strip())
    cand.text = text or f"Viral Moment {index + 1}"


def find_viral_clips(
    total_duration: float,
    rms: np.ndarray,
    rms_window: float,
    target_duration_sec: float = 600.0,
    segments: list | None = None,
) -> list[Candidate]:
    candidates = _build_candidates(total_duration, target_duration_sec)
    for cand in candidates:
        _score_candidate(cand, rms, rms_window)

    selected = _select_top(candidates)

    for i, cand in enumerate(selected):
        if segments:
            _attach_transcript(cand, segments, i)
        else:
            cand.text = f"Viral Moment {i + 1}"

    return selected
