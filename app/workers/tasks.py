"""
The pipeline task.

One Celery task runs all 9 stages in sequence for a given job. Progress is
surfaced two ways so a client can poll either the Celery task state or the
job's own result JSON on disk (useful if the client only has the job_id and
not the Celery task_id):

  1. `self.update_state(state="PROGRESS", meta={"progress": N, "stage": ...})`
  2. `result.progress` is updated and persisted to storage after every stage.

If any stage raises, the exception is caught here (not per-stage) so a
single try/except keeps failure handling — status=FAILED, error captured,
result persisted — in exactly one place rather than duplicated 9 times.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models.schema import JobStatus, PipelineResult
from app.pipeline import (
    stage1_validate,
    stage2_preprocess,
    stage3_enhance,
    stage4_eq_normalize,
    stage5_vad,
    stage6_diarize,
    stage7_transcribe,
    stage8_role_map,
    stage9_assemble,
)
from app.utils.logger import get_logger
from app.utils.storage import JobStorage
from app.workers.celery_app import celery_app

log = get_logger("pipeline_task")

# (stage_number, percent_complete_after_this_stage)
STAGE_PROGRESS = {
    1: 5, 2: 15, 3: 40, 4: 55, 5: 62, 6: 78, 7: 92, 8: 96, 9: 100,
}


@celery_app.task(bind=True, name="app.workers.tasks.run_pipeline")
def run_pipeline(
    self,
    job_id: str,
    original_filename: str,
    precomputed_diarization: Optional[list[dict]] = None,
) -> dict:
    storage = JobStorage(job_id)
    result = storage.load_result() or PipelineResult(job_id=job_id)
    result.status = JobStatus.PROCESSING
    result.processing_start = datetime.now(timezone.utc)

    def checkpoint(stage_num: int, stage_name: str):
        result.progress = STAGE_PROGRESS[stage_num]
        storage.save_result(result)
        self.update_state(
            state="PROGRESS",
            meta={"progress": result.progress, "stage": stage_name, "job_id": job_id},
        )

    try:
        ext = Path(original_filename).suffix
        original_path = storage.original_audio_path(ext)
        preprocessed_path = storage.processed_dir / "preprocessed.wav"
        enhanced_path = storage.processed_dir / "enhanced.wav"
        clean_path = storage.clean_audio_path()

        # Stage 1: Validate
        result = stage1_validate.run(result, original_path)
        checkpoint(1, "validate")

        # Stage 2: Preprocess (FFmpeg filtering + format normalization)
        result = stage2_preprocess.run(result, original_path, preprocessed_path)
        checkpoint(2, "preprocess")

        # Stage 3: Enhance (DeepFilterNet noise suppression)
        result = stage3_enhance.run(result, preprocessed_path, enhanced_path)
        checkpoint(3, "enhance")

        # Stage 4: EQ + Normalize (presence EQ + two-pass loudnorm, computes metrics)
        result = stage4_eq_normalize.run(result, enhanced_path, original_path, clean_path)
        checkpoint(4, "eq_normalize")

        # Stage 5: VAD (speech ratio)
        result = stage5_vad.run(result, clean_path)
        checkpoint(5, "vad")

        # Stage 6: Diarize (Pyannote or pre-computed JSON)
        result = stage6_diarize.run(result, clean_path, precomputed_diarization)
        checkpoint(6, "diarize")

        # Stage 7: Transcribe (per-speaker faster-whisper)
        result = stage7_transcribe.run(result, clean_path)
        checkpoint(7, "transcribe")

        # Stage 8: Role Map (heuristic agent/customer assignment)
        result = stage8_role_map.run(result)
        checkpoint(8, "role_map")

        # Stage 9: Assemble (spectrograms, final metrics, status=COMPLETED)
        result = stage9_assemble.run(
            result,
            original_path,
            clean_path,
            storage.spectrogram_path("original"),
            storage.spectrogram_path("cleaned"),
        )
        storage.save_result(result)

        log.info(f"[{job_id}] Pipeline finished successfully")
        return {"job_id": job_id, "status": "completed"}

    except Exception as e:  # noqa: BLE001 — single centralized failure path, see docstring
        log.exception(f"[{job_id}] Pipeline failed: {e}")
        result.status = JobStatus.FAILED
        result.error = str(e)
        storage.save_result(result)
        # Re-raise so Celery also marks the task FAILURE for anyone polling task state directly.
        raise
