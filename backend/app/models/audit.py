import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuditLog(Base):
    """
    Immutable append-only audit log.
    Never update or delete rows — enforced at the service layer.
    Records every agent run, approval, action, and role-sensitive operation.
    """
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # nullable for system actions
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False)  # denormalized (user may be deleted)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # e.g. 'draft.approved', 'escalation.resolved', 'message.ingested', 'agent_run.created'
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # e.g. 'draft', 'escalation', 'message', 'legal_flag'
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    # Redacted JSONB: sensitive fields replaced with [REDACTED]
    change_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
