"""
Celery app instance.

Uses Redis as both broker and result backend (matches the single REDIS_URL
in .env, keeping local/dev setup to one running service). `--pool=solo` is
recommended on Windows in the README because Celery's default prefork pool
doesn't work there; solo also happens to be the right choice here since each
job is itself a heavy single-threaded GPU pipeline — you don't want two
jobs fighting for the same GPU concurrently on a single worker anyway.
"""3
from celery import Celery

from app.config import settings

celery_app = Celery(
    "audioiq",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=60 * 60 * 24,  # 24h
    worker_prefetch_multiplier=1,  # don't grab a 2nd heavy job before the 1st finishes
    task_acks_late=True,
)
