"""ZIP upload endpoint."""
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.db.models import BatchUpload
from app.workers.tasks import process_batch

router = APIRouter()


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_zip(
    file: UploadFile = File(...),
    payroll_period_id: str = Form(None),
    notes: str = Form(None),
    db: Session = Depends(get_db),
):
    """Accept a ZIP file, create a batch record, and enqueue processing."""
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
        summary_json={"notes": notes} if notes else None,
    )
    db.add(batch)
    db.commit()

    # Enqueue Celery task
    process_batch.delay(batch_id)

    return {
        "batch_id": batch_id,
        "status": "UPLOADED",
        "message": "Processing started. Monitor progress at /api/v1/batches/{batch_id}",
        "file_name": file.filename,
        "file_size_bytes": len(content),
    }
