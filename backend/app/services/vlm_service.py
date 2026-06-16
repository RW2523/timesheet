"""
VLM Service — Vision OCR layer.

SOLE PURPOSE: read every piece of visible text from an image or PDF page
and return it as a plain string.  No JSON, no structured extraction, no
rule parsing.  Callers receive raw text and can feed it to the LLM stage.

Pipeline:
  image / PDF  →  VLMService.read_text_from_*()
              →  per-page raw text list  +  combined raw_text (str)
              →  caller feeds raw_text to LLM

Model priority (first available in Ollama):
  llava:13b > llava:7b > llava > llava-phi3 > moondream >
  bakllava > minicpm-v > llama3.2-vision > any model with "vision"/"llava"
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".bmp"}

# 250 DPI gives sharp text on dense tables without being huge
PDF_RENDER_DPI = 250

VISION_MODEL_CANDIDATES = [
    # Qwen2.5-VL — best document/table understanding, top priority
    "qwen2.5vl:7b", "qwen2.5vl:3b", "qwen2.5vl:72b", "qwen2.5vl",
    # llava fallbacks
    "llava:13b", "llava:7b", "llava", "llava-phi3",
    "moondream", "bakllava", "minicpm-v", "llama3.2-vision",
]

# ── OCR prompt ────────────────────────────────────────────────────────────────
# The VLM is used like a high-accuracy scanner.
# It MUST NOT invent values, add JSON, or summarise — only transcribe.

OCR_PROMPT = """\
You are an OCR scanner reading a timesheet document image.

YOUR JOB: transcribe every piece of text you can see, exactly as it appears, \
and — critically — REPRODUCE TABLES AS TABLES so the column structure survives.

INCLUDE ALL OF THE FOLLOWING:
- Company / employer name, logo text, header lines
- Employee name, employee ID, department, job title, manager name
- Pay period, pay dates, timesheet period, week ending date
- Every row in every table: date, day of week, in-time, out-time, \
  break time, regular hours, overtime hours, sick hours, vacation hours, \
  holiday hours, total hours, task / project code, notes / comments
- Sub-total rows, weekly total rows, grand total rows
- Footer lines, certification text, signature labels, approval text, \
  approval dates, status fields

TABLE RULES (most important):
- Output every table as a GitHub-style Markdown table using pipes (|).
- Keep the header row, then one line per data row.
- Preserve the EXACT column order, one cell per column.
- If a cell is empty, still emit the empty column (`| |`) so columns stay aligned.
- Do NOT merge two columns into one and do NOT split one row across multiple lines.

DO NOT:
- Add commentary, explanations, or headings that are not in the image
- Invent or guess any value you cannot clearly see (leave the cell blank instead)
- Skip any row or column
- Summarise or paraphrase

