import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MarketIntelCache(Base):
    __tablename__ = "market_intel_cache"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_url: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'review' | 'competitor_pricing'
    # Available fields: rating, review_count, complaint_themes, pricing_snapshot
    response_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # 'success' | 'failed' | 'robots_denied' | 'timeout'
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # fetched_at + 6 hours
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
