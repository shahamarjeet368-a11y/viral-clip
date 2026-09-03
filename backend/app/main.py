import os
import threading
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import ffmpeg_utils
from .config import MUSIC_DIR, MUSIC_TRACK_DURATION, MUSIC_TRACKS, OUTPUTS_DIR, UPLOADS_DIR, RIGHTS_DISCLAIMER
from .pipeline import new_upload_path, start_project
from .security import (
    ALLOWED_AUDIO_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    MAX_UPLOAD_SIZE_BYTES,
    read_upload_with_limit,
    validate_extension,
    validate_video_url,
)
from .store import store

app = FastAPI(title="ViralCut AI")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Comma-separated extra origins (e.g. the deployed Vercel URL) via env var -
# no credentialed cookies are used anywhere in this app, so we don't need
# allow_credentials, and we don't want to reflect every origin (previous
# allow_origin_regex=r"https?://.*" + allow_credentials=True combo let any
# website on the internet make credentialed calls to this API).
_DEFAULT_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://viral-clip-mu.vercel.app",
]
_EXTRA_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

if "*" in _EXTRA_ORIGINS or os.environ.get("ALLOWED_ORIGINS", "").strip() == "*":
    cors_origins = ["*"]
else:
    cors_origins = list(set(_DEFAULT_ORIGINS + _EXTRA_ORIGINS))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/music", StaticFiles(directory=str(MUSIC_DIR)), name="music")


def _project_to_dict(project) -> dict:
    data = asdict(project)
    data["status"] = project.status.value
    return data


def _normalize_filter_and_effects(
    filter_name: str | None, effects: list[str] | None
) -> tuple[str | None, list[str]]:
    name = filter_name if filter_name and filter_name != "none" else None
    if name and name not in ffmpeg_utils.FILTER_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown filter: {name}")
    clean_effects = [e for e in (effects or []) if e in ffmpeg_utils.EFFECT_PRESETS]
    return name, clean_effects


@app.get("/")
def root():
    return {
        "message": "ViralCut AI Backend Server is running!",
        "health": "/api/health",
        "docs": "/docs"
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "disclaimer": RIGHTS_DISCLAIMER}


@app.get("/api/music-library")
def music_library():
    return [
        {
            "id": track["id"],
            "name": track["name"],
            "mood": track["mood"],
            "duration": MUSIC_TRACK_DURATION,
            "url": f"/music/{track['id']}.mp3",
        }
        for track in MUSIC_TRACKS
    ]


@app.post("/api/projects")
@limiter.limit("5/minute")
async def create_project(
    request: Request,
    confirm_rights: bool = Form(...),
    youtube_url: str | None = Form(None),
    video_url: str | None = Form(None),
    file: UploadFile | None = File(None),
    target_duration_min: float = Form(10.0),
    target_duration_sec: float | None = Form(None),
    burn_captions: bool = Form(False),
    bg_music_file: UploadFile | None = File(None),
    bg_music_track_id: str | None = Form(None),
    bg_music_volume: float = Form(0.15),
    filter_name: str | None = Form(None),
    effects: list[str] = Form([]),
):
    if not confirm_rights:
        raise HTTPException(
            status_code=400,
            detail="You must confirm you own or have rights to this video.",
        )

    url = video_url or youtube_url
    if not url and not file:
        raise HTTPException(status_code=400, detail="Provide a video file or a video URL (YouTube/Facebook).")
    if url and file:
        raise HTTPException(status_code=400, detail="Provide only one of file or video URL.")
    if url:
        url = validate_video_url(url)

    if target_duration_sec is None:
        target_duration_sec = float(target_duration_min) * 60.0

    default_filter, default_effects = _normalize_filter_and_effects(filter_name, effects)

    bg_music_path = None
    if bg_music_file and bg_music_file.filename:
        bgm_suffix = validate_extension(bg_music_file.filename, ALLOWED_AUDIO_EXTENSIONS)
        bgm_dest = UPLOADS_DIR / f"bgm_{uuid.uuid4()}{bgm_suffix}"
        await read_upload_with_limit(bg_music_file, bgm_dest)
        bg_music_path = str(bgm_dest)
    elif bg_music_track_id:
        track_path = MUSIC_DIR / f"{bg_music_track_id}.mp3"
        if not any(t["id"] == bg_music_track_id for t in MUSIC_TRACKS) or not track_path.exists():
            raise HTTPException(status_code=400, detail=f"Unknown music track: {bg_music_track_id}")
        bg_music_path = str(track_path)

    if file:
        validate_extension(file.filename or "", ALLOWED_VIDEO_EXTENSIONS)
        dest = new_upload_path(file.filename or "upload.mp4")
        await read_upload_with_limit(file, dest)
        project_id = start_project(
            "upload",
            file.filename or dest.name,
            target_duration_min=target_duration_min,
            target_duration_sec=target_duration_sec,
            burn_captions=burn_captions,
            bg_music_path=bg_music_path,
            bg_music_volume=bg_music_volume,
            uploaded_path=str(dest),
            default_filter=default_filter,
            default_effects=default_effects,
        )
    else:
        project_id = start_project(
            "youtube",
            url,
            target_duration_min=target_duration_min,
            target_duration_sec=target_duration_sec,
            burn_captions=burn_captions,
            bg_music_path=bg_music_path,
            bg_music_volume=bg_music_volume,
            default_filter=default_filter,
            default_effects=default_effects,
        )

    return {"project_id": project_id}


