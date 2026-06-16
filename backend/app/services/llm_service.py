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

Debug logging:
  Set LOG_LEVEL=DEBUG (in .env) to see full prompts + raw responses in the logs.
  Each call is tagged with a short call_id so extraction + verification can be
  correlated even when multiple requests run concurrently.
"""
import json
import logging
import textwrap
import uuid
from typing import Optional, Dict, Any

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.extraction import TimesheetExtraction, timesheet_extraction_schema

logger = logging.getLogger(__name__)

# How many characters of prompt / response to print at DEBUG level.
# Set to 0 to disable truncation (very verbose).
_DBG_PROMPT_CHARS    = 2000
_DBG_RESPONSE_CHARS  = 2000


def _dbg(call_id: str, tag: str, content: str, limit: int = _DBG_RESPONSE_CHARS) -> None:
    """Emit a single DEBUG log line with a consistent prefix for easy grep."""
    if not logger.isEnabledFor(logging.DEBUG):
        return
    body = content[:limit] + (" …[truncated]" if len(content) > limit else "")
    logger.debug("[LLM:%s] %s\n%s", call_id, tag, body)


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

# ── Lab v2 prompts (test-lab only, does NOT affect main pipeline) ──────────────

LAB_SYSTEM_PROMPT = """\
You are a strict timesheet and payroll extraction engine.

Your job is to extract structured payroll/timesheet information from raw text \
produced from PDFs, Excel files, Word documents, scanned images, OCR, or mixed \
document layouts.

You must follow these rules:
- Return only valid JSON. Do not include markdown, explanation, comments, or extra text.
- Extract only information supported by the raw text.
- Do not hallucinate missing employee names, employer names, manager names, \
  signatures, dates, or hours.
- If a value is missing, unclear, or only inferable, return null and explain \
  it in the relevant confidence or notes field.
- Always focus only on the requested target month.
- If the raw text contains multiple months, multiple pages, weekly sheets, \
  monthly sheets, or unrelated dates, include only rows whose work date falls \
  inside the target month. Ignore dates outside the target month, but list them \
  under ignored_dates with a reason.
- Normalize all dates to ISO format: YYYY-MM-DD.
- Normalize time to 24-hour HH:MM format when possible.
- Treat rows with 0, 0.0, blank hours, no In/Out time, or no payable hours as \
  non-worked days unless sick/vacation/holiday hours are explicitly present.
- Worked days are days with regular hours, overtime hours, sick hours, vacation \
  hours, holiday hours, or total payable hours greater than 0.
- Use the document's stated total if it matches the sum of extracted rows.
- If the document total and row-level calculated total disagree, return both and \
  set validation_status to "mismatch".
- Calculate overtime using the overtime policy provided. Default policy: overtime \
  is hours above 8 hours per day or above 40 regular hours per workweek.
- Never count sick, vacation, holiday, or nonbillable hours as overtime unless \
  the prompt explicitly says to do so.
- For manager approval, mark "approved" only if a manager signature, manager \
  approval text, approval date, or clear approval indicator is present. Mark \
  "not_found" if only a blank signature line exists. Mark "unclear" if ambiguous.
- Preserve evidence. For important extracted values, include source_text or \
  evidence where possible.
- Be robust to table formatting errors, OCR mistakes, broken rows, repeated \
  headers, page footers, and extra signature/date lines.
- If a row appears duplicated, keep only one unique record per employee/date/source \
  row unless the document clearly shows multiple shifts for the same day.

You are not a chatbot. You are a deterministic extraction component. \
Output must be machine-parseable JSON only."""

LAB_BASE_PROMPT_TEMPLATE = """\
Extract timesheet and payroll information from the raw text below.

TARGET MONTH: {target_month}
TARGET MONTH START DATE: {target_month_start_date}
TARGET MONTH END DATE: {target_month_end_date}

OVERTIME POLICY: {overtime_policy}
DEFAULT OVERTIME POLICY IF NOT PROVIDED:
Overtime is any time above 8 hours in a single workday or above 40 regular hours \
in a workweek. Sick, vacation, holiday, and nonbillable hours should not be counted \
as overtime unless the document explicitly says they are overtime.

