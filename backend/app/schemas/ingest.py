"""
AURA Ingestion API Schemas
Pydantic models for POST /api/ingest, GET /api/jobs/{job_id}, POST /api/replay.
"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class IngestRequest(BaseModel):
    """Inbound payload for ingesting a new email message."""
    external_message_id: str  # required, unique identifier from upstream mail system
    sender_email: EmailStr
    sender_name: Optional[str] = None
    subject: str
    body: str  # raw body; will be HTML-stripped and validated server-side
    received_at: datetime
    external_thread_id: Optional[str] = None    # upstream thread/conversation ID
    reply_to_external_id: Optional[str] = None  # Message-ID of the parent message


class IngestResponse(BaseModel):
    """Response after successfully ingesting (or deduplicating) a message."""
    message_id: uuid.UUID
    thread_id: uuid.UUID
    job_id: str       # ARQ job ID string
    duplicate: bool   # True if this external_message_id already existed
    status: str       # "queued" | "duplicate"


class JobStatusResponse(BaseModel):
    """Status response for a background classification job."""
    job_id: str
    status: str                         # pending | running | complete | failed
    result: Optional[dict] = None       # classification result payload when complete
    error: Optional[str] = None         # error message when failed
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
