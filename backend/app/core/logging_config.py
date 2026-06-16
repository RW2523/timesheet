import logging
import os
import sys
from app.core.config import settings


def setup_logging() -> None:
    # Priority: LOG_LEVEL env var > APP_ENV heuristic
    env_level = os.getenv("LOG_LEVEL", "").upper()
    if env_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = getattr(logging, env_level)
    else:
        level = logging.DEBUG if settings.APP_ENV == "development" else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Always keep these noisy libraries quiet regardless of LOG_LEVEL
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)
    logging.getLogger("paddle").setLevel(logging.WARNING)
    logging.getLogger("ppocr").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)
    logging.getLogger("multipart.multipart").setLevel(logging.WARNING)
    logging.getLogger("pdfminer").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("docling").setLevel(logging.INFO)

    # LLM service always gets at least DEBUG so call traces always show
    logging.getLogger("app.services.llm_service").setLevel(logging.DEBUG)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
