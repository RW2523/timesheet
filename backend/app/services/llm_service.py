"""
LLM service — Phase 4 (optional, gated by LLM_ENABLED).
OpenAI-compatible interface to TensorRT-LLM on DGX Spark.
"""
import json
import logging
from typing import Optional, Dict, Any

from app.core.config import settings

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are a timesheet data extraction specialist.
Extract timesheet data from the following raw text and return ONLY valid JSON in this exact schema:

{
  "employee_name": "string or null",
  "period_start": "YYYY-MM-DD or null",
  "period_end": "YYYY-MM-DD or null",
  "approved_by_name": "string or null",
  "approved_by_email": "string or null",
  "entries": [
    {
      "date": "YYYY-MM-DD",
      "in_time": "HH:MM or null",
      "out_time": "HH:MM or null",
      "break_minutes": integer_or_0,
      "hours": float_or_null,
      "entry_type": "WORK|LEAVE|HOLIDAY|ABSENT",
      "leave_type": "string or null",
      "notes": "string or null"
    }
  ]
}

Rules:
- Dates must be YYYY-MM-DD format
- Times must be HH:MM 24-hour format
- hours should be total worked hours (NOT including break)
- entry_type defaults to WORK if not specified
- Return ONLY the JSON, no explanation

Raw timesheet text:
---
{raw_text}
---"""


class LLMService:
    def __init__(self):
        self._client = None

    def is_enabled(self) -> bool:
        return settings.LLM_ENABLED

    def extract_timesheet_json(
        self, raw_text: str, file_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Send raw text to LLM and return parsed JSON dict. Returns None if LLM disabled or failed."""
        if not self.is_enabled():
            logger.debug("LLM disabled — skipping LLM extraction")
            return None

        if not raw_text or len(raw_text.strip()) < 10:
            return None

        try:
            client = self._get_client()
            prompt = EXTRACTION_PROMPT.format(raw_text=raw_text[:8000])

            response = client.chat.completions.create(
                model=settings.PRIMARY_LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=2048,
                timeout=settings.LLM_TIMEOUT,
            )

            raw_json = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw_json.startswith("```"):
                raw_json = raw_json.split("```")[1]
                if raw_json.startswith("json"):
                    raw_json = raw_json[4:]

            parsed = json.loads(raw_json)
            logger.info("LLM extraction succeeded")
            return parsed

        except json.JSONDecodeError as e:
            logger.warning(f"LLM returned invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return None

    def _get_client(self):
        if self._client is None:
            import httpx
            from openai import OpenAI
            self._client = OpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key="not-needed",
                http_client=httpx.Client(timeout=settings.LLM_TIMEOUT),
            )
        return self._client
