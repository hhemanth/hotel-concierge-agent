"""One-shot ingest: chunk + embed + upsert `data/*.json` and `data/faqs.md` into pgvector.

Run with:
    python -m app.rag.ingest

STUB — implementation needed. Suggested approach:

1. Load `app/data/properties.json` — for each property, build a single doc per
   property with title=name and text concatenating description, amenities,
   neighbourhood, policies. id = "property:<property_id>".

2. Load `app/data/faqs.md` — split on `## ` headings. Each section is one doc.
   id = "faq:<slug>", source = "faq", title = heading text, text = body.

3. Embed each doc.text with OpenAI text-embedding-3-small (model name from env).
   Batch up to 100 inputs per call.

4. Upsert into the docs table from retriever.py module docstring:
       INSERT INTO docs (id, source, title, text, embedding)
       VALUES (%s, %s, %s, %s, %s::vector)
       ON CONFLICT (id) DO UPDATE SET
           source = EXCLUDED.source,
           title = EXCLUDED.title,
           text = EXCLUDED.text,
           embedding = EXCLUDED.embedding;

5. Print a summary: n docs ingested, n tokens billed.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    print("ingest stub — implement me (see module docstring).", file=sys.stderr)
    print("Required env: DATABASE_URL, OPENAI_API_KEY, EMBEDDING_MODEL", file=sys.stderr)
    for var in ("DATABASE_URL", "OPENAI_API_KEY"):
        present = "set" if os.getenv(var) else "MISSING"
        print(f"  {var}: {present}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
