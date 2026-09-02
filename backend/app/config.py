import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
OUTPUTS_DIR = STORAGE_DIR / "outputs"
MUSIC_DIR = STORAGE_DIR / "music"

for d in (STORAGE_DIR, UPLOADS_DIR, OUTPUTS_DIR, MUSIC_DIR):
    d.mkdir(parents=True, exist_ok=True)

MUSIC_TRACK_DURATION = 40  # seconds; looped by ffmpeg to cover the full clip length

# Every track below is synthesized from scratch by generate_music.py (sine
# oscillators + noise textures, no external audio) so the whole library is
# 100% original and copyright-free to use in generated clips.
MUSIC_TRACKS = [
    {
        "id": "chill-vibes",
        "name": "Chill Vibes",
        "mood": "Calm ambient pad",
        "freqs": [220.00, 261.63, 329.63, 392.00],
        "extra": "chorus=0.6:0.9:55:0.4:0.25:2",
    },
    {
        "id": "upbeat-energy",
        "name": "Upbeat Energy",
        "mood": "Bright pulsing chord",
        "freqs": [261.63, 329.63, 392.00, 523.25],
        "extra": "tremolo=f=3:d=0.45",
    },
    {
        "id": "cinematic-epic",
        "name": "Cinematic Epic",
        "mood": "Deep dramatic drone",
        "freqs": [65.41, 98.00, 130.81],
        "extra": "aecho=0.8:0.85:900:0.3",
    },
    {
        "id": "lofi-chill",
        "name": "Lo-fi Chill",
        "mood": "Warm mellow loop",
        "freqs": [174.61, 220.00, 261.63, 329.63],
        "extra": "lowpass=f=3200",
    },
]

# Winget installs ffmpeg but doesn't refresh PATH for already-open shells.
# Fall back to the known winget install location if `ffmpeg` isn't resolvable yet.
_WINGET_FFMPEG_GLOB = list(
    Path.home().glob(
        "AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_*/ffmpeg-*-full_build/bin/ffmpeg.exe"
    )
)


def _resolve(binary: str, winget_matches: list[Path]) -> str:
    found = shutil.which(binary)
    if found:
        return found
    if winget_matches:
        return str(winget_matches[0])
    return binary  # let it fail loudly at call time with a clear error


FFMPEG_BIN = _resolve("ffmpeg", _WINGET_FFMPEG_GLOB)
FFPROBE_BIN = _resolve(
    "ffprobe",
    [p.parent / "ffprobe.exe" for p in _WINGET_FFMPEG_GLOB if (p.parent / "ffprobe.exe").exists()],
)

# Clip generation: long-form highlights, 8-15 minutes each.
CANDIDATE_DURATIONS = [480, 600, 720, 900]  # seconds (8, 10, 12, 15 min)
MAX_CLIPS_RETURNED = 4  # long clips leave little room for many non-overlapping picks
MIN_GAP_BETWEEN_CLIPS = 60  # seconds, avoids near-duplicate overlapping picks

RIGHTS_DISCLAIMER = (
    "Only process videos you own or have explicit rights to use. "
    "Processing third-party content without authorization may violate "
    "platform terms of service and copyright law."
)
