from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "timesheet_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.workers.tasks.process_batch": {"queue": "batch"},
        "app.workers.tasks.process_single_file": {"queue": "files"},
    },
)
