"""Celery application configuration."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "nexa",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_routes={
        "app.workers.tasks.send_scheduled_reminder_task": {"queue": "reminders"},
        "app.workers.tasks.execute_approved_plan": {"queue": "default"},
        "app.workers.tasks.cleanup_expired_tokens_task": {"queue": "default"},
    },
    beat_schedule={
        "cleanup-expired-tokens-daily": {
            "task": "app.workers.tasks.cleanup_expired_tokens_task",
            "schedule": crontab(hour=3, minute=0),  # Run every night at 3:00 AM UTC
        },
    },
)
