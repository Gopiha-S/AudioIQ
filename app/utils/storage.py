"""
Local storage layer.

Every job gets its own subtree under STORAGE_ROOT:

    storage/
      uploads/{job_id}/original.<ext>
      processed/{job_id}/clean.wav
      processed/{job_id}/spectrogram_original.png
      processed/{job_id}/spectrogram_cleaned.png
      output/{job_id}/result.json

This module is the only place that knows about that directory layout —
pipeline stages and API routes go through it rather than hardcoding paths,
so the layout can change without touching stage logic.
"""
import json
from pathlib import Path

from app.config import settings
from app.models.schema import PipelineResult


class JobStorage:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.upload_dir = settings.storage_path / "uploads" / job_id
        self.processed_dir = settings.storage_path / "processed" / job_id
        self.output_dir = settings.storage_path / "output" / job_id
        for d in (self.upload_dir, self.processed_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)

    # --- raw / processed audio -------------------------------------------------
    def original_audio_path(self, ext: str) -> Path:
        return self.upload_dir / f"original{ext}"

    def clean_audio_path(self) -> Path:
        return self.processed_dir / "clean.wav"

    def spectrogram_path(self, which: str) -> Path:
        # which: "original" | "cleaned"
        return self.processed_dir / f"spectrogram_{which}.png"

    # --- result JSON --------------------------------------------------------
    def result_path(self) -> Path:
        return self.output_dir / "result.json"

    def save_result(self, result: PipelineResult) -> None:
        import os

        p = self.result_path()
        tmp_p = self.output_dir / f"result.tmp.{os.getpid()}"
        tmp_p.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_p, p)

    def load_result(self) -> PipelineResult | None:
        p = self.result_path()
        if not p.exists() or p.stat().st_size == 0:
            return None
        try:
            return PipelineResult.model_validate(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return None

    def delete_all(self) -> None:
        import shutil

        for d in (self.upload_dir, self.processed_dir, self.output_dir):
            shutil.rmtree(d, ignore_errors=True)
