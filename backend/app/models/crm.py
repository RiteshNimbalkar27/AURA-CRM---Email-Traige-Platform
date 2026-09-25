import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plan: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 'starter' | 'professional' | 'enterprise'
    billing_status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    contacts: Mapped[list["Contact"]] = relationship("Contact", back_populates="account")
    threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="account")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True)
    operational_status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)  # 'active' | 'inactive' | 'at_risk'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    account: Mapped["Account | None"] = relationship("Account", back_populates="contacts")
    threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="contact")
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="contact")
    classifications: Mapped[list["Classification"]] = relationship("Classification", back_populates="contact")
