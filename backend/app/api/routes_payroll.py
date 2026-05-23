"""Payroll run endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import PayrollRun, PayrollResult
from app.schemas.report import PayrollRunSchema, PayrollResultSchema

router = APIRouter()


@router.post("/payroll/run")
def create_payroll_run(payroll_period_id: str, db: Session = Depends(get_db)):
    from app.services.payroll_service import PayrollService
    svc = PayrollService(db)
    run = svc.create_run(payroll_period_id)
    return PayrollRunSchema.model_validate(run)


@router.get("/payroll/runs/{run_id}", response_model=PayrollRunSchema)
def get_payroll_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    return run


@router.get("/payroll/runs/{run_id}/results")
def get_payroll_results(run_id: str, db: Session = Depends(get_db)):
    results = db.query(PayrollResult).filter(PayrollResult.payroll_run_id == run_id).all()
    return {"items": [PayrollResultSchema.model_validate(r) for r in results], "total": len(results)}
