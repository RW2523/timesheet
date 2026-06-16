"""
OCR + VLM fusion extraction.

Image-only documents are the hard case: OCR alone gives accurate characters but
destroys table layout; a VLM alone understands layout but hallucinates digits.
This service runs BOTH per page and correlates them:

    render page image
        │
        ├── OCR (PaddleOCR -> Tesseract)  -> accurate text + bounding boxes
        │        └── cluster boxes into rows/cols -> layout-ordered transcript
        │
        └── VLM (image + OCR transcript)  -> clean Markdown tables
                 (image = layout, OCR text = source of truth for characters)
        ▼
    fused Markdown  ->  parse tables  ->  raw_tables (canonical rows)
        ▼
    (downstream) schema-enforced LLM extraction -> structured JSON

Output matches the parser contract used elsewhere:
    { raw_text, raw_tables, ocr_text, page_results, model, confidence,
      extraction_method, warnings }
"""
from __future__ import annotations

import base64
import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.services.vlm_service import VLMService, IMAGE_EXTS

logger = logging.getLogger(__name__)

# Render DPI for OCR/VLM. High enough for small table fonts, capped for payload size.
_FUSION_DPI = 220
# Boxes whose vertical centres are within this fraction of the median line height
# are treated as the same row when rebuilding the layout-ordered transcript.
_ROW_MERGE_RATIO = 0.6


