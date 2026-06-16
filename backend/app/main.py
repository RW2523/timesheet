"""
Ajace TimeSheet AI Bot — FastAPI application entry point.
"""
from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.security import require_api_key
from app.db.session import engine
from app.db.models import Base

from app.api import (
    routes_upload,
    routes_batches,
    routes_files,
    routes_entries,
    routes_validation,
    routes_reports,
    routes_admin,
    routes_payroll,
    routes_approvals,
    routes_email,
    routes_debug,
)

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Ajace TimeSheet AI Bot...")
    Base.metadata.create_all(bind=engine)
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Ajace TimeSheet AI Bot",
    description="Local, GPU-accelerated timesheet processing for Ajace",
    version="1.0.0",
    lifespan=lifespan,
)

_origins = settings.allowed_origins_list
_use_wildcard = _origins == ["*"]
# Wildcard origins cannot safely be combined with credentials (any site could
# read authed responses).  The frontend talks to the backend same-origin via a
# Next.js proxy, so cross-origin credentials aren't needed in the wildcard case.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _use_wildcard else _origins,
    allow_credentials=False if _use_wildcard else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional API-key gate (no-op unless settings.API_KEY is set). Health endpoints
# below are intentionally left open for probes.
_auth = [Depends(require_api_key)]

# Register routers
PREFIX = "/api/v1"
app.include_router(routes_upload.router, prefix=PREFIX, tags=["upload"], dependencies=_auth)
app.include_router(routes_batches.router, prefix=PREFIX, tags=["batches"], dependencies=_auth)
app.include_router(routes_files.router, prefix=PREFIX, tags=["files"], dependencies=_auth)
app.include_router(routes_entries.router, prefix=PREFIX, tags=["entries"], dependencies=_auth)
app.include_router(routes_validation.router, prefix=PREFIX, tags=["validation"], dependencies=_auth)
app.include_router(routes_reports.router, prefix=PREFIX, tags=["reports"], dependencies=_auth)
app.include_router(routes_payroll.router, prefix=PREFIX, tags=["payroll"], dependencies=_auth)
app.include_router(routes_approvals.router, prefix=PREFIX, tags=["approvals"], dependencies=_auth)
app.include_router(routes_admin.router, prefix=PREFIX, tags=["admin"], dependencies=_auth)
app.include_router(routes_email.router, prefix=PREFIX, tags=["email"], dependencies=_auth)
app.include_router(routes_debug.router, prefix=PREFIX, tags=["debug"], dependencies=_auth)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok", "service": "backend"}


@app.get("/worker-health", tags=["health"])
def worker_health():
    from app.workers.celery_app import celery_app
    try:
        inspect = celery_app.control.inspect(timeout=2)
        stats = inspect.stats()
        workers = list(stats.keys()) if stats else []
        return {"status": "ok", "workers": workers, "worker_count": len(workers)}
    except Exception as e:
        return {"status": "degraded", "error": str(e), "workers": []}
