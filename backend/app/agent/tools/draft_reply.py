"""
AURA Agent Tool — draft_reply
==============================
Generates a grounded, citation-backed draft reply for a customer email.

Safety invariant
----------------
If the current message has ``urgency == 'critical'`` the tool is disabled
and returns an error immediately — no LLM call is made and no Draft is
persisted.  This guard is enforced at two layers:
  1. The ``urgency`` value is captured at factory time from the caller's
     closure (already fetched from the DB), making it tamper-resistant.
  2. The tool itself re-checks urgency before any I/O.

Policy chunk resolution
-----------------------
- If *policy_refs* are supplied the tool fetches those specific KBChunk rows
  by ID and uses them verbatim.
- If *policy_refs* is empty the tool calls ``retrieve_and_record()`` (or
  ``retrieve_chunks()`` in dry_run) with the message subject as the query.

Draft persistence
-----------------
- Live mode  : a ``Draft`` row is inserted with ``status='pending_approval'``.
- dry_run mode: DB write is skipped; a mock ``draft_id`` is returned so the
  agent trace remains complete.
"""
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Draft
from app.models.email import Message
from app.models.knowledge import KBChunk, KBDocument
from app.rag.retriever import retrieve_and_record, retrieve_chunks
from app.services.llm_adapter import get_llm_adapter

logger = logging.getLogger(__name__)

_MOCK_DRAFT_ID = "00000000-0000-0000-0000-000000000000"


