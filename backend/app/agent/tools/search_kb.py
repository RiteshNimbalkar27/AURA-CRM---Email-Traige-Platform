"""
AURA Agent Tool — search_knowledge_base
=======================================
Semantic search over the AURA knowledge base using the RAG retriever.

In live mode  : calls retrieve_and_record() to search AND write an audit trail.
In dry_run mode: calls retrieve_chunks() to search without writing audit rows.

Returned chunks are clamped to max_results ∈ [1, 3].
"""
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.retriever import retrieve_and_record, retrieve_chunks

logger = logging.getLogger(__name__)

# Hard limits per PLAN.md spec
_MIN_RESULTS = 1
_MAX_RESULTS = 3


def make_search_knowledge_base(
    db: AsyncSession,
    agent_run_id: uuid.UUID,
    message_id: uuid.UUID,
    dry_run: bool = False,
):
    """
    Factory that returns the ``search_knowledge_base`` async callable
    with *db*, *agent_run_id*, *message_id*, and *dry_run* bound via closure.

    Args:
        db:           Active SQLAlchemy AsyncSession.
        agent_run_id: UUID of the current AgentRun row.
        message_id:   UUID of the email message being processed.
        dry_run:      When True the search is performed but no audit rows are
                      written to ``rag_retrievals``.

    Returns:
        An async callable suitable for inclusion in the tool registry.
    """

    async def search_knowledge_base(
        query: str,
        max_results: int = 3,
    ) -> dict[str, Any]:
        """
        Semantic search over the AURA knowledge base.

        Args:
            query:       Natural-language search query.
            max_results: Number of chunks to return (clamped to 1–3, default 3).

        Returns:
            On success::

                {
                    "ok": True,
                    "tool_name": "search_knowledge_base",
                    "data": {
                        "chunks": [
                            {
                                "chunk_id":    "<uuid>",
                                "document_id": "<uuid>",
                                "title":       "<kb document title>",
                                "excerpt":     "<chunk content>",
                                "score":       0.87          # cosine similarity 0–1
                            },
                            ...
                        ]
                    }
                }

            On failure::

                {"ok": False, "tool_name": "search_knowledge_base", "error": "<message>"}
        """
        tool_name = "search_knowledge_base"
        try:
            # Clamp max_results to [1, 3]
            clamped = max(
                _MIN_RESULTS,
                min(_MAX_RESULTS, int(max_results)),
            )

            if dry_run:
                # Search only — no audit trail written
                logger.debug(
                    "[dry_run] search_knowledge_base: query=%.80s max_results=%d",
                    query,
                    clamped,
                )
                chunks = await retrieve_chunks(
                    query=query,
                    max_results=clamped,
                    db=db,
                )
            else:
                chunks = await retrieve_and_record(
                    query=query,
                    agent_run_id=agent_run_id,
                    message_id=message_id,
                    db=db,
                    max_results=clamped,
                )

            logger.info(
                "search_knowledge_base returned %d chunk(s) [dry_run=%s]",
                len(chunks),
                dry_run,
            )
            return {
                "ok": True,
                "tool_name": tool_name,
                "data": {"chunks": chunks},
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("search_knowledge_base error: %s", exc, exc_info=True)
            return {"ok": False, "tool_name": tool_name, "error": str(exc)}

    return search_knowledge_base
