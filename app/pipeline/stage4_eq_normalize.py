"""
Stage 4 — EQ + Normalize.

Applies a presence-band EQ boost (helps speech intelligibility around
2-4kHz) and two-pass EBU R128 loudness normalization to a target LUFS via
FFmpeg's `loudnorm` filter. Two-pass is used (measure, then apply) because
single-pass loudnorm is noticeably less accurate for speech-length clips.

This is also where before/after SNR and peak/RMS metrics get computed for
the final `audio_metrics` block, since this is the last stage that touches
the raw waveform before diarization.
"""
import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from app.config import settings
from app.models.schema import PipelineResult
from app.utils.logger import get_logger

log = get_logger("stage4_eq_normalize")


def _estimate_snr_db(audio: np.ndarray, sr: int) -> float:
    """
    Rough SNR estimate: treat the quietest 10% of 20ms frames as the noise
    floor and the remaining frames as signal+noise. This is a heuristic
    (no ground-truth clean reference exists), good enough for a relative
    before/after comparison rather than an absolute SNR figure.
    """
    frame_len = max(int(sr * 0.02), 1)
    n_frames = len(audio) // frame_len
    if n_frames < 5:
        return 0.0
    frames = audio[: n_frames * frame_len].reshape(n_frames, frame_len)
    energies = np.mean(frames ** 2, axis=1)
    sorted_e = np.sort(energies)
    noise_floor = np.mean(sorted_e[: max(n_frames // 10, 1)]) + 1e-12
    signal_power = np.mean(energies) + 1e-12
    return float(10 * np.log10(signal_power / noise_floor))


def run(
    result: PipelineResult,
    clean_path: Path,
    original_path: Path,
    output_path: Path,
) -> PipelineResult:
    log.info(f"[{result.job_id}] EQ + loudness normalization")

    # --- Pass 1: measure loudness stats -------------------------------------
    target = settings.loudness_target_lufs
    eq_filter = "equalizer=f=3000:t=q:w=1.5:g=4"

    measure_cmd = [
        "ffmpeg", "-i", str(clean_path),
        "-af", f"{eq_filter},loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    proc = subprocess.run(measure_cmd, capture_output=True, text=True, timeout=600)

    stats = None
    try:
        start = proc.stderr.rindex("{")
        end = proc.stderr.rindex("}") + 1
        stats = json.loads(proc.stderr[start:end])
    except (ValueError, json.JSONDecodeError):
        log.warning(f"[{result.job_id}] Could not parse loudnorm measurement, using single-pass")

    # --- Pass 2: apply normalization -----------------------------------------
    if stats:
        loudnorm_apply = (
            f"loudnorm=I={target}:TP=-1.5:LRA=11:"
            f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
            f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
            f"offset={stats['target_offset']}:linear=true:print_format=summary"
        )
    else:
        loudnorm_apply = f"loudnorm=I={target}:TP=-1.5:LRA=11"

    apply_cmd = [
        "ffmpeg", "-y", "-i", str(clean_path),
        "-af", f"{eq_filter},{loudnorm_apply}",
        "-ar", str(settings.target_sample_rate),
        str(output_path),
    ]
    proc2 = subprocess.run(apply_cmd, capture_output=True, text=True, timeout=600)
    if proc2.returncode != 0:
        raise RuntimeError(f"Loudness normalization failed: {proc2.stderr.strip()[-800:]}")

    # --- Metrics: SNR before (original) vs after (final clean) -------------
    orig_audio, orig_sr = sf.read(original_path, dtype="float32")
    if orig_audio.ndim > 1:
        orig_audio = orig_audio.mean(axis=1)
    clean_audio, clean_sr = sf.read(output_path, dtype="float32")

    snr_before = _estimate_snr_db(orig_audio, orig_sr)
    snr_after = _estimate_snr_db(clean_audio, clean_sr)

    result.audio_metrics.snr_before_db = round(snr_before, 2)
    result.audio_metrics.snr_after_db = round(snr_after, 2)
    result.audio_metrics.snr_improvement_db = round(snr_after - snr_before, 2)
    result.audio_metrics.peak_before = round(float(np.max(np.abs(orig_audio))), 4)
    result.audio_metrics.peak_after = round(float(np.max(np.abs(clean_audio))), 4)

    noise_before = 10 ** (-snr_before / 10)
    noise_after = 10 ** (-snr_after / 10)
    removed_pct = max(0.0, (1 - (noise_after / noise_before))) * 100 if noise_before else 0.0
    result.audio_metrics.noise_removed_pct = round(removed_pct, 2)

    result.clean_audio_path = str(output_path)
    log.info(
        f"[{result.job_id}] SNR {snr_before:.1f} -> {snr_after:.1f} dB "
        f"({result.audio_metrics.noise_removed_pct}% noise removed)"
    )
    return result
