from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+psycopg://timesheet_user:timesheet_pass@localhost:5432/timesheet_ai"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Storage
    STORAGE_ROOT: str = "/storage"
    MAX_UPLOAD_MB: int = 2000
    MAX_EXTRACTED_MB: int = 5000

    # LLM
    LLM_ENABLED: bool = False
    LLM_BASE_URL: str = "http://trt-llm:8000/v1"
    PRIMARY_LLM_MODEL: str = "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4"
    LLM_TIMEOUT: int = 120

    # OCR
    OCR_ENABLED: bool = True
    OCR_USE_GPU: bool = False
    TESSERACT_ENABLED: bool = True
    OCR_CONFIDENCE_THRESHOLD: float = 0.7

    # App
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # Payroll rules
    REGULAR_DAILY_LIMIT_HOURS: float = 8.0
    REGULAR_WEEKLY_LIMIT_HOURS: float = 40.0
    MAX_DAILY_HOURS: float = 12.0
    LATE_SUBMISSION_DAYS: int = 5
    INACTIVE_MONTHS_THRESHOLD: int = 2

    # Noise files
    NOISE_FILE_PATTERNS: str = "desktop.ini,thumbs.db,.ds_store,.gitkeep,__macosx"

    @property
    def noise_patterns(self) -> list[str]:
        return [p.strip().lower() for p in self.NOISE_FILE_PATTERNS.split(",")]

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]


settings = Settings()
