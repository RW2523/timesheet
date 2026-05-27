"""
Email classifier service.

Two-tier classification:
1. Rule-based (fast, no LLM): checks subject, sender patterns, attachment types
2. LLM-based (for ambiguous emails): sends subject + body snippet to LLM

Returns: (is_timesheet: bool, confidence: float, method: str, reason: str)
"""
import logging
import re
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# Strong signals in subject/body that this is a timesheet submission
_TIMESHEET_SUBJECT_PATTERNS = re.compile(
    r"\btimesheet\b|\btime\s*sheet\b|\btime\s*record\b"
    r"|\bhours?\s*submission\b|\bhours?\s*report\b"
    r"|\bweekly\s*hours?\b|\bmonthly\s*hours?\b"
    r"|\bwork\s*log\b|\battendance\b"
    r"|\bts\s+(?:for|submission|apr|may|jan|feb|mar|jun|jul|aug|sep|oct|nov|dec)\b"
    r"|\bts[-_\s]?\d{4}\b"
    r"|\bplease\s+find.*(?:timesheet|hours)\b"
    r"|\bsubmitting.*(?:timesheet|hours)\b",
    re.IGNORECASE,
)

_TIMESHEET_BODY_PATTERNS = re.compile(
    r"\btimesheet\b|\btime\s*sheet\b|\bhours?\s+for\b"
    r"|\bplease\s+(find|see|review)\b|\bkindly\s+(find|approve)\b"
    r"|\battached.*(?:timesheet|hours)\b"
    r"|\bpayroll\s+period\b|\bbilling\s+period\b",
    re.IGNORECASE,
)

# Strong signals this is NOT a timesheet
_NON_TIMESHEET_PATTERNS = re.compile(
    r"\binvoice\b|\breceipt\b|\bquotation\b|\bproposal\b"
    r"|\bmeeting\b|\bcalendar\b|\binterview\b"
    r"|\bunsubscribe\b|\bnewsletter\b|\bpromotion\b"
    r"|\bpurchase\s+order\b|\bstatement\b",
    re.IGNORECASE,
)

# Attachment MIME types that are likely to contain timesheets
_TIMESHEET_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
    "application/vnd.ms-excel",                                            # xls
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "image/png", "image/jpeg", "image/tiff",                              # scanned images
}

_TIMESHEET_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".tiff"}


class EmailClassifier:
    def __init__(self):
        from app.core.config import settings
        self._settings = settings

    def classify(
        self,
        subject: str,
        body_text: str,
        attachments: list,
        sender_email: str = "",
    ) -> Tuple[bool, float, str, str]:
        """
        Classify an email as timesheet submission or not.

        Returns: (is_timesheet, confidence 0-1, method, reason)
        """
        subject = subject or ""
        body = body_text or ""

        # ── Rule-based tier ──────────────────────────────────────────────────
        rule_result = self._rule_based(subject, body, attachments)
        rb_is_ts, rb_conf, rb_reason = rule_result

        # If rule-based is decisive (high confidence either way), use it
        if rb_conf >= 0.80:
            return rb_is_ts, rb_conf, "RULE_BASED", rb_reason

        # ── LLM tier for ambiguous cases ────────────────────────────────────
        if self._settings.LLM_ENABLED:
            try:
                llm_is_ts, llm_conf, llm_reason = self._llm_classify(subject, body)
                # Blend: LLM result with a slight rule-based bias
                blended = 0.6 * llm_conf + 0.4 * rb_conf
                if llm_is_ts == rb_is_ts:
                    return llm_is_ts, min(blended + 0.1, 1.0), "LLM", llm_reason
                # Disagreement: trust LLM when confidence is high
                if llm_conf >= 0.70:
                    return llm_is_ts, llm_conf, "LLM", llm_reason
            except Exception as e:
                logger.warning(f"LLM email classification failed: {e}")

        # Fall back to rule-based result
        return rb_is_ts, rb_conf, "RULE_BASED", rb_reason

    def _rule_based(
        self, subject: str, body: str, attachments: list
    ) -> Tuple[bool, float, str]:
        score = 0.0
        reasons = []

        # Non-timesheet — hard veto
        if _NON_TIMESHEET_PATTERNS.search(subject):
            return False, 0.95, f"Subject contains non-timesheet keywords"

        # Subject match
        if _TIMESHEET_SUBJECT_PATTERNS.search(subject):
            score += 0.50
            reasons.append("subject matches timesheet pattern")

        # Body match
        if _TIMESHEET_BODY_PATTERNS.search(body):
            score += 0.25
            reasons.append("body mentions timesheet/hours")

        # Has timesheet-type attachments
        ts_attachments = [
            a for a in attachments
            if (
                any(a["name"].lower().endswith(ext) for ext in _TIMESHEET_EXTENSIONS)
                or a.get("mime", "") in _TIMESHEET_MIME_TYPES
            )
        ]
        if ts_attachments:
            score += 0.30
            names = ", ".join(a["name"] for a in ts_attachments[:3])
            reasons.append(f"has timesheet-type attachments: {names}")

        # No attachments at all and no subject match — probably not a submission
        if not attachments and score < 0.25:
            return False, 0.70, "no attachments and no subject match"

        reason = "; ".join(reasons) if reasons else "no matching signals"
        is_ts  = score >= 0.40
        # Normalise confidence: cap at 0.95 from rules alone
        confidence = min(score, 0.95) if is_ts else max(0.05, 1.0 - score)
        return is_ts, round(confidence, 3), reason

    def _llm_classify(self, subject: str, body: str) -> Tuple[bool, float, str]:
        """Ask the LLM to classify the email."""
        from app.services.llm_service import LLMService
        llm = LLMService()
        prompt = (
            "You are an HR document classifier. Determine if this email is a timesheet submission.\n\n"
            f"Subject: {subject[:200]}\n"
            f"Body snippet: {body[:500]}\n\n"
            "Reply in JSON only:\n"
            '{"is_timesheet": true/false, "confidence": 0.0-1.0, "reason": "short explanation"}'
        )
        raw = llm._call_with_fallback(prompt)
        if not raw:
            raise RuntimeError("LLM returned no response")
        parsed = llm._parse_json(raw)
        if not parsed:
            raise RuntimeError("LLM returned unparseable JSON")
        is_ts  = bool(parsed.get("is_timesheet", False))
        conf   = float(parsed.get("confidence", 0.5))
        reason = str(parsed.get("reason", ""))
        return is_ts, conf, reason
