"""pgvector-backed retriever.

STUB — implementation needed. Suggested approach:

1. On startup (or lazily), open a single psycopg connection to DATABASE_URL.
2. Ensure the `docs` table exists:
       CREATE EXTENSION IF NOT EXISTS vector;
       CREATE TABLE IF NOT EXISTS docs (
           id          TEXT PRIMARY KEY,
           source      TEXT,
           title       TEXT,
           text        TEXT,
           embedding   VECTOR(1536)
       );
       CREATE INDEX IF NOT EXISTS docs_embedding_idx
           ON docs USING ivfflat (embedding vector_cosine_ops)
           WITH (lists = 50);
3. `search(query, top_k)`:
       - Embed the query with OpenAI text-embedding-3-small (1536 dims).
       - ORDER BY embedding <=> %s::vector LIMIT %s
       - Return RetrievedDoc TypedDicts with score = 1 - distance.

Until this is implemented, the function returns an empty list — the agent
will still respond (with no context) and won't crash.
"""

from __future__ import annotations

from app.agent.state import RetrievedDoc


async def search(query: str, top_k: int = 5) -> list[RetrievedDoc]:
    # TODO: implement pgvector search. See module docstring.
    return []
