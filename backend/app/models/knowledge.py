import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.database import Base


class KBDocument(Base):
    __tablename__ = "kb_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0.0")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    chunks: Mapped[list["KBChunk"]] = relationship("KBChunk", back_populates="document")


class KBChunk(Base):
    __tablename__ = "kb_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kb_documents.id"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    token_start: Mapped[int] = mapped_column(Integer, nullable=False)
    token_end: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document: Mapped["KBDocument"] = relationship("KBDocument", back_populates="chunks")
    rag_retrievals: Mapped[list["RAGRetrieval"]] = relationship("RAGRetrieval", back_populates="chunk")


class RAGRetrieval(Base):
    __tablename__ = "rag_retrievals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=True)
    classification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("classifications.id"), nullable=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kb_chunks.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, or 3
    score: Mapped[float] = mapped_column(Float, nullable=False)  # cosine similarity
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    chunk: Mapped["KBChunk"] = relationship("KBChunk", back_populates="rag_retrievals")
    classification: Mapped["Classification | None"] = relationship("Classification", back_populates="rag_retrievals")
    agent_run: Mapped["AgentRun | None"] = relationship("AgentRun", back_populates="rag_retrievals")
