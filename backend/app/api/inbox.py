"""
AURA Inbox/Dashboard API
GET /api/dashboard/stats       — Inbox summary counts by queue + urgency
GET /api/threads               — Paginated thread list with filters
GET /api/threads/{thread_id}   — Single thread with message timeline
GET /api/messages/{message_id} — Single message with classification detail
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_user
from app.database import get_db
from app.models.agent import Escalation, LegalFlag, Ticket
from app.models.crm import Contact, Account
from app.models.email import Message, Thread
from app.models.intelligence import Classification

logger = logging.getLogger(__name__)

router = APIRouter()


# ===========================================================================
# GET /api/dashboard/stats
# ===========================================================================

@router.get("/dashboard/stats", tags=["Dashboard"])
async def get_dashboard_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
) -> dict[str, Any]:
    """
    Return summary counts for the Mission Control Inbox.

    Returns:
        - total_open_threads: Total open threads across all queues
        - threads_by_queue: Count per queue
        - threads_by_urgency: Count per urgency level (from latest classification)
        - pending_review: Threads with human_review_required=True
        - unclassified: Messages awaiting classification (job_status != 'completed')
        - open_escalations: Count of open escalations
        - open_legal_flags: Count of open legal flags
    """
    # Total open threads
    total_open = (await db.execute(
        select(func.count()).select_from(Thread).where(Thread.status == "open")
    )).scalar_one()

    # Threads by queue
    queue_rows = (await db.execute(
        select(Thread.queue, func.count().label("count"))
        .where(Thread.status == "open")
        .group_by(Thread.queue)
    )).fetchall()
    threads_by_queue = {row.queue: row.count for row in queue_rows}

    # Threads by urgency (from the most recent classification per thread)
    # Subquery: latest classification per thread
    latest_cls_subq = (
        select(
            Classification.thread_id,
            func.max(Classification.created_at).label("max_created_at"),
        )
        .group_by(Classification.thread_id)
        .subquery()
    )
    urgency_rows = (await db.execute(
        select(Classification.urgency, func.count().label("count"))
        .join(
            latest_cls_subq,
            (Classification.thread_id == latest_cls_subq.c.thread_id)
            & (Classification.created_at == latest_cls_subq.c.max_created_at),
        )
        .join(Thread, Classification.thread_id == Thread.id)
        .where(Thread.status == "open")
        .group_by(Classification.urgency)
    )).fetchall()
    threads_by_urgency = {row.urgency: row.count for row in urgency_rows}

    # Pending human review
    pending_review = (await db.execute(
        select(func.count())
        .select_from(Classification)
        .join(Thread, Classification.thread_id == Thread.id)
        .where(
            Classification.human_review_required == True,
            Thread.status == "open",
        )
    )).scalar_one()

    # Unclassified messages (job pending or queued but not completed)
    unclassified = (await db.execute(
        select(func.count())
        .select_from(Message)
        .where(Message.job_status.in_(["pending", "queued", "processing"]))
    )).scalar_one()

    # Open escalations
    open_escalations = (await db.execute(
        select(func.count()).select_from(Escalation).where(Escalation.status == "open")
    )).scalar_one()

    # Open legal flags
    open_legal_flags = (await db.execute(
        select(func.count()).select_from(LegalFlag).where(LegalFlag.legal_status == "open")
    )).scalar_one()

    return {
        "total_open_threads": total_open,
        "threads_by_queue": threads_by_queue,
        "threads_by_urgency": threads_by_urgency,
        "pending_review": pending_review,
        "unclassified": unclassified,
        "open_escalations": open_escalations,
        "open_legal_flags": open_legal_flags,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ===========================================================================
# GET /api/threads
# ===========================================================================

@router.get("/threads", tags=["Threads"])
async def list_threads(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
    queue: Annotated[str | None, Query(description="Filter by queue name")] = None,
    status: Annotated[str | None, Query(description="Filter by status: open|in_progress|resolved")] = None,
    urgency: Annotated[str | None, Query(description="Filter by urgency: low|medium|high|critical")] = None,
    human_review: Annotated[bool | None, Query(description="Filter by human_review_required")] = None,
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 25,
) -> dict[str, Any]:
    """
    Return a paginated, filterable list of threads for the Mission Control Inbox.

    Each thread includes the latest classification summary (category, urgency, sentiment)
    and the most recent message excerpt.
    """
    # Build the latest classification subquery per thread
    latest_cls_subq = (
        select(
            Classification.thread_id,
            func.max(Classification.created_at).label("max_created_at"),
        )
        .group_by(Classification.thread_id)
        .subquery()
    )

    # Base query: threads + latest classification (left join so unclassified threads appear)
    stmt = (
        select(Thread, Classification)
        .outerjoin(
            latest_cls_subq,
            Thread.id == latest_cls_subq.c.thread_id,
        )
        .outerjoin(
            Classification,
            (Classification.thread_id == latest_cls_subq.c.thread_id)
            & (Classification.created_at == latest_cls_subq.c.max_created_at),
        )
        .order_by(Thread.last_message_at.desc().nullslast())
    )

    # Apply filters
    if queue:
        stmt = stmt.where(Thread.queue == queue)
    if status:
        stmt = stmt.where(Thread.status == status)
    else:
        # Default: open + in_progress (exclude resolved from default inbox view)
        stmt = stmt.where(Thread.status.in_(["open", "in_progress"]))
    if urgency:
        stmt = stmt.where(Classification.urgency == urgency)
    if human_review is not None:
        stmt = stmt.where(Classification.human_review_required == human_review)

    # Count total (before pagination)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Paginate
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    rows = (await db.execute(stmt)).fetchall()

    threads_out = []
    for thread, cls in rows:
        threads_out.append({
            "thread_id": str(thread.id),
            "subject": thread.subject,
            "queue": thread.queue,
            "status": thread.status,
            "last_message_at": thread.last_message_at.isoformat() if thread.last_message_at else None,
            "created_at": thread.created_at.isoformat(),
            "classification": {
                "category": cls.category if cls else None,
                "urgency": cls.urgency if cls else None,
                "sentiment_score": cls.sentiment_score if cls else None,
                "confidence": cls.confidence if cls else None,
                "human_review_required": cls.human_review_required if cls else None,
                "proposed_action": cls.proposed_action if cls else None,
            } if cls else None,
        })

    return {
        "threads": threads_out,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


# ===========================================================================
# GET /api/threads/{thread_id}
# ===========================================================================

@router.get("/threads/{thread_id}", tags=["Threads"])
async def get_thread(
    thread_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
) -> dict[str, Any]:
    """
    Return a single thread with its full message timeline and all classifications.
    Used by the Thread Workspace view.
    """
    # Load thread with messages and their classifications
    result = await db.execute(
        select(Thread)
        .where(Thread.id == thread_id)
        .options(
            selectinload(Thread.messages).selectinload(Message.classifications),
        )
    )
    thread = result.scalar_one_or_none()

    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "THREAD_NOT_FOUND",
                "message": f"Thread {thread_id} not found.",
                "details": {"thread_id": str(thread_id)},
            },
        )

    messages_out = []
    for msg in thread.messages:
        # Latest classification for this message
        latest_cls = (
            sorted(msg.classifications, key=lambda c: c.created_at, reverse=True)[0]
            if msg.classifications else None
        )
        messages_out.append({
            "message_id": str(msg.id),
            "external_message_id": msg.external_message_id,
            "sender_email": msg.sender_email,
            "subject": msg.subject,
            "body_excerpt": (msg.body_sanitized or "")[:500],
            "received_at": msg.received_at.isoformat(),
            "job_status": msg.job_status,
            "classification": {
                "classification_id": str(latest_cls.id),
                "category": latest_cls.category,
                "urgency": latest_cls.urgency,
                "sentiment_score": latest_cls.sentiment_score,
                "confidence": latest_cls.confidence,
                "human_review_required": latest_cls.human_review_required,
                "rationale": latest_cls.rationale,
                "proposed_action": latest_cls.proposed_action,
                "model_name": latest_cls.model_name,
                "classified_at": latest_cls.created_at.isoformat(),
            } if latest_cls else None,
        })

    return {
        "thread_id": str(thread.id),
        "external_thread_id": thread.external_thread_id,
        "subject": thread.subject,
        "queue": thread.queue,
        "status": thread.status,
        "created_at": thread.created_at.isoformat(),
        "last_message_at": thread.last_message_at.isoformat() if thread.last_message_at else None,
        "message_count": len(messages_out),
        "messages": messages_out,
    }


# ===========================================================================
# GET /api/messages/{message_id}
# ===========================================================================

@router.get("/messages/{message_id}", tags=["Messages"])
async def get_message(
    message_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
) -> dict[str, Any]:
    """
    Return a single message with its full classification history, agent runs,
    drafts, tickets, escalations, and legal flags.
    """
    result = await db.execute(
        select(Message)
        .where(Message.id == message_id)
        .options(
            selectinload(Message.classifications),
            selectinload(Message.agent_runs),
            selectinload(Message.drafts),
            selectinload(Message.tickets),
            selectinload(Message.escalations),
            selectinload(Message.legal_flags),
        )
    )
    message = result.scalar_one_or_none()

    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "MESSAGE_NOT_FOUND",
                "message": f"Message {message_id} not found.",
                "details": {"message_id": str(message_id)},
            },
        )

    # Sort classifications by created_at descending
    classifications_out = [
        {
            "classification_id": str(c.id),
            "category": c.category,
            "urgency": c.urgency,
            "sentiment_score": c.sentiment_score,
            "confidence": c.confidence,
            "human_review_required": c.human_review_required,
            "entities": c.entities,
            "rationale": c.rationale,
            "proposed_action": c.proposed_action,
            "model_name": c.model_name,
            "classified_at": c.created_at.isoformat(),
        }
        for c in sorted(message.classifications, key=lambda c: c.created_at, reverse=True)
    ]

    agent_runs_out = [
        {
            "agent_run_id": str(r.id),
            "mode": r.mode,
            "outcome": r.outcome,
            "tool_calls_count": r.tool_calls_count,
            "created_at": r.created_at.isoformat(),
        }
        for r in message.agent_runs
    ]

    drafts_out = [
        {
            "draft_id": str(d.id),
            "tone": d.tone,
            "status": d.status,
            "body_preview": (d.body or "")[:300],
            "citations_count": len(d.citations) if d.citations else 0,
            "created_at": d.created_at.isoformat(),
        }
        for d in message.drafts
    ]

    tickets_out = [
        {
            "ticket_id": str(t.id),
            "title": t.title,
            "assignee_queue": t.assignee_queue,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
        }
        for t in message.tickets
    ]

    escalations_out = [
        {
            "escalation_id": str(e.id),
            "queue": e.queue,
            "priority": e.priority,
            "brief": e.brief[:300],
            "status": e.status,
            "created_at": e.created_at.isoformat(),
        }
        for e in message.escalations
    ]

    legal_flags_out = [
        {
            "legal_flag_id": str(lf.id),
            "issue_type": lf.issue_type,
            "summary": lf.summary[:300],
            "status": lf.legal_status,
            "created_at": lf.created_at.isoformat(),
        }
        for lf in message.legal_flags
    ]

    return {
        "message_id": str(message.id),
        "external_message_id": message.external_message_id,
        "thread_id": str(message.thread_id) if message.thread_id else None,
        "sender_email": message.sender_email,
        "subject": message.subject,
        "body_sanitized": message.body_sanitized,
        "received_at": message.received_at.isoformat(),
        "job_status": message.job_status,
        "classifications": classifications_out,
        "agent_runs": agent_runs_out,
        "drafts": drafts_out,
        "tickets": tickets_out,
        "escalations": escalations_out,
        "legal_flags": legal_flags_out,
    }
