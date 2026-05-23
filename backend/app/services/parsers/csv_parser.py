"""CSV parser."""
import logging
from typing import Dict, Any
import pandas as pd

logger = logging.getLogger(__name__)


class CsvParser:
    def parse(self, file_path: str) -> Dict[str, Any]:
        try:
            df = pd.read_csv(file_path, header=None, encoding="utf-8", on_bad_lines="skip")
            df = df.dropna(how="all")
            rows = df.astype(str).values.tolist()
            raw_text = "\n".join(" | ".join(r) for r in rows)
            return {
                "raw_text": raw_text,
                "raw_tables": [{"sheet": "csv", "rows": rows}],
                "ocr_required": False,
                "confidence": 0.95,
                "warnings": [],
            }
        except UnicodeDecodeError:
            try:
                df = pd.read_csv(file_path, header=None, encoding="latin-1", on_bad_lines="skip")
                rows = df.astype(str).values.tolist()
                raw_text = "\n".join(" | ".join(r) for r in rows)
                return {
                    "raw_text": raw_text,
                    "raw_tables": [{"sheet": "csv", "rows": rows}],
                    "ocr_required": False,
                    "confidence": 0.9,
                    "warnings": ["latin-1 encoding fallback used"],
                }
            except Exception as e:
                return {"raw_text": None, "raw_tables": None, "ocr_required": False, "confidence": 0.0, "warnings": [str(e)]}
        except Exception as e:
            return {"raw_text": None, "raw_tables": None, "ocr_required": False, "confidence": 0.0, "warnings": [str(e)]}
