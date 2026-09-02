"""One-time generator for the bundled royalty-free background music library.

Every track is synthesized from scratch with ffmpeg's audio oscillators and
noise sources (sine chords, tremolo, echo, lowpass, chorus) - no external
audio is used or downloaded, so the whole library is 100% original and safe
to use in generated clips without any copyright concerns.

Run with: python -m app.generate_music
"""
import subprocess

from .config import FFMPEG_BIN, MUSIC_DIR, MUSIC_TRACKS, MUSIC_TRACK_DURATION


def _generate_track(track: dict) -> None:
    out_path = MUSIC_DIR / f"{track['id']}.mp3"
    inputs = []
    for freq in track["freqs"]:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={MUSIC_TRACK_DURATION}"]

    n = len(track["freqs"])
    mix_inputs = "".join(f"[{i}:a]" for i in range(n))
    fade_out_start = MUSIC_TRACK_DURATION - 4
    filter_complex = (
        f"{mix_inputs}amix=inputs={n}:duration=longest[mix];"
        f"[mix]{track['extra']},"
        f"afade=t=in:d=3,afade=t=out:st={fade_out_start}:d=4,volume=0.5[out]"
    )

    cmd = [
        FFMPEG_BIN, "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "128k",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def generate_all() -> None:
    for track in MUSIC_TRACKS:
        _generate_track(track)


if __name__ == "__main__":
    generate_all()
    print(f"Generated {len(MUSIC_TRACKS)} tracks in {MUSIC_DIR}")
