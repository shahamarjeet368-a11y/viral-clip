import uuid
import subprocess
from pathlib import Path

import yt_dlp

from .config import BGUTIL_POT_BASE_URL, COOKIE_FILE, FFMPEG_BIN, UPLOADS_DIR
from .security import validate_video_url


# Client sets tried in order until one works. YouTube's anti-bot checks and
# PO-token requirements vary per client and change over time, so we fall
# back through several combinations rather than giving up after one.
_CLIENT_FALLBACKS = [
    ["mweb", "ios", "android", "web"],
    ["ios", "android"],
    ["mweb", "android"],
    None,
]


def _friendly_youtube_error(exc: Exception) -> str:
    """Translate a raw yt-dlp exception into an actionable message for the UI."""
    msg = str(exc)
    if "Sign in" in msg or "not a bot" in msg or "cookie" in msg.lower():
        return (
            "YouTube is blocking this download because it suspects a bot "
            "(this happens more often from server IPs). Please add a cookies.txt Secret File "
            "(exported from a browser signed into YouTube) on Render at /etc/secrets/cookies.txt, "
            "or try again with a different video."
        )
    if "Private video" in msg:
        return "This video is private and can't be downloaded."
    if (
        "unavailable" in msg.lower()
        or "failed to extract" in msg.lower()
        or "does not exist" in msg.lower()
    ):
        return "This video is unavailable (it may be deleted, private, region-blocked, or the URL is invalid)."
    return msg


def _download_video(url: str, dest_dir: Path) -> Path:
    """Download a video (YouTube or Facebook) with yt-dlp.

    Returns the absolute Path to the downloaded file.
    """
    dest_path = dest_dir / f"{uuid.uuid4()}.%(ext)s"
    base_opts = {
        "outtmpl": str(dest_path),
        "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/b[height<=720]/bestvideo+bestaudio/b/best",
        "noplaylist": True,
        "quiet": True,
        "concurrent_fragment_downloads": 8,
        "http_chunk_size": 10 * 1024 * 1024,
        "retries": 10,
        "socket_timeout": 15,
        "source_address": "0.0.0.0",
        "nocheckcertificate": True,
        "js_runtimes": {"node": {}},
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    if COOKIE_FILE and COOKIE_FILE.exists() and COOKIE_FILE.stat().st_size > 0:
        base_opts["cookiefile"] = str(COOKIE_FILE)

    # PO Token provider: only kicks in if a bgutil HTTP server is actually
    # reachable at this URL (see config.BGUTIL_POT_BASE_URL) - harmless no-op
    # otherwise, so it's always safe to pass.
    pot_extractor_args = {"youtubepot-bgutilhttp": {"base_url": [BGUTIL_POT_BASE_URL]}}

    info = None
    last_exc: Exception | None = None
    for clients in _CLIENT_FALLBACKS:
        extractor_args = {**pot_extractor_args}
        if clients is not None:
            extractor_args["youtube"] = {"player_client": clients}
        ydl_opts = {**base_opts, "extractor_args": extractor_args}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            continue

    if last_exc is not None:
        raise RuntimeError(_friendly_youtube_error(last_exc)) from last_exc

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
    url = validate_video_url(url)

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
    info_opts = {
        "quiet": True,
        "nocheckcertificate": True,
        "js_runtimes": {"node": {}},
        "source_address": "0.0.0.0",
        "extractor_args": {
            "youtube": {
                "player_client": ["tv_embedded", "android_vr", "ios", "mweb"],
            }
        },
    }
    if COOKIE_FILE and COOKIE_FILE.exists() and COOKIE_FILE.stat().st_size > 0:
        info_opts["cookiefile"] = str(COOKIE_FILE)

    try:
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        info = {}
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
