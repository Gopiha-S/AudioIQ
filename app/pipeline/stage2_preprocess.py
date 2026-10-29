"""
Stage 2 — Preprocess.

Runs FFmpeg to normalize the incoming file to a single canonical format
(mono, TARGET_SAMPLE_RATE, 16-bit PCM WAV) and applies highpass/lowpass
filtering to strip out-of-band rumble and hiss before any ML stage touches
the signal. Every downstream stage can then assume a consistent format
regardless of what the user uploaded (mp3, m4a, webm, etc.).
"""
import subprocess
from pathlib import Path

from app.config import settings
from app.models.schema import PipelineResult
from app.utils.logger import get_logger

log = get_logger("stage2_preprocess")


class PreprocessError(Exception):
    pass


def run(result: PipelineResult, input_path: Path, output_path: Path) -> PipelineResult:
    log.info(f"[{result.job_id}] Preprocessing -> {output_path.name}")

    filters = f"highpass=f={settings.highpass_hz},lowpass=f={settings.lowpass_hz}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", filters,
        "-ac", "1",                                   # mono
        "-ar", str(settings.target_sample_rate),       # canonical sample rate
        "-sample_fmt", "s16",
        str(output_path),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise PreprocessError(f"FFmpeg preprocessing failed: {proc.stderr.strip()[-800:]}")

    log.info(f"[{result.job_id}] Preprocess complete")
    return result
