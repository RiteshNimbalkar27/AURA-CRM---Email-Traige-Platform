"""
AURA Agent Tool — get_thread_history
=====================================
Returns the most recent email messages sent by a given email address,
grouped by thread, including lightweight classification metadata.

The query performs:
  SELECT messages.id, threads.id, messages.received_at, messages.subject,
         messages.body_sanitized, classifications.category, classifications.urgency
  FROM   messages
  JOIN   threads ON messages.thread_id = threads.id
  LEFT JOIN classifications ON classifications.message_id = messages.id
  WHERE  messages.sender_email = :sender_email
  ORDER BY messages.received_at DESC
  LIMIT  :limit

Results are post-processed in Python into a thread-grouped structure.
The limit is clamped to [1, 50].
"""
import logging
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import Message, Thread
from app.models.intelligence import Classification

logger = logging.getLogger(__name__)

_MIN_LIMIT = 1
_MAX_LIMIT = 50
_BODY_EXCERPT_LEN = 300


def make_get_thread_history(
    db: AsyncSession,
    agent_run_id: uuid.UUID,  # noqa: ARG001 — reserved for future audit use
    message_id: uuid.UUID,    # noqa: ARG001 — reserved for future audit use
    dry_run: bool = False,    # noqa: ARG001 — read-only; dry_run has no effect
):
    """
    Factory that returns the ``get_thread_history`` async callable
    with *db* bound via closure.

    Args:
        db:           Active SQLAlchemy AsyncSession.
        agent_run_id: UUID of the current AgentRun (reserved for future audit logging).
        message_id:   UUID of the email message being processed (reserved).
        dry_run:      No effect for this read-only tool; accepted for API uniformity.

    Returns:
        An async callable suitable for inclusion in the tool registry.
    """

    async def get_thread_history(
        sender_email: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Retrieve historical email messages from *sender_email*, grouped by thread.

        Args:
            sender_email: Email address of the sender to look up.
            limit:        Maximum number of messages to return across all threads
                          (clamped to 1–50, default 10).

        Returns:
            On success::

                {
                    "ok": True,
                    "tool_name": "get_thread_history",
                    "data": {
                        "threads": [
                            {
                                "thread_id": "<uuid>",
                                "messages": [
                                    {
                                        "message_id":  "<uuid>",
                                        "received_at": "2026-09-20T14:32:00+00:00",
                                        "subject":     "Re: Billing issue",
                                        "body_excerpt": "<first 300 chars of body>",
                                        "classification": {
                                            "category": "billing_refund",
                                            "urgency":  "medium"
                                        } | null
                                    },
                                    ...
                                ]
                            },
                            ...
                        ]
                    }
                }

            On failure::

                {"ok": False, "tool_name": "get_thread_history", "error": "<message>"}
        """
        tool_name = "get_thread_history"
        try:
            clamped_limit = max(_MIN_LIMIT, min(_MAX_LIMIT, int(limit)))

            # ----------------------------------------------------------------
            # Build the query: messages → threads (JOIN) + classifications (LEFT)
            # We use the *latest* classification per message (by created_at).
            # ----------------------------------------------------------------
            # Subquery: latest classification id per message
            latest_cls_subq = (
                select(
                    Classification.message_id,
                    Classification.category,
                    Classification.urgency,
                )
                .distinct(Classification.message_id)
                .order_by(
                    Classification.message_id,
                    Classification.created_at.desc(),
                )
                .subquery("latest_cls")
            )

            stmt = (
                select(
                    Message.id.label("message_id"),
                    Message.thread_id,
                    Message.received_at,
                    Message.subject,
                    Message.body_sanitized,
                    latest_cls_subq.c.category,
                    latest_cls_subq.c.urgency,
                )
                .join(Thread, Message.thread_id == Thread.id)
                .outerjoin(
                    latest_cls_subq,
                    latest_cls_subq.c.message_id == Message.id,
                )
                .where(Message.sender_email == sender_email)
                .order_by(Message.received_at.desc())
                .limit(clamped_limit)
            )

            result = await db.execute(stmt)
            rows = result.fetchall()

            # ----------------------------------------------------------------
            # Group messages by thread, preserving per-thread order
            # ----------------------------------------------------------------
            thread_order: list[str] = []  # preserves first-seen order
            threads_map: dict[str, list[dict]] = defaultdict(list)

            for row in rows:
                tid = str(row.thread_id) if row.thread_id else "__no_thread__"
                if tid not in threads_map:
                    thread_order.append(tid)

                classification = None
                if row.category is not None:
                    classification = {
                        "category": row.category,
                        "urgency": row.urgency,
                    }

                body_excerpt = (row.body_sanitized or "")[:_BODY_EXCERPT_LEN]

                threads_map[tid].append(
                    {
                        "message_id": str(row.message_id),
                        "received_at": row.received_at.isoformat() if row.received_at else None,
                        "subject": row.subject,
                        "body_excerpt": body_excerpt,
                        "classification": classification,
                    }
                )

            threads_payload = [
                {"thread_id": tid, "messages": threads_map[tid]}
                for tid in thread_order
            ]

            logger.info(
                "get_thread_history: sender=%s → %d message(s) across %d thread(s) [limit=%d]",
                sender_email,
                len(rows),
                len(threads_payload),
                clamped_limit,
            )

            return {
                "ok": True,
                "tool_name": tool_name,
                "data": {"threads": threads_payload},
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("get_thread_history error: %s", exc, exc_info=True)
            return {"ok": False, "tool_name": tool_name, "error": str(exc)}

    return get_thread_history
