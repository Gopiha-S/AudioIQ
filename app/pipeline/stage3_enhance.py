"""
Stage 3 — Enhance.

Runs DeepFilterNet (2/3) deep-learning noise suppression over the
preprocessed audio. This is the heaviest CPU/GPU stage before diarization —
it's what actually removes background noise (fans, traffic, room hum)
rather than just filtering frequency bands like stage 2 did.

DeepFilterNet is an optional heavy dependency. If it isn't installed (or no
GPU is available and the CPU fallback path is undesired), this stage degrades
gracefully by copying the preprocessed audio through unchanged and flagging
that enhancement was skipped, rather than crashing the whole job.
"""
import shutil
from pathlib import Path

import numpy as np
import soundfile as sf

from app.config import settings
from app.models.schema import PipelineResult
from app.utils.logger import get_logger

log = get_logger("stage3_enhance")

_df_model = None
_df_state = None


def _load_deepfilternet():
    """Lazy-load DeepFilterNet so the API process doesn't pay this cost at import time."""
    global _df_model, _df_state
    if _df_model is not None:
        return _df_model, _df_state

    from df.enhance import init_df  # deepfilternet package

    log.info("Loading DeepFilterNet model (first call only)...")
    _df_model, _df_state, _ = init_df()
    return _df_model, _df_state


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


def run(result: PipelineResult, input_path: Path, output_path: Path) -> PipelineResult:
    log.info(f"[{result.job_id}] Enhancing (noise suppression)")

    audio_before, sr_before = sf.read(input_path, dtype="float32")
    rms_before = _rms(audio_before)

    try:
        from df.enhance import enhance
        import torch

        model, df_state = _load_deepfilternet()
        with torch.no_grad():
            audio_tensor = torch.from_numpy(audio_before).unsqueeze(0)
            enhanced = enhance(model, df_state, audio_tensor)
        enhanced_np = enhanced.squeeze(0).cpu().numpy()
        sf.write(output_path, enhanced_np, samplerate=settings.target_sample_rate)
        rms_after = _rms(enhanced_np)
        log.info(f"[{result.job_id}] DeepFilterNet enhancement applied")

    except Exception as e:  # noqa: BLE001 — deliberate: model may legitimately be unavailable
        log.warning(
            f"[{result.job_id}] DeepFilterNet unavailable ({e}); "
            "passing audio through unmodified"
        )
        shutil.copyfile(input_path, output_path)
        rms_after = rms_before

    result.audio_metrics.rms_before = round(rms_before, 6)
    result.audio_metrics.rms_after = round(rms_after, 6)
    return result
