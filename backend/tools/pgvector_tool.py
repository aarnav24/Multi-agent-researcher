"""pgvector tool — internal corpus vector search for user-uploaded documents.

Enables agents to search over a local vector store (Postgres + pgvector)
without external API calls. Used for the "Internal Corpus" tool routing
category — when the planner determines a sub-question relates to previously
indexed content.

Schema:
  CREATE TABLE IF NOT EXISTS corpus_embeddings (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT '',
    doc_name    TEXT NOT NULL,
    chunk_idx   INTEGER NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(384) NOT NULL,  -- all-MiniLM-L6-v2 dimension
    created_at  TIMESTAMPTZ DEFAULT now()
  );
  CREATE INDEX IF NOT EXISTS corpus_user_doc_idx
    ON corpus_embeddings (user_id, doc_name);
  CREATE INDEX IF NOT EXISTS corpus_embedding_idx
    ON corpus_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from backend.config import settings
from backend.tools.base import ToolOutput

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
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            await register_vector(conn)
            # Ensure table exists (ignore error if already exists).
            # user_id scopes each document to its owner so multi-tenant
            # searches don't leak across users.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS corpus_embeddings (
                    id          BIGSERIAL PRIMARY KEY,
                    user_id     TEXT NOT NULL DEFAULT '',
                    doc_name    TEXT NOT NULL,
                    chunk_idx   INTEGER NOT NULL,
                    content     TEXT NOT NULL,
                    embedding   vector(384) NOT NULL,
                    created_at  TIMESTAMPTZ DEFAULT now()
                )
            """)
            # Backfill user_id column if the table pre-existed without it.
            await conn.execute("""
                ALTER TABLE corpus_embeddings
                ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT ''
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS corpus_user_doc_idx
                ON corpus_embeddings (user_id, doc_name)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS corpus_embedding_idx
                ON corpus_embeddings USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """)
    return _pool


async def index_document(
    doc_name: str,
    content: str,
    user_id: str = "",
    chunk_size: int = 500,
) -> int:
    """Chunk a document and insert embeddings into the vector store.

    Args:
        doc_name: Human-readable document name.
        content: Full document text.
        user_id: Owning user — scopes the document so other users can't search it.
        chunk_size: Max characters per chunk (default 500 ≈ 125 tokens).

    Returns:
        Number of chunks indexed.
    """
    from backend.utils.embeddings import embed_texts

    pool = await _get_pool()

    # Replace previous version of this document for the same user so re-uploads
    # don't leave orphan chunks. Cheap O(rows) cleanup before insert.
    if user_id:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM corpus_embeddings WHERE user_id=$1 AND doc_name=$2",
                user_id, doc_name,
            )

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
            await conn.execute(
                """INSERT INTO corpus_embeddings (user_id, doc_name, chunk_idx, content, embedding)
                   VALUES ($1, $2, $3, $4, $5)""",
                user_id, doc_name, i, chunk, emb.tolist(),
            )

    logger.info(f"pgvector: indexed {len(chunks)} chunks for '{doc_name}' (user={user_id})")
    return len(chunks)


async def has_documents(user_id: str) -> bool:
    """Cheap existence check — does this user have *any* indexed chunks?

    Used by the orchestrator to decide whether to wire the pgvector tool into
    this research run. Returns False for anonymous / empty user_id.
    """
    if not user_id:
        return False
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM corpus_embeddings WHERE user_id=$1 LIMIT 1",
                user_id,
            )
            return (count or 0) > 0
    except Exception as e:
        logger.warning(f"pgvector: has_documents check failed: {e}")
        return False


async def pgvector_search(
    query: str,
    max_results: int = 5,
    doc_name: str | None = None,
    user_id: str | None = None,
) -> list[ToolOutput]:
    """Search the internal corpus using vector similarity.

    Args:
        query: The search query text.
        max_results: Maximum number of results to return.
        doc_name: Optional filter by document name.
        user_id: Restricts the search to the calling user's documents only.
                 Without a user_id, results span the entire (unfiltered) corpus.

    Returns:
        List of ToolOutput with matching chunks.
    """
    from backend.utils.embeddings import embed_texts

    start = __import__("time").time()

    try:
        # Embed the query
        query_embedding = embed_texts([query])[0]

        pool = await _get_pool()

        async with pool.acquire() as conn:
            # Build a filtered query so users never cross-pollute.
            if user_id and doc_name:
                rows = await conn.fetch(
                    """SELECT doc_name, chunk_idx, content, 1 - (embedding <=> $1) AS similarity
                       FROM corpus_embeddings
                       WHERE user_id = $2 AND doc_name = $3
                       ORDER BY embedding <=> $1
                       LIMIT $4""",
                    query_embedding.tolist(), user_id, doc_name, max_results,
                )
            elif user_id:
                rows = await conn.fetch(
                    """SELECT doc_name, chunk_idx, content, 1 - (embedding <=> $1) AS similarity
                       FROM corpus_embeddings
                       WHERE user_id = $2
                       ORDER BY embedding <=> $1
                       LIMIT $3""",
                    query_embedding.tolist(), user_id, max_results,
                )
            elif doc_name:
                rows = await conn.fetch(
                    """SELECT doc_name, chunk_idx, content, 1 - (embedding <=> $1) AS similarity
                       FROM corpus_embeddings
                       WHERE doc_name = $2
                       ORDER BY embedding <=> $1
                       LIMIT $3""",
                    query_embedding.tolist(), doc_name, max_results,
                )
            else:
                rows = await conn.fetch(
                    """SELECT doc_name, chunk_idx, content, 1 - (embedding <=> $1) AS similarity
                       FROM corpus_embeddings
                       ORDER BY embedding <=> $1
                       LIMIT $2""",
                    query_embedding.tolist(), max_results,
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


async def index_document_for_user(
    user_id: str,
    filename: str,
    content: str,
) -> int:
    """Convenience wrapper: index a document owned by a specific user.

    The doc_name is derived from the original filename (sans extension) so
    re-uploading the same file replaces, rather than duplicates, its chunks.
    """
    # Strip the trailing extension if present — keeps doc_name human-friendly.
    doc_name = filename
    for ext in (".txt", ".md", ".markdown", ".text"):
        if doc_name.lower().endswith(ext):
            doc_name = doc_name[: -len(ext)]
            break
    if not doc_name.strip():
        doc_name = filename or "untitled"
    return await index_document(doc_name=doc_name, content=content, user_id=user_id)


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
