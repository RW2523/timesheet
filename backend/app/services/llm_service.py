"""
LLM service — Phase 4.
Multi-backend with provider selection via LLM_PROVIDER setting.

Providers:
  mock         — returns empty/minimal JSON (for testing without any LLM)
  ollama       — local Ollama server (default, preferred for production)
  tensorrt_llm — DGX Spark TRT-LLM via OpenAI-compatible /v1/chat/completions
  openai       — cloud OpenAI (only used when ALLOW_CLOUD_LLM=true)

Safety rules enforced here:
- Cloud LLM (OpenAI) is disabled by default (ALLOW_CLOUD_LLM=false).
- LLM output must be validated against JSON schema before use.
- Invalid JSON does not crash pipeline; returns None with a warning.
- LLM cannot mark payroll ready.
- LLM cannot calculate salary.
- LLM returns strictly extraction JSON only; payroll logic is in deterministic services.
"""
import json
import logging
from typing import Optional, Dict, Any

from app.core.config import settings

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_TEMPLATE = """\
You are a precise timesheet data extraction specialist. Timesheets come in many formats:
employer portals (Fieldglass, Beeline, Bullhorn, Kronos, SAP, Workday, Replicon, etc.),
plain spreadsheets, PDF scans, email screenshots, or custom company formats.

Extract ALL timesheet entries from the text below and return ONLY valid JSON.
Never skip entries. Include zero-hour days (weekends, holidays) as entries with hours=0.

IMPORTANT CONTEXT:
- "employee_name" is the PERSON this timesheet belongs to — a human name (e.g. "John Smith", "Maria Garcia")
- Street addresses (e.g. "123 Main Street", "Court", "Ave", "Blvd") are NOT employee names
- Company/vendor/client names are NOT employee names
- Look for labels like "Employee:", "Name:", "Prepared by:", "Staff:", "Worker:", "Consultant:",
  "Submitted by:", or "Timesheet for:" followed by the person's name
- "In" / "Time In" / "Punch In" = clock-in time; "Out" / "Time Out" / "Punch Out" = clock-out time
- Times without AM/PM in a work context: if out_time < in_time and out_time < 12:00, add 12h to out_time
- A "Lunch" / "Break" / "Minus" / "Deduct" column means unpaid break in minutes (or hours if < 5)
- Do NOT invent entries for dates not in the source text
- Use source="FILE_EXTRACTED" for all entries you extract from the document
- Dates may appear in many formats (MM/DD/YYYY, DD/MM/YYYY, YYYY-MM-DD, "Mon DD", etc.) —
  always output dates as YYYY-MM-DD
- Hours columns may be labelled "Regular Hrs", "Billable Hours", "Total Hrs", "Worked",
  "Daily Total", "Net Hours", or similar — use the total/regular worked hours value
- Leave/absence may appear as PTO, SL, AL, CL, PL, EL, Sick, Vacation, Holiday, WFH, LOP, etc.

Return this exact JSON schema (replace placeholder values):
{{
  "employee_name": "First Last or null",
  "period_start": "YYYY-MM-DD or null",
  "period_end": "YYYY-MM-DD or null",
  "approved_by_name": "string or null",
  "approved_by_email": "string or null",
  "entries": [
    {{
      "date": "YYYY-MM-DD",
      "in_time": "HH:MM (24h) or null",
      "out_time": "HH:MM (24h) or null",
      "break_minutes": 0,
      "hours": 8.0,
      "entry_type": "WORK",
      "leave_type": null,
      "source": "FILE_EXTRACTED",
      "notes": null
    }}
  ]
}}

Rules:
- dates: YYYY-MM-DD only
- times: HH:MM 24-hour format
- hours: net worked hours; if in/out present → ((out_mins - in_mins) - break_minutes) / 60
- If a totals column exists, use that value for hours
- entry_type: WORK | LEAVE | HOLIDAY | ABSENT | WEEKEND
- Weekend days (Sat/Sun) with no hours → entry_type=WEEKEND, hours=0
- Return ONLY the JSON object, no markdown, no explanation

Raw timesheet text:
---
{raw_text}
---"""

VERIFICATION_PROMPT_TEMPLATE = """\
You are a data quality checker for timesheet data.

Review the extracted timesheet JSON below. Fix any issues:
1. Correct obviously wrong dates (e.g. signature dates mixed in as work entries)
2. Correct AM/PM ambiguity: work hours are 7:00-22:00; "5:00" after "8:00" start means 17:00
3. Remove duplicate entries for the same date
4. Recalculate hours where in/out times exist: hours = (out_mins - in_mins - break_minutes) / 60
5. Do NOT add entries that are not in the source text. Only remove or correct.

Current extracted JSON:
{extracted_json}

Return ONLY the corrected JSON, no explanation."""


