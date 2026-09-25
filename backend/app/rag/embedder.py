"""
AURA RAG Embedder
Local embedding using sentence-transformers all-MiniLM-L6-v2 (384-dim, CPU).
Model is loaded lazily as a singleton — only on the first call.
"""
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton — populated on first use
# ---------------------------------------------------------------------------
_model: "SentenceTransformer | None" = None


def _get_model() -> "SentenceTransformer":
    """Return the cached SentenceTransformer, loading it on first call."""
    global _model
    if _model is not None:
        return _model

    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    settings = get_settings()

    # Resolve and create the cache directory if it doesn't exist yet
    cache_dir = Path(settings.embedding_cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    model_name = settings.embedding_model  # "all-MiniLM-L6-v2"
    logger.info(
        "Loading embedding model '%s' (cache_dir=%s) …", model_name, cache_dir
    )

    _model = SentenceTransformer(model_name, cache_folder=str(cache_dir))
    logger.info("Embedding model loaded — output dim: %d", _model.get_sentence_embedding_dimension())
    return _model


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_embedding(text: str) -> list[float]:
    """
    Encode a single text string and return a 384-dim float list.

    Args:
        text: The input string to embed.

    Returns:
        A list of 384 floats representing the embedding vector.
    """
    model = _get_model()
    vector = model.encode(text, convert_to_numpy=True)
    return vector.tolist()


def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Encode a batch of text strings in a single forward pass.

    Args:
        texts: List of input strings to embed.

    Returns:
        A list of 384-dim float lists, one per input text.
    """
    if not texts:
        return []

    model = _get_model()
    logger.debug("Embedding batch of %d texts", len(texts))
    vectors = model.encode(texts, convert_to_numpy=True, batch_size=32)
    return [v.tolist() for v in vectors]
