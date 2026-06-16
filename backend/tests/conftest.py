"""Conftest: ensure backend/app is importable in tests without a live DB."""
import sys, os

# put backend/ on sys.path so "from app.xxx import ..." works
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Patch the DB session so models don't try to connect on import
from unittest.mock import MagicMock, patch
import importlib

# Prevent SQLModel/SQLAlchemy from trying to connect at import time
sys.modules.setdefault("sqlmodel", MagicMock())
