import uuid
import subprocess
from pathlib import Path

import yt_dlp

from .config import FFMPEG_BIN, UPLOADS_DIR


def _download_video(url: str, dest_dir: Path) -> Path:
    """Download a video (YouTube or Facebook) with yt-dlp.

    Returns the absolute Path to the downloaded file.
    """
    dest_path = dest_dir / f"{uuid.uuid4()}.%(ext)s"
    ydl_opts = {
        "outtmpl": str(dest_path),
        "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/b[height<=720]/18/best",
        "noplaylist": True,
        "quiet": True,
        "concurrent_fragment_downloads": 8,
        "http_chunk_size": 10 * 1024 * 1024,
        "retries": 10,
        "socket_timeout": 15,
        "nocheckcertificate": True,
        "js_runtimes": {"node": {}},
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    # yt-dlp may have added an extension; locate the real file.
    pattern = dest_dir / f"{info.get('id', '*')}.*"
    matches = list(dest_dir.glob(pattern.name))
    if not matches:
        raise RuntimeError("Video download failed – no file found.")
    return matches[0]


def _trim_video(src: Path, max_len: int, out_dir: Path) -> Path:
    """Trim the first *max_len* seconds of *src* and place the result in *out_dir*.

    Returns the absolute Path to the trimmed clip.
    """
    out_path = out_dir / f"{uuid.uuid4()}.mp4"
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-i",
        str(src),
        "-t",
        str(max_len),
        # Use a fast preset to keep processing quick.
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg trimming failed: {result.stderr}")
    return out_path


def _generate_hashtags(title: str, limit: int = 5) -> list[str]:
    """Very simple hashtag generator – picks distinct alphanumeric words from the title.
    """
    words = [w for w in title.split() if w.isalnum()]
    seen = set()
    tags = []
    for w in words:
        w_clean = w.lower()
        if w_clean not in seen:
            seen.add(w_clean)
            tags.append(f"#{w_clean}")
        if len(tags) >= limit:
            break
    return tags


def process_short_video(url: str, max_len: int = 30) -> dict:
    """Download *url*, trim to *max_len* seconds, and produce hashtags & description.

    Returns a dictionary with keys ``video_path`` (relative URL), ``hashtags`` (list), and ``description`` (string).
    """
    # Prepare working directories.
    temp_dir = UPLOADS_DIR / "temp"
    short_dir = UPLOADS_DIR / "shorts"
    for d in (temp_dir, short_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Download the source video.
    downloaded_path = _download_video(url, temp_dir)

    # 2. Trim the video.
    trimmed_path = _trim_video(downloaded_path, max_len, short_dir)

    # 3. Grab title metadata for hashtags/description.
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    title = info.get("title", "Untitled")
    description = info.get("description", "") or title
    hashtags = _generate_hashtags(title)

    # Clean up the original download to save space.
    try:
        downloaded_path.unlink()
    except Exception:
        pass

    # Return a relative path suitable for serving via the existing static folder.
    rel_path = f"/uploads/shorts/{trimmed_path.name}"
    return {"video_path": rel_path, "hashtags": hashtags, "description": description}
