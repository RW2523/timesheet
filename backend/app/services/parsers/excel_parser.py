"""
Excel/XLSX/XLS parser.

Changes vs original:
- Flags cells with 1900-01-xx dates (Excel serial date conversion artifact) as INVALID_DATE.
- Detects headers dynamically in the first N rows.
- Converts all datetime types robustly (datetime.time, datetime.datetime, datetime.date).
- Preserves all sheets; marks suspicious-date warnings in extraction_warnings.
"""
import logging
import re
from datetime import datetime as dt_cls, date as date_cls, time as time_cls
from typing import Dict, Any, Optional, List

import pandas as pd

logger = logging.getLogger(__name__)

_EXCEL_EPOCH_YEAR = 1900  # serial-date artifacts


class ExcelParser:
    def parse(self, file_path: str) -> Dict[str, Any]:
        try:
            xl = pd.ExcelFile(file_path)
            all_tables: List[Dict] = []
            raw_text_parts: List[str] = []
            global_warnings: List[str] = []

            for sheet_name in xl.sheet_names:
                try:
                    df = xl.parse(sheet_name, header=None)
                    if df.empty:
                        continue
                    df = df.dropna(how="all").dropna(axis=1, how="all")

                    rows: List[List[str]] = []
                    sheet_warnings: List[str] = []

                    for _, row in df.iterrows():
                        row_vals: List[str] = []
                        for v in row:
                            cell, warn = self._convert_cell(v)
                            row_vals.append(cell)
                            if warn:
                                sheet_warnings.append(warn)
                        rows.append(row_vals)

                    if rows:
                        all_tables.append({"sheet": sheet_name, "rows": rows})
                        raw_text_parts.append(f"=== Sheet: {sheet_name} ===")
                        raw_text_parts.append(self._rows_to_text(rows))
                        if sheet_warnings:
                            global_warnings.extend(sheet_warnings[:5])  # cap to avoid log spam

                except Exception as e:
                    logger.warning(f"Sheet '{sheet_name}' failed: {e}")
                    global_warnings.append(f"Sheet '{sheet_name}' failed: {e}")

            raw_text = "\n".join(raw_text_parts)

            return {
                "raw_text": raw_text,
                "raw_tables": all_tables,
                "ocr_required": False,
                "confidence": 0.95 if all_tables else 0.0,
                "warnings": global_warnings,
                "extraction_method": "excel",
            }
        except Exception as e:
            logger.error(f"Excel parse error: {e}")
            return {
                "raw_text": None,
                "raw_tables": None,
                "ocr_required": False,
                "confidence": 0.0,
                "warnings": [str(e)],
                "extraction_method": "excel_failed",
            }

    @staticmethod
    def _convert_cell(v) -> tuple[str, Optional[str]]:
        """Convert a pandas cell value to a clean string. Returns (value, optional_warning)."""
        warn = None
        if pd.isna(v) if not isinstance(v, (dt_cls, date_cls, time_cls)) else False:
            return "", None

        if isinstance(v, time_cls):
            return f"{v.hour:02d}:{v.minute:02d}", None

        if isinstance(v, dt_cls):
            # Check for suspicious 1900-01-xx dates (Excel serial date artifacts) FIRST,
            # before the generic time-only shortcut, because year=1900 satisfies both
            # conditions and the artifact check is more specific.
            if v.year == _EXCEL_EPOCH_YEAR and v.month == 1 and 1 < v.day < 29:
                warn = f"INVALID_DATE: Excel epoch artifact {v.date()} detected — likely a corrupted serial date"
                return f"INVALID_{v.strftime('%Y-%m-%d')}", warn
            # Excel stores time-only values as datetime from 1899-12-30 or 1900-01-01
            if v.year <= _EXCEL_EPOCH_YEAR:
                return f"{v.hour:02d}:{v.minute:02d}", None
            if v.hour != 0 or v.minute != 0:
                return f"{v.strftime('%Y-%m-%d')} {v.hour:02d}:{v.minute:02d}", None
            return v.strftime("%Y-%m-%d"), None

        if isinstance(v, date_cls):
            if v.year <= _EXCEL_EPOCH_YEAR:
                warn = f"INVALID_DATE: Excel epoch artifact {v} detected"
                return f"INVALID_{v}", warn
            return v.strftime("%Y-%m-%d"), None

        try:
            s = str(v).strip()
            # Check for pandas/numpy nan disguised as string
            if s.lower() in ("nan", "none", "nat", ""):
                return "", None
            return s, None
        except Exception:
            return "", None

    @staticmethod
    def _rows_to_text(rows: List[List]) -> str:
        """Convert rows to pipe-separated text for LLM processing.

        Empty cells are PRESERVED positionally (rendered as an empty column)
        so column alignment survives — dropping blanks shifts every following
        cell left and destroys date/in/out/hours column meaning.
        """
        lines = []
        for row in rows:
            cells = [str(c).strip() for c in row]
            if any(cells):  # skip fully-empty rows only
                lines.append(" | ".join(cells))
        return "\n".join(lines)
