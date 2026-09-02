import json
import shutil
import subprocess
import uuid
import wave
from pathlib import Path

import numpy as np

from .config import FFMPEG_BIN, FFPROBE_BIN


class FFmpegError(RuntimeError):
    pass


def _run_to_temp_then_replace(cmd: list[str], out_path: Path, label: str = "Command") -> None:
    """Run an ffmpeg command whose last arg is out_path, but write to a unique
    temp file first and atomically replace out_path only on success.

    Without this, a killed/crashed encode - or two requests racing on the
    same output filename (e.g. a clip edited twice before the first finishes)
    - leaves a half-written or interleaved, unplayable file at out_path with
    no error surfaced anywhere. Writing to a private temp name means a losing
    or failed writer never touches the file another reader/writer is using.
    """
    tmp_path = out_path.with_name(f".{out_path.stem}.{uuid.uuid4().hex[:8]}.tmp{out_path.suffix}")
    cmd = [*cmd[:-1], str(tmp_path.resolve())]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        raise FFmpegError(f"{label} failed for {out_path.name}:\n{result.stderr[-4000:]}")
    tmp_path.replace(out_path)


# Color-grading filters applied to the whole clip. Values are ffmpeg
# filtergraph fragments (chained with commas), keyed by an id the frontend
# sends back. "none" applies no filter.
FILTER_PRESETS: dict[str, str | None] = {
    "none": None,
    "vivid": "eq=saturation=1.5:contrast=1.15:brightness=0.03",
    "warm": "eq=saturation=1.1:brightness=0.02,colorbalance=rs=0.12:gs=0.02:bs=-0.12",
    "cool": "eq=saturation=1.05,colorbalance=rs=-0.1:bs=0.15",
    "bw": "hue=s=0,eq=contrast=1.1",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131:0",
    "vintage": "curves=preset=vintage,eq=contrast=1.05:saturation=0.85",
    "cinematic": "curves=preset=medium_contrast,eq=saturation=0.9:contrast=1.12,vignette=PI/5",
}

FILTER_LABELS: dict[str, str] = {
    "none": "None",
    "vivid": "Vivid",
    "warm": "Warm",
    "cool": "Cool",
    "bw": "Black & White",
    "sepia": "Sepia",
    "vintage": "Vintage",
    "cinematic": "Cinematic",
}

# Standalone effects, stacked on top of the chosen filter in this order.
# All are single-input/single-output filters so they can be comma-chained
# together in a plain -vf graph alongside the color filter above.
EFFECT_PRESETS: dict[str, str] = {
    "vignette": "vignette=PI/4",
    "grain": "noise=alls=14:allf=t+u",
    "sharpen": "unsharp=5:5:0.8:5:5:0.0",
    "soft_focus": "unsharp=5:5:-0.5:5:5:0.0",
}

