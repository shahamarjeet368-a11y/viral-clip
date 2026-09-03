"""Input-validation helpers shared by the upload and URL-ingest endpoints.

Centralized here so every entry point (HTTP handlers in main.py, the
background pipeline in pipeline.py) enforces the same rules instead of
each caller re-implementing its own checks slightly differently.
"""
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException

# --- File upload validation ------------------------------------------------

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav"}

MAX_UPLOAD_SIZE_BYTES = 500 * 1024 * 1024  # 500MB


def validate_extension(filename: str, allowed: set[str]) -> str:
    """Return the lowercased suffix if it's on the allow-list, else raise 400."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix or '(none)'}'. Allowed: {', '.join(sorted(allowed))}",
        )
    return suffix


async def read_upload_with_limit(upload_file, out_path: Path, max_bytes: int = MAX_UPLOAD_SIZE_BYTES) -> None:
    """Stream an UploadFile to disk, aborting with HTTP 400 if it exceeds max_bytes.

    Streams in chunks (never buffers the whole file in memory) and deletes
    the partial file on disk if the limit is exceeded, instead of silently
    truncating or letting an unbounded upload exhaust disk space.
    """
    import aiofiles

    total = 0
    try:
        async with aiofiles.open(out_path, "wb") as out:
            while chunk := await upload_file.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=400,
                        detail=f"File exceeds maximum allowed size of {max_bytes // (1024 * 1024)}MB.",
                    )
                await out.write(chunk)
    except HTTPException:
        out_path.unlink(missing_ok=True)
        raise
    except Exception:
        out_path.unlink(missing_ok=True)
        raise


# --- URL validation / SSRF prevention --------------------------------------

# Only these hosts may be handed to yt-dlp. Keeps user-submitted "video URL"
# input from being used to make the server fetch arbitrary/internal URLs
# (cloud metadata endpoints, internal services, localhost, etc).
TRUSTED_VIDEO_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "fb.watch",
}


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def validate_video_url(url: str) -> str:
    """Raise HTTP 400 unless `url` is a plain http(s) URL on a trusted domain.

    Defends against SSRF via the "video URL" field: rejects non-http(s)
    schemes (file://, gopher://, etc), embedded credentials, raw IP literals
    (blocks direct hits on internal/link-local/metadata addresses like
    169.254.169.254), and any host not on the explicit allow-list.
    """
    if not url or len(url) > 2048:
        raise HTTPException(status_code=400, detail="Invalid video URL.")

    parts = urlsplit(url.strip())

    if parts.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Video URL must use http or https.")

    if parts.username or parts.password:
        raise HTTPException(status_code=400, detail="Video URL must not contain credentials.")

    host = (parts.hostname or "").lower()
    if not host:
        raise HTTPException(status_code=400, detail="Invalid video URL.")

    if _is_ip_literal(host):
        raise HTTPException(status_code=400, detail="Video URL must be a domain name, not an IP address.")

    if host not in TRUSTED_VIDEO_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video source '{host}'. Only YouTube and Facebook URLs are accepted.",
        )

    return url.strip()


def resolves_to_public_address(host: str) -> bool:
    """Best-effort defense-in-depth against DNS-rebinding: confirm the
    hostname doesn't currently resolve to a private/loopback/link-local
    address before we let yt-dlp fetch it. Not a hard guarantee (TOCTOU),
    but cheap and catches the common case.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True
