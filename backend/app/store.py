import json
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .config import MUSIC_DIR, OUTPUTS_DIR, STORAGE_DIR, UPLOADS_DIR
from .supabase_client import (
    delete_project_from_supabase,
    fetch_projects_from_supabase,
    upsert_project_to_supabase,
)

DB_FILE = STORAGE_DIR / "db.json"


class Status(str, Enum):
    QUEUED = "queued"
    FETCHING = "fetching"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    DONE = "done"
    ERROR = "error"


@dataclass
class Clip:
    id: str
    start: float
    end: float
    duration: float
    score: float
    score_breakdown: dict
    transcript: str
    file_path: str
    seo: dict
    thumbnail_path: str | None = None
    raw_file_path: str | None = None
    filter_name: str | None = None
    effects: list[str] = field(default_factory=list)


@dataclass
class Project:
    id: str
    source_type: str  # "upload" | "youtube"
    source: str
    status: Status = Status.QUEUED
    progress: str = ""
    error: str | None = None
    duration: float | None = None
    clips: list[Clip] = field(default_factory=list)
    target_duration_min: float = 10.0
    target_duration_sec: float = 600.0
    burn_captions: bool = False
    bg_music_path: str | None = None
    bg_music_volume: float = 0.15
    default_filter: str | None = None
    default_effects: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _serialize_project(project: Project) -> dict:
    d = asdict(project)
    d["status"] = project.status.value
    return d


def _deserialize_project(d: dict) -> Project:
    d = dict(d)  # shallow copy
    raw_clips = d.get("clips", [])
    clips = []
    for c in raw_clips:
        if isinstance(c, dict):
            c_dict = dict(c)
            if "thumbnail_path" not in c_dict:
                c_dict["thumbnail_path"] = None
            if "raw_file_path" not in c_dict:
                c_dict["raw_file_path"] = c_dict.get("file_path")
            if "filter_name" not in c_dict:
                c_dict["filter_name"] = None
            if "effects" not in c_dict:
                c_dict["effects"] = []
            clips.append(Clip(**c_dict))
        else:
            clips.append(c)
    d["clips"] = clips
    status_val = d.get("status", Status.QUEUED.value)
    d["status"] = Status(status_val) if isinstance(status_val, str) else status_val
    if "target_duration_sec" not in d:
        d["target_duration_sec"] = float(d.get("target_duration_min", 10.0)) * 60.0
    if "bg_music_path" not in d:
        d["bg_music_path"] = None
    if "bg_music_volume" not in d:
        d["bg_music_volume"] = 0.15
    return Project(**d)


class ProjectStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._projects: dict[str, Project] = {}
        self._load_all()

    def _load_all(self) -> None:
        if DB_FILE.exists():
            try:
                with DB_FILE.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    for pid, pdata in data.items():
                        self._projects[pid] = _deserialize_project(pdata)
            except Exception as e:
                print(f"Failed to load store DB: {e}")

        supa_data = fetch_projects_from_supabase()
        if supa_data is not None:
            for pdata in supa_data:
                try:
                    pid = pdata.get("id")
                    if pid:
                        self._projects[pid] = _deserialize_project(pdata)
                except Exception as e:
                    print(f"Error parsing project from Supabase: {e}")

    def _save_to_disk(self) -> None:
        try:
            data = {pid: _serialize_project(p) for pid, p in self._projects.items()}
            with DB_FILE.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to save store DB: {e}")

    def _sync_project(self, project: Project) -> None:
        self._save_to_disk()
        p_dict = _serialize_project(project)
        upsert_project_to_supabase(p_dict)

    def create(
        self,
        source_type: str,
        source: str,
        target_duration_min: float = 10.0,
        target_duration_sec: float = 600.0,
        burn_captions: bool = False,
        bg_music_path: str | None = None,
        bg_music_volume: float = 0.15,
        default_filter: str | None = None,
        default_effects: list[str] | None = None,
    ) -> Project:
        with self._lock:
            # Check for existing project with same source to prevent duplicate history items
            existing_pid = None
            for p in self._projects.values():
                if p.source_type == source_type and p.source == source:
                    existing_pid = p.id
                    break

            pid = existing_pid or str(uuid.uuid4())
            project = Project(
                id=pid,
                source_type=source_type,
                source=source,
                status=Status.QUEUED,
                progress="",
                error=None,
                clips=[],
                target_duration_min=target_duration_min,
                target_duration_sec=target_duration_sec,
                burn_captions=burn_captions,
                bg_music_path=bg_music_path,
                bg_music_volume=bg_music_volume,
                default_filter=default_filter,
                default_effects=default_effects or [],
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._projects[project.id] = project
            self._sync_project(project)
            return project

    def get(self, project_id: str) -> Project | None:
        with self._lock:
            return self._projects.get(project_id)

    def list(self) -> list[Project]:
        with self._lock:
            sorted_projects = sorted(self._projects.values(), key=lambda p: p.created_at, reverse=True)
            # Deduplicate by source so each project source appears exactly once in history
            seen_sources = set()
            unique_projects = []
            for p in sorted_projects:
                key = (p.source_type, p.source)
                if key not in seen_sources:
                    seen_sources.add(key)
                    unique_projects.append(p)
            return unique_projects

    def update(self, project_id: str, **kwargs) -> None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                return
            for key, value in kwargs.items():
                setattr(project, key, value)
            self._sync_project(project)

    def delete(self, project_id: str) -> bool:
        with self._lock:
            project = self._projects.pop(project_id, None)
            if project is None:
                return False
            self._save_to_disk()
            delete_project_from_supabase(project_id)

        self._delete_project_files(project_id, project)
        return True

    def _delete_project_files(self, project_id: str, project: "Project") -> None:
        # Deleting a project only ever dropped the JSON record; the rendered
        # clips/thumbnails and downloaded source video stayed on disk forever,
        # which is how storage silently fills up over repeated use.
        #
        # The record itself is already gone from the store by the time this
        # runs. A file still locked by another process (e.g. Windows holding
        # a handle open on a source video a just-killed ffmpeg/job was still
        # using) must not turn into a 500 for what the client correctly sees
        # as a successful delete - so every removal here is best-effort.
        output_dir = OUTPUTS_DIR / project_id
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)

        for upload_file in UPLOADS_DIR.glob(f"{project_id}.*"):
            try:
                upload_file.unlink(missing_ok=True)
            except OSError as e:
                print(f"Warning: could not delete {upload_file}: {e}")

        bg_music_path = getattr(project, "bg_music_path", None)
        if bg_music_path:
            bgm_path = Path(bg_music_path)
            if bgm_path.exists() and MUSIC_DIR not in bgm_path.resolve().parents:
                try:
                    bgm_path.unlink(missing_ok=True)
                except OSError as e:
                    print(f"Warning: could not delete {bgm_path}: {e}")


store = ProjectStore()
