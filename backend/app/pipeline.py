import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yt_dlp
from . import video_processor

from . import ffmpeg_utils, seo, transcribe
from .config import COOKIE_FILE, FFMPEG_BIN, OUTPUTS_DIR, UPLOADS_DIR
from .scoring import Candidate, find_viral_clips
from .security import validate_video_url
from .store import Clip, Status, store

_executor = ThreadPoolExecutor(max_workers=2)


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _download_youtube(url: str, project_id: str) -> Path:
    # Defense-in-depth: main.py already validates this at the API boundary,
    # re-checking here means this background worker never hands yt-dlp a
    # URL from an untrusted/internal host even if some future caller of
    # start_project() skips the HTTP layer's validation.
    validate_video_url(url)
    out_path = UPLOADS_DIR / f"{project_id}.mp4"

    def on_progress(d: dict) -> None:
        if d["status"] == "downloading":
            pct = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()
            store.update(
                project_id,
                progress=f"Downloading video... {pct} at {speed} (ETA {eta})",
            )
        elif d["status"] == "finished":
            store.update(project_id, progress="Download complete, preparing video...")

    base_opts = {
        "outtmpl": str(out_path.with_suffix(".%(ext)s")),
        # Ends in an unrestricted "b/best" so that if the [height<=720][ext=mp4]
        # filters don't match anything for a given player client (e.g. it only
        # exposes webm/HLS formats), download still proceeds instead of raising
        # "Requested format is not available".
        "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/b[height<=720]/bestvideo+bestaudio/b/best",
        "noplaylist": True,
        "quiet": True,
        "progress_hooks": [on_progress],
        "ffmpeg_location": str(Path(FFMPEG_BIN).parent),
        "nocheckcertificate": True,
        "socket_timeout": 15,
        "retries": 10,
        "source_address": "0.0.0.0",
        "js_runtimes": {"node": {}},
        "concurrent_fragment_downloads": 8,
        "http_chunk_size": 10 * 1024 * 1024,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    if COOKIE_FILE and COOKIE_FILE.exists() and COOKIE_FILE.stat().st_size > 0:
        base_opts["cookiefile"] = str(COOKIE_FILE)

    last_exc: Exception | None = None
    for clients in video_processor._CLIENT_FALLBACKS:
        if clients is not None:
            ydl_opts = {**base_opts, "extractor_args": {"youtube": {"player_client": clients}}}
        else:
            ydl_opts = {**base_opts}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            continue

    if last_exc is not None:
        raise RuntimeError(video_processor._friendly_youtube_error(last_exc)) from last_exc

    if not out_path.exists():
        candidates = list(UPLOADS_DIR.glob(f"{project_id}.*"))
        if not candidates:
            raise RuntimeError("Download finished but output file was not found.")
        out_path = candidates[0]
    return out_path


def _build_clip(
    candidate: Candidate,
    source_video: Path,
    project_id: str,
    index: int,
    burn_captions: bool,
    bg_music_path: Path | None = None,
    bg_music_volume: float = 0.15,
    filter_name: str | None = None,
    effects: list[str] | None = None,
) -> Clip:
    clip_id = f"{project_id}-{index}"
    clip_dir = OUTPUTS_DIR / project_id
    clip_dir.mkdir(parents=True, exist_ok=True)

    out_path = clip_dir / f"{clip_id}.mp4"
    ffmpeg_utils.render_vertical_clip(
        source_video=source_video,
        start=candidate.start,
        duration=candidate.duration,
        out_path=out_path,
        burn_captions=burn_captions,
        candidate_segments=candidate.segments if burn_captions else None,
        bg_music_path=bg_music_path,
        bg_music_volume=bg_music_volume,
        filter_name=filter_name,
        effects=effects,
    )

    seo_data = seo.generate_seo(candidate.text)

    headline = seo_data.get("selected_title") or (
        seo_data.get("titles")[0] if seo_data.get("titles") else "VIRAL CLIP"
    )
    thumb_path = clip_dir / f"{clip_id}_thumb.jpg"
    thumb_timestamp = candidate.start + (candidate.duration / 2.0)
    thumbnail_rel_path = None
    try:
        ffmpeg_utils.generate_viral_thumbnail(
            source_video=source_video,
            timestamp=thumb_timestamp,
            headline_text=headline,
            out_thumb_path=thumb_path,
        )
        thumbnail_rel_path = f"/outputs/{project_id}/{clip_id}_thumb.jpg"
    except Exception as err:
        print(f"Warning: Thumbnail generation failed for {clip_id}: {err}")

    raw_rel_path = f"/outputs/{project_id}/{clip_id}.mp4"
    return Clip(
        id=clip_id,
        start=round(candidate.start, 2),
        end=round(candidate.end, 2),
        duration=round(candidate.duration, 2),
        score=candidate.score,
        score_breakdown=candidate.breakdown,
        transcript=candidate.text,
        file_path=raw_rel_path,
        seo=seo_data,
        thumbnail_path=thumbnail_rel_path,
        raw_file_path=raw_rel_path,
        filter_name=filter_name,
        effects=effects or [],
    )


def _run(project_id: str, uploaded_path: str | None) -> None:
    try:
        project = store.get(project_id)
        assert project is not None

        if project.source_type == "youtube":
            store.update(project_id, status=Status.FETCHING, progress="Downloading video...")
            video_path = _download_youtube(project.source, project_id)
        else:
            assert uploaded_path is not None
            video_path = Path(uploaded_path)

        duration = ffmpeg_utils.probe_duration(video_path)
        store.update(project_id, duration=duration)

        store.update(project_id, status=Status.TRANSCRIBING, progress="Extracting audio...")
        audio_path = UPLOADS_DIR / f"{project_id}.wav"
        ffmpeg_utils.extract_audio_wav(video_path, audio_path)

        def _on_transcribe_progress(done: float, total: float) -> None:
            pct = round(min(done, total) / total * 100) if total else 0
            store.update(project_id, progress=f"Transcribing speech... {pct}%")

        store.update(project_id, progress="Transcribing speech... 0%")
        segments = transcribe.transcribe(audio_path, duration, on_progress=_on_transcribe_progress)

        store.update(project_id, status=Status.ANALYZING, progress="Scoring viral potential...")
        rms, rms_window = ffmpeg_utils.read_wav_rms(audio_path)
        target_duration_sec = getattr(project, "target_duration_sec", None) or ((project.target_duration_min or 10) * 60)
        candidates = find_viral_clips(duration, rms, rms_window, target_duration_sec, segments)

        if not candidates:
            store.update(
                project_id,
                status=Status.ERROR,
                error="No speech content found to build clips from.",
            )
            return

        store.update(
            project_id,
            status=Status.RENDERING,
            progress=f"Rendering {len(candidates)} clips...",
        )
        bg_music_p = Path(project.bg_music_path) if project.bg_music_path else None
        bg_music_vol = getattr(project, "bg_music_volume", 0.15)
        clips = []
        for i, candidate in enumerate(candidates):
            pct = round(i / len(candidates) * 100)
            store.update(
                project_id,
                progress=f"Rendering clip {i + 1} of {len(candidates)}... ({pct}%)",
            )
            clips.append(
                _build_clip(
                    candidate,
                    video_path,
                    project_id,
                    i,
                    project.burn_captions,
                    bg_music_path=bg_music_p,
                    bg_music_volume=bg_music_vol,
                    filter_name=getattr(project, "default_filter", None),
                    effects=getattr(project, "default_effects", None),
                )
            )

        store.update(project_id, status=Status.DONE, progress="Done", clips=clips)

    except Exception as exc:  # noqa: BLE001 - surfaced to the client, not swallowed
        traceback.print_exc()
        store.update(project_id, status=Status.ERROR, error=str(exc))


def start_project(
    source_type: str,
    source: str,
    target_duration_min: float = 10.0,
    target_duration_sec: float | None = None,
    burn_captions: bool = False,
    bg_music_path: str | None = None,
    bg_music_volume: float = 0.15,
    uploaded_path: str | None = None,
    default_filter: str | None = None,
    default_effects: list[str] | None = None,
) -> str:
    if target_duration_sec is None:
        target_duration_sec = float(target_duration_min) * 60.0
    else:
        target_duration_min = round(target_duration_sec / 60.0, 1)

    project = store.create(
        source_type=source_type,
        source=source,
        target_duration_min=target_duration_min,
        target_duration_sec=target_duration_sec,
        burn_captions=burn_captions,
        bg_music_path=bg_music_path,
        bg_music_volume=bg_music_volume,
        default_filter=default_filter,
        default_effects=default_effects,
    )
    _executor.submit(_run, project.id, uploaded_path)
    return project.id


def new_upload_path(filename: str) -> Path:
    # Existing function retained
    suffix = Path(filename).suffix or ".mp4"
    return UPLOADS_DIR / f"{uuid.uuid4()}{suffix}"


def process_short_video(url: str, max_len: int = 30) -> dict:
    """Download a video from YouTube or Facebook, trim to a short clip, and generate metadata.

    Returns a dictionary with keys:
        - video_path: str (relative path to the trimmed clip)
        - hashtags: list[str]
        - description: str
    """
    return video_processor.process_short_video(url, max_len)
