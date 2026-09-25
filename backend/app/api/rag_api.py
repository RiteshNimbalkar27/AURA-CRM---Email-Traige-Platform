"""
AURA RAG API Router
Exposes GET /api/rag/search for knowledge-base vector search.
Requires JWT authentication.
"""
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.database import DBSession
from app.rag.retriever import retrieve_chunks

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/rag/search")
async def rag_search(
    query: Annotated[str, Query(min_length=1, max_length=2000, description="Natural-language search query")],
    max_results: Annotated[int, Query(ge=1, le=20, description="Maximum number of chunks to return")] = 3,
    db: DBSession = None,
    current_user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Search the AURA knowledge base using vector similarity.

    Embeds *query* locally (all-MiniLM-L6-v2, 384-dim) and returns the
    top *max_results* KB chunks ranked by cosine similarity.

    Returns:
        ```json
        {
          "chunks": [
            {
              "chunk_id":    "uuid",
              "document_id": "uuid",
              "title":       "Policy document title",
              "excerpt":     "Relevant chunk text …",
              "score":       0.87
            }
          ]
        }
        ```
    """
    logger.info(
        "RAG search requested by user=%s | query=%.80s … | max_results=%d",
        current_user.id,
        query,
        max_results,
    )

    chunks = await retrieve_chunks(query=query, max_results=max_results, db=db)

    return {"chunks": chunks}