EXTRACTION GOALS:
1. Identify the employee name.
2. Identify the employer/company name.
3. Identify the timesheet period.
4. Extract only rows inside the target month.
5. For each day in the target month, identify whether the employee worked.
6. For each worked day, extract: date, day of week, in time, out time, \
   lunch/break deduction, regular hours, sick hours, vacation hours, holiday hours, \
   overtime hours, total hours.
7. Calculate total worked/payable hours for the target month.
8. Determine whether overtime exists.
9. Determine whether manager approval exists.
10. List any ignored dates outside the target month.
11. Validate whether row-level totals match document-level totals.

IMPORTANT RULES:
- Focus only on the target month.
- Do not include rows from previous or next month.
- Do not infer employee name unless it is clearly present.
- If employer name is not directly present but can be inferred from email/domain/header, \
  return the inferred value with low or medium confidence.
- If a signature line exists but no actual signature is present, manager approval \
  status must be "not_found".
- If total hours are listed in the document, compare them against your calculated total.
- Return only JSON matching the required schema — no prose, no markdown.

REQUIRED JSON SCHEMA:
{{
  "target_month": "YYYY-MM",
  "employee_name": "string or null",
  "employer_name": {{"value": "string or null", "confidence": 0.0-1.0, "evidence": "string or null"}},
  "period": {{"start_date": "YYYY-MM-DD or null", "end_date": "YYYY-MM-DD or null", "source_text": "string or null"}},
  "daily_records": [
    {{
      "date": "YYYY-MM-DD",
      "day": "Monday etc. or null",
      "worked": true/false,
      "in_time": "HH:MM or null",
      "out_time": "HH:MM or null",
      "lunch_hours": 0.0,
      "regular_hours": 0.0,
      "sick_hours": 0.0,
      "vacation_hours": 0.0,
      "holiday_hours": 0.0,
      "overtime_hours": 0.0,
      "total_hours": 0.0,
      "evidence": "source row text or null"
    }}
  ],
  "summary": {{
    "worked_days_count": 0,
    "total_regular_hours": 0.0,
    "total_sick_hours": 0.0,
    "total_vacation_hours": 0.0,
    "total_holiday_hours": 0.0,
    "total_overtime_hours": 0.0,
    "total_payable_hours": 0.0,
    "document_reported_total_hours": null
  }},
  "overtime": {{
    "has_overtime": false,
    "daily_overtime_hours": 0.0,
    "weekly_overtime_hours": 0.0,
    "total_overtime_hours": 0.0,
    "policy_used": "string"
  }},
  "manager_approval": {{
    "status": "approved|not_found|unclear",
    "manager_name": null,
    "approval_date": null,
    "evidence": null
  }},
  "ignored_dates": [{{"date": "YYYY-MM-DD", "reason": "outside target month"}}],
  "validation": {{
    "validation_status": "matched|mismatch|missing_document_total|unclear",
    "calculated_total": 0.0,
    "document_total": null,
    "issues": []
  }}
}}

RAW TEXT:
---
{raw_text}
---"""


def build_lab_prompts(
    raw_text: str,
    period_filter: dict,
    overtime_policy: str = "",
) -> tuple:
    """
    Build (system_prompt, user_prompt) for the test-lab v2 extraction.
    period_filter: {month: int, year: int}
    Returns (system_prompt_str, user_prompt_str, target_month_str, pf_start, pf_end)
    """
    import calendar as _cal
    from datetime import datetime as _dtt

    m = int(period_filter.get("month", _dtt.now().month))
    y = int(period_filter.get("year",  _dtt.now().year))
    last_day   = _cal.monthrange(y, m)[1]
    pf_start   = f"{y:04d}-{m:02d}-01"
    pf_end     = f"{y:04d}-{m:02d}-{last_day:02d}"
    target_mon = _dtt(y, m, 1).strftime("%B %Y")    # e.g. "May 2026"
    target_ym  = f"{y:04d}-{m:02d}"                 # e.g. "2026-05"

    policy = overtime_policy.strip() or (
        "Overtime is any time above 8 hours in a single workday or above 40 "
        "regular hours in a workweek."
    )

    user_prompt = LAB_BASE_PROMPT_TEMPLATE.format(
        target_month            = target_mon,
        target_month_start_date = pf_start,
        target_month_end_date   = pf_end,
        overtime_policy         = policy,
        raw_text                = raw_text,
    )

    return LAB_SYSTEM_PROMPT, user_prompt, target_ym, pf_start, pf_end


VERIFICATION_PROMPT_TEMPLATE = """\
You are a data quality checker for timesheet data.

