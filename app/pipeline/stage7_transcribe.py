"""
Stage 7 — Transcribe.

Runs faster-whisper independently over each diarized segment, so each turn
in the final transcript is attributed to the correct speaker rather than
transcribing the whole file once and guessing at speaker boundaries
afterward. Segments shorter than MIN_SEGMENT_SECONDS are merged with their
neighbor of the same speaker first to avoid wasting a full model call on a
100ms blip.
"""
from pathlib import Path

import numpy as np
import soundfile as sf

from app.config import settings
from app.models.schema import DiarizedSegment, PipelineResult, TranscriptTurn
from app.utils.logger import get_logger

log = get_logger("stage7_transcribe")

MIN_SEGMENT_SECONDS = 0.3

_whisper_model = None


def _load_whisper():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    from faster_whisper import WhisperModel
    import torch

    device = settings.device
    compute_type = settings.compute_type

    if device == "cuda" and not torch.cuda.is_available():
        log.warning("CUDA requested but not available. Falling back to CPU (compute_type='int8').")
        device = "cpu"
        if compute_type == "float16":
            compute_type = "int8"

    log.info(f"Loading faster-whisper '{settings.whisper_model}' on {device} ({compute_type}) (first call only)...")
    _whisper_model = WhisperModel(
        settings.whisper_model,
        device=device,
        compute_type=compute_type,
    )
    return _whisper_model


def _merge_short_segments(segments: list[DiarizedSegment]) -> list[DiarizedSegment]:
    if not segments:
        return segments
    merged = [segments[0]]
    for seg in segments[1:]:
        prev = merged[-1]
        if seg.speaker == prev.speaker and (seg.start - prev.end) < 0.5:
            merged[-1] = DiarizedSegment(start=prev.start, end=seg.end, speaker=prev.speaker)
        else:
            merged.append(seg)
    return merged


def run(result: PipelineResult, audio_path: Path) -> PipelineResult:
    log.info(f"[{result.job_id}] Transcribing {len(result.diarized_segments)} segment(s)")

    if not result.diarized_segments:
        result.transcript = []
        return result

    audio, sr = sf.read(audio_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    segments = _merge_short_segments(result.diarized_segments)
    model = None
    turns: list[TranscriptTurn] = []

    for seg in segments:
        duration = seg.end - seg.start
        if duration < MIN_SEGMENT_SECONDS:
            continue

        start_sample = max(int(seg.start * sr), 0)
        end_sample = min(int(seg.end * sr), len(audio))
        chunk = audio[start_sample:end_sample]
        if chunk.size == 0:
            continue

        try:
            if model is None:
                model = _load_whisper()
            segments_out, info = model.transcribe(chunk, language=None, vad_filter=False)
            text_parts = []
            confidences = []
            for s in segments_out:
                text_parts.append(s.text.strip())
                if s.avg_logprob is not None:
                    confidences.append(np.exp(s.avg_logprob))  # rough prob proxy
            text = " ".join(t for t in text_parts if t)
            confidence = round(float(np.mean(confidences)), 3) if confidences else 0.0
        except Exception as e:  # noqa: BLE001 — model unavailable / decode failure for this chunk
            log.error(f"[{result.job_id}] Transcription failed for segment {seg.start}-{seg.end}: {e}")
            text, confidence = "", 0.0

        if not text:
            continue

        turns.append(
            TranscriptTurn(
                speaker_id=seg.speaker,
                start=round(seg.start, 3),
                end=round(seg.end, 3),
                text=text,
                confidence=confidence,
            )
        )

    result.transcript = turns
    log.info(f"[{result.job_id}] Produced {len(turns)} transcript turn(s)")
    return result
