#!/usr/bin/env python3
"""
AURA Knowledge Base Seeder
Chunks, embeds, and indexes all 6 KB policy documents.
Uses sentence-transformers all-MiniLM-L6-v2 for 384-dim local embeddings.
Idempotent: safe to run multiple times (updates existing documents).

Usage (from backend/ directory with venv active):
    python scripts/seed_kb.py
"""
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.knowledge import KBDocument, KBChunk

settings = get_settings()

# KB documents directory
KB_DIR = Path(__file__).parent.parent / "kb_documents"

# Document metadata
KB_DOCUMENTS = [
    {
        "filename": "pricing_tiers_and_discounts.md",
        "title": "Pricing Tiers and Discounts",
        "version": "1.0.0",
    },
    {
        "filename": "sla_and_credits.md",
        "title": "SLA and Credits",
        "version": "1.0.0",
    },
    {
        "filename": "refunds_and_retention_offers.md",
        "title": "Refunds and Retention Offers",
        "version": "1.0.0",
    },
    {
        "filename": "api_limits_and_deprecations.md",
        "title": "API Limits and Deprecations",
        "version": "1.0.0",
    },
    {
        "filename": "gdpr_hipaa_soc2_data_residency.md",
        "title": "GDPR, HIPAA, SOC 2, and Data Residency",
        "version": "1.0.0",
    },
    {
        "filename": "escalation_ownership_matrix.md",
        "title": "Escalation Ownership Matrix",
        "version": "1.0.0",
    },
]

CHUNK_TOKENS = 400
OVERLAP_TOKENS = 50


def chunk_text(text: str, tokenizer) -> list[dict]:
    """
    Chunk text at CHUNK_TOKENS tokens with OVERLAP_TOKENS token overlap.
    Returns list of {content, token_start, token_end, chunk_index}.
    """
    tokens = tokenizer.encode(text, add_special_tokens=False)
    chunks = []
    start = 0
    chunk_index = 0

    while start < len(tokens):
        end = min(start + CHUNK_TOKENS, len(tokens))
        chunk_token_ids = tokens[start:end]
        chunk_text_content = tokenizer.decode(chunk_token_ids, skip_special_tokens=True)

        chunks.append({
            "content": chunk_text_content,
            "token_start": start,
            "token_end": end,
            "chunk_index": chunk_index,
        })

        chunk_index += 1
        if end >= len(tokens):
            break
        start = end - OVERLAP_TOKENS  # overlap

    return chunks


async def seed_document(
    session: AsyncSession,
    doc_meta: dict,
    model: SentenceTransformer,
    tokenizer,
) -> None:
    """Seed a single KB document: upsert doc record + all chunks."""
    filepath = KB_DIR / doc_meta["filename"]
    if not filepath.exists():
        print(f"  WARNING: {doc_meta['filename']} not found at {filepath}")
        return

    content = filepath.read_text(encoding="utf-8")
    print(f"\n  Processing: {doc_meta['title']}")
    print(f"    File: {doc_meta['filename']} ({len(content)} chars)")

    # Upsert document record
    result = await session.execute(
        select(KBDocument).where(KBDocument.filename == doc_meta["filename"])
    )
    doc = result.scalar_one_or_none()

    if doc:
        doc.content = content
        doc.version = doc_meta["version"]
        doc.title = doc_meta["title"]
        print(f"    UPDATE: Document record updated")
    else:
        doc = KBDocument(
            title=doc_meta["title"],
            filename=doc_meta["filename"],
            version=doc_meta["version"],
            content=content,
        )
        session.add(doc)
        await session.flush()  # get ID
        print(f"    CREATE: Document record created (id={doc.id})")

    # Delete existing chunks for this document (re-embed on update)
    existing_chunks = await session.execute(
        select(KBChunk).where(KBChunk.document_id == doc.id)
    )
    for chunk in existing_chunks.scalars():
        await session.delete(chunk)

    # Chunk the content
    chunks = chunk_text(content, tokenizer)
    print(f"    Chunking: {len(chunks)} chunks at {CHUNK_TOKENS} tokens with {OVERLAP_TOKENS} overlap")

    # Generate embeddings in batch
    chunk_texts = [c["content"] for c in chunks]
    embeddings = model.encode(chunk_texts, show_progress_bar=False, normalize_embeddings=True)
    print(f"    Embedding: {len(embeddings)} vectors (dim={embeddings.shape[1]})")

    # Insert chunks
    for i, (chunk_data, embedding) in enumerate(zip(chunks, embeddings)):
        chunk = KBChunk(
            document_id=doc.id,
            chunk_index=chunk_data["chunk_index"],
            token_start=chunk_data["token_start"],
            token_end=chunk_data["token_end"],
            content=chunk_data["content"],
            embedding=embedding.tolist(),
        )
        session.add(chunk)

    await session.flush()
    print(f"    Done: {len(chunks)} chunks embedded and stored")


async def main() -> None:
    print("=" * 60)
    print("AURA Knowledge Base Seeder")
    print("=" * 60)
    print(f"KB directory: {KB_DIR}")
    print(f"Embedding model: {settings.embedding_model}")
    print(f"Cache dir: {settings.embedding_cache_dir}")

    # Load embedding model (cached to project data dir)
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = settings.embedding_cache_dir
    os.makedirs(settings.embedding_cache_dir, exist_ok=True)

    print(f"\nLoading embedding model: {settings.embedding_model}")
    model = SentenceTransformer(settings.embedding_model)
    try:
        emb_dim = model.get_embedding_dimension()
    except AttributeError:
        emb_dim = model.get_sentence_embedding_dimension()
    print(f"  Model loaded. Embedding dim: {emb_dim}")

    # Load tokenizer for chunking (all-MiniLM-L6-v2 uses bert-base-uncased tokenizer)
    tokenizer = AutoTokenizer.from_pretrained(
        "sentence-transformers/all-MiniLM-L6-v2",
        cache_dir=settings.embedding_cache_dir,
    )

    # Connect to database
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        for doc_meta in KB_DOCUMENTS:
            await seed_document(session, doc_meta, model, tokenizer)
        await session.commit()

    await engine.dispose()

    print("\n" + "=" * 60)
    print("Knowledge base seeding complete!")
    print(f"  {len(KB_DOCUMENTS)} documents processed")
    print("  Chunks and embeddings stored in kb_chunks table")
    print("  pgvector ivfflat cosine index ready for similarity search")
    print("=" * 60)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
