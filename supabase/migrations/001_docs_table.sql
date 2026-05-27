-- TFE Hotels Concierge — vector store schema
-- Run once: psql $DATABASE_URL -f supabase/migrations/001_docs_table.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS docs (
  id          TEXT PRIMARY KEY,
  content     TEXT NOT NULL,
  embedding   vector(1024) NOT NULL,
  source_type TEXT,
  metadata    JSONB
);

CREATE INDEX IF NOT EXISTS docs_embedding_idx
  ON docs USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
