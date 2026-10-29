"""
Central configuration for AudioIQ.

All tunables live here and are sourced from a `.env` file at the project
root. Every pipeline stage and the Celery app import `settings` from this
module instead of reading os.environ directly, so there is a single source
of truth for configuration.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Model access -----------------------------------------------------
    hf_token: str = ""

    # --- Transcription ------------------------------------------------------
    whisper_model: str = "medium"
    device: str = "cuda"          # "cuda" or "cpu" — pipeline auto-falls back
    compute_type: str = "float16"  # use "int8" or "float32" on CPU

    # --- Audio processing -----------------------------------------------
    target_sample_rate: int = 16000
    highpass_hz: int = 80
    lowpass_hz: int = 8000
    loudness_target_lufs: float = -16.0

    # --- Queue ------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
 
    # --- Diarization --------------------------------------------------------
    diarization_min_speakers: int = 2
    diarization_max_speakers: int = 4

    # --- System -------------------------------------------------------------
    log_level: str = "INFO"
    storage_root: str = "./storage"
    max_upload_mb: int = 200

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_root)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
