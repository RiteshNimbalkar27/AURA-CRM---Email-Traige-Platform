"""
AURA RAG Retriever
Vector similarity search against pgvector kb_chunks table.
Returns top-k chunks by cosine similarity and records audit trail.
"""
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KBChunk, KBDocument, RAGRetrieval
from app.rag.embedder import get_embedding

logger = logging.getLogger(__name__)


async def retrieve_chunks(
    query: str,
    max_results: int = 3,
    db: AsyncSession = None,
) -> list[dict[str, Any]]:
    """
    Embed *query* and return the top *max_results* KB chunks by cosine similarity.

    Args:
        query:       Natural-language search query.
        max_results: Maximum number of chunks to return (default 3).
        db:          An active AsyncSession (required).

    Returns:
        List of dicts with keys:
            chunk_id    – UUID of the kb_chunk row
            document_id – UUID of the parent kb_document
            title       – Document title
            excerpt     – Chunk content text
            score       – Cosine similarity (1 − cosine_distance), 0–1
    """
    if db is None:
        raise ValueError("A database session must be provided to retrieve_chunks()")

    # 1. Embed the query (CPU, synchronous — fast enough for 384-dim)
    logger.debug("Embedding query for RAG retrieval: %.80s …", query)
    query_vector = get_embedding(query)

    # 2. Build the pgvector cosine-distance query with a JOIN to kb_documents
    #    The <=> operator returns cosine distance; we want similarity = 1 − distance.
    distance_expr = KBChunk.embedding.cosine_distance(query_vector).label("distance")

    stmt = (
        select(
            KBChunk.id.label("chunk_id"),
            KBChunk.document_id,
            KBDocument.title,
            KBChunk.content.label("excerpt"),
            distance_expr,
        )
        .join(KBDocument, KBChunk.document_id == KBDocument.id)
        .order_by(distance_expr.asc())
        .limit(max_results)
    )

    result = await db.execute(stmt)
    rows = result.fetchall()

    chunks: list[dict[str, Any]] = []
    for row in rows:
        score = float(1.0 - row.distance)
        chunks.append(
            {
                "chunk_id": str(row.chunk_id),
                "document_id": str(row.document_id),
                "title": row.title,
                "excerpt": row.excerpt,
                "score": round(score, 6),
            }
        )

    logger.info(
        "RAG retrieval returned %d chunk(s) for query: %.80s …",
        len(chunks),
        query,
    )
    return chunks


async def record_retrieval(
    chunk_ids: list[str],
    agent_run_id: uuid.UUID | None,
    message_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """
    Persist a RAGRetrieval row for each chunk (audit trail).

    Args:
        chunk_ids:    Ordered list of chunk UUID strings (rank = list position + 1).
        agent_run_id: Optional UUID of the associated agent run.
        message_id:   UUID of the email message that triggered this retrieval.
                      (Used to derive the score via a quick lookup so we don't
                       have to thread it through separately.)
        db:           An active AsyncSession.
    """
    if not chunk_ids:
        return

    # Fetch the scores we already computed by re-running the chunk lookup —
    # cheaper than threading scores through; chunk set is tiny (≤ max_results).
    stmt = select(KBChunk.id).where(
        KBChunk.id.in_([uuid.UUID(cid) for cid in chunk_ids])
    )
    result = await db.execute(stmt)
    existing_ids = {str(r[0]) for r in result.fetchall()}

    for rank, chunk_id_str in enumerate(chunk_ids, start=1):
        if chunk_id_str not in existing_ids:
            logger.warning("chunk_id %s not found in kb_chunks; skipping retrieval record", chunk_id_str)
            continue

        retrieval = RAGRetrieval(
            agent_run_id=agent_run_id,
            chunk_id=uuid.UUID(chunk_id_str),
            rank=rank,
            # Score is not available here without re-embedding; default to 0.
            # Callers that have scores should create RAGRetrieval rows directly.
            score=0.0,
        )
        db.add(retrieval)

    await db.flush()
    logger.debug(
        "Recorded %d RAG retrieval row(s) for agent_run_id=%s",
        len(chunk_ids),
        agent_run_id,
    )


async def retrieve_and_record(
    query: str,
    agent_run_id: uuid.UUID | None,
    message_id: uuid.UUID,
    db: AsyncSession,
    max_results: int = 3,
) -> list[dict[str, Any]]:
    """
    Convenience wrapper: retrieve chunks AND record the audit trail in one call.

    This is the preferred entry-point for the agent's ``search_knowledge_base`` tool
    because it captures accurate per-chunk scores.

    Returns the same list-of-dicts as :func:`retrieve_chunks`.
    """
    chunks = await retrieve_chunks(query=query, max_results=max_results, db=db)

    for rank, chunk in enumerate(chunks, start=1):
        retrieval = RAGRetrieval(
            agent_run_id=agent_run_id,
            chunk_id=uuid.UUID(chunk["chunk_id"]),
            rank=rank,
            score=chunk["score"],
        )
        db.add(retrieval)

    if chunks:
        await db.flush()
        logger.info(
            "Recorded %d RAG retrieval audit row(s) (agent_run_id=%s)",
            len(chunks),
            agent_run_id,
        )

    return chunks
