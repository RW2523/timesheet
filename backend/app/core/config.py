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
    MAX_ZIP_FILE_COUNT: int = 5000

    # LLM provider selection:  mock | ollama | tensorrt_llm | openai
    LLM_PROVIDER: str = "ollama"
    LLM_ENABLED: bool = True
    ALLOW_CLOUD_LLM: bool = False   # cloud (OpenAI) is opt-in only

    # LLM — Ollama (primary local)
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    OLLAMA_FALLBACK_MODEL: str = "llama3.2:1b"

    # LLM — OpenAI (cloud fallback, only used when ALLOW_CLOUD_LLM=true)
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # LLM — TRT-LLM on DGX Spark GPU
    LLM_BASE_URL: str = "http://trt-llm:8000/v1"
    PRIMARY_LLM_MODEL: str = "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4"
    LLM_TIMEOUT: int = 180

    # LLM — structured output / validation
    # When true, the extractor asks the model for schema-constrained JSON
    # (Ollama `format`, OpenAI/TRT `response_format`) and validates the result
    # with Pydantic, retrying once on a schema failure before giving up.
    LLM_STRUCTURED_OUTPUT: bool = True
    LLM_VALIDATE_RETRIES: int = 1
    # The verification ("second opinion") pass can mutate good extractions; off by default.
    LLM_VERIFY_PASS: bool = False

    # Date locale: False -> MM/DD (US); True -> DD/MM (EU). Applies to ambiguous dates only.
    DATE_DAYFIRST: bool = False

    # OCR
    OCR_ENABLED: bool = True
    OCR_USE_GPU: bool = False
    OCR_MAX_PAGES: int = 25           # cap to avoid hours-long processing
    OCR_DPI_NORMAL: int = 200         # DPI for multi-page docs (speed/quality balance)
    OCR_DPI_HIGH: int = 300           # DPI for single-page / few-page docs (accuracy)
    OCR_DPI_THRESHOLD_PAGES: int = 10 # use high DPI when page count <= this
    TESSERACT_ENABLED: bool = True
    OCR_CONFIDENCE_THRESHOLD: float = 0.6
    MIN_TEXT_CHARS_PDF: int = 80      # below this triggers OCR for PDFs
    MIN_TEXT_MEANINGFUL: int = 30     # below this the text is considered empty

    # Docling
    DOCLING_ENABLED: bool = True
    DOCLING_ARTIFACTS_PATH: str = "/storage/docling_models"
    # Enable Docling's own OCR (TableFormer) for scanned PDFs/images. Preserves
    # table structure far better than flat OCR text, at a speed cost.
    DOCLING_OCR: bool = False

    # OCR + VLM fusion: when on, scanned PDFs / images in the main pipeline are
    # processed by OcrVlmFusionService (OCR text grounds a VLM that rebuilds the
    # table layout) instead of flat OCR. Slower but preserves table structure.
    PIPELINE_USE_FUSION: bool = False
    FUSION_MAX_RENDER_PX: int = 2200   # cap the longest image edge sent to the VLM
    FUSION_MIN_OCR_PX: int = 1600      # upscale small/low-res images to at least this before OCR

    # Sanity: a single day cannot plausibly exceed this many hours. Entries above
    # it are flagged IMPLAUSIBLE_HOURS and excluded so totals/calendar stay clean.
    MAX_PLAUSIBLE_DAILY_HOURS: float = 24.0

    # Multi-engine extraction for IMAGE-BASED files (scanned PDFs + images):
    # run all three engines (flat OCR, OCR+VLM fusion, VLM-only), score each,
    # and keep the best single result. Text-based files keep their recommended
    # parser. Most powerful but slowest path. Takes precedence over PIPELINE_USE_FUSION.
    PIPELINE_MULTIENGINE_IMAGES: bool = True

    # App
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    ALLOWED_ORIGINS: str = "*"
    # Optional API-key gate. When empty, the API is open (local/Tailscale use).
    # When set, every /api request must send `X-API-Key: <value>`.
    API_KEY: Optional[str] = None

    # Payroll rules
    REGULAR_DAILY_LIMIT_HOURS: float = 8.0
    REGULAR_WEEKLY_LIMIT_HOURS: float = 40.0
    # Reclassify regular hours above the weekly limit (Mon–Sun) into overtime.
    WEEKLY_OVERTIME_ENABLED: bool = True
    MAX_DAILY_HOURS: float = 16.0
    LATE_SUBMISSION_DAYS: int = 5
    INACTIVE_MONTHS_THRESHOLD: int = 2
    HOURS_MISMATCH_TOLERANCE: float = 0.1   # hours difference before flagging mismatch

    # Employee matching thresholds (0.0–1.0)
    FUZZY_AUTO_THRESHOLD: float = 0.85     # >= this → AUTO_MATCHED
    FUZZY_REVIEW_THRESHOLD: float = 0.60   # >= this → NEEDS_REVIEW; below → NOT_MATCHED

    # Normalizer
    NORMALIZATION_MIN_ENTRIES: int = 1      # min entries needed to set NORMALIZED (not NEEDS_REVIEW)
    NORMALIZATION_MIN_DATED_RATIO: float = 0.5  # fraction of entries that must have a valid date
    NORMALIZATION_MIN_HOURS_RATIO: float = 0.3  # fraction of entries that must have hours or in/out

    # Noise files
    NOISE_FILE_PATTERNS: str = "desktop.ini,thumbs.db,.ds_store,.gitkeep,__macosx"

    # Blocked executable / script extensions (never process these)
    BLOCKED_EXTENSIONS: str = ".exe,.bat,.sh,.cmd,.ps1,.vbs,.js,.py,.rb,.pl,.php,.dll,.so,.bin"

    # Generic company / vendor name tokens that appear in filenames but are NOT
    # part of an employee name.  Add your own org tokens here via the env var.
    # Example:  COMPANY_NAME_STOPWORDS="acme,globalcorp,staffinc"
    COMPANY_NAME_STOPWORDS: str = (
        "ajace,brillio,akkodis,innova,hcpss,hexaware,npo,reimburs,reimbursement,"
        "staffing,consulting,services,solutions,inc,llc,ltd,corp,group"
    )

    # Leave type tokens that mark an entry as non-WORK.
    # Can be overridden per deployment via environment variable.
    LEAVE_TYPE_TOKENS: str = (
        "leave,sick,vacation,pto,al,sl,pl,cl,ml,el,fl,wfh,holiday,ph,"
        "comp,compensatory,bereavement,jury,furlough,absent,lop"
    )

    # Normalizer thresholds
    LLM_TRIGGER_MIN_ENTRIES: int = 10    # trigger LLM if table pass found fewer than this
    MULTISHEET_SPAN_DAYS: int = 65       # merge multi-sheet workbooks spanning <= this many days
    DATE_OUTLIER_THRESHOLD_DAYS: int = 35  # remove entries further than this from the median date

    # Gmail Integration (OAuth2)
    # Set these in .env after creating a Google Cloud OAuth2 app
    GMAIL_CLIENT_ID: Optional[str] = None
    GMAIL_CLIENT_SECRET: Optional[str] = None
    # Redirect URI must match what's registered in Google Cloud Console
    GMAIL_REDIRECT_URI: str = "http://localhost:3000/admin/email/callback"
    # Scopes (read-only is sufficient)
    GMAIL_SCOPES: str = "https://www.googleapis.com/auth/gmail.readonly"

    @property
    def gmail_scopes_list(self) -> list[str]:
        return [s.strip() for s in self.GMAIL_SCOPES.split(",") if s.strip()]

    @property
    def noise_patterns(self) -> list[str]:
        return [p.strip().lower() for p in self.NOISE_FILE_PATTERNS.split(",")]

    @property
    def blocked_extensions(self) -> list[str]:
        return [e.strip().lower() for e in self.BLOCKED_EXTENSIONS.split(",")]

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    @property
    def company_stopwords(self) -> set[str]:
        return {t.strip().lower() for t in self.COMPANY_NAME_STOPWORDS.split(",") if t.strip()}

    @property
    def leave_type_tokens(self) -> set[str]:
        return {t.strip().lower() for t in self.LEAVE_TYPE_TOKENS.split(",") if t.strip()}


settings = Settings()
