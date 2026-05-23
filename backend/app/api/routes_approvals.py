"""Approval management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

from app.db.session import get_db
from app.db.models import ApprovalRecord, TimesheetSubmission, gen_uuid

router = APIRouter()


class ApprovalUpdateRequest(BaseModel):
    approval_status: str
    approver_name: Optional[str] = None
    approver_email: Optional[str] = None
    notes: Optional[str] = None


@router.get("/batches/{batch_id}/approvals")
def list_approvals(batch_id: str, db: Session = Depends(get_db)):
    submissions = (
        db.query(TimesheetSubmission)
        .filter(TimesheetSubmission.batch_id == batch_id)
        .all()
    )
    return {
        "items": [
            {
                "submission_id": s.id,
                "employee_id": s.employee_id,
                "approval_status": s.approval_status,
                "approved_by_name": s.approved_by_name,
                "approved_by_email": s.approved_by_email,
                "approved_at": s.approved_at,
            }
            for s in submissions
        ],
        "total": len(submissions),
    }


@router.post("/submissions/{submission_id}/approve")
def update_approval(
    submission_id: str,
    body: ApprovalUpdateRequest,
    db: Session = Depends(get_db),
):
    if body.approval_status not in ("APPROVED", "REJECTED", "PENDING"):
        raise HTTPException(status_code=400, detail="Invalid approval status")

    sub = db.query(TimesheetSubmission).filter(TimesheetSubmission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    sub.approval_status = body.approval_status
    if body.approver_name:
        sub.approved_by_name = body.approver_name
    if body.approver_email:
        sub.approved_by_email = body.approver_email
    if body.approval_status == "APPROVED":
        sub.approved_at = datetime.utcnow()
    sub.updated_at = datetime.utcnow()

    record = ApprovalRecord(
        id=gen_uuid(),
        submission_id=submission_id,
        employee_id=sub.employee_id,
        approver_name=body.approver_name,
        approver_email=body.approver_email,
        approval_status=body.approval_status,
        approval_source="MANUAL_HR",
        approval_date=datetime.utcnow(),
        notes=body.notes,
    )
    db.add(record)
    db.commit()
    return {"status": "ok", "submission_id": submission_id, "approval_status": body.approval_status}
