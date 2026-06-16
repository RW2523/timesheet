"""
Regression tests for the extraction / structuring / payroll fixes.

These exercise the actual parsers and shared utilities — the gap the original
suite had (it started from already-parsed inputs and so could not catch
column-misalignment or locale bugs).

Run: cd backend && python -m pytest tests/test_fixes.py -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ── Shared date/time util ─────────────────────────────────────────────────────

def test_date_locale_us_vs_eu():
    from app.services.date_utils import parse_date
    assert parse_date("03/04/2026") == "2026-03-04"               # default US
    assert parse_date("03/04/2026", dayfirst=True) == "2026-04-03"  # EU
    assert parse_date("2026-04-03") == "2026-04-03"               # ISO unchanged


def test_date_rejects_invalid_and_empty():
    from app.services.date_utils import parse_date
    assert parse_date("INVALID_1900-01-05") is None
    assert parse_date("") is None
    assert parse_date("nan") is None
    assert parse_date(None) is None


def test_time_no_blind_pm_shift():
    from app.services.date_utils import parse_time
    assert parse_time("06:00") == "06:00"          # early clock-in preserved
    assert parse_time("5:00pm") == "17:00"
    assert parse_time("12:00am") == "00:00"
    assert parse_time("06:00", infer_pm=True) == "18:00"  # opt-in only


# ── Pydantic extraction schema ────────────────────────────────────────────────

def test_extraction_schema_coerces_messy_values():
    from app.schemas.extraction import TimesheetExtraction
    obj = TimesheetExtraction.model_validate({
        "employee_name": "John Smith",
        "entries": [
            {"date": "2026-04-01", "break_minutes": "30.0", "hours": "7.5"},
            {"date": "2026-04-02", "break_minutes": "", "hours": None},
        ],
    }).model_dump()
    assert len(obj["entries"]) == 2
    assert obj["entries"][0]["break_minutes"] == 30.0
    assert obj["entries"][0]["hours"] == 7.5
    assert obj["entries"][1]["break_minutes"] == 0.0


def test_extraction_schema_rejects_non_object():
    from app.schemas.extraction import TimesheetExtraction
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TimesheetExtraction.model_validate({"entries": "not a list"})


def test_extraction_schema_is_json_schema():
    from app.schemas.extraction import timesheet_extraction_schema
    sch = timesheet_extraction_schema()
    assert "entries" in sch["properties"]
    assert sch["type"] == "object"


# ── Excel parser: empty cells preserved in raw_text (column alignment) ─────────

def test_excel_rows_to_text_preserves_empty_cells():
    from app.services.parsers.excel_parser import ExcelParser
    txt = ExcelParser._rows_to_text([
        ["2026-04-01", "", "8"],
        ["", "", ""],            # fully empty -> skipped
        ["2026-04-02", "09:00", "8"],
    ])
    lines = txt.split("\n")
    assert lines[0] == "2026-04-01 |  | 8"   # blank In/Out column kept
    assert lines[1] == "2026-04-02 | 09:00 | 8"
    assert len(lines) == 2                    # empty row dropped


# ── CSV parser: delimiter sniffing + NaN handling + empty-cell preservation ────

def test_csv_semicolon_and_empty_cells(tmp_path):
    from app.services.parsers.csv_parser import CsvParser
    p = tmp_path / "ts.csv"
    p.write_text("name;in;out;hours\nJohn;09:00;;8\nJane;08:00;16:00;8\n")
    res = CsvParser().parse(str(p))
    assert res["extraction_method"] == "csv"
    rows = res["raw_tables"][0]["rows"]
    # semicolon was detected -> 4 columns, not 1
    assert all(len(r) == 4 for r in rows)
    # empty out-time preserved as "" (not "nan")
    john = [r for r in rows if r[0] == "John"][0]
    assert john[2] == ""
    assert "nan" not in res["raw_text"]


# ── Report: CSV/Excel formula-injection neutralization ────────────────────────

def test_report_san_neutralizes_formulas():
    from app.services.report_service import ReportService
    assert ReportService._san("=cmd|calc") == "'=cmd|calc"
    assert ReportService._san("@SUM(A1)") == "'@SUM(A1)"
    assert ReportService._san("-2+3") == "'-2+3"
    assert ReportService._san("John Smith") == "John Smith"   # untouched
    assert ReportService._san(42) == 42                       # non-str passthrough