You have access to the ORIGINAL SOURCE TEXT (ground truth) and the extracted JSON below.
Your job is to ONLY fix clearly wrong values supported by the source text.

Rules:
1. Correct AM/PM ambiguity: work hours are 7:00-22:00; "5:00" after "8:00" start → 17:00
2. Remove duplicate entries for the same date+time
3. Recalculate hours where in/out times exist: hours = (out_mins - in_mins - break_minutes) / 60
4. Fix obviously wrong dates (e.g. signature dates mixed in as work entries)
5. Do NOT add entries that are not in the source text
6. Do NOT remove valid entries — only remove exact duplicates
7. Do NOT change hours if in/out times are absent from the source
8. Do NOT invent times, names, or dates

Original source text (use this as ground truth):
---
{source_text}
---

Current extracted JSON:
{extracted_json}

Return ONLY the corrected JSON object, no explanation, no markdown."""


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
        source_text: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Send raw text to LLM and return structured timesheet JSON."""
        call_id  = uuid.uuid4().hex[:8]
        filename = (file_metadata or {}).get("filename", "unknown")

        logger.info("[LLM:%s] START extract — file=%s  text_len=%d  provider=%s",
                    call_id, filename, len(raw_text), settings.LLM_PROVIDER)

        if not self.is_enabled():
            logger.info("[LLM:%s] SKIP — LLM_ENABLED=false", call_id)
            return None

        if not raw_text or len(raw_text.strip()) < 20:
            logger.warning("[LLM:%s] SKIP — input text too short (%d chars)", call_id, len(raw_text))
            return None

        # Send the full extracted text to the LLM.
        # LLM_MAX_CHARS can be set in .env to cap very large documents (default: no cap).
        # Most Ollama models support 32K–128K context; we also pass num_ctx to ensure
        # the model doesn't silently truncate on its side.
        max_chars = getattr(settings, "LLM_MAX_CHARS", 0)
        if max_chars and len(raw_text) > max_chars:
            text = raw_text[:max_chars]
            logger.warning("[LLM:%s] text capped by LLM_MAX_CHARS: %d → %d chars",
                           call_id, len(raw_text), max_chars)
        else:
            text = raw_text
            if len(text) > 12000:
                logger.info("[LLM:%s] sending full text: %d chars (no cap)", call_id, len(text))

        base_prompt = EXTRACTION_PROMPT_TEMPLATE.format(raw_text=text)
        schema = timesheet_extraction_schema() if settings.LLM_STRUCTURED_OUTPUT else None

        # Schema-constrained call + validation, with a corrective retry.  A bad
        # response no longer kills the document silently — we re-ask once with the
        # validation error before giving up.
        parsed: Optional[Dict[str, Any]] = None
        max_attempts = 1 + max(0, int(getattr(settings, "LLM_VALIDATE_RETRIES", 1)))
        prompt = base_prompt
        for attempt in range(1, max_attempts + 1):
            _dbg(call_id, f"EXTRACTION PROMPT SENT (attempt {attempt})", prompt, _DBG_PROMPT_CHARS)
            result = self._call_with_fallback(prompt, call_id=call_id, step="extraction", schema=schema)
            if not result:
                logger.error("[LLM:%s] FAILED — all backends returned empty for extraction", call_id)
                return None
            _dbg(call_id, f"EXTRACTION RAW RESPONSE (attempt {attempt})", result)

            raw_parsed = self._parse_json(result)
            err_msg = None
            if not raw_parsed:
                err_msg = "Response was not valid JSON."
            else:
                try:
                    parsed = TimesheetExtraction.model_validate(raw_parsed).model_dump()
                    break
                except ValidationError as ve:
                    err_msg = ve.errors(include_url=False, include_input=False).__str__()[:600]

            logger.warning("[LLM:%s] EXTRACTION attempt %d/%d invalid: %s",
                           call_id, attempt, max_attempts, err_msg)
            if attempt < max_attempts:
                prompt = (
                    base_prompt
                    + "\n\nYour previous answer was rejected: "
                    + (err_msg or "invalid JSON")
                    + "\nReturn ONLY a single JSON object matching the schema exactly. No prose, no markdown."
                )

        if not parsed:
            logger.warning("[LLM:%s] PARSE/VALIDATION FAILED after %d attempts", call_id, max_attempts)
            return None

        logger.info("[LLM:%s] EXTRACTION OK — %d entries  employee=%s",
                    call_id, len(parsed["entries"]), parsed.get("employee_name"))
        _dbg(call_id, "EXTRACTION PARSED JSON", json.dumps(parsed, indent=2))

        # Verification pass (off by default — it can mutate good extractions)
        if verify and settings.LLM_VERIFY_PASS and parsed.get("entries"):
            logger.debug("[LLM:%s] Starting verification pass", call_id)
            try:
                # Pass source text into verification so LLM has ground truth.
                # Never feed it TRUNCATED JSON — that makes it "fix" entries it
                # cannot see and corrupt good data.
                src_for_verify = (source_text or raw_text)
                verify_prompt = VERIFICATION_PROMPT_TEMPLATE.format(
                    source_text=src_for_verify,
                    extracted_json=json.dumps(parsed, indent=2),
                )
                _dbg(call_id, "VERIFICATION PROMPT SENT", verify_prompt, _DBG_PROMPT_CHARS)

                verified_raw = self._call_with_fallback(
                    verify_prompt, call_id=call_id, step="verification", schema=schema)
                if verified_raw:
                    _dbg(call_id, "VERIFICATION RAW RESPONSE", verified_raw)
                    verified = self._parse_json(verified_raw)
                    if verified:
                        try:
                            verified = TimesheetExtraction.model_validate(verified).model_dump()
                        except ValidationError:
                            verified = None
                    if verified and isinstance(verified.get("entries"), list):
                        before, after = len(parsed["entries"]), len(verified["entries"])
                        # Safety guard: do NOT let verification remove entries
                        if after >= before:
                            logger.info("[LLM:%s] VERIFICATION OK — entries %d → %d", call_id, before, after)
                            _dbg(call_id, "VERIFICATION PARSED JSON", json.dumps(verified, indent=2))
                            parsed = verified
                        else:
                            logger.warning(
                                "[LLM:%s] VERIFICATION would remove entries (%d → %d) — keeping extraction result",
                                call_id, before, after,
                            )
                    else:
                        logger.warning("[LLM:%s] VERIFICATION parse failed — keeping extraction result", call_id)
                else:
                    logger.warning("[LLM:%s] VERIFICATION returned empty — keeping extraction result", call_id)
            except Exception as exc:
                logger.warning("[LLM:%s] VERIFICATION exception: %s", call_id, exc)

        logger.info("[LLM:%s] DONE via %s — %d entries  employee=%s",
                    call_id, self._active_backend,
                    len(parsed.get("entries", [])), parsed.get("employee_name"))
        return parsed

    def _call_with_fallback(self, prompt: str, call_id: str = "", step: str = "",
                            schema: Optional[dict] = None) -> Optional[str]:
        """Call configured provider, then fall back to next available.

        ``schema`` (a JSON Schema dict) constrains the model to structured JSON
        output when the provider supports it.
        """
        provider = settings.LLM_PROVIDER.lower()
        tag = f"{step}/" if step else ""

        logger.debug("[LLM:%s] %scalling provider=%s", call_id, tag, provider)

        if provider == "mock":
            return self._call_mock()
        if provider == "ollama":
            result = self._call_ollama(prompt, call_id=call_id, step=step, schema=schema)
            if result:
                self._active_backend = "ollama"
                return result
            result = self._call_trt_llm(prompt, call_id=call_id, step=step, schema=schema)
            if result:
                self._active_backend = "tensorrt_llm"
                return result
        elif provider == "tensorrt_llm":
            result = self._call_trt_llm(prompt, call_id=call_id, step=step, schema=schema)
            if result:
                self._active_backend = "tensorrt_llm"
                return result
            result = self._call_ollama(prompt, call_id=call_id, step=step, schema=schema)
            if result:
                self._active_backend = "ollama"
                return result
        elif provider == "openai":
            if not settings.ALLOW_CLOUD_LLM:
                logger.warning("[LLM:%s] OpenAI provider configured but ALLOW_CLOUD_LLM=false", call_id)
                return None
            result = self._call_openai(prompt, call_id=call_id, step=step, schema=schema)
            if result:
                self._active_backend = "openai"
                return result

        if settings.ALLOW_CLOUD_LLM and settings.OPENAI_API_KEY:
            result = self._call_openai(prompt, call_id=call_id, step=step, schema=schema)
            if result:
                self._active_backend = "openai"
                return result

        logger.error("[LLM:%s] All backends failed for step=%s", call_id, step or "unknown")
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

    def _call_ollama(self, prompt: str, call_id: str = "", step: str = "",
                     system_prompt: str = "", schema: Optional[dict] = None) -> Optional[str]:
        """Call Ollama API. Tries preferred model, then fallback model."""
        base_url      = settings.OLLAMA_BASE_URL
        models_to_try = [settings.OLLAMA_MODEL, settings.OLLAMA_FALLBACK_MODEL]

        for model in models_to_try:
            try:
                import httpx
                logger.debug("[LLM:%s] ollama/%s → POST %s/api/generate  model=%s  prompt_chars=%d  schema=%s",
                             call_id, step, base_url, model, len(prompt), bool(schema))
                payload: dict = {
                    "model": model,
                    # /no_think prefix suppresses <think> blocks on reasoning models
                    # (Nemotron, Qwen3, QwQ) so JSON is produced immediately
                    "prompt": "/no_think\n" + prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0,
                        "num_predict": 8192,   # max tokens in the response
                        "num_ctx":     32768,  # context window — fits full timesheets
                    },
                }
                # Constrain output to the JSON schema when requested (Ollama >= 0.5).
                if schema:
                    payload["format"] = schema
                if system_prompt:
                    payload["system"] = system_prompt
                response = httpx.post(
                    f"{base_url}/api/generate",
                    json=payload,
                    timeout=max(settings.LLM_TIMEOUT, 180),
                )
                logger.debug("[LLM:%s] ollama/%s ← HTTP %d  response_chars=%d",
                             call_id, step, response.status_code,
                             len(response.text))
                if response.status_code == 200:
                    raw = response.json().get("response", "")
                    logger.debug("[LLM:%s] ollama/%s raw response (%d chars): %s",
                                 call_id, step, len(raw),
                                 raw[:_DBG_RESPONSE_CHARS] + (" …" if len(raw) > _DBG_RESPONSE_CHARS else ""))
                    return raw
                elif response.status_code == 404:
                    logger.warning("[LLM:%s] ollama model '%s' not found — trying next", call_id, model)
                    continue
                else:
                    logger.warning("[LLM:%s] ollama HTTP %d: %s", call_id, response.status_code, response.text[:300])
            except Exception as exc:
                logger.warning("[LLM:%s] ollama (%s) exception: %s", call_id, model, exc)
                break

        return None

    def _call_trt_llm(self, prompt: str, call_id: str = "", step: str = "",
                      schema: Optional[dict] = None) -> Optional[str]:
        """Call TRT-LLM on DGX Spark via OpenAI-compatible /v1/chat/completions endpoint."""
        if not settings.LLM_BASE_URL:
            return None
        try:
            import httpx
            logger.debug("[LLM:%s] trtllm/%s → POST %s/chat/completions  prompt_chars=%d",
                         call_id, step, settings.LLM_BASE_URL, len(prompt))
            body: dict = {
                "model":       settings.PRIMARY_LLM_MODEL,
                "messages":    [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens":  4096,
            }
            if schema:
                body["response_format"] = {"type": "json_object"}
            response = httpx.post(
                f"{settings.LLM_BASE_URL}/chat/completions",
                json=body,
                timeout=settings.LLM_TIMEOUT,
            )
            logger.debug("[LLM:%s] trtllm/%s ← HTTP %d", call_id, step, response.status_code)
            if response.status_code == 200:
                data = response.json()
                raw  = data["choices"][0]["message"]["content"].strip()
                logger.debug("[LLM:%s] trtllm/%s raw response (%d chars): %s",
                             call_id, step, len(raw),
                             raw[:_DBG_RESPONSE_CHARS] + (" …" if len(raw) > _DBG_RESPONSE_CHARS else ""))
                return raw
            else:
                logger.warning("[LLM:%s] trtllm HTTP %d: %s", call_id, response.status_code, response.text[:300])
        except Exception as exc:
            logger.warning("[LLM:%s] trtllm exception: %s", call_id, exc)
        return None

    def _call_openai(self, prompt: str, call_id: str = "", step: str = "",
                     schema: Optional[dict] = None) -> Optional[str]:
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
            logger.debug("[LLM:%s] openai/%s → model=%s  prompt_chars=%d",
                         call_id, step, settings.OPENAI_MODEL, len(prompt))
            kwargs: dict = dict(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=4096,
            )
            if schema:
                kwargs["response_format"] = {"type": "json_object"}
            response = self._openai_client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content.strip()
            logger.debug("[LLM:%s] openai/%s raw response (%d chars): %s",
                         call_id, step, len(raw),
                         raw[:_DBG_RESPONSE_CHARS] + (" …" if len(raw) > _DBG_RESPONSE_CHARS else ""))
            return raw
        except Exception as exc:
            logger.warning("[LLM:%s] openai exception: %s", call_id, exc)
            return None

    @staticmethod
    def _parse_json(text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON from LLM response.
        Handles: markdown fences, <think>...</think> reasoning blocks,
        array-wrapped output (Nemotron outputs [{...}] instead of {...}),
        and truncated JSON (missing closing brackets).
        """
        import re as _re
        if not text:
            return None

        def _try_parse(s: str) -> Optional[Dict[str, Any]]:
            try:
                obj = json.loads(s)
                # Unwrap array: some models return [{...}] instead of {...}
                if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                    return obj[0]
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
            return None

        def _repair_and_parse(s: str) -> Optional[Dict[str, Any]]:
            """Close open brackets/braces to repair truncated JSON."""
            repaired = s.rstrip()
            stack: list[str] = []
            in_str = False
            escape = False
            for ch in repaired:
                if escape:
                    escape = False
                    continue
                if ch == "\\" and in_str:
                    escape = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if not in_str:
                    if ch in "{[":
                        stack.append("}" if ch == "{" else "]")
                    elif ch in "}]":
                        if stack and stack[-1] == ch:
                            stack.pop()
            if in_str:
                repaired += '"'
            for closer in reversed(stack):
                repaired += closer
            return _try_parse(repaired)

        try:
            t = text.strip()

            # 1. Strip reasoning/thinking blocks (Nemotron, Qwen3, QwQ, DeepSeek)
            t = _re.sub(r"<think>.*?</think>", "", t, flags=_re.DOTALL | _re.IGNORECASE)
            t = _re.sub(r"<\|thinking\|>.*?<\|/thinking\|>", "", t, flags=_re.DOTALL | _re.IGNORECASE)
            t = _re.sub(r"<\|begin_of_thought\|>.*?<\|end_of_thought\|>", "", t, flags=_re.DOTALL | _re.IGNORECASE)
            t = t.strip()

            # 2. Strip markdown code fences
            if "```" in t:
                parts = t.split("```")
                for part in parts:
                    part = part.strip()
                    if part.startswith("json"):
                        part = part[4:].strip()
                    if part.startswith("{") or part.startswith("["):
                        t = part
                        break

            # 3. Try direct parse first (handles [{...}] array wrapping)
            r = _try_parse(t)
            if r is not None:
                return r

            # 4. Try repair on full text (handles truncated JSON)
            r = _repair_and_parse(t)
            if r is not None:
                return r

            # 5. Find first structural char { or [ and slice from there
            obj_start = t.find("{")
            arr_start = t.find("[")
            if obj_start < 0 and arr_start < 0:
                logger.warning("LLM JSON parse failed: no JSON object found\n  raw (first 400): %s", text[:400])
                return None
            # Pick whichever comes first
            if arr_start >= 0 and (obj_start < 0 or arr_start < obj_start):
                slice_start = arr_start
            else:
                slice_start = obj_start
            sliced = t[slice_start:]

            r = _try_parse(sliced)
            if r is not None:
                return r
            r = _repair_and_parse(sliced)
            if r is not None:
                return r

            logger.warning("LLM JSON parse failed after all attempts\n  raw (first 400): %s", text[:400])
            return None

        except Exception as exc:
            logger.warning("LLM JSON parse unexpected error: %s\n  raw (first 400 chars): %s",
                           exc, text[:400])
            return None
