import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False, index=True)
    classification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("classifications.id"), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="live")  # 'live' | 'dry_run'
    tool_calls_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Redacted JSONB trace: [{step, rationale, action, observation}] — no private CoT
    trace: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    outcome: Mapped[str] = mapped_column(String(50), default="completed", nullable=False)  # 'completed' | 'failed' | 'dry_run'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    message: Mapped["Message"] = relationship("Message", back_populates="agent_runs")
    classification: Mapped["Classification | None"] = relationship("Classification", back_populates="agent_runs")
    drafts: Mapped[list["Draft"]] = relationship("Draft", back_populates="agent_run")
    tickets: Mapped[list["Ticket"]] = relationship("Ticket", back_populates="agent_run")
    escalations: Mapped[list["Escalation"]] = relationship("Escalation", back_populates="agent_run")
    legal_flags: Mapped[list["LegalFlag"]] = relationship("LegalFlag", back_populates="agent_run")
    rag_retrievals: Mapped[list["RAGRetrieval"]] = relationship("RAGRetrieval", back_populates="agent_run")


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=True)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str] = mapped_column(String(50), default="empathetic", nullable=False)
    # citations: [{document_id, chunk_id, title, excerpt}]
    citations: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending_approval", nullable=False)  # 'pending_approval' | 'approved' | 'rejected'
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    agent_run: Mapped["AgentRun | None"] = relationship("AgentRun", back_populates="drafts")
    message: Mapped["Message"] = relationship("Message", back_populates="drafts")
    approver: Mapped["User | None"] = relationship("User")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=True)
    assignee_queue: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="open", nullable=False)  # 'open' | 'in_progress' | 'resolved'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    source_message: Mapped["Message"] = relationship("Message", back_populates="tickets")
    agent_run: Mapped["AgentRun | None"] = relationship("AgentRun", back_populates="tickets")


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=True)
    queue: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)  # 'low' | 'medium' | 'high' | 'critical'
    brief: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="open", nullable=False)  # 'open' | 'in_progress' | 'resolved'
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    source_message: Mapped["Message"] = relationship("Message", back_populates="escalations")
    agent_run: Mapped["AgentRun | None"] = relationship("AgentRun", back_populates="escalations")
    resolver: Mapped["User | None"] = relationship("User")


class LegalFlag(Base):
    __tablename__ = "legal_flags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=True)
    issue_type: Mapped[str] = mapped_column(String(100), nullable=False)  # 'dsar' | 'gdpr' | 'cease_and_desist' | 'lawsuit' | 'regulatory'
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    legal_status: Mapped[str] = mapped_column(String(50), default="open", nullable=False)  # 'open' | 'under_review' | 'resolved'
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    source_message: Mapped["Message"] = relationship("Message", back_populates="legal_flags")
    agent_run: Mapped["AgentRun | None"] = relationship("AgentRun", back_populates="legal_flags")
    resolver: Mapped["User | None"] = relationship("User")
