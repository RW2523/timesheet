"""Audit logging service."""
from datetime import datetime
from typing import Any, Optional
from sqlalchemy.orm import Session
from app.db.models import AuditLog, gen_uuid


class AuditService:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        before: Optional[Any] = None,
        after: Optional[Any] = None,
        actor_user_id: Optional[str] = None,
    ) -> None:
        entry = AuditLog(
            id=gen_uuid(),
            actor_user_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before_json=before,
            after_json=after,
            created_at=datetime.utcnow(),
        )
        self.db.add(entry)
        self.db.commit()
