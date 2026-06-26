"""pgvector tool — internal corpus vector search for user-uploaded documents.

Enables agents to search over a local vector store (Postgres + pgvector)
without external API calls. Used for the "Internal Corpus" tool routing
category — when the planner determines a sub-question relates to previously
indexed content.

Schema:
  CREATE TABLE IF NOT EXISTS corpus_embeddings (
    id          BIGSERIAL PRIMARY KEY,
    doc_name    TEXT NOT NULL,
    chunk_idx   INTEGER NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(384) NOT NULL,  -- all-MiniLM-L6-v2 dimension
    created_at  TIMESTAMPTZ DEFAULT now()
  );
  CREATE INDEX IF NOT EXISTS corpus_embedding_idx
    ON corpus_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.config import settings
from app.tools.base import ToolOutput

logger = logging.getLogger(__name__)

# Lazy pool reference
_pool = None


async def _get_pool():
    """Get or create the asyncpg pool with pgvector registered."""
    global _pool
    if _pool is None:
        import asyncpg
        from pgvector.asyncpg import register_vector
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url.replace("+asyncpg", ""),
            min_size=1,
            max_size=5,
        )
        async with _pool.acquire() as conn:
            await register_vector(conn)
            # Ensure table exists (ignore error if already exists)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS corpus_embeddings (
                    id          BIGSERIAL PRIMARY KEY,
                    doc_name    TEXT NOT NULL,
                    chunk_idx   INTEGER NOT NULL,
                    content     TEXT NOT NULL,
                    embedding   vector(384) NOT NULL,
                    created_at  TIMESTAMPTZ DEFAULT now()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS corpus_embedding_idx
                ON corpus_embeddings USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """)
    return _pool


async def index_document(doc_name: str, content: str, chunk_size: int = 500) -> int:
    """Chunk a document and insert embeddings into the vector store.

    Args:
        doc_name: Human-readable document name.
        content: Full document text.
        chunk_size: Max characters per chunk (default 500 ≈ 125 tokens).

    Returns:
        Number of chunks indexed.
    """
    from app.utils.embeddings import embed_texts

    pool = await _get_pool()

    # Simple chunking by character count with overlap
    overlap = 50
    chunks: list[str] = []
    start = 0
    while start < len(content):
        end = min(start + chunk_size, len(content))
        chunks.append(content[start:end])
        start += chunk_size - overlap

    if not chunks:
        return 0

    # Embed all chunks at once (batch)
    embeddings = embed_texts(chunks)

    async with pool.acquire() as conn:
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            # Convert numpy array to pgvector literal: "[0.1,0.2,...]"
            emb_str = "[" + ",".join(f"{v:.6f}" for v in emb) + "]"
            await conn.execute(
                """INSERT INTO corpus_embeddings (doc_name, chunk_idx, content, embedding)
                   VALUES ($1, $2, $3, $4::vector)""",
                doc_name, i, chunk, emb_str,
            )

    logger.info(f"pgvector: indexed {len(chunks)} chunks for '{doc_name}'")
    return len(chunks)


async def pgvector_search(
    query: str,
    max_results: int = 5,
    doc_name: str | None = None,
) -> list[ToolOutput]:
    """Search the internal corpus using vector similarity.

    Args:
        query: The search query text.
        max_results: Maximum number of results to return.
        doc_name: Optional filter by document name.

    Returns:
        List of ToolOutput with matching chunks.
    """
    from app.utils.embeddings import embed_texts

    start = __import__("time").time()

    try:
        # Embed the query
        query_embedding = embed_texts([query])[0]
        emb_str = "[" + ",".join(f"{v:.6f}" for v in query_embedding) + "]"

        pool = await _get_pool()

        async with pool.acquire() as conn:
            if doc_name:
                rows = await conn.fetch(
                    """SELECT doc_name, chunk_idx, content, 1 - (embedding <=> $1::vector) AS similarity
                       FROM corpus_embeddings
                       WHERE doc_name = $2
                       ORDER BY embedding <=> $1::vector
                       LIMIT $3""",
                    emb_str, doc_name, max_results,
                )
            else:
                rows = await conn.fetch(
                    """SELECT doc_name, chunk_idx, content, 1 - (embedding <=> $1::vector) AS similarity
                       FROM corpus_embeddings
                       ORDER BY embedding <=> $1::vector
                       LIMIT $2""",
                    emb_str, max_results,
                )

        elapsed = (__import__("time").time() - start) * 1000
        logger.info(f"pgvector: found {len(rows)} results for '{query[:60]}' ({elapsed:.0f}ms)")

        results = []
        for row in rows:
            # similarity score (0-1) — use as authority boost
            similarity = float(row.get("similarity", 0.5))
            # Scale: 0.5 similarity → 60 authority, 1.0 similarity → 90 authority
            authority = 40.0 + similarity * 50.0
            results.append(ToolOutput(
                source_id=str(uuid.uuid4()),
                url=f"corpus://{row['doc_name']}#chunk-{row['chunk_idx']}",
                title=f"{row['doc_name']} (chunk {row['chunk_idx']})",
                snippet=row["content"][:300],
                full_content=row["content"],
                domain_authority=round(authority, 1),
                tool_name="pgvector",
            ))

        return results

    except Exception as e:
        elapsed = (__import__("time").time() - start) * 1000
        logger.error(f"pgvector: search failed: {e} ({elapsed:.0f}ms)")
        return []


async def get_corpus_stats() -> dict[str, Any]:
    """Get statistics about the indexed corpus."""
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM corpus_embeddings")
            docs = await conn.fetchval("SELECT COUNT(DISTINCT doc_name) FROM corpus_embeddings")
            return {
                "total_chunks": total,
                "total_documents": docs,
                "enabled": True,
            }
    except Exception as e:
        logger.warning(f"pgvector: stats failed: {e}")
        return {"enabled": False, "error": str(e)}