EFFECT_LABELS: dict[str, str] = {
    "vignette": "Vignette",
    "grain": "Film Grain",
    "sharpen": "Sharpen",
    "soft_focus": "Soft Focus",
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise FFmpegError(f"Command failed: {' '.join(cmd)}\n{result.stderr[-4000:]}")
    return result


def probe_duration(path: Path) -> float:
    cmd = [
        FFPROBE_BIN,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    result = _run(cmd)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def extract_audio_wav(video_path: Path, out_wav: Path, sample_rate: int = 16000) -> None:
    """Extract mono PCM16 wav, suitable for both whisper and RMS energy analysis."""
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-c:a", "pcm_s16le",
        str(out_wav),
    ]
    _run(cmd)


def read_wav_rms(wav_path: Path, window_seconds: float = 0.5) -> tuple[np.ndarray, float]:
    """Returns (rms_per_window, window_seconds). RMS values are min-max normalized 0-1."""
    with wave.open(str(wav_path), "rb") as wf:
        n_frames = wf.getnframes()
        sample_rate = wf.getframerate()
        raw = wf.readframes(n_frames)

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    window_size = max(1, int(window_seconds * sample_rate))
    n_windows = max(1, len(samples) // window_size)
    trimmed = samples[: n_windows * window_size]
    windows = trimmed.reshape(n_windows, window_size)
    rms = np.sqrt(np.mean(windows**2, axis=1))
    peak = rms.max() if rms.max() > 0 else 1.0
    normalized = rms / peak
    return normalized, window_seconds


def format_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds % 1) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(segments: list, clip_start: float, srt_path: Path) -> None:
    with srt_path.open("w", encoding="utf-8") as f:
        for idx, seg in enumerate(segments, 1):
            rel_start = max(0.0, seg.start - clip_start)
            rel_end = max(rel_start + 0.1, seg.end - clip_start)
            f.write(f"{idx}\n")
            f.write(f"{format_srt_time(rel_start)} --> {format_srt_time(rel_end)}\n")
            clean_text = seg.text.strip().replace("\n", " ")
            f.write(f"{clean_text}\n\n")


def _build_edit_chain(filter_name: str | None, effects: list[str] | None) -> str:
    """Comma-chain of the color filter (if any) plus each requested effect."""
    chain = []
    preset_filter = FILTER_PRESETS.get(filter_name) if filter_name else None
    if preset_filter:
        chain.append(preset_filter)
    for effect_id in effects or []:
        effect_filter = EFFECT_PRESETS.get(effect_id)
        if effect_filter:
            chain.append(effect_filter)
    return ",".join(chain)


def render_vertical_clip(
    source_video: Path,
    start: float,
    duration: float,
    out_path: Path,
    burn_captions: bool = False,
    candidate_segments: list = None,
    bg_music_path: Path | None = None,
    bg_music_volume: float = 0.15,
    filter_name: str | None = None,
    effects: list[str] | None = None,
) -> None:
    """Cut a segment and crop/pad it to 9:16 HD (blurred-background pillarbox).

    Clips run 8-15 minutes now, so filter cost matters: boxblur at full
    1080x1920 over that many frames dominates render time far more than the
    encoder does. Blurring a tiny downscaled copy of the background and
    scaling it back up gives the same look for a fraction of the cost.

    `filter_name`/`effects` are baked in during this same encode pass (instead
    of a separate re-encode afterwards) so picking a look at creation time
    costs nothing extra beyond the filter's own negligible compute.
    """
    out_w, out_h = 1080, 1920

    overlay_out = "[base]"
    if burn_captions and candidate_segments:
        srt_path = out_path.with_suffix(".srt")
        generate_srt(candidate_segments, start, srt_path)

        srt_path_str = str(srt_path.resolve()).replace("\\", "/")
        if ":" in srt_path_str:
            drive, rest = srt_path_str.split(":", 1)
            srt_path_str = f"{drive}\\:{rest}"

        sub_style = "force_style='Fontname=Arial,Fontsize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=2,Alignment=2'"
        overlay_out = f"overlay=(W-w)/2:(H-h)/2,subtitles='{srt_path_str}':{sub_style}[base]"
    else:
        overlay_out = "overlay=(W-w)/2:(H-h)/2[base]"

    video_filter = (
        f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},scale=90:160,boxblur=6:3,scale={out_w}:{out_h}[bg];"
        f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]{overlay_out}"
    )

    final_video_label = "base"
    edit_chain = _build_edit_chain(filter_name, effects)
    if edit_chain:
        video_filter += f";[base]{edit_chain}[graded]"
        final_video_label = "graded"

    if bg_music_path and bg_music_path.exists():
        inputs = [
            "-ss", f"{start:.3f}",
            "-i", str(source_video.resolve()),
            "-stream_loop", "-1",
            "-i", str(bg_music_path.resolve()),
            "-t", f"{duration:.3f}",
        ]
        audio_filter = (
            f"[1:a]volume={bg_music_volume:.2f}[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        filter_complex = f"{video_filter};{audio_filter}"
        audio_maps = ["-map", "[aout]"]
    else:
        inputs = [
            "-ss", f"{start:.3f}",
            "-i", str(source_video.resolve()),
            "-t", f"{duration:.3f}",
        ]
        filter_complex = video_filter
        audio_maps = ["-map", "0:a?"]

    cmd = [
        FFMPEG_BIN, "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{final_video_label}]",
        *audio_maps,
        # Clips run 8-15 minutes, so preset dominates render time far more than
        # crf does (benchmarked: veryfast/crf20 at 1080p ~2.9x slower than the
        # old 720p/ultrafast/crf25 baseline; ultrafast/crf22 at the same 1080p
        # is only ~1.6x slower, matching the extra pixel count and nothing more).
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out_path.resolve()),
    ]
    _run_to_temp_then_replace(cmd, out_path, label="Render")


