"""DOCX parser."""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class DocxParser:
    def parse(self, file_path: str) -> Dict[str, Any]:
        try:
            from docx import Document
            doc = Document(file_path)
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

            tables_data = []
            for i, table in enumerate(doc.tables):
                rows = []
                for row in table.rows:
                    rows.append([cell.text.strip() for cell in row.cells])
                tables_data.append({"sheet": f"table_{i+1}", "rows": rows})

            raw_text = "\n".join(paragraphs)
            if tables_data:
                raw_text += "\n\n" + "\n".join(
                    " | ".join(cell for cell in row)
                    for t in tables_data
                    for row in t["rows"]
                )

            return {
                "raw_text": raw_text,
                "raw_tables": tables_data,
                "ocr_required": False,
                "confidence": 0.9,
                "warnings": [],
            }
        except Exception as e:
            logger.error(f"DOCX parse error: {e}")
            return {"raw_text": None, "raw_tables": None, "ocr_required": False, "confidence": 0.0, "warnings": [str(e)]}