@app.get("/api/projects")
def list_projects():
    return [_project_to_dict(p) for p in store.list()]


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    project = store.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_to_dict(project)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    deleted = store.delete(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "deleted", "project_id": project_id}


class ClipUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    hashtags: dict[str, list[str]] | None = None


@app.patch("/api/projects/{project_id}/clips/{clip_id}")
def update_clip(project_id: str, clip_id: str, update: ClipUpdate):
    project = store.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    clip = next((c for c in project.clips if c.id == clip_id), None)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    if update.title is not None:
        clip.seo["selected_title"] = update.title
    if update.description is not None:
        clip.seo["description"] = update.description
    if update.hashtags is not None:
        clip.seo["hashtags"] = update.hashtags

    store.update(project_id, clips=project.clips)
    return asdict(clip)


def _resolve_output_path(url_path: str) -> Path:
    rel = url_path.split("/outputs/", 1)[1]
    return OUTPUTS_DIR / rel


# Two overlapping edit requests for the same clip both write to the same
# output filename; run concurrently they interleave/corrupt each other's
# output with no error surfaced anywhere. Reject the second one outright
# instead - clearer than silently producing a broken video.
_clips_being_edited: set[str] = set()
_clips_being_edited_lock = threading.Lock()


@app.get("/api/edit-options")
def edit_options():
    return {
        "filters": [
            {"id": key, "label": ffmpeg_utils.FILTER_LABELS[key]}
            for key in ffmpeg_utils.FILTER_PRESETS
        ],
        "effects": [
            {"id": key, "label": ffmpeg_utils.EFFECT_LABELS[key]}
            for key in ffmpeg_utils.EFFECT_PRESETS
        ],
    }


class ClipEditRequest(BaseModel):
    filter_name: str | None = None
    effects: list[str] = []


@app.post("/api/projects/{project_id}/clips/{clip_id}/edit")
@limiter.limit("20/minute")
def edit_clip(request: Request, project_id: str, clip_id: str, edit: ClipEditRequest):
    project = store.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    clip = next((c for c in project.clips if c.id == clip_id), None)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    with _clips_being_edited_lock:
        if clip_id in _clips_being_edited:
            raise HTTPException(
                status_code=409,
                detail="This clip is already being edited - please wait for it to finish before applying again.",
            )
        _clips_being_edited.add(clip_id)

    try:
        raw_rel_path = clip.raw_file_path or clip.file_path
        raw_path = _resolve_output_path(raw_rel_path)
        if not raw_path.exists():
            raise HTTPException(status_code=404, detail="Original clip file is missing on disk")

        filter_name, effects = _normalize_filter_and_effects(edit.filter_name, edit.effects)

        if not filter_name and not effects:
            clip.file_path = raw_rel_path
            clip.filter_name = None
            clip.effects = []
        else:
            edited_path = OUTPUTS_DIR / project_id / f"{clip_id}_edited.mp4"
            try:
                ffmpeg_utils.apply_edits(raw_path, edited_path, filter_name, effects)
            except ffmpeg_utils.FFmpegError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            clip.file_path = f"/outputs/{project_id}/{clip_id}_edited.mp4"
            clip.filter_name = filter_name
            clip.effects = effects

        store.update(project_id, clips=project.clips)
        return asdict(clip)
    finally:
        with _clips_being_edited_lock:
            _clips_being_edited.discard(clip_id)
