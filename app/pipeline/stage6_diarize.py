"""
Stage 6 — Diarize.

Identifies distinct speakers and segment boundaries. Two paths converge on
the same internal `DiarizedSegment` schema:

1. **Pre-computed diarization**: if the caller supplies a diarization JSON
   (e.g. produced by another tool, or a cached run), it's validated and used
   directly — this is the "self-correcting fallback" the README describes,
   letting the pipeline skip the most expensive stage when the answer is
   already known.
2. **Live Pyannote 3.1**: runs the actual diarization model, gated by
   HF_TOKEN and DIARIZATION_MIN/MAX_SPEAKERS from settings.
"""
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models.schema import DiarizedSegment, PipelineResult
from app.utils.logger import get_logger

log = get_logger("stage6_diarize")

_diarization_pipeline = None


def _load_pyannote():
    global _diarization_pipeline
    if _diarization_pipeline is not None:
        return _diarization_pipeline

    # In pyannote.audio 4.x, SpeakerDiarization unconditionally attempts to download
    # pyannote/speaker-diarization-community-1 for PLDA weights, even when using
    # AgglomerativeClustering (which never uses PLDA). Gracefully fallback to dummy PLDA.
    try:
        import pyannote.audio.pipelines.speaker_diarization as sd
        from pyannote.audio.core.plda import PLDA

        orig_get_plda = getattr(sd, "get_plda", None)
        if orig_get_plda is not None:
            def safe_get_plda(plda, token=None, cache_dir=None):
                try:
                    return orig_get_plda(plda, token=token, cache_dir=cache_dir)
                except Exception:
                    return object.__new__(PLDA)

            sd.get_plda = safe_get_plda
    except Exception as exc:
        log.debug(f"PLDA patch skipped: {exc}")

    from pyannote.audio import Pipeline

    log.info("Loading Pyannote 3.1 diarization pipeline (first call only)...")

    kwargs = {}
    if settings.hf_token:
        # Pyannote 3.x+ expects the Hugging Face token as "token".
        # Some older versions still accept "use_auth_token". Support both,
        # preferring the modern keyword while remaining compatible.
        try:
            kwargs["token"] = settings.hf_token
            _diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                **kwargs,
            )
        except TypeError as exc:
            if "unexpected keyword argument 'token'" not in str(exc):
                raise
            kwargs = {"use_auth_token": settings.hf_token}
            _diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                **kwargs,
            )
    else:
        _diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
        )

    import torch

    if settings.device == "cuda" and torch.cuda.is_available():
        _diarization_pipeline.to(torch.device("cuda"))

    return _diarization_pipeline


def _from_precomputed(json_segments: list[dict]) -> list[DiarizedSegment]:
    return [
        DiarizedSegment(start=float(s["start"]), end=float(s["end"]), speaker=str(s["speaker"]))
        for s in json_segments
    ]


def _from_pyannote(audio_path: Path) -> list[DiarizedSegment]:
    import soundfile as sf
    import torch

    pipeline = _load_pyannote()

    # Load audio via soundfile to prevent torchcodec / FFmpeg DLL dependency issues on Windows
    audio_data, sr = sf.read(str(audio_path), dtype="float32")
    if audio_data.ndim == 1:
        waveform = torch.from_numpy(audio_data).unsqueeze(0)
    else:
        waveform = torch.from_numpy(audio_data.T)

    diarization = pipeline(
        {"waveform": waveform, "sample_rate": sr},
        min_speakers=settings.diarization_min_speakers,
        max_speakers=settings.diarization_max_speakers,
    )

    # In pyannote 4+, pipeline returns DiarizeOutput whose annotation is in .speaker_diarization
    annotation = getattr(diarization, "speaker_diarization", diarization)

    segments = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        segments.append(
            DiarizedSegment(start=round(turn.start, 3), end=round(turn.end, 3), speaker=speaker)
        )
    return segments


def run(
    result: PipelineResult,
    audio_path: Path,
    precomputed_diarization: Optional[list[dict]] = None,
) -> PipelineResult:
    if precomputed_diarization:
        log.info(f"[{result.job_id}] Using pre-computed diarization ({len(precomputed_diarization)} segments)")
        segments = _from_precomputed(precomputed_diarization)
    else:
        log.info(f"[{result.job_id}] Running live Pyannote diarization")
        try:
            segments = _from_pyannote(audio_path)
        except Exception as e:  # noqa: BLE001 — model download / HF token issues, etc.
            log.error(f"[{result.job_id}] Pyannote diarization failed: {e}")
            raise

    if not segments:
        log.warning(f"[{result.job_id}] Diarization produced 0 segments")

    result.diarized_segments = segments
    speakers = sorted({s.speaker for s in segments})
    log.info(f"[{result.job_id}] Found {len(speakers)} speaker(s), {len(segments)} segments")
    return result
