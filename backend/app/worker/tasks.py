"""
AURA ARQ Background Worker — Classification Task

This module defines the ARQ task functions that process ingested email messages.
The worker picks up jobs enqueued by POST /api/ingest, runs the two-layer
intelligence pipeline (prefilter + LLM), and persists the Classification result.

Task: classify_message_task(ctx, message_id, subject, body)

Worker entrypoint: arq app.worker.main.WorkerSettings
"""
import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.intelligence.classifier import classify_message
from app.models.email import Message, Thread
from app.models.intelligence import Classification

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Task: classify_message_task
# ---------------------------------------------------------------------------

async def classify_message_task(
    ctx: dict,
    message_id: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    """
    ARQ task: run the full intelligence pipeline on a queued message.

    Args:
        ctx:        ARQ context dict (contains Redis pool, attempt count, etc.)
        message_id: UUID string of the Message row to classify.
        subject:    Email subject.
        body:       Sanitized email body text.

    Returns:
        Dict with classification results for ARQ job result storage.

    Side effects:
        - Updates Message.job_status to 'completed' or 'failed'.
        - Inserts a Classification row.
        - Updates Thread.queue based on the classified category.
    """
    logger.info(
        "classify_message_task started: message_id=%s (attempt=%d)",
        message_id, ctx.get("job_try", 1),
    )

    # Build a fresh DB session for this task (not shared with the web process)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with async_session() as db:
            # 1. Fetch the message for thread context
            msg_result = await db.execute(
                select(Message).where(Message.id == uuid.UUID(message_id))
            )
            message = msg_result.scalar_one_or_none()

            if message is None:
                logger.error("classify_message_task: message_id=%s not found", message_id)
                return {"ok": False, "error": f"Message {message_id} not found"}

            # 2. Mark as processing
            message.job_status = "processing"
            db.add(message)
            await db.flush()

            # 3. Build thread context (last 5 messages in thread for LLM context)
            thread_context: list[dict] = []
            if message.thread_id:
                ctx_result = await db.execute(
                    select(Message)
                    .where(
                        Message.thread_id == message.thread_id,
                        Message.id != message.id,  # exclude current message
                    )
                    .order_by(Message.received_at.desc())
                    .limit(5)
                )
                prior_messages = ctx_result.scalars().all()
                thread_context = [
                    {
                        "received_at": str(m.received_at),
                        "sender_email": m.sender_email,
                        "body_excerpt": (m.body_sanitized or "")[:500],
                    }
                    for m in reversed(prior_messages)  # chronological order
                ]

            # Prepend current sender for prefilter internal domain check
            thread_context_with_sender = [
                {
                    "received_at": str(message.received_at),
                    "sender_email": message.sender_email,
                    "body_excerpt": body[:500],
                }
            ] + thread_context

            # 4. Run the two-layer intelligence pipeline
            try:
                result = await classify_message(
                    subject=subject,
                    body=body,
                    thread_context=thread_context_with_sender,
                )
            except ValueError as e:
                # BLOCKED by prefilter (spam/scam)
                logger.warning(
                    "Message %s blocked by prefilter: %s", message_id, e
                )
                message.job_status = "failed"
                db.add(message)
                await db.commit()
                return {"ok": False, "error": str(e), "blocked": True}

            # 5. Persist the Classification row
            classification = Classification(
                id=uuid.uuid4(),
                message_id=message.id,
                thread_id=message.thread_id,
                contact_id=message.contact_id,
                category=result.category,
                urgency=result.urgency,
                sentiment_score=result.sentiment_score,
                confidence=result.confidence,
                human_review_required=result.human_review_required,
                entities=result.entities,
                rationale=result.rationale,
                proposed_action=result.proposed_action,
                model_name=result.model_name,
            )
            db.add(classification)

            # 6. Route the thread to the appropriate queue
            queue = _category_to_queue(result.category, result.urgency)
            if message.thread_id:
                thread_result = await db.execute(
                    select(Thread).where(Thread.id == message.thread_id)
                )
                thread = thread_result.scalar_one_or_none()
                if thread:
                    thread.queue = queue
                    db.add(thread)

            # 7. Mark message as completed
            message.job_status = "completed"
            db.add(message)

            await db.commit()

        logger.info(
            "classify_message_task complete: message_id=%s category=%s urgency=%s queue=%s",
            message_id, result.category, result.urgency, queue,
        )

        return {
            "ok": True,
            "message_id": message_id,
            "category": result.category,
            "urgency": result.urgency,
            "sentiment_score": result.sentiment_score,
            "confidence": result.confidence,
            "human_review_required": result.human_review_required,
            "proposed_action": result.proposed_action,
            "queue": queue,
        }

    except Exception as e:
        logger.error(
            "classify_message_task FAILED: message_id=%s error=%s",
            message_id, e, exc_info=True,
        )
        # Best-effort: mark message as failed
        try:
            async with async_session() as db:
                msg = (await db.execute(
                    select(Message).where(Message.id == uuid.UUID(message_id))
                )).scalar_one_or_none()
                if msg:
                    msg.job_status = "failed"
                    db.add(msg)
                    await db.commit()
        except Exception:
            pass
        raise  # Re-raise so ARQ can retry
    finally:
        await engine.dispose()


def _category_to_queue(category: str, urgency: str) -> str:
    """
    Map a classified category + urgency to the appropriate routing queue.

    Route: security → 'security', legal_compliance → 'legal_compliance',
           reputation → 'reputation_retention', others → 'support_operations'
    Critical urgency always goes to 'security' queue if category is security.
    """
    queue_map = {
        "security": "security",
        "legal_compliance": "legal_compliance",
        "reputation": "reputation_retention",
        "billing_refund": "support_operations",
        "product_support": "support_operations",
        "sales_pricing": "support_operations",
        "general_inquiry": "support_operations",
    }
    return queue_map.get(category, "support_operations")