class LLMService:
    def __init__(self):
        self._openai_client = None
        self._active_backend = None

    def is_enabled(self) -> bool:
        return settings.LLM_ENABLED

    def extract_timesheet_json(
        self,
        raw_text: str,
        file_metadata: Optional[Dict[str, Any]] = None,
        verify: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Send raw text to LLM and return structured timesheet JSON.

        Tries configured provider, then falls back in order:
        ollama → tensorrt_llm → openai (only if ALLOW_CLOUD_LLM) → None
        """
        if not self.is_enabled():
            return None

        if not raw_text or len(raw_text.strip()) < 20:
            return None

        # Trim to fit context window — give more budget when text is long (needs full context)
        max_chars = 12000
        text = raw_text[:max_chars]
        prompt = EXTRACTION_PROMPT_TEMPLATE.format(raw_text=text)

        result = self._call_with_fallback(prompt)
        if not result:
            return None

        parsed = self._parse_json(result)
        if not parsed:
            logger.warning(f"LLM_EXTRACTION_FAILED: could not parse JSON from LLM response")
            return None

        # Validate schema minimally
        if not isinstance(parsed.get("entries"), list):
            logger.warning("LLM returned JSON without entries list — discarding")
            return None

        # Verification pass
        if verify and parsed.get("entries"):
            try:
                verify_prompt = VERIFICATION_PROMPT_TEMPLATE.format(
                    extracted_json=json.dumps(parsed, indent=2)[:6000]
                )
                verified_raw = self._call_with_fallback(verify_prompt)
                if verified_raw:
                    verified = self._parse_json(verified_raw)
                    if verified and isinstance(verified.get("entries"), list):
                        parsed = verified
            except Exception as e:
                logger.warning(f"LLM verification pass failed: {e}")

        logger.info(
            f"LLM extraction via {self._active_backend}: "
            f"{len(parsed.get('entries', []))} entries, "
            f"employee={parsed.get('employee_name')}"
        )
        return parsed

    def _call_with_fallback(self, prompt: str) -> Optional[str]:
        """Call configured provider, then fall back to next available."""
        provider = settings.LLM_PROVIDER.lower()

        # Primary provider
        if provider == "mock":
            return self._call_mock()
        if provider == "ollama":
            result = self._call_ollama(prompt)
            if result:
                self._active_backend = "ollama"
                return result
            # Fallback chain: TRT-LLM → OpenAI
            result = self._call_trt_llm(prompt)
            if result:
                self._active_backend = "tensorrt_llm"
                return result
        elif provider == "tensorrt_llm":
            result = self._call_trt_llm(prompt)
            if result:
                self._active_backend = "tensorrt_llm"
                return result
            # Fallback: Ollama
            result = self._call_ollama(prompt)
            if result:
                self._active_backend = "ollama"
                return result
        elif provider == "openai":
            if not settings.ALLOW_CLOUD_LLM:
                logger.warning("OpenAI provider configured but ALLOW_CLOUD_LLM=false — skipping")
                return None
            result = self._call_openai(prompt)
            if result:
                self._active_backend = "openai"
                return result

        # Cloud fallback (only when explicitly allowed)
        if settings.ALLOW_CLOUD_LLM and settings.OPENAI_API_KEY:
            result = self._call_openai(prompt)
            if result:
                self._active_backend = "openai"
                return result

        logger.error("All LLM backends failed")
        return None

    def _call_mock(self) -> Optional[str]:
        """Return minimal valid JSON for testing without a real LLM."""
        return json.dumps({
            "employee_name": None,
            "period_start": None,
            "period_end": None,
            "approved_by_name": None,
            "approved_by_email": None,
            "entries": [],
        })

    def _call_ollama(self, prompt: str) -> Optional[str]:
        """Call Ollama API. Tries preferred model, then fallback model."""
        base_url = settings.OLLAMA_BASE_URL
        models_to_try = [settings.OLLAMA_MODEL, settings.OLLAMA_FALLBACK_MODEL]

        for model in models_to_try:
            try:
                import httpx
                response = httpx.post(
                    f"{base_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0,
                            "num_predict": 6144,
                        },
                    },
                    timeout=max(settings.LLM_TIMEOUT, 180),
                )
                if response.status_code == 200:
                    return response.json().get("response", "")
                elif response.status_code == 404:
                    logger.warning(f"Ollama model {model} not found, trying next")
                    continue
            except Exception as e:
                logger.warning(f"Ollama ({model}) failed: {e}")
                break

        return None

    def _call_trt_llm(self, prompt: str) -> Optional[str]:
        """Call TRT-LLM on DGX Spark via OpenAI-compatible /v1/chat/completions endpoint."""
        if not settings.LLM_BASE_URL:
            return None
        try:
            import httpx
            response = httpx.post(
                f"{settings.LLM_BASE_URL}/chat/completions",
                json={
                    "model": settings.PRIMARY_LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 4096,
                },
                timeout=settings.LLM_TIMEOUT,
            )
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"TRT-LLM failed: {e}")
        return None

    def _call_openai(self, prompt: str) -> Optional[str]:
        """Call OpenAI API. Only used when ALLOW_CLOUD_LLM=true and key is set."""
        if not settings.OPENAI_API_KEY:
            return None
        if not settings.ALLOW_CLOUD_LLM:
            return None
        try:
            import httpx
            from openai import OpenAI
            if self._openai_client is None:
                self._openai_client = OpenAI(
                    api_key=settings.OPENAI_API_KEY,
                    http_client=httpx.Client(timeout=settings.LLM_TIMEOUT),
                )
            response = self._openai_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=4096,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"OpenAI failed: {e}")
            return None

    @staticmethod
    def _parse_json(text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON from LLM response. Strips markdown fences."""
        if not text:
            return None
        try:
            t = text.strip()
            if "```" in t:
                parts = t.split("```")
                for part in parts:
                    part = part.strip()
                    if part.startswith("json"):
                        part = part[4:].strip()
                    if part.startswith("{"):
                        t = part
                        break
            start = t.find("{")
            end = t.rfind("}") + 1
            if start >= 0 and end > start:
                t = t[start:end]
            return json.loads(t)
        except json.JSONDecodeError as e:
            logger.warning(f"LLM JSON parse failed: {e} — raw: {text[:200]}")
            return None
