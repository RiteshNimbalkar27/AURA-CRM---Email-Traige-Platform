import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_thread_id: Mapped[str | None] = mapped_column(String(500), unique=True, nullable=True, index=True)
    external_reply_reference_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # array of message-ids
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)  # normalized subject
    queue: Mapped[str] = mapped_column(String(50), default="support_operations", nullable=False)
    # queues: 'support_operations' | 'security' | 'legal_compliance' | 'reputation_retention' | 'internal' | 'spam'
    status: Mapped[str] = mapped_column(String(50), default="open", nullable=False)  # 'open' | 'in_progress' | 'resolved'
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True, index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    contact: Mapped["Contact | None"] = relationship("Contact", back_populates="threads")
    account: Mapped["Account | None"] = relationship("Account", back_populates="threads")
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="thread", order_by="Message.received_at")
    classifications: Mapped[list["Classification"]] = relationship("Classification", back_populates="thread")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_message_id: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=True, index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_sanitized: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Job tracking for async processing
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    job_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)  # 'pending' | 'processing' | 'completed' | 'failed'

    thread: Mapped["Thread | None"] = relationship("Thread", back_populates="messages")
    contact: Mapped["Contact | None"] = relationship("Contact", back_populates="messages")
    classifications: Mapped[list["Classification"]] = relationship("Classification", back_populates="message")
    agent_runs: Mapped[list["AgentRun"]] = relationship("AgentRun", back_populates="message")
    drafts: Mapped[list["Draft"]] = relationship("Draft", back_populates="message")
    tickets: Mapped[list["Ticket"]] = relationship("Ticket", back_populates="source_message")
    escalations: Mapped[list["Escalation"]] = relationship("Escalation", back_populates="source_message")
    legal_flags: Mapped[list["LegalFlag"]] = relationship("LegalFlag", back_populates="source_message")
