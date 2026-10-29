"""
Stage 5 — VAD (Voice Activity Detection).

Runs Silero VAD 5.1 over the cleaned audio to detect speech vs. silence
regions and compute the overall speech ratio. This feeds two things
downstream: (1) diarization can be skipped/short-circuited for
near-silent files, and (2) `speech_ratio` is a useful quality signal
surfaced in the final metadata (a low ratio on a "conversation" upload
usually means something upstream went wrong).
"""
from pathlib import Path

import torch

from app.models.schema import PipelineResult
from app.utils.logger import get_logger

log = get_logger("stage5_vad")

_vad_model = None
_vad_utils = None


def _load_silero():
    global _vad_model, _vad_utils
    if _vad_model is not None:
        return _vad_model, _vad_utils

    log.info("Loading Silero VAD model (first call only)...")
    model, utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
        onnx=False,
    )
    _vad_model, _vad_utils = model, utils
    return _vad_model, _vad_utils


def run(result: PipelineResult, audio_path: Path) -> PipelineResult:
    log.info(f"[{result.job_id}] Running VAD")

    sr = result.audio_metadata.sample_rate or 16000

    try:
        model, utils = _load_silero()
        get_speech_timestamps, _, read_audio, *_ = utils

        wav = read_audio(str(audio_path), sampling_rate=sr)
        speech_segments = get_speech_timestamps(wav, model, sampling_rate=sr)

        total_speech = sum((s["end"] - s["start"]) for s in speech_segments) / sr
        total_duration = len(wav) / sr
        speech_ratio = round(total_speech / total_duration, 4) if total_duration else 0.0

    except Exception as e:  # noqa: BLE001 — VAD model may be unavailable offline
        log.warning(f"[{result.job_id}] Silero VAD unavailable ({e}); assuming full speech")
        speech_ratio = 1.0

    result.audio_metadata.speech_ratio = speech_ratio
    log.info(f"[{result.job_id}] Speech ratio: {speech_ratio}")
    return result
