"""
API routes.

Maps 1:1 onto the README's API reference table. Routes themselves stay thin:
they validate the request, queue/read via JobStorage + Celery, and return
JSON or a file response — all real work happens in the pipeline stages.
"""
import json
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.models.schema import JobStatus, PipelineResult
from app.utils.audio_utils import AudioValidationError, validate_extension
from app.utils.logger import get_logger
from app.utils.storage import JobStorage
from app.workers.celery_app import celery_app
from app.workers.tasks import run_pipeline

router = APIRouter(prefix="/audio", tags=["audio"])
log = get_logger("api")


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    diarization_json: Optional[str] = Form(
        None, description="Optional pre-computed diarization segments as a JSON string"
    ),
):
    """Upload audio, returns job_id. Queues the 9-stage pipeline as a Celery task."""
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()

    try:
        validate_extension(Path(filename))
    except AudioValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.max_upload_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f}MB) — max is {settings.max_upload_mb}MB",
        )
    if size_mb == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    precomputed = None
    if diarization_json:
        try:
            precomputed = json.loads(diarization_json)
            if not isinstance(precomputed, list):
                raise ValueError("diarization_json must be a JSON array of segments")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(status_code=422, detail=f"Invalid diarization_json: {e}") from e

    job_id = str(uuid.uuid4())
    storage = JobStorage(job_id)
    storage.original_audio_path(ext).write_bytes(contents)

    from app.models.schema import PipelineResult

    storage.save_result(PipelineResult(job_id=job_id, status=JobStatus.QUEUED))

    run_pipeline.apply_async(
        args=[job_id, filename, precomputed],
        task_id=job_id,  # Celery task_id == job_id, so status polling needs only one ID
    )

    log.info(f"Queued job {job_id} for {filename} ({size_mb:.1f}MB)")
    return {"job_id": job_id, "status": "queued"}


def _get_result_or_404(job_id: str):
    storage = JobStorage(job_id)
    result = storage.load_result()
    if result is None:
        if storage.upload_dir.exists() and any(storage.upload_dir.glob("original.*")):
            task = celery_app.AsyncResult(job_id)
            status = JobStatus.QUEUED
            if task.state == "FAILURE":
                status = JobStatus.FAILED
            elif task.state in ("PROGRESS", "STARTED"):
                status = JobStatus.PROCESSING
            result = PipelineResult(job_id=job_id, status=status)
            return storage, result
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return storage, result


@router.get("/jobs/{job_id}/status")
async def job_status(job_id: str):
    """Poll job progress (0-100%)."""
    _, result = _get_result_or_404(job_id)

    task = celery_app.AsyncResult(job_id)
    task_meta = task.info if isinstance(task.info, dict) else {}

    return {
        "job_id": job_id,
        "status": result.status,
        "progress": task_meta.get("progress", result.progress),
        "current_stage": task_meta.get("stage"),
        "error": result.error,
    }


@router.get("/jobs/{job_id}/result")
async def job_result(job_id: str):
    """Full transcript JSON."""
    _, result = _get_result_or_404(job_id)
    if result.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Job is {result.status}, not completed yet",
        )
    return result.model_dump()


@router.get("/jobs/{job_id}/audio/original")
async def download_original(job_id: str):
    storage, result = _get_result_or_404(job_id)
    if not result.original_audio_path or not Path(result.original_audio_path).exists():
        raise HTTPException(status_code=404, detail="Original audio not found")
    return FileResponse(result.original_audio_path, filename=f"{job_id}_original{Path(result.original_audio_path).suffix}")


@router.get("/jobs/{job_id}/audio/clean")
async def download_clean(job_id: str):
    storage, result = _get_result_or_404(job_id)
    if not result.clean_audio_path or not Path(result.clean_audio_path).exists():
        raise HTTPException(status_code=404, detail="Enhanced audio not available yet")
    return FileResponse(result.clean_audio_path, filename=f"{job_id}_clean.wav")


@router.get("/jobs/{job_id}/spectrogram/original")
async def spectrogram_original(job_id: str):
    _, result = _get_result_or_404(job_id)
    path = result.spectrogram_paths.original
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Original spectrogram not available yet")
    return FileResponse(path, media_type="image/png")


@router.get("/jobs/{job_id}/spectrogram/cleaned")
async def spectrogram_cleaned(job_id: str):
    _, result = _get_result_or_404(job_id)
    path = result.spectrogram_paths.cleaned
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Cleaned spectrogram not available yet")
    return FileResponse(path, media_type="image/png")


@router.get("/jobs/{job_id}/metrics")
async def job_metrics(job_id: str):
    """SNR, noise removed %, RMS, processing time."""
    _, result = _get_result_or_404(job_id)
    return result.audio_metrics.model_dump()


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Clean up all files for a job."""
    storage, _ = _get_result_or_404(job_id)
    storage.delete_all()
    celery_app.control.revoke(job_id, terminate=True)
    log.info(f"Deleted job {job_id}")
    return {"job_id": job_id, "deleted": True}
