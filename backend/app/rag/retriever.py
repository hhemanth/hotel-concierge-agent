"""Voyage AI + Supabase pgvector retriever."""
from __future__ import annotations

import json
import os

import psycopg
import voyageai

from app.agent.state import RetrievedDoc
from app.observability import logger

_voyage_client: voyageai.AsyncClient | None = None
_db_conn: psycopg.AsyncConnection | None = None


def _get_voyage() -> voyageai.AsyncClient:
    global _voyage_client
    if _voyage_client is None:
        _voyage_client = voyageai.AsyncClient(api_key=os.environ["VOYAGE_API_KEY"])
    return _voyage_client


async def _get_db() -> psycopg.AsyncConnection:
    global _db_conn
    if _db_conn is None or _db_conn.closed:
        _db_conn = await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"])
        from pgvector.psycopg import register_vector_async
        await register_vector_async(_db_conn)
    return _db_conn


async def search(query: str, top_k: int = 5, threshold: float = 0.3) -> list[RetrievedDoc]:
    """Embed query, run cosine similarity search, return top results."""
    # Graceful fallback when env vars are absent
    if not os.environ.get("DATABASE_URL") or not os.environ.get("VOYAGE_API_KEY"):
        logger.warning("rag_search_skipped", reason="DATABASE_URL or VOYAGE_API_KEY not set")
        return []

    # 1. Embed the query
    client = _get_voyage()
    result = await client.embed([query], model="voyage-large-2-instruct", input_type="query")
    query_embedding = result.embeddings[0]

    # 2. Query the database
    conn = await _get_db()
    sql = """
        SELECT id, content, source_type, metadata,
               1 - (embedding <=> %s::vector) AS score
        FROM docs
        WHERE 1 - (embedding <=> %s::vector) > %s
        ORDER BY score DESC
        LIMIT %s
    """
    async with conn.cursor() as cur:
        await cur.execute(sql, (query_embedding, query_embedding, threshold, top_k))
        rows = await cur.fetchall()

    # 3. Map to RetrievedDoc
    docs: list[RetrievedDoc] = []
    for row in rows:
        doc_id, content, source_type, metadata_raw, score = row
        # metadata may be a dict already (psycopg json adapter) or a JSON string
        if isinstance(metadata_raw, str):
            metadata: dict = json.loads(metadata_raw)
        else:
            metadata = metadata_raw or {}

        if source_type == "property":
            source = f"property:{metadata.get('property_id', doc_id)}"
            title = metadata.get("name", doc_id)
        else:
            source = f"faq:{metadata.get('topic', doc_id)}"
            title = metadata.get("topic", doc_id)

        docs.append(
            RetrievedDoc(
                id=doc_id,
                source=source,
                title=title,
                text=content,
                score=float(score),
            )
        )

    top_score = docs[0]["score"] if docs else 0.0
    logger.info("rag_search", query_len=len(query), n_results=len(docs), top_score=round(top_score, 4))
    return docs
