"""
FastAPI application entrypoint.

Run with:
    uvicorn app.main:app --reload --port 8000

Note: the API process only queues jobs — it never runs pipeline stages
inline. A Celery worker (see app/workers/celery_app.py) must be running
against the same Redis instance for jobs to actually process.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as audio_router
from app.utils.logger import get_logger

log = get_logger("main")

app = FastAPI(
    title="AudioIQ",
    description="Multi-speaker audio intelligence pipeline: noise suppression, "
    "diarization, per-speaker transcription, and role mapping.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audio_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Mount static directory for frontend
static_dir = Path(__file__).resolve().parent.parent / "static"
if not static_dir.exists():
    static_dir.mkdir(parents=True, exist_ok=True)

app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


@app.on_event("startup")
async def on_startup():
    log.info("AudioIQ API started. Web App at http://localhost:8000 (Docs at /docs)")

