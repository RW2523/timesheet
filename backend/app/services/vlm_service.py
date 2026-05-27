"""
VLM Service — Vision-as-OCR layer.

The VLM is used ONLY to read visible text from image/PDF pages.
It does NOT extract structured JSON.  All structuring and validation
is delegated to TimesheetRuleParser (app/services/timesheet_rule_parser.py).

Pipeline:
  image/PDF  →  VLMService.read_text_from_*()  →  raw_text (str)
             →  TimesheetRuleParser.parse(raw_text)  →  validated result dict

Model priority (first one found in Ollama):
  1. llava:13b
  2. llava:7b  (default pull)
  3. llava
  4. llava-phi3
  5. moondream
  6. bakllava
  7. minicpm-v
  8. llama3.2-vision
  9. Any model containing "vision" or "llava"
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
    "llava:13b", "llava:7b", "llava", "llava-phi3",
    "moondream", "bakllava", "minicpm-v", "llama3.2-vision",
]

# ── OCR prompt ─────────────────────────────────────────────────────────────────
# The VLM is used like a smart scanner.  Ask for EXACT text, nothing invented.

OCR_PROMPT = """\
You are acting as an OCR scanner reading a document image.

Your only job: output every piece of text you can see in this image,
line by line, exactly as it appears.

Include:
- All header lines (company name, employee name, ID, department, dates, period)
- Every row in every table (date, day, in-time, out-time, break, hours, task, notes)
- All total/summary lines at the bottom
- Any approval, signature, or stamp text

Do NOT:
- Add commentary, explanations, or formatting
- Invent or guess values you cannot see
- Skip any line, even if it looks empty or redundant

Output the raw document text only.
"""


class VLMService:
    """Vision-as-OCR service.  Returns raw text; caller handles structuring."""

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
                    if m == candidate or m.startswith(candidate):
                        self._vision_model = m
                        return m
            for m in models:
                if any(kw in m.lower() for kw in ("vision", "llava", "moondream")):
                    self._vision_model = m
                    return m
        except httpx.ConnectError:
            logger.warning(
                "VLM: cannot reach Ollama at %s — start ollama with "
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

        img_b64 = self._load_image_as_b64(path)
        text, err = self._call_vision_raw_text(model, img_b64)
        if err:
            return {"error": err, "raw_text": "", "model": model, "pages_processed": 0}

        return self._finalize(model, raw_text=text, pages_processed=1,
                              page_results=[{"page": 1, "status": "success",
                                             "chars": len(text)}])

    def read_text_from_pdf(self, path: str, max_pages: int = 10) -> Dict[str, Any]:
        """Render each PDF page to an image, read OCR text from each."""
        model = self.get_available_vision_model()
        if not model:
            return self._no_model_result()

        images = self._render_pdf_pages(path, max_pages)
        if not images:
            return {"error": "Could not render PDF pages to images.",
                    "raw_text": "", "model": model, "pages_processed": 0}

        return self._process_pages(images, model)

    # ── Backward-compat aliases used by existing callers ───────────────────────

    def extract_from_image_file(self, path: str, ext: str) -> Dict[str, Any]:
        return self.read_text_from_image(path, ext)

    def extract_from_pdf(self, path: str, max_pages: int = 10) -> Dict[str, Any]:
        return self.read_text_from_pdf(path, max_pages)

    # ── Core page processing ───────────────────────────────────────────────────

    def _process_pages(
        self, page_b64_list: List[str], model: str
    ) -> Dict[str, Any]:
        page_texts:   List[str]  = []
        page_results: List[Dict] = []
        errors:       List[str]  = []

        for idx, img_b64 in enumerate(page_b64_list):
            t0       = time.perf_counter()
            page_num = idx + 1
            text, err = self._call_vision_raw_text(model, img_b64)
            elapsed  = round((time.perf_counter() - t0) * 1000)

            if err:
                errors.append(f"Page {page_num}: {err}")
                page_results.append({
                    "page": page_num, "status": "error",
                    "error": err, "duration_ms": elapsed,
                })
                continue

            page_texts.append(text)
            page_results.append({
                "page": page_num, "status": "success",
                "chars": len(text), "duration_ms": elapsed,
                "preview": text[:200] + ("…" if len(text) > 200 else ""),
            })

        combined = "\n\n--- PAGE BREAK ---\n\n".join(page_texts)
        return self._finalize(
            model,
            raw_text       = combined,
            pages_processed= len(page_b64_list),
            page_results   = page_results,
            errors         = errors,
        )

    def _finalize(
        self,
        model:           str,
        raw_text:        str,
        pages_processed: int,
        page_results:    List[Dict],
        errors:          Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Run the rule parser on the combined raw text and return full result."""
        from app.services.timesheet_rule_parser import TimesheetRuleParser

        parsed = TimesheetRuleParser.parse(raw_text)
        return {
            "model":           model,
            "pages_processed": pages_processed,
            "raw_text":        raw_text,
            "page_results":    page_results,
            "errors":          errors or [],
            # Rule-parser fields — promoted to top level for easy access
            **parsed,
        }

    # ── Single-image OCR call ──────────────────────────────────────────────────

    def _call_vision_raw_text(
        self, model: str, img_b64: str
    ) -> Tuple[str, Optional[str]]:
        """Send one image to Ollama with the OCR prompt.

        Returns (raw_text, error_or_None).
        The VLM is NOT asked to format JSON — just to transcribe the visible text.
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
                        "num_predict": 4096,
                    },
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                return "", f"HTTP {resp.status_code}: {resp.text[:200]}"
            text = resp.json().get("response", "").strip()
            return text, None
        except Exception as exc:
            return "", str(exc)

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
    def _render_pdf_pages(path: str, max_pages: int = 10) -> List[str]:
        try:
            import fitz
            import io
            doc    = fitz.open(path)
            n      = min(len(doc), max_pages)
            result = []
            for i in range(n):
                page     = doc[i]
                mat      = fitz.Matrix(PDF_RENDER_DPI / 72, PDF_RENDER_DPI / 72)
                pix      = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
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
            "error":           f"No vision model found in Ollama. {hint}. "
                               "Pull one with: ollama pull llava:7b",
            "raw_text":        "",
            "entries":         [],
            "entries_found":   0,
            "model":           None,
            "pages_processed": 0,
        }