Output the non-table text as plain lines, and every table as a Markdown table.
"""


class VLMService:
    """Vision OCR service.  Returns raw page text; all structuring is done by callers."""

    def __init__(self) -> None:
        self._base_url      = settings.OLLAMA_BASE_URL
        self._vision_model: Optional[str] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_available_vision_model(self) -> Optional[str]:
        """Return the first available Ollama vision model, or None."""
        if self._vision_model:
            return self._vision_model
        try:
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=10)
            if resp.status_code != 200:
                return None
            models = [m["name"] for m in resp.json().get("models", [])]
            for candidate in VISION_MODEL_CANDIDATES:
                for m in models:
                    if m == candidate or m.startswith(candidate + ":"):
                        self._vision_model = m
                        logger.info("VLM: selected model %s", m)
                        return m
            for m in models:
                if any(kw in m.lower() for kw in ("vision", "llava", "moondream", "qwen2.5vl")):
                    self._vision_model = m
                    logger.info("VLM: selected model %s (keyword match)", m)
                    return m
        except httpx.ConnectError:
            logger.warning(
                "VLM: cannot reach Ollama at %s — ensure Ollama is running with "
                "OLLAMA_HOST=0.0.0.0:11434", self._base_url,
            )
        except Exception as exc:
            logger.warning("VLM: could not list Ollama models: %s", exc)
        return None

    def read_text_from_image(self, path: str, ext: str) -> Dict[str, Any]:
        """Read raw OCR text from a single image file."""
        model = self.get_available_vision_model()
        if not model:
            return self._no_model_result()

        t0      = time.perf_counter()
        img_b64 = self._load_image_as_b64(path)
        text, err = self._call_vision(model, img_b64)
        elapsed = round((time.perf_counter() - t0) * 1000)

        if err:
            return {
                "error": err, "raw_text": "", "model": model,
                "pages_processed": 0, "page_results": [],
            }

        return self._build_result(
            model, raw_text=text, pages_processed=1,
            page_results=[{
                "page": 1, "status": "success",
                "chars": len(text), "duration_ms": elapsed,
                "preview": text[:200] + ("…" if len(text) > 200 else ""),
            }],
        )

    def read_text_from_pdf(self, path: str, max_pages: int = 20) -> Dict[str, Any]:
        """Render every PDF page to an image and read OCR text from each page."""
        model = self.get_available_vision_model()
        if not model:
            return self._no_model_result()

        images = self._render_pdf_pages(path, max_pages)
        if not images:
            return {
                "error": "Could not render PDF pages to images.",
                "raw_text": "", "model": model,
                "pages_processed": 0, "page_results": [],
            }

        return self._process_pages(images, model)

    # ── Backward-compat aliases used by existing callers ───────────────────────

    def extract_from_image_file(self, path: str, ext: str) -> Dict[str, Any]:
        return self.read_text_from_image(path, ext)

    def extract_from_pdf(self, path: str, max_pages: int = 20) -> Dict[str, Any]:
        return self.read_text_from_pdf(path, max_pages)

    # ── Core page processing ───────────────────────────────────────────────────

    def _process_pages(self, page_b64_list: List[str], model: str) -> Dict[str, Any]:
        """Call the vision model on each page and accumulate raw text."""
        page_texts:   List[str]  = []
        page_results: List[Dict] = []
        errors:       List[str]  = []

        for idx, img_b64 in enumerate(page_b64_list):
            t0       = time.perf_counter()
            page_num = idx + 1
            logger.info("vlm: processing page %d/%d  model=%s", page_num, len(page_b64_list), model)

            text, err = self._call_vision(model, img_b64)
            elapsed   = round((time.perf_counter() - t0) * 1000)

            if err:
                errors.append(f"Page {page_num}: {err}")
                page_results.append({
                    "page": page_num, "status": "error",
                    "error": err, "duration_ms": elapsed, "chars": 0,
                })
                logger.warning("vlm page %d error: %s", page_num, err)
                continue

            page_texts.append(text)
            page_results.append({
                "page":        page_num,
                "status":      "success",
                "chars":       len(text),
                "duration_ms": elapsed,
                "preview":     text[:300] + ("…" if len(text) > 300 else ""),
            })
            logger.info("vlm page %d: %d chars  elapsed=%dms  preview=%s",
                        page_num, len(text), elapsed, repr(text[:120]))

        # Join pages with a clear page-break separator so the LLM can see page boundaries
        combined = "\n\n--- PAGE BREAK ---\n\n".join(page_texts)

        logger.info(
            "vlm: DONE  pages=%d  successful=%d  errors=%d  total_chars=%d",
            len(page_b64_list), len(page_texts), len(errors), len(combined),
        )

        return self._build_result(
            model,
            raw_text        = combined,
            pages_processed = len(page_b64_list),
            page_results    = page_results,
            errors          = errors,
        )

    def _build_result(
        self,
        model:           str,
        raw_text:        str,
        pages_processed: int,
        page_results:    List[Dict],
        errors:          Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Return raw OCR result.
        NO rule-parser, NO JSON extraction — raw text only.
        The caller (test-lab LLM stage, main pipeline, etc.) handles structuring.
        """
        return {
            "model":           model,
            "pages_processed": pages_processed,
            "raw_text":        raw_text,
            "text_chars":      len(raw_text),
            "page_results":    page_results,
            "errors":          errors or [],
        }

    # ── Single-image OCR call ──────────────────────────────────────────────────

    def _call_vision(self, model: str, img_b64: str) -> Tuple[str, Optional[str]]:
        """Send one image to the vision model with the raw OCR prompt.

        Returns (raw_text, error_or_None).
        The VLM is NOT asked to produce JSON — only to transcribe visible text.
        """
        timeout = max(getattr(settings, "LLM_TIMEOUT", 300), 300)
        try:
            resp = httpx.post(
                f"{self._base_url}/api/generate",
                json={
                    "model":   model,
                    "prompt":  OCR_PROMPT,
                    "images":  [img_b64],
                    "stream":  False,
                    "options": {
                        "temperature": 0,
                        "num_predict": 8192,   # large enough to capture full tables
                        "num_ctx":     16384,
                    },
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                return "", f"Ollama HTTP {resp.status_code}: {resp.text[:300]}"
            text = resp.json().get("response", "").strip()
            if not text:
                return "", "VLM returned an empty response — no visible text found"
            return text, None
        except httpx.TimeoutException:
            return "", f"VLM request timed out after {timeout}s"
        except Exception as exc:
            return "", str(exc)

    # ── Backward-compat alias ──────────────────────────────────────────────────

    def _call_vision_raw_text(self, model: str, img_b64: str) -> Tuple[str, Optional[str]]:
        """Alias kept for callers that used the old method name."""
        return self._call_vision(model, img_b64)

    # ── Image helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_image_as_b64(path: str) -> str:
        from PIL import Image
        import io
        with Image.open(path) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()

    @staticmethod
    def _render_pdf_pages(path: str, max_pages: int = 20) -> List[str]:
        """Render all PDF pages as base64 PNG strings."""
        try:
            import fitz
            doc    = fitz.open(path)
            n      = min(len(doc), max_pages)
            logger.info("vlm: rendering %d/%d PDF pages at %d DPI", n, len(doc), PDF_RENDER_DPI)
            result = []
            for i in range(n):
                page = doc[i]
                mat  = fitz.Matrix(PDF_RENDER_DPI / 72, PDF_RENDER_DPI / 72)
                pix  = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                result.append(base64.b64encode(pix.tobytes("png")).decode())
            doc.close()
            return result
        except Exception as exc:
            logger.warning("VLM: PDF render failed: %s", exc)
            return []

    # ── Error helpers ──────────────────────────────────────────────────────────

    def _no_model_result(self) -> Dict[str, Any]:
        hint = (
            f"Ollama unreachable at {self._base_url} — "
            "ensure Ollama is running with OLLAMA_HOST=0.0.0.0:11434"
        )
        return {
            "error":           (
                f"No vision model found in Ollama. {hint}. "
                "Pull one with: ollama pull qwen2.5vl:7b"
            ),
            "raw_text":        "",
            "text_chars":      0,
            "model":           None,
            "pages_processed": 0,
            "page_results":    [],
            "errors":          [],
        }
