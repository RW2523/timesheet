"""Excel/XLSX/XLS parser."""
import logging
from typing import Dict, Any, Optional
import pandas as pd

logger = logging.getLogger(__name__)


class ExcelParser:
    def parse(self, file_path: str) -> Dict[str, Any]:
        try:
            xl = pd.ExcelFile(file_path)
            sheets_data = {}
            all_tables = []

            for sheet_name in xl.sheet_names:
                try:
                    df = xl.parse(sheet_name, header=None)
                    if df.empty:
                        continue
                    df = df.dropna(how="all").dropna(axis=1, how="all")
                    # Convert to JSON-serialisable records
                    rows = df.astype(str).values.tolist()
                    sheets_data[sheet_name] = rows
                    all_tables.append({"sheet": sheet_name, "rows": rows})
                except Exception as e:
                    logger.warning(f"Sheet '{sheet_name}' failed: {e}")

            raw_text = self._tables_to_text(all_tables)

            return {
                "raw_text": raw_text,
                "raw_tables": all_tables,
                "ocr_required": False,
                "confidence": 0.95,
                "warnings": [],
            }
        except Exception as e:
            return {
                "raw_text": None,
                "raw_tables": None,
                "ocr_required": False,
                "confidence": 0.0,
                "warnings": [str(e)],
                "error": str(e),
            }

    @staticmethod
    def _tables_to_text(tables: list) -> str:
        lines = []
        for t in tables:
            lines.append(f"=== Sheet: {t['sheet']} ===")
            for row in t["rows"]:
                lines.append(" | ".join(str(c) for c in row))
        return "\n".join(lines)