class OcrVlmFusionService:
    def __init__(self) -> None:
        self.vlm = VLMService()

    # ── Public API ──────────────────────────────────────────────────────────

    def process(self, path: str, ext: str, max_pages: int = 20) -> Dict[str, Any]:
        ext = (ext or "").lower()
        model = self.vlm.get_available_vision_model()
        if not model:
            return {
                "raw_text": "", "raw_tables": [], "ocr_text": "",
                "page_results": [], "model": None, "confidence": 0.0,
                "extraction_method": "ocr_vlm_fusion",
                "warnings": [self.vlm._no_model_result()["error"]],
                "error": "No vision model available for fusion.",
            }

        if ext in IMAGE_EXTS:
            page_images = [path]
            temp_pages = False
        elif ext == ".pdf":
            page_images = self._render_pdf_pages(path, max_pages)
            temp_pages = True
        else:
            return {
                "raw_text": "", "raw_tables": [], "ocr_text": "",
                "page_results": [], "model": model, "confidence": 0.0,
                "extraction_method": "ocr_vlm_fusion",
                "warnings": [f"Fusion not applicable for {ext}"],
                "error": f"OCR+VLM fusion supports PDF and images, not {ext}",
            }

        if not page_images:
            return {
                "raw_text": "", "raw_tables": [], "ocr_text": "",
                "page_results": [], "model": model, "confidence": 0.0,
                "extraction_method": "ocr_vlm_fusion",
                "warnings": ["Could not render any pages"],
                "error": "Could not render document pages to images.",
            }

        fused_parts: List[str] = []
        ocr_parts: List[str] = []
        page_results: List[Dict[str, Any]] = []
        warnings: List[str] = []

        try:
            for idx, img_path in enumerate(page_images):
                page_num = idx + 1
                t0 = time.perf_counter()
                try:
                    ocr_text, ocr_engine, ocr_conf = self._ocr_with_geometry(img_path)
                    img_b64 = self._image_to_b64(img_path)
                    fused, err = self.vlm.correlate_page(img_b64, ocr_text, model=model)
                    elapsed = round((time.perf_counter() - t0) * 1000)

                    if err and not fused:
                        # VLM failed — still keep the OCR transcript so we lose nothing.
                        fused = ocr_text
                        warnings.append(f"Page {page_num}: VLM failed ({err}); using OCR transcript")

                    fused_parts.append(fused)
                    ocr_parts.append(ocr_text)
                    page_results.append({
                        "page": page_num,
                        "status": "success" if fused else "empty",
                        "ocr_engine": ocr_engine,
                        "ocr_chars": len(ocr_text),
                        "ocr_confidence": ocr_conf,
                        "fused_chars": len(fused),
                        "duration_ms": elapsed,
                        "ocr_preview": ocr_text[:200] + ("…" if len(ocr_text) > 200 else ""),
                        "fused_preview": fused[:200] + ("…" if len(fused) > 200 else ""),
                    })
                    logger.info("fusion page %d/%d: ocr=%d chars (%s), fused=%d chars, %dms",
                                page_num, len(page_images), len(ocr_text), ocr_engine,
                                len(fused), elapsed)
                except Exception as exc:
                    logger.exception("fusion page %d failed", page_num)
                    page_results.append({"page": page_num, "status": "error", "error": str(exc)})
        finally:
            if temp_pages:
                for p in page_images:
                    try:
                        os.remove(p)
                    except OSError:
                        pass

        combined = "\n\n--- PAGE BREAK ---\n\n".join(p for p in fused_parts if p)
        raw_tables = self._markdown_to_tables(combined)

        return {
            "raw_text": combined,
            "raw_tables": raw_tables,
            "ocr_text": "\n\n--- PAGE BREAK ---\n\n".join(ocr_parts),
            "page_results": page_results,
            "model": model,
            "pages_processed": len(page_images),
            "confidence": 0.9 if combined.strip() else 0.0,
            "extraction_method": "ocr_vlm_fusion",
            "ocr_required": False,
            "warnings": warnings,
        }

    # ── Rendering helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _render_pdf_pages(path: str, max_pages: int) -> List[str]:
        """Render PDF pages to temp PNG files (OCR needs files on disk)."""
        try:
            import fitz
        except Exception as exc:
            logger.warning("fusion: PyMuPDF unavailable: %s", exc)
            return []
        out: List[str] = []
        try:
            doc = fitz.open(path)
            n = min(len(doc), max_pages)
            mat = fitz.Matrix(_FUSION_DPI / 72, _FUSION_DPI / 72)
            for i in range(n):
                pix = doc[i].get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                fd, tmp = tempfile.mkstemp(suffix=f"_fusion_p{i}.png")
                os.close(fd)
                pix.save(tmp)
                out.append(tmp)
            doc.close()
        except Exception as exc:
            logger.warning("fusion: PDF render failed: %s", exc)
        return out

    @staticmethod
    def _image_to_b64(image_path: str) -> str:
        from PIL import Image
        import io
        with Image.open(image_path) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()

    # ── OCR with geometry ─────────────────────────────────────────────────────

    def _ocr_with_geometry(self, image_path: str) -> Tuple[str, str, float]:
        """Return (layout_ordered_transcript, engine, mean_confidence).

        Tries PaddleOCR (keeps bounding boxes) then Tesseract (image_to_data).
        Boxes are clustered into rows so the transcript keeps reading order.
        """
        boxes = self._paddle_boxes(image_path)
        engine = "paddleocr"
        if not boxes:
            boxes = self._tesseract_boxes(image_path)
            engine = "tesseract"
        if not boxes:
            return "", "none", 0.0

        transcript = self._boxes_to_transcript(boxes)
        confs = [b["conf"] for b in boxes if b.get("conf") is not None]
        mean_conf = round(sum(confs) / len(confs), 3) if confs else 0.0
        return transcript, engine, mean_conf

    @staticmethod
    def _paddle_boxes(image_path: str) -> List[Dict[str, Any]]:
        try:
            from paddleocr import PaddleOCR
        except Exception:
            return []
        try:
            ocr = PaddleOCR(use_angle_cls=True, lang="en",
                            use_gpu=settings.OCR_USE_GPU, show_log=False)
            data = ocr.ocr(image_path, cls=True)
            out: List[Dict[str, Any]] = []
            if data and data[0]:
                for item in data[0]:
                    if not item or len(item) < 2:
                        continue
                    poly = item[0]            # 4 (x, y) points
                    text = item[1][0]
                    conf = float(item[1][1]) if len(item[1]) > 1 else None
                    xs = [pt[0] for pt in poly]
                    ys = [pt[1] for pt in poly]
                    out.append({
                        "text": text, "conf": conf,
                        "x": min(xs), "y": min(ys),
                        "h": max(ys) - min(ys), "w": max(xs) - min(xs),
                    })
            return out
        except Exception as exc:
            logger.warning("fusion: PaddleOCR failed: %s", exc)
            return []

    @staticmethod
    def _tesseract_boxes(image_path: str) -> List[Dict[str, Any]]:
        try:
            import pytesseract
            from PIL import Image
        except Exception:
            return []
        try:
            data = pytesseract.image_to_data(
                Image.open(image_path), output_type=pytesseract.Output.DICT)
            out: List[Dict[str, Any]] = []
            n = len(data["text"])
            for i in range(n):
                txt = (data["text"][i] or "").strip()
                if not txt:
                    continue
                conf = float(data["conf"][i]) / 100.0 if data["conf"][i] not in ("-1", -1) else None
                out.append({
                    "text": txt, "conf": conf,
                    "x": data["left"][i], "y": data["top"][i],
                    "h": data["height"][i], "w": data["width"][i],
                })
            return out
        except Exception as exc:
            logger.warning("fusion: Tesseract failed: %s", exc)
            return []

    @staticmethod
    def _boxes_to_transcript(boxes: List[Dict[str, Any]]) -> str:
        """Cluster word/line boxes into rows (by y), order each row by x.

        Produces a tab-separated, reading-ordered transcript that preserves the
        rough column structure for the VLM to ground on.
        """
        if not boxes:
            return ""
        heights = sorted(b["h"] for b in boxes if b["h"] > 0)
        median_h = heights[len(heights) // 2] if heights else 12
        tol = max(median_h * _ROW_MERGE_RATIO, 4)

        rows: List[List[Dict[str, Any]]] = []
        for b in sorted(boxes, key=lambda d: (d["y"], d["x"])):
            cy = b["y"] + b["h"] / 2
            placed = False
            for row in rows:
                ry = row[0]["y"] + row[0]["h"] / 2
                if abs(cy - ry) <= tol:
                    row.append(b)
                    placed = True
                    break
            if not placed:
                rows.append([b])

        lines: List[str] = []
        for row in rows:
            cells = sorted(row, key=lambda d: d["x"])
            lines.append("\t".join(c["text"] for c in cells))
        return "\n".join(lines)

    # ── Markdown table parsing ────────────────────────────────────────────────

    @staticmethod
    def _markdown_to_tables(md: str) -> List[Dict[str, Any]]:
        """Extract GitHub-style Markdown tables into {sheet, rows} structures."""
        tables: List[Dict[str, Any]] = []
        block: List[List[str]] = []
        idx = 0

        def _flush():
            nonlocal block, idx
            # A real table needs a header + at least one data row.
            if len(block) >= 2:
                idx += 1
                tables.append({"sheet": f"table_{idx}", "rows": block})
            block = []

        for line in md.splitlines():
            s = line.strip()
            if s.startswith("|") and s.count("|") >= 2:
                cells = [c.strip() for c in s.strip("|").split("|")]
                # skip the |---|---| separator row
                if all(set(c) <= {"-", ":", " "} and c for c in cells):
                    continue
                block.append(cells)
            else:
                _flush()
        _flush()
        return tables
