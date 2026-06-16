"""
Shared date / time normalization.

Single source of truth used by the normalizer, the rule parser and the
timesheet service so that an ambiguous date like "03/04/2026" is interpreted
the SAME way everywhere.

Locale is controlled by settings.DATE_DAYFIRST:
  - False (default, US): 03/04/2026 -> March 4
  - True (EU / DD-MM):   03/04/2026 -> April 3

ISO dates (YYYY-MM-DD) and unambiguous dates are interpreted the same way
regardless of the flag.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Tokens an extractor may emit for "no usable date"
_EMPTY_TOKENS = {"", "none", "nan", "nat", "null"}


def parse_date(value, *, dayfirst: Optional[bool] = None) -> Optional[str]:
    """Parse a value into an ISO date string (YYYY-MM-DD) or return None.

    ``dayfirst`` overrides the configured default when given.  Values that were
    flagged upstream as Excel epoch artifacts (``INVALID_...``) are rejected.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    s = str(value).strip()
    if s.lower() in _EMPTY_TOKENS:
        return None
    # Excel epoch artifact token emitted by the parsers, e.g. "INVALID_1900-01-05"
    if s.upper().startswith("INVALID_") or s.upper().startswith("INVALID"):
        return None

    if dayfirst is None:
        dayfirst = bool(getattr(settings, "DATE_DAYFIRST", False))

    # Fast path: already ISO
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None

    try:
        from dateutil import parser as _dp

        # default=Jan 1 keeps a missing day/month deterministic
        dt = _dp.parse(s, dayfirst=dayfirst, default=datetime(2000, 1, 1))
        return dt.date().isoformat()
    except (ValueError, OverflowError, TypeError):
        return None


def parse_time(value, *, infer_pm: bool = False) -> Optional[str]:
    """Parse a clock time into 24-hour ``HH:MM`` or return None.

    ``infer_pm`` is OFF by default: blindly adding 12h to ambiguous low hours
    corrupts legitimate early clock-ins (a 06:00 start becomes 18:00).  Callers
    that have surrounding context (an out-time earlier than the in-time) can opt
    in explicitly.
    """
    if value is None:
        return None
    if isinstance(value, time):
        return f"{value.hour:02d}:{value.minute:02d}"
    if isinstance(value, datetime):
        return f"{value.hour:02d}:{value.minute:02d}"

    s = str(value).strip().lower()
    if s in _EMPTY_TOKENS:
        return None

    has_pm = "pm" in s
    has_am = "am" in s
    m = re.search(r"(\d{1,2})[:.](\d{2})", s) or re.search(r"\b(\d{1,2})\s*(am|pm)\b", s)
    if not m:
        return None

    try:
        hour = int(m.group(1))
        minute = int(m.group(2)) if (m.lastindex and m.group(2) and m.group(2).isdigit()) else 0
    except (ValueError, IndexError):
        return None

    if has_pm and hour < 12:
        hour += 12
    elif has_am and hour == 12:
        hour = 0
    elif not has_pm and not has_am and infer_pm and 0 < hour < 8:
        hour += 12

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"
