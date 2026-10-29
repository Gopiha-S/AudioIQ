import uuid

import pytest

from app.models.schema import DiarizedSegment, JobStatus, PipelineResult
from app.utils.audio_utils import AudioValidationError, validate_duration, validate_extension
from app.utils.storage import JobStorage
from pathlib import Path


def test_validate_extension_accepts_supported_formats():
    validate_extension(Path("clip.wav"))
    validate_extension(Path("clip.mp3"))


def test_validate_extension_rejects_unsupported_format():
    with pytest.raises(AudioValidationError):
        validate_extension(Path("clip.xyz"))


def test_validate_duration_rejects_too_short():
    from app.models.schema import AudioMetadata

    with pytest.raises(AudioValidationError):
        validate_duration(AudioMetadata(duration_seconds=0.1, sample_rate=16000, channels=1))


def test_job_storage_round_trip(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "storage_root", str(tmp_path))

    job_id = str(uuid.uuid4())
    storage = JobStorage(job_id)

    result = PipelineResult(job_id=job_id, status=JobStatus.PROCESSING)
    result.diarized_segments = [DiarizedSegment(start=0, end=1.5, speaker="SPEAKER_00")]
    storage.save_result(result)

    loaded = storage.load_result()
    assert loaded is not None
    assert loaded.job_id == job_id
    assert loaded.status == JobStatus.PROCESSING
    assert len(loaded.diarized_segments) == 1

    storage.delete_all()
    assert storage.load_result() is None
