"""One-shot ingest: embed hotel + FAQ data into Supabase pgvector.

Run: python -m app.rag.ingest
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
import voyageai

from app.data.properties import load_properties
from app.observability import logger

_DATA_DIR = Path(__file__).parent.parent / "data"
_FAQS_PATH = _DATA_DIR / "faqs.md"

_EMBED_MODEL = "voyage-large-2-instruct"
_BATCH_SIZE = 50


@dataclass
class Doc:
    id: str
    content: str
    source_type: str
    metadata: dict


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _load_property_docs() -> list[Doc]:
    docs: list[Doc] = []
    for p in load_properties():
        amenities_str = ", ".join(p.get("amenities", []))
        content = (
            f"{p['name']}. "
            f"{p['description']}. "
            f"Amenities: {amenities_str}. "
            f"Check-in: {p['check_in_time']}. "
            f"Check-out: {p['check_out_time']}. "
            f"{p.get('pet_policy', '')}. "
            f"{p.get('parking', '')}."
        )
        docs.append(
            Doc(
                id=f"property:{p['property_id']}",
                content=content,
                source_type="property",
                metadata={
                    "property_id": p["property_id"],
                    "name": p["name"],
                    "city": p["city"],
                },
            )
        )
    return docs


def _load_faq_docs() -> list[Doc]:
    raw = _FAQS_PATH.read_text(encoding="utf-8")
    # Split on lines that start with "## " — each is a new FAQ section
    sections = re.split(r"(?m)^## ", raw)
    docs: list[Doc] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # First line is the heading, rest is body
        lines = section.split("\n", 1)
        heading = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        if not heading:
            continue
        slug = _slugify(heading)
        content = f"{heading}. {body}"
        docs.append(
            Doc(
                id=f"faq:{slug}",
                content=content,
                source_type="faq",
                metadata={"topic": heading},
            )
        )
    return docs


async def _embed_docs(client: voyageai.AsyncClient, docs: list[Doc]) -> list[list[float]]:
    """Embed all docs in batches, return list of embedding vectors."""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(docs), _BATCH_SIZE):
        batch = docs[i : i + _BATCH_SIZE]
        texts = [d.content for d in batch]
        result = await client.embed(texts, model=_EMBED_MODEL, input_type="document")
        all_embeddings.extend(result.embeddings)
    return all_embeddings


async def _upsert_docs(
    conn: psycopg.AsyncConnection,
    docs: list[Doc],
    embeddings: list[list[float]],
) -> None:
    sql = """
        INSERT INTO docs (id, content, embedding, source_type, metadata)
        VALUES (%s, %s, %s::vector, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
          content = EXCLUDED.content,
          embedding = EXCLUDED.embedding,
          source_type = EXCLUDED.source_type,
          metadata = EXCLUDED.metadata
    """
    async with conn.cursor() as cur:
        for doc, emb in zip(docs, embeddings):
            await cur.execute(
                sql,
                (
                    doc.id,
                    doc.content,
                    emb,
                    doc.source_type,
                    json.dumps(doc.metadata),
                ),
            )
    await conn.commit()


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    voyage_api_key = os.environ.get("VOYAGE_API_KEY")

    if not database_url or not voyage_api_key:
        missing = [v for v in ("DATABASE_URL", "VOYAGE_API_KEY") if not os.environ.get(v)]
        print(f"ERROR: missing required env vars: {', '.join(missing)}", file=sys.stderr)
        return 1

    # Load documents
    property_docs = _load_property_docs()
    faq_docs = _load_faq_docs()
    all_docs = property_docs + faq_docs

    logger.info("ingest_start", n_property=len(property_docs), n_faq=len(faq_docs), total=len(all_docs))

    # Embed
    voyage_client = voyageai.AsyncClient(api_key=voyage_api_key)
    embeddings = await _embed_docs(voyage_client, all_docs)

    # Upsert
    conn = await psycopg.AsyncConnection.connect(database_url)
    try:
        from pgvector.psycopg import register_vector_async
        await register_vector_async(conn)
        await _upsert_docs(conn, all_docs, embeddings)
    finally:
        await conn.close()

    logger.info(
        "ingest_complete",
        n_docs=len(all_docs),
        n_property=len(property_docs),
        n_faq=len(faq_docs),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
