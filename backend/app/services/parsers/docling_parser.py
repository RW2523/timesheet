"""
Docling parser — AI-powered layout-aware document extraction.
Uses IBM Docling for superior table, form, and text extraction from PDFs and DOCX.
Falls back gracefully if Docling is unavailable or fails.
"""
import logging
import os
from typing import Dict, Any, Optional, List

from app.core.config import settings

logger = logging.getLogger(__name__)

_docling_converter = None


def _get_converter():
    """Lazy-init Docling converter. Downloads models on first use to /storage/docling_models."""
    global _docling_converter
    if _docling_converter is None:
        try:
            import os

            # Configure HuggingFace to use persistent storage before importing Docling
            hf_home = settings.DOCLING_ARTIFACTS_PATH
            os.makedirs(hf_home, exist_ok=True)
            os.environ["HF_HOME"] = hf_home
            os.environ["TRANSFORMERS_CACHE"] = hf_home
            # Docling-specific cache env var
            os.environ["DOCLING_ARTIFACTS_PATH"] = hf_home

            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
            import torch

            use_gpu = torch.cuda.is_available()
            logger.info(f"Docling: initializing (GPU={'yes' if use_gpu else 'no/CPU'}, cache={hf_home})")

            # do_ocr=False — we use our own PaddleOCR/Tesseract pipeline for scanned docs
            # Docling focuses on layout analysis and table structure extraction
            pipeline_options = PdfPipelineOptions(
                do_ocr=False,
                do_table_structure=True,
            )
            pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
            pipeline_options.table_structure_options.do_cell_matching = True

            _docling_converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                }
            )
            logger.info("Docling converter initialized successfully (models will auto-download)")
        except ImportError:
            logger.warning("Docling not installed — skipping Docling extraction")
            _docling_converter = "unavailable"
        except Exception as e:
            logger.error(f"Docling init failed: {e}")
            _docling_converter = "unavailable"

    return None if _docling_converter == "unavailable" else _docling_converter


class DoclingParser:
    """
    Wraps IBM Docling for AI-powered document parsing.

    Output format matches the rest of the parsers:
    {
        "raw_text": str,
        "raw_tables": [{"sheet": str, "rows": [[cell, ...]]}],
        "ocr_required": bool,
        "confidence": float,
        "warnings": [str],
        "extraction_method": "docling",
    }
    """

    def parse(self, file_path: str) -> Optional[Dict[str, Any]]:
        converter = _get_converter()
        if converter is None:
            return None

        try:
            from docling.datamodel.base_models import ConversionStatus
            result = converter.convert(file_path)

            if result.status not in (
                ConversionStatus.SUCCESS,
                ConversionStatus.PARTIAL_SUCCESS,
            ):
                logger.warning(f"Docling conversion failed for {file_path}: {result.status}")
                return None

            doc = result.document

            # Extract full markdown text (preserves structure)
            raw_text = doc.export_to_markdown()

            # Extract all tables as structured rows
            raw_tables = self._extract_tables(doc)

            warnings = []
            if result.status == ConversionStatus.PARTIAL_SUCCESS:
                warnings.append("Docling partial success — some pages may be incomplete")

            logger.info(
                f"Docling extracted: {len(raw_text)} chars, {len(raw_tables)} tables from {os.path.basename(file_path)}"
            )

            return {
                "raw_text": raw_text,
                "raw_tables": raw_tables,
                "ocr_required": False,
                "confidence": 0.92,
                "warnings": warnings,
                "extraction_method": "docling",
            }

        except Exception as e:
            logger.error(f"Docling parse failed for {file_path}: {e}", exc_info=True)
            return None

    def _extract_tables(self, doc) -> List[Dict[str, Any]]:
        """Extract all tables from a Docling document as row arrays."""
        tables = []
        try:
            for table_idx, table in enumerate(doc.tables):
                try:
                    # Export table to pandas DataFrame, then to rows
                    df = table.export_to_dataframe()
                    if df.empty:
                        continue
                    # First row is header
                    rows = [list(df.columns)]
                    for _, row in df.iterrows():
                        rows.append([str(v) if v is not None else "" for v in row])
                    if len(rows) > 1:
                        tables.append({
                            "sheet": f"table_{table_idx + 1}",
                            "rows": rows,
                        })
                except Exception as e:
                    logger.debug(f"Docling table {table_idx} export failed: {e}")
                    # Try raw cell extraction
                    try:
                        rows = self._extract_table_cells(table)
                        if rows:
                            tables.append({"sheet": f"table_{table_idx + 1}", "rows": rows})
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Docling table extraction error: {e}")
        return tables

    def _extract_table_cells(self, table) -> List[List[str]]:
        """Fallback: extract table cells by row/col grid."""
        if not hasattr(table, "data") or table.data is None:
            return []
        grid = table.data.grid
        rows = []
        for row in grid:
            rows.append([cell.text if cell else "" for cell in row])
        return [r for r in rows if any(c.strip() for c in r)]
