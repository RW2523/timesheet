"""File inventory and file management endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.session import get_db
from app.db.models import UploadedFile, EmployeeFileMatch, AuditLog
from app.schemas.file import FileRecord, FileListResponse, AssignEmployeeRequest, MarkNonTimesheetRequest
from app.db.models import gen_uuid
from datetime import datetime

router = APIRouter()


@router.get("/batches/{batch_id}/files", response_model=FileListResponse)
def list_files(
    batch_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(UploadedFile).filter(UploadedFile.batch_id == batch_id)
    if status:
        q = q.filter(UploadedFile.processing_status == status)
    total = q.count()
    items = q.order_by(UploadedFile.folder_path, UploadedFile.file_name).offset(skip).limit(limit).all()
    return FileListResponse(items=items, total=total)


@router.get("/files/{file_id}", response_model=FileRecord)
def get_file(file_id: str, db: Session = Depends(get_db)):
    f = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    return f


@router.get("/files/{file_id}/raw-extraction")
def get_raw_extraction(file_id: str, db: Session = Depends(get_db)):
    from app.db.models import RawExtraction
    ext = db.query(RawExtraction).filter(RawExtraction.file_id == file_id).first()
    if not ext:
        raise HTTPException(status_code=404, detail="No raw extraction found")
    return {
        "id": ext.id,
        "extraction_method": ext.extraction_method,
        "raw_text": ext.raw_text,
        "raw_tables": ext.raw_tables,
        "llm_json": ext.llm_json,
        "confidence": float(ext.confidence) if ext.confidence else None,
        "extraction_warnings": ext.extraction_warnings,
    }


@router.post("/files/{file_id}/assign-employee")
def assign_employee(
    file_id: str,
    body: AssignEmployeeRequest,
    db: Session = Depends(get_db),
):
    f = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    old_employee_id = f.matched_employee_id
    f.matched_employee_id = body.employee_id
    f.match_status = "MANUALLY_MATCHED"
    f.match_confidence = 1.0
    f.updated_at = datetime.utcnow()

    # Record in employee_file_matches
    match = EmployeeFileMatch(
        id=gen_uuid(),
        file_id=file_id,
        detected_name=f.detected_employee_name,
        matched_employee_id=body.employee_id,
        match_method="MANUAL",
        match_confidence=1.0,
        review_status="MANUAL",
        reviewed_at=datetime.utcnow(),
    )
    db.add(match)

    # Audit log
    audit = AuditLog(
        id=gen_uuid(),
        entity_type="UploadedFile",
        entity_id=file_id,
        action="ASSIGN_EMPLOYEE",
        before_json={"employee_id": old_employee_id},
        after_json={"employee_id": body.employee_id, "reason": body.override_reason},
        created_at=datetime.utcnow(),
    )
    db.add(audit)
    db.commit()
    return {"status": "ok", "file_id": file_id, "employee_id": body.employee_id}


@router.post("/files/{file_id}/mark-non-timesheet")
def mark_non_timesheet(
    file_id: str,
    body: MarkNonTimesheetRequest,
    db: Session = Depends(get_db),
):
    f = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    f.is_timesheet_candidate = False
    f.processing_status = "IGNORED_NON_TIMESHEET"
    f.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "file_id": file_id}


@router.post("/files/{file_id}/reprocess")
def reprocess_file(file_id: str, db: Session = Depends(get_db)):
    f = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    from app.workers.tasks import process_single_file
    process_single_file.delay(file_id, f.batch_id)
    f.processing_status = "QUEUED"
    f.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "queued", "file_id": file_id}


@router.get("/batches/{batch_id}/employee-matches")
def get_employee_matches(batch_id: str, db: Session = Depends(get_db)):
    files = (
        db.query(UploadedFile)
        .filter(
            UploadedFile.batch_id == batch_id,
            UploadedFile.match_status == "NEEDS_REVIEW",
        )
        .all()
    )
    return {"items": [FileRecord.model_validate(f) for f in files], "total": len(files)}
