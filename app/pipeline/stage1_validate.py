"""
Stage 1 — Validate.

Checks duration, format, and sample rate before the job is allowed onto the
rest of the pipeline. This runs fast and cheap so obviously-bad uploads
(corrupt files, silence, wrong container) fail immediately instead of
burning GPU time three stages later.
"""
from pathlib import Path

from app.models.schema import PipelineResult
from app.utils.audio_utils import (
    AudioValidationError,
    probe_audio_metadata,
    validate_duration,
    validate_extension,
)
from app.utils.logger import get_logger

log = get_logger("stage1_validate")


def run(result: PipelineResult, audio_path: Path) -> PipelineResult:
    log.info(f"[{result.job_id}] Validating {audio_path.name}")

    validate_extension(audio_path)
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise AudioValidationError("Uploaded file is missing or empty")

    meta = probe_audio_metadata(audio_path)
    validate_duration(meta)

    if meta.sample_rate == 0 or meta.channels == 0:
        raise AudioValidationError("Could not determine sample rate/channel count")

    result.audio_metadata = meta
    result.original_audio_path = str(audio_path)
    log.info(
        f"[{result.job_id}] OK — {meta.duration_seconds}s, "
        f"{meta.sample_rate}Hz, {meta.channels}ch, codec={meta.codec}"
    )
    return result
