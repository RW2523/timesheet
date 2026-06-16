"""CSV parser."""
import logging
from typing import Dict, Any, List

import pandas as pd

logger = logging.getLogger(__name__)


class CsvParser:
    def parse(self, file_path: str) -> Dict[str, Any]:
        for encoding in ("utf-8", "latin-1"):
            try:
                return self._parse_with_encoding(file_path, encoding)
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.error(f"CSV parse error ({encoding}): {e}")
                return {
                    "raw_text": None, "raw_tables": None, "ocr_required": False,
                    "confidence": 0.0, "warnings": [str(e)],
                    "extraction_method": "csv_failed",
                }
        return {
            "raw_text": None, "raw_tables": None, "ocr_required": False,
            "confidence": 0.0, "warnings": ["Could not decode CSV (utf-8/latin-1)"],
            "extraction_method": "csv_failed",
        }

    def _parse_with_encoding(self, file_path: str, encoding: str) -> Dict[str, Any]:
        warnings: List[str] = []
        if encoding != "utf-8":
            warnings.append(f"{encoding} encoding fallback used")

        # Count raw non-empty lines first so we can detect silently dropped rows.
        with open(file_path, "r", encoding=encoding) as fh:
            raw_line_count = sum(1 for ln in fh if ln.strip())

        # sep=None + python engine sniffs the delimiter (comma / semicolon / tab).
        df = pd.read_csv(
            file_path, header=None, encoding=encoding,
            sep=None, engine="python", on_bad_lines="skip", dtype=str,
        )
        df = df.dropna(how="all")

        # NaN -> "" (not the literal string "nan"); preserve empty cells positionally.
        rows = [["" if pd.isna(v) else str(v).strip() for v in r] for r in df.values.tolist()]
        raw_text = "\n".join(" | ".join(r) for r in rows)

        # Surface ragged-row loss instead of swallowing it.
        kept = len(rows)
        if raw_line_count - kept > 1:  # tolerate a header/blank delta
            warnings.append(
                f"{raw_line_count - kept} CSV row(s) skipped (inconsistent column count)"
            )

        return {
            "raw_text": raw_text,
            "raw_tables": [{"sheet": "csv", "rows": rows}],
            "ocr_required": False,
            "confidence": 0.95 if rows else 0.0,
            "warnings": warnings,
            "extraction_method": "csv",
        }
