"""ZIP upload endpoint — accepts period filter options."""
import os
import uuid
from datetime import datetime, date
from calendar import monthrange
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.db.models import BatchUpload
from app.workers.tasks import process_batch

router = APIRouter()


def _resolve_period(period_type: str, period_value: str) -> tuple[Optional[str], Optional[str]]:
    """Convert a period_type + period_value into ISO start/end dates.

    period_type: 'month' | 'week' | 'year' | 'custom' | 'all'
    period_value:
      month  → 'YYYY-MM'  e.g. '2026-04'
      week   → 'YYYY-WNN' e.g. '2026-W17'  or ISO date of Monday
      year   → 'YYYY'     e.g. '2026'
      custom → 'YYYY-MM-DD:YYYY-MM-DD'
      all    → no filter
    """
    if not period_type or period_type == "all":
        return None, None

    today = date.today()

    if period_type == "month":
        val = period_value or f"{today.year}-{today.month:02d}"
        y, m = map(int, val.split("-"))
        start = date(y, m, 1)
        end = date(y, m, monthrange(y, m)[1])
        return start.isoformat(), end.isoformat()

    if period_type == "year":
        y = int(period_value or today.year)
        return date(y, 1, 1).isoformat(), date(y, 12, 31).isoformat()

    if period_type == "week":
        # Accept 'YYYY-WNN' (ISO week) or 'YYYY-MM-DD' (Monday of the week)
        import re
        val = period_value or ""
        m = re.match(r"^(\d{4})-W(\d{1,2})$", val)
        if m:
            from datetime import datetime as dt
            monday = dt.strptime(f"{m.group(1)}-W{m.group(2)}-1", "%Y-W%W-%w").date()
        else:
            from dateutil.parser import parse as dp
            monday = dp(val).date() if val else today

        from datetime import timedelta
        return monday.isoformat(), (monday + timedelta(days=6)).isoformat()

    if period_type == "custom":
        parts = (period_value or "").split(":")
        if len(parts) == 2:
            return parts[0], parts[1]
        return None, None

    return None, None


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_zip(
    file: UploadFile = File(...),
    payroll_period_id: str = Form(None),
    notes: str = Form(None),
    period_type: str = Form("month"),       # month | week | year | custom | all
    period_value: str = Form(None),         # e.g. '2026-04' for month
    db: Session = Depends(get_db),
):
    """Accept a ZIP file, create a batch record, and enqueue processing.

    period_type + period_value define a date filter: only timesheet entries
    that fall within this window are kept.  Default = current month.
    """
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .zip files are accepted.",
        )

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_MB} MB.",
        )

    # Resolve the period filter
    filter_start, filter_end = _resolve_period(period_type, period_value)

    # Save ZIP to storage
    batch_id = str(uuid.uuid4())
    upload_dir = os.path.join(settings.STORAGE_ROOT, "uploads", batch_id)
    os.makedirs(upload_dir, exist_ok=True)
    zip_path = os.path.join(upload_dir, file.filename)
    with open(zip_path, "wb") as f:
        f.write(content)

    # Create batch record
    batch = BatchUpload(
        id=batch_id,
        source_type="ZIP_UPLOAD",
        source_name=file.filename,
        payroll_period_id=payroll_period_id,
        original_file_path=zip_path,
        status="UPLOADED",
        filter_period_start=filter_start,
        filter_period_end=filter_end,
        current_stage="Queued…",
        summary_json={"notes": notes, "period_type": period_type, "period_value": period_value} if notes or period_type else None,
    )
    db.add(batch)
    db.commit()

    # Enqueue Celery task and persist task_id for later cancellation
    task = process_batch.delay(batch_id)
    batch.summary_json = {**(batch.summary_json or {}), "celery_task_id": task.id}
    db.commit()

    return {
        "batch_id": batch_id,
        "status": "UPLOADED",
        "message": "Processing started. Monitor progress at /api/v1/batches/{batch_id}",
        "file_name": file.filename,
        "file_size_bytes": len(content),
        "filter_period_start": filter_start,
        "filter_period_end": filter_end,
    }
