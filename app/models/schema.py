"""
Shared pipeline state schema.

A single `PipelineResult` instance is created when a job is queued and is
progressively filled in by each of the 9 stages. It is (de)serialized to/from
JSON at the storage layer between stages so job status/results can be polled
independently of the running Celery task.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AudioMetadata(BaseModel):
    duration_seconds: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    codec: str = ""
    format: str = ""
    speech_ratio: Optional[float] = None  # filled in by VAD stage


class DiarizedSegment(BaseModel):
    start: float
    end: float
    speaker: str  # e.g. "SPEAKER_00"


class SpeakerProfile(BaseModel):
    speaker_id: str
    role: Optional[str] = None          # e.g. "agent", "customer"
    role_confidence: float = 0.0
    word_count: int = 0
    turn_count: int = 0
    question_count: int = 0


class TranscriptTurn(BaseModel):
    speaker_id: str
    role: Optional[str] = None
    start: float
    end: float
    text: str
    confidence: float = 0.0


class AudioMetrics(BaseModel):
    snr_before_db: Optional[float] = None
    snr_after_db: Optional[float] = None
    snr_improvement_db: Optional[float] = None
    noise_removed_pct: Optional[float] = None
    rms_before: Optional[float] = None
    rms_after: Optional[float] = None
    peak_before: Optional[float] = None
    peak_after: Optional[float] = None
    processing_time_seconds: Optional[float] = None


class SpectrogramPaths(BaseModel):
    original: Optional[str] = None
    cleaned: Optional[str] = None


class PipelineResult(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0  # 0-100, surfaced via Celery task state too

    audio_metadata: AudioMetadata = Field(default_factory=AudioMetadata)
    diarized_segments: list[DiarizedSegment] = Field(default_factory=list)
    speaker_profiles: list[SpeakerProfile] = Field(default_factory=list)
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    audio_metrics: AudioMetrics = Field(default_factory=AudioMetrics)
    spectrogram_paths: SpectrogramPaths = Field(default_factory=SpectrogramPaths)

    # File paths (relative to storage root), populated as stages run
    original_audio_path: Optional[str] = None
    clean_audio_path: Optional[str] = None

    processing_start: Optional[datetime] = None
    processing_time_seconds: Optional[float] = None
    error: Optional[str] = None

    model_config = {"use_enum_values": True}
