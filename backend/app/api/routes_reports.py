"""Report generation and download endpoints."""
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import GeneratedReport, BatchUpload
from app.schemas.report import ReportListResponse, ReportSchema

router = APIRouter()


@router.get("/batches/{batch_id}/reports", response_model=ReportListResponse)
def list_reports(batch_id: str, db: Session = Depends(get_db)):
    reports = db.query(GeneratedReport).filter(GeneratedReport.batch_id == batch_id).all()
    return ReportListResponse(items=reports)


@router.post("/batches/{batch_id}/reports/generate")
def generate_report(batch_id: str, db: Session = Depends(get_db)):
    batch = db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    from app.services.report_service import ReportService
    svc = ReportService(db)
    report = svc.generate_batch_report(batch_id)
    # Also regenerate summary CSV
    svc.generate_summary_csv(batch_id)
    return {"status": "generated", "report_id": report.id, "file_name": report.file_name}


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, db: Session = Depends(get_db)):
    report = db.query(GeneratedReport).filter(GeneratedReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not os.path.exists(report.file_path):
        raise HTTPException(status_code=404, detail="Report file not found on disk")

    # Pick the correct MIME type
    if report.file_name.lower().endswith(".csv"):
        media_type = "text/csv"
    elif report.file_name.lower().endswith(".xlsx"):
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path=report.file_path,
        filename=report.file_name,
        media_type=media_type,
    )