def apply_edits(
    source_path: Path,
    out_path: Path,
    filter_name: str | None,
    effects: list[str],
) -> None:
    """Re-encode an already-rendered clip with a color filter and/or effects stacked on top.

    `source_path` should be the untouched master render so repeated edits
    never compound quality loss from re-encoding an already-filtered file.
    """
    chain = _build_edit_chain(filter_name, effects)

    if not chain:
        tmp_path = out_path.with_name(f".{out_path.stem}.{uuid.uuid4().hex[:8]}.tmp{out_path.suffix}")
        shutil.copyfile(source_path, tmp_path)
        tmp_path.replace(out_path)
        return

    cmd = [
        FFMPEG_BIN, "-y",
        "-i", str(source_path.resolve()),
        "-vf", chain,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_path.resolve()),
    ]
    _run_to_temp_then_replace(cmd, out_path, label="Edit")


def generate_viral_thumbnail(
    source_video: Path,
    timestamp: float,
    headline_text: str,
    out_thumb_path: Path,
) -> Path:
    """Extract a 9:16 snapshot frame with dark gradient overlay and high-contrast bold headline text."""
    import textwrap

    out_w, out_h = 1080, 1920
    wrapped_headline = textwrap.fill(headline_text.upper(), width=22)

    txt_path = out_thumb_path.with_suffix(".txt")
    txt_path.write_text(wrapped_headline, encoding="utf-8")

    txt_path_str = str(txt_path.resolve()).replace("\\", "/")
    if ":" in txt_path_str:
        drive, rest = txt_path_str.split(":", 1)
        txt_path_str = f"{drive}\\:{rest}"

    # Windows dev box has Arial; Linux (Docker/Render) doesn't, so fall back
    # to a bundled-by-package font that's actually present in the container.
    _BOLD_FONT_CANDIDATES = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]
    bold_font = next((p for p in _BOLD_FONT_CANDIDATES if p.exists()), None)
    if bold_font:
        font_path_str = str(bold_font).replace("\\", "/")
        if ":" in font_path_str:
            d, r = font_path_str.split(":", 1)
            font_path_str = f"{d}\\:{r}"
        font_option = f":fontfile='{font_path_str}'"
    else:
        font_option = ":font='Arial'"

    filter_complex = (
        f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},scale=90:160,boxblur=6:3,scale={out_w}:{out_h}[bg];"
        f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base];"
        f"[base]drawbox=y=(ih-600)/2:color=black@0.65:w=iw:h=600:t=fill,"
        f"drawtext=textfile='{txt_path_str}'{font_option}:fontcolor=yellow:fontsize=66:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:bordercolor=black:borderw=7:line_spacing=18:align=center[out]"
    )

    cmd = [
        FFMPEG_BIN, "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", str(source_video.resolve()),
        "-vframes", "1",
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-q:v", "2",
        str(out_thumb_path.resolve()),
    ]

    try:
        _run(cmd)
    finally:
        txt_path.unlink(missing_ok=True)

    return out_thumb_path