def make_draft_reply(
    db: AsyncSession,
    agent_run_id: uuid.UUID,
    message_id: uuid.UUID,
    dry_run: bool = False,
    urgency: str | None = None,
):
    """
    Factory that returns the ``draft_reply`` async callable with all
    context bound via closure.

    Args:
        db:           Active SQLAlchemy AsyncSession.
        agent_run_id: UUID of the current AgentRun row.
        message_id:   UUID of the email message being processed.
        dry_run:      When True the Draft row is NOT written to the DB.
        urgency:      Urgency level from the message's latest Classification.
                      When ``'critical'`` the tool is fully disabled.

    Returns:
        An async callable suitable for inclusion in the tool registry.
    """

    async def draft_reply(
        message_id_str: str,
        tone: str = "empathetic",
        policy_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Generate and (optionally) persist a draft reply for a customer email.

        Args:
            message_id_str: UUID string of the Message to draft a reply for.
                            Must match the message currently being triaged.
            tone:           Tone for the reply (e.g. ``'empathetic'``,
                            ``'formal'``, ``'concise'``).  Defaults to
                            ``'empathetic'``.
            policy_refs:    Optional list of KBChunk UUID strings to use as
                            grounding.  When empty/omitted the tool performs a
                            fallback RAG search using the message subject.

        Returns:
            On success::

                {
                    "ok": True,
                    "tool_name": "draft_reply",
                    "data": {
                        "draft_id":         "<uuid | mock-uuid>",
                        "body":             "<drafted reply text>",
                        "citations":        [{"document_id": "<uuid>", "chunk_id": "<uuid>"}, ...],
                        "requires_approval": True
                    }
                }

            On critical-urgency block::

                {
                    "ok": False,
                    "tool_name": "draft_reply",
                    "error": "draft_reply is disabled for critical urgency incidents"
                }

            On failure::

                {"ok": False, "tool_name": "draft_reply", "error": "<message>"}
        """
        tool_name = "draft_reply"

        # ------------------------------------------------------------------
        # SAFETY: block draft generation for critical incidents
        # ------------------------------------------------------------------
        if urgency == "critical":
            logger.warning(
                "draft_reply blocked: message_id=%s has critical urgency",
                message_id_str,
            )
            return {
                "ok": False,
                "tool_name": tool_name,
                "error": "draft_reply is disabled for critical urgency incidents",
            }

        try:
            # ------------------------------------------------------------------
            # 1. Fetch the Message from DB
            # ------------------------------------------------------------------
            msg_uuid = uuid.UUID(message_id_str)
            result = await db.execute(
                select(Message).where(Message.id == msg_uuid)
            )
            message: Message | None = result.scalar_one_or_none()
            if message is None:
                return {
                    "ok": False,
                    "tool_name": tool_name,
                    "error": f"Message not found: {message_id_str}",
                }

            message_context = {
                "sender_email": message.sender_email,
                "subject": message.subject or "",
                "body": message.body_sanitized or "",
            }

            # ------------------------------------------------------------------
            # 2. Resolve policy chunks
            # ------------------------------------------------------------------
            policy_chunks: list[dict[str, Any]] = []

            if policy_refs:
                # Fetch specific chunks by ID
                chunk_uuids = [uuid.UUID(ref) for ref in policy_refs]
                chunks_result = await db.execute(
                    select(
                        KBChunk.id.label("chunk_id"),
                        KBChunk.document_id,
                        KBDocument.title,
                        KBChunk.content.label("excerpt"),
                    )
                    .join(KBDocument, KBChunk.document_id == KBDocument.id)
                    .where(KBChunk.id.in_(chunk_uuids))
                )
                for row in chunks_result.fetchall():
                    policy_chunks.append(
                        {
                            "chunk_id": str(row.chunk_id),
                            "document_id": str(row.document_id),
                            "title": row.title,
                            "excerpt": row.excerpt,
                        }
                    )
                logger.debug(
                    "draft_reply: resolved %d/%d policy_refs by ID",
                    len(policy_chunks),
                    len(policy_refs),
                )
            else:
                # Fallback: RAG search using message subject
                fallback_query = message_context["subject"] or message_context["body"][:200]
                if dry_run:
                    policy_chunks = await retrieve_chunks(
                        query=fallback_query,
                        max_results=3,
                        db=db,
                    )
                else:
                    policy_chunks = await retrieve_and_record(
                        query=fallback_query,
                        agent_run_id=agent_run_id,
                        message_id=message.id,
                        db=db,
                        max_results=3,
                    )
                logger.debug(
                    "draft_reply: fallback RAG returned %d chunk(s)",
                    len(policy_chunks),
                )

            # ------------------------------------------------------------------
            # 3. Generate draft via LLM
            # ------------------------------------------------------------------
            adapter = get_llm_adapter()
            draft_body = await adapter.generate_draft(
                message_context=message_context,
                policy_chunks=policy_chunks,
                tone=tone,
            )

            # ------------------------------------------------------------------
            # 4. Build citation list from resolved chunks
            # ------------------------------------------------------------------
            citations = [
                {
                    "document_id": c["document_id"],
                    "chunk_id": c["chunk_id"],
                }
                for c in policy_chunks
            ]

            # ------------------------------------------------------------------
            # 5. Persist Draft row (skipped in dry_run)
            # ------------------------------------------------------------------
            if dry_run:
                draft_id = _MOCK_DRAFT_ID
                logger.info(
                    "[dry_run] draft_reply: skipping DB write, mock draft_id=%s",
                    draft_id,
                )
            else:
                draft_row = Draft(
                    agent_run_id=agent_run_id,
                    message_id=message.id,
                    body=draft_body,
                    tone=tone,
                    citations=citations,
                    status="pending_approval",
                )
                db.add(draft_row)
                await db.flush()
                draft_id = str(draft_row.id)
                logger.info(
                    "draft_reply: persisted Draft id=%s for message_id=%s",
                    draft_id,
                    message_id_str,
                )

            return {
                "ok": True,
                "tool_name": tool_name,
                "data": {
                    "draft_id": draft_id,
                    "body": draft_body,
                    "citations": citations,
                    "requires_approval": True,
                },
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("draft_reply error: %s", exc, exc_info=True)
            return {"ok": False, "tool_name": tool_name, "error": str(exc)}

    return draft_reply
