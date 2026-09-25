import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, Boolean, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Classification(Base):
    """
    Append-only classification history.
    One row per LLM run on a message — never update, only insert.
    Indexed on (contact_id, created_at) for sentiment trend queries.
    """
    __tablename__ = "classifications"
    __table_args__ = (
        Index("ix_classifications_contact_sentiment", "contact_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False, index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True, index=True)  # denormalized for performance
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=True)

    category: Mapped[str] = mapped_column(String(50), nullable=False)
    # categories: 'security' | 'legal_compliance' | 'reputation' | 'billing_refund' | 'product_support' | 'sales_pricing' | 'general_inquiry'

    urgency: Mapped[str] = mapped_column(String(20), nullable=False)
    # urgency: 'low' | 'medium' | 'high' | 'critical'

    sentiment_score: Mapped[float] = mapped_column(Float, nullable=False)  # -1.0 to 1.0
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 to 1.0
    human_review_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    entities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {people, orgs, topics}
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, default="gemini-1.5-flash")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    message: Mapped["Message"] = relationship("Message", back_populates="classifications")
    contact: Mapped["Contact | None"] = relationship("Contact", back_populates="classifications")
    thread: Mapped["Thread | None"] = relationship("Thread", back_populates="classifications")
    agent_runs: Mapped[list["AgentRun"]] = relationship("AgentRun", back_populates="classification")
    rag_retrievals: Mapped[list["RAGRetrieval"]] = relationship("RAGRetrieval", back_populates="classification")
