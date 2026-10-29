"""
Stage 9 — Assemble.

Final stage: generates before/after spectrogram PNGs, stamps total
processing time, and flips job status to COMPLETED. This is intentionally
the only stage allowed to change `result.status`, so status transitions
are traceable to one place.
"""
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — this runs inside a Celery worker, no display
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

from app.models.schema import JobStatus, PipelineResult
from app.utils.logger import get_logger

log = get_logger("stage9_assemble")


def _save_spectrogram(audio_path: Path, out_path: Path, title: str) -> str:
    audio, sr = sf.read(audio_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.specgram(audio, Fs=sr, NFFT=1024, noverlap=512, cmap="magma")
    ax.set_title(title)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Frequency (Hz)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return str(out_path)


def run(
    result: PipelineResult,
    original_audio_path: Path,
    clean_audio_path: Path,
    spectrogram_original_path: Path,
    spectrogram_cleaned_path: Path,
) -> PipelineResult:
    log.info(f"[{result.job_id}] Assembling final result")

    try:
        result.spectrogram_paths.original = _save_spectrogram(
            original_audio_path, spectrogram_original_path, "Original"
        )
        result.spectrogram_paths.cleaned = _save_spectrogram(
            clean_audio_path, spectrogram_cleaned_path, "Cleaned"
        )
    except Exception as e:  # noqa: BLE001 — spectrograms are a nice-to-have, not fatal
        log.warning(f"[{result.job_id}] Spectrogram generation failed: {e}")

    if result.processing_start:
        elapsed = (datetime.now(timezone.utc) - result.processing_start).total_seconds()
        result.processing_time_seconds = round(elapsed, 2)
        result.audio_metrics.processing_time_seconds = result.processing_time_seconds

    result.status = JobStatus.COMPLETED
    result.progress = 100
    log.info(f"[{result.job_id}] Job completed in {result.processing_time_seconds}s")
    return result
