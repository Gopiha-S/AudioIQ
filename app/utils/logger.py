"""
Structured logging setup using loguru.

Import `get_logger(stage_name)` anywhere a pipeline stage needs to log —
it binds a `stage` field so every log line is filterable by pipeline stage,
which matters once a job is running through 9 stages inside one Celery task.
"""
import sys

from loguru import logger

from app.config import settings

logger.remove()
logger.add(
    sys.stdout,
    level=settings.log_level,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[stage]}</cyan> | "
        "<level>{message}</level>"
    ),
    colorize=True,
)
logger.configure(extra={"stage": "system"})


def get_logger(stage_name: str):
    return logger.bind(stage=stage_name)
