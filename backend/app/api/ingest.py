"""
AURA Ingestion API
POST /api/ingest      — Ingest a new email message (with deduplication & thread linking)
GET  /api/jobs/{id}  — Poll ARQ job status
POST /api/replay     — Replay synthetic scenarios (Phase 2 stub)

Error envelope: {"error_code": str, "message": str, "details": any}
"""
import logging
import re
import uuid
from datetime import timezone
from typing import Annotated, Any

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import get_current_user
from app.database import get_db
from app.models.email import Message, Thread
from app.schemas.ingest import IngestRequest, IngestResponse, JobStatusResponse

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_html(raw: str) -> str:
    """Strip HTML tags and decode entities. Returns plain text."""
    soup = BeautifulSoup(raw, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def _normalize_subject(subject: str) -> str:
    """Remove all stacked reply/forward prefixes and lowercase for thread matching."""
    cleaned = subject.strip()
    # Strip all leading Re:/Fwd:/Fw: prefixes iteratively
    while True:
        new = re.sub(r"^(re:|fw:|fwd:)\s*", "", cleaned, flags=re.IGNORECASE).strip()
        if new == cleaned:
            break
        cleaned = new
    return cleaned.lower()


async def _get_arq_pool():
    """Lazily create an ARQ Redis pool. Returns None if Redis is unavailable."""
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        # Parse redis URL into arq RedisSettings
        redis_url = settings.redis_url  # e.g. redis://localhost:6379/0
        # arq RedisSettings.from_dsn is available in recent arq versions
        pool = await create_pool(RedisSettings.from_dsn(redis_url))
        return pool
    except Exception as exc:
        logger.error("Failed to connect to Redis for ARQ: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Thread linking logic
# ---------------------------------------------------------------------------

async def _find_or_create_thread(
    db: AsyncSession,
    external_thread_id: str | None,
    reply_to_external_id: str | None,
    sender_email: str,
    subject: str,
) -> Thread:
    """
    Link or create a Thread using a 3-level fallback strategy:
      1. Match by external_thread_id (exact, if provided)
      2. Match by reply_to_external_id — find message with that external_message_id,
         use its thread.
      3. Fallback: normalized sender_email + normalized subject match on most recent open thread.

    Returns an existing Thread or a freshly-created one (not yet flushed to DB).
    """
    # Strategy 1: external_thread_id
    if external_thread_id:
        result = await db.execute(
            select(Thread).where(Thread.external_thread_id == external_thread_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            logger.debug("Thread found by external_thread_id: %s", existing.id)
            return existing

    # Strategy 2: reply_to_external_id → find parent message → use its thread
    if reply_to_external_id:
        msg_result = await db.execute(
            select(Message).where(
                Message.external_message_id == reply_to_external_id
            )
        )
        parent_msg = msg_result.scalar_one_or_none()
        if parent_msg and parent_msg.thread_id:
            thread_result = await db.execute(
                select(Thread).where(Thread.id == parent_msg.thread_id)
            )
            existing = thread_result.scalar_one_or_none()
            if existing:
                logger.debug(
                    "Thread found via reply_to_external_id %s → thread %s",
                    reply_to_external_id, existing.id,
                )
                return existing

    # Strategy 3: normalized sender + subject fuzzy match on open threads
    norm_subject = _normalize_subject(subject)
    sender_lower = sender_email.strip().lower()
    threads_result = await db.execute(
        select(Thread)
        .join(Message, Thread.id == Message.thread_id)
        .where(
            Message.sender_email == sender_lower,
            Thread.status == "open",
        )
        .order_by(Thread.last_message_at.desc())
        .limit(10)
    )
    candidate_threads = threads_result.scalars().all()

    for thread in candidate_threads:
        if thread.subject and _normalize_subject(thread.subject) == norm_subject:
            logger.debug(
                "Thread found by normalized sender+subject match: %s", thread.id
            )
            return thread

    # No match — create a new thread
    new_thread = Thread(
        id=uuid.uuid4(),
        external_thread_id=external_thread_id,
        subject=subject,
        queue="support_operations",
        status="open",
    )
    db.add(new_thread)
    await db.flush()  # get the UUID without committing
    logger.info("Created new thread: %s", new_thread.id)
    return new_thread


# ---------------------------------------------------------------------------
# POST /api/ingest
# ---------------------------------------------------------------------------

@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_message(
    payload: IngestRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
) -> IngestResponse:
    """
    Ingest an incoming email message.

    - Deduplicates by external_message_id.
    - Strips HTML from body; rejects blank bodies.
    - Links or creates a Thread via 3-level strategy.
    - Creates a Message record.
    - Enqueues an ARQ background job for LLM classification.
    """
    # ------------------------------------------------------------------
    # 1. HTML strip + blank body validation
    # ------------------------------------------------------------------
    body_sanitized = _strip_html(payload.body)
    if not body_sanitized.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "BLANK_BODY",
                "message": "Email body is blank after HTML stripping.",
                "details": {"external_message_id": payload.external_message_id},
            },
        )

    # Truncate oversized bodies: first 8000 + last 2000 chars
    MAX_BODY = 10_000
    if len(body_sanitized) > MAX_BODY:
        body_sanitized = body_sanitized[:8000] + "\n...[truncated]...\n" + body_sanitized[-2000:]

    # ------------------------------------------------------------------
    # 2. Deduplication check
    # ------------------------------------------------------------------
    dup_result = await db.execute(
        select(Message).where(
            Message.external_message_id == payload.external_message_id
        )
    )
    existing_message = dup_result.scalar_one_or_none()

    if existing_message is not None:
        logger.info(
            "Duplicate message detected: external_message_id=%s existing_id=%s",
            payload.external_message_id,
            existing_message.id,
        )
        # Return original IDs; job_id may be None if stored as UUID; cast to str
        existing_job_id = (
            str(existing_message.job_id) if existing_message.job_id else "none"
        )
        return IngestResponse(
            message_id=existing_message.id,
            thread_id=existing_message.thread_id or uuid.UUID(int=0),
            job_id=existing_job_id,
            duplicate=True,
            status="duplicate",
        )

    # ------------------------------------------------------------------
    # 3. Thread linking
    # ------------------------------------------------------------------
    thread = await _find_or_create_thread(
        db=db,
        external_thread_id=payload.external_thread_id,
        reply_to_external_id=payload.reply_to_external_id,
        sender_email=payload.sender_email,
        subject=payload.subject,
    )

    # Ensure received_at is timezone-aware
    received_at = payload.received_at
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    # ------------------------------------------------------------------
    # 4. Create Message record
    # ------------------------------------------------------------------
    new_message = Message(
        id=uuid.uuid4(),
        external_message_id=payload.external_message_id,
        thread_id=thread.id,
        sender_email=payload.sender_email.strip().lower(),
        subject=payload.subject,
        body_sanitized=body_sanitized,
        received_at=received_at,
        job_status="pending",
    )
    db.add(new_message)

    # Update thread's last_message_at timestamp
    thread.last_message_at = received_at
    db.add(thread)

    await db.flush()  # generate IDs before enqueueing

    # ------------------------------------------------------------------
    # 5. Enqueue ARQ background classification job
    # ------------------------------------------------------------------
    arq_job_id: str = f"classify:{new_message.id}"
    pool = await _get_arq_pool()

    if pool:
        try:
            job = await pool.enqueue_job(
                "classify_message_task",
                str(new_message.id),
                payload.subject,
                body_sanitized,
                _job_id=arq_job_id,
            )
            arq_job_id = job.job_id if job else arq_job_id
            await pool.aclose()
            logger.info(
                "Enqueued ARQ job %s for message %s", arq_job_id, new_message.id
            )
        except Exception as exc:
            logger.error(
                "Failed to enqueue ARQ job for message %s: %s", new_message.id, exc
            )
            # Continue — message is persisted; job can be requeued manually
    else:
        logger.warning(
            "ARQ pool unavailable — message %s saved but not enqueued for classification.",
            new_message.id,
        )

    # Store job_id reference on the message record
    # job_id column is UUID type in model; we store the message UUID as the tracking key
    # (ARQ job ID is a string; we use message.id as correlation key)
    new_message.job_id = new_message.id  # use message UUID as job correlation key
    new_message.job_status = "queued"
    db.add(new_message)

    # Session commit happens via get_db dependency on successful return
    logger.info(
        "Ingested message %s → thread %s | job=%s",
        new_message.id, thread.id, arq_job_id,
    )

    return IngestResponse(
        message_id=new_message.id,
        thread_id=thread.id,
        job_id=arq_job_id,
        duplicate=False,
        status="queued",
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    current_user: Annotated[Any, Depends(get_current_user)],
) -> JobStatusResponse:
    """
    Poll the status of a background classification job via ARQ.
    """
    pool = await _get_arq_pool()
    if not pool:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "REDIS_UNAVAILABLE",
                "message": "Redis/ARQ is unavailable. Cannot fetch job status.",
                "details": {"job_id": job_id},
            },
        )

    try:
        from arq.jobs import Job, JobStatus

        job = Job(job_id=job_id, redis=pool)
        job_status = await job.status()
        info = await job.info()
        await pool.aclose()

        # Map ARQ status to AURA status strings
        status_map = {
            JobStatus.queued: "pending",
            JobStatus.in_progress: "running",
            JobStatus.complete: "complete",
            JobStatus.not_found: "failed",
            JobStatus.deferred: "pending",
        }
        aura_status = status_map.get(job_status, str(job_status))

        result_payload: dict | None = None
        error_msg: str | None = None
        created_at = None
        completed_at = None

        if info:
            created_at = info.enqueue_time
            if hasattr(info, "finish_time"):
                completed_at = info.finish_time
            if info.result is not None:
                if isinstance(info.result, Exception):
                    error_msg = str(info.result)
                    aura_status = "failed"
                elif isinstance(info.result, dict):
                    result_payload = info.result
                else:
                    result_payload = {"raw": str(info.result)}

        return JobStatusResponse(
            job_id=job_id,
            status=aura_status,
            result=result_payload,
            error=error_msg,
            created_at=created_at,
            completed_at=completed_at,
        )

    except Exception as exc:
        logger.error("Error fetching ARQ job status for %s: %s", job_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "JOB_STATUS_ERROR",
                "message": f"Failed to retrieve job status: {exc}",
                "details": {"job_id": job_id},
            },
        )


# ---------------------------------------------------------------------------
# POST /api/replay  (Phase 2 stub)
# ---------------------------------------------------------------------------

@router.post("/replay")
async def replay_scenario(
    payload: dict,
    current_user: Annotated[Any, Depends(get_current_user)],
) -> dict:
    """
    Replay a versioned synthetic scenario at configurable speed.
    Phase 2 stub — not yet implemented.

    Expected body: {"scenario": str, "speed_multiplier": float = 1.0}
    """
    scenario = payload.get("scenario", "")
    speed = payload.get("speed_multiplier", 1.0)
    logger.info(
        "Replay stub called: scenario=%s speed_multiplier=%s user=%s",
        scenario, speed, getattr(current_user, "email", "unknown"),
    )
    return {
        "status": "not_implemented",
        "message": "Replay endpoint stub - Phase 2",
    }
