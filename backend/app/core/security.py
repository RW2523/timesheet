"""
Lightweight API-key authentication.

Auth is OPT-IN so the default local/Tailscale workflow keeps working: when
``settings.API_KEY`` is empty the dependency is a no-op.  When it is set, every
request to a protected router must present ``X-API-Key: <value>``.

This is deliberately minimal — it is the floor that stops an exposed instance
from being wide open (e.g. ``DELETE /admin/clear-all-data``), not a full
user/session system.
"""
import logging

from fastapi import Header, HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = settings.API_KEY
    if not expected:
        return  # auth disabled
    if not x_api_key or x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
