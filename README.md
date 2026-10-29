<<<<<<< HEAD
# AudioIQ — Multi-Speaker Audio Intelligence Pipeline

AudioIQ is a production-grade audio preprocessing and transcription engine built using FastAPI and Celery. It acts as an asynchronous signal-processing orchestrator, taking raw noisy recordings through a structured 9-stage pipeline, dynamically diarizing speakers, running per-speaker transcription, and assembling a role-mapped, quality-scored transcript.

## Key Features

- **Celery Task-Graph Orchestration**: The full pipeline runs as a single asynchronous Celery task with discrete, individually-logged stages, rather than a blocking inline script — the API stays responsive while heavy ML inference runs in the background.
- **9-Stage Pipeline**: From format validation, FFmpeg filtering, and deep noise suppression, through voice activity detection, speaker diarization, per-speaker ASR transcription, and semantic role mapping.
- **Self-Correcting Diarization Fallback**: Accepts pre-computed diarization JSON when available, or runs Pyannote 3.1 diarization live; both paths converge on the same internal segment schema.
- **Robust Local Storage Layer**: Tracks per-job audio artifacts (original, cleaned, spectrograms) and transcript JSON across upload, processed, and output directories.
- **Comprehensive Observability**: Structured logging via `loguru`, per-stage progress percentages surfaced through Celery task state, and computed audio-quality metrics (SNR improvement, noise removed %, RMS before/after) for every completed job.

## Core Architecture

### State Schema (`PipelineResult`)

The pipeline shares a result object (Pydantic model, `app/models/schema.py`) assembled across all stages:

- `job_id`: Unique identifier for the transcription job.
- `audio_metadata`: Duration, sample rate, channel count, codec, speech ratio.
- `diarized_segments`: Speaker-labeled time segments from Pyannote or pre-computed JSON.
- `speaker_profiles`: Per-speaker role, confidence, word count, turn count, question count.
- `transcript`: Ordered list of transcribed turns with speaker ID, role, timestamps, and confidence.
- `audio_metrics`: SNR before/after, noise removed %, RMS/peak before/after, processing time.
- `spectrogram_paths`: Generated original/cleaned spectrogram PNG locations.
- `processing_start` / `processing_time_seconds`: Job timing for performance tracking.
- `status`: `queued` / `processing` / `completed` / `failed`.
- `error`: Captured exception detail if the job fails at any stage.

## Getting Started

### 1. Prerequisites

- **Python**: 3.11+
- **FFmpeg**: installed and available on PATH
- **Redis**: a running instance (local, Docker, or native Windows install)
- **GPU**: CUDA-capable card recommended (falls back to CPU automatically)
- **HuggingFace token**: with accepted license for `pyannote/speaker-diarization-3.1`

### 2. Configuration

Copy `.env.example` to `.env` and fill in `HF_TOKEN` at minimum. Every other tunable (Whisper model size, device, sample rate, filter cutoffs, diarization speaker bounds, etc.) has a sensible default in `.env.example` and is read once into `app/config.py:Settings`, used consistently across every stage.

### 3. Install Dependencies

```
pip install -r requirements.txt
```

On Windows, if you hit a build error on `pyannote.audio` or `deepfilternet`, install `torch`/`torchaudio` first from the matching CUDA wheel index (see pytorch.org), then re-run `pip install -r requirements.txt`.

### 4. Run the System

The pipeline requires three processes running concurrently:

```
# Terminal 1 — Redis (broker + result backend)
docker run -d -p 6379:6379 --name redis redis:7-alpine

# Terminal 2 — Celery worker (runs the actual pipeline)
celery -A app.workers.celery_app worker --loglevel=info --concurrency=1 --pool=solo

# Terminal 3 — FastAPI application
uvicorn app.main:app --reload --port 8000
```

`--pool=solo` is required on Windows (Celery's prefork pool isn't supported there), and is the right choice here regardless of OS since each job is a single heavy GPU-bound pipeline — running two concurrently on one worker just contends for the same GPU.

Open your browser at `http://127.0.0.1:8000/docs` to view the interactive Swagger documentation.

## Pipeline Stages

| # | Stage | Tool | Module |
|---|-------|------|--------|
| 1 | Validate | `audio_utils.py` (ffprobe) | `app/pipeline/stage1_validate.py` |
| 2 | Preprocess | FFmpeg | `app/pipeline/stage2_preprocess.py` |
| 3 | Enhance | DeepFilterNet2/3 | `app/pipeline/stage3_enhance.py` |
| 4 | EQ + Normalize | FFmpeg `loudnorm` | `app/pipeline/stage4_eq_normalize.py` |
| 5 | VAD | Silero VAD 5.1 | `app/pipeline/stage5_vad.py` |
| 6 | Diarize | Pyannote 3.1 | `app/pipeline/stage6_diarize.py` |
| 7 | Transcribe | faster-whisper | `app/pipeline/stage7_transcribe.py` |
| 8 | Role Map | Custom heuristic | `app/pipeline/stage8_role_map.py` |
| 9 | Assemble | `stage9_assemble.py` | Spectrograms, final metrics, status |

All 9 stages are chained in `app/workers/tasks.py:run_pipeline`, the single Celery task queued by `POST /audio/transcribe`.

## API Reference

| Method | Endpoint | Description |
|--------|----------|--------------|
| `POST` | `/audio/transcribe` | Upload audio (`file`), optional `diarization_json` form field for pre-computed diarization. Returns `job_id`. |
| `GET` | `/audio/jobs/{id}/status` | Poll job progress (0–100%) and current stage |
| `GET` | `/audio/jobs/{id}/result` | Full transcript JSON (409 if not yet completed) |
| `GET` | `/audio/jobs/{id}/audio/original` | Download original upload |
| `GET` | `/audio/jobs/{id}/audio/clean` | Download enhanced audio |
| `GET` | `/audio/jobs/{id}/spectrogram/original` | Original spectrogram PNG |
| `GET` | `/audio/jobs/{id}/spectrogram/cleaned` | Enhanced spectrogram PNG |
| `GET` | `/audio/jobs/{id}/metrics` | SNR, noise removed %, RMS, processing time |
| `DELETE` | `/audio/jobs/{id}` | Clean up all files for a job |

## Graceful Degradation

Stages 3 (DeepFilterNet), 5 (Silero VAD), and 6 (Pyannote) depend on model downloads that require network access and, in some cases, an accepted HuggingFace license. Rather than crash the whole job:

- **Stage 3** falls back to passing audio through unmodified if DeepFilterNet can't load.
- **Stage 5** falls back to assuming `speech_ratio = 1.0` if Silero can't load.
- **Stage 6** has no silent fallback (diarization is structurally required for everything downstream) — but accepts a pre-computed `diarization_json` to skip the live model entirely.

Every other stage (1, 2, 4, 7, 8, 9) has no optional-model dependency and runs deterministically wherever FFmpeg and faster-whisper are available.

## Testing

```
pytest tests/ -v --cov=app --cov-report=term-missing
```

The included tests cover the role-mapping heuristic (stage 8) and the audio-validation/storage layer — both have no heavy ML dependency and run in any environment (verified: 7/7 passing). Stages 3/5/6/7 are best exercised with an integration test against real model weights on a machine with the models downloaded.

## License

MIT
=======
# AudioIQ
>>>>>>> ccc18ff0b3089b98843380bf34e3bcc8900ec725
