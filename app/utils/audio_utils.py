"""
Low-level audio inspection helpers built on `ffprobe`.

Kept separate from the pipeline stages so both stage 1 (validation) and the
FastAPI upload route (for a fast early rejection before a job is even queued)
can reuse the same probing logic.
"""
import json
import subprocess
from pathlib import Path

from app.models.schema import AudioMetadata

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".aac"}
MIN_DURATION_SECONDS = 1.0
MAX_DURATION_SECONDS = 4 * 60 * 60  # 4 hours


class AudioValidationError(Exception):
    pass


def ffprobe(path: Path) -> dict:
    """Run ffprobe and return the parsed JSON stream/format info."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as e:
        raise AudioValidationError(
            "ffprobe not found — is FFmpeg installed and on PATH?"
        ) from e

    if proc.returncode != 0:
        raise AudioValidationError(f"ffprobe failed: {proc.stderr.strip()}")

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise AudioValidationError("Could not parse ffprobe output") from e


def probe_audio_metadata(path: Path) -> AudioMetadata:
    """Extract duration/sample-rate/channels/codec via ffprobe."""
    info = ffprobe(path)
    audio_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio_streams:
        raise AudioValidationError("No audio stream found in file")

    stream = audio_streams[0]
    fmt = info.get("format", {})

    duration = float(fmt.get("duration") or stream.get("duration") or 0.0)

    return AudioMetadata(
        duration_seconds=round(duration, 3),
        sample_rate=int(stream.get("sample_rate") or 0),
        channels=int(stream.get("channels") or 0),
        codec=stream.get("codec_name", "unknown"),
        format=fmt.get("format_name", "unknown"),
    )


def validate_extension(path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise AudioValidationError(
            f"Unsupported file extension '{path.suffix}'. "
            f"Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )


def validate_duration(meta: AudioMetadata) -> None:
    if meta.duration_seconds < MIN_DURATION_SECONDS:
        raise AudioValidationError(
            f"Audio too short ({meta.duration_seconds}s) — minimum is {MIN_DURATION_SECONDS}s"
        )
    if meta.duration_seconds > MAX_DURATION_SECONDS:
        raise AudioValidationError(
            f"Audio too long ({meta.duration_seconds}s) — maximum is {MAX_DURATION_SECONDS}s"
        )
