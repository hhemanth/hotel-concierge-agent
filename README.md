# TFE Hotels — Guest Concierge Agent

[![CI](https://github.com/hemanth/tfe-hotels-concierge/actions/workflows/ci.yml/badge.svg)](https://github.com/hemanth/tfe-hotels-concierge/actions/workflows/ci.yml)

A production-grade AI agent demo for hotel guest experience: a chat interface that handles both **information questions** (RAG over property descriptions and FAQs) and **multi-step bookings** (search or direct-reserve, availability check, option cards, confirmation) in a single LangGraph agent.

**Built as a portfolio piece for an AI Systems Engineer application to TFE Hotels.**

---

## Honest framing

- Hotel property data was **scraped from TFE Hotels' public website** (`scrape_tfe.py`) — may not reflect current listings.
- The booking back-end is **mocked** (in-memory, in-process) — no real reservations are made and no money moves.
- Every architectural choice is what I would build inside TFE's environment with a real PMS wired in on day one.

---

## Architecture

```
Browser (Vercel — Next.js 14)
  ├─ SSE streaming chat UI (token events → typing indicator → message)
  ├─ Hotel option cards  (selectable, navy/gold design)
  └─ Booking summary card  (ref number, dates, total, .ics download)
          │  POST /chat  (SSE stream)
          ▼
Railway (FastAPI + LangGraph)
  ├─ GET  /healthz
  └─ POST /chat  → StreamingResponse (text/event-stream)
       └─ LangGraph graph
            ├─ router node     (Haiku)  → intent: info | booking | smalltalk
            ├─ retrieve node            → RAG: Supabase pgvector + Voyage AI
            ├─ extract_params node      → mode: search | direct + booking params
            ├─ booking node             → calls MCP tool functions
            └─ respond node    (Sonnet) → SSE token events + metadata event

MCP Booking Server  (fastmcp, imported in-process for the demo)
  ├─ search_hotels(location, amenities, vibe, max_price, min_nights)
  ├─ check_hotel_availability(property_id, check_in, check_out, guests)
  ├─ get_hotel_offers(property_id, nights)
  ├─ create_hotel_booking(property_id, check_in, check_out, guests)
  ├─ cancel_hotel_booking(booking_id)
  └─ get_hotel_booking(booking_id)

Supabase (pgvector)
  └─ docs table: id TEXT PK, content TEXT, embedding vector(1024),
                 source_type TEXT, metadata JSONB
```

### Two tool patterns

| Path | Trigger examples | Tool | Why |
|---|---|---|---|
| Info / Q&A | "Do you allow pets?", "Cancellation policy?" | RAG (Supabase + Voyage AI) | Unstructured semantic search over hotel descriptions + FAQs |
| Booking | "Beach hotel next month", "Book Vibe Sydney June 15–17" | MCP server | Structured, deterministic: filter → availability → offers → confirm |

---

## Repository layout

```
backend/
  app/
    main.py               # FastAPI: /chat (SSE), /healthz
    agent/
      graph.py            # LangGraph topology
      state.py            # AgentState TypedDict
      nodes/
        router.py         # Haiku intent classifier
        retrieve.py       # RAG retrieval
        extract_params.py # Booking param extraction (search | direct mode)
        booking.py        # MCP tool calls
        respond.py        # Sonnet response synthesis + metadata envelope
    mcp/
      booking_server.py   # fastmcp server with 6 booking tools
    rag/
      ingest.py           # Voyage AI + Supabase upsert (run once)
      retriever.py        # pgvector cosine similarity search
    data/
      properties.py       # Loader (prefers properties_scraped.json)
      scrape_tfe.py       # httpx + BeautifulSoup scraper
      properties.json     # Fallback synthetic data
      faqs.md             # Hotel FAQ content
    tools/
      booking_api.py      # In-memory mock PMS
  Dockerfile
  requirements.txt

frontend/
  app/
    page.tsx              # SSE consumer, PropertyCard, BookingConfirmation
    layout.tsx            # Inter + Playfair Display fonts
    api/chat/route.ts     # SSE proxy to backend
  tailwind.config.ts      # Navy #1B2A4A + Gold #C9A84C theme

supabase/
  migrations/
    001_docs_table.sql    # pgvector schema (run once)

.github/
  workflows/
    ci.yml                # On PR: ruff + pyright + pytest + next build
    deploy.yml            # On merge to main: Railway ∥ Vercel
```

---

## Quick start (local)

### Prerequisites

- Docker (for Postgres + pgvector)
- Python 3.11+
- Node.js 20+
- API keys: `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`
- Supabase project (free tier) — or use the local Postgres with the pgvector extension

### 1. Spin up local Postgres

```bash
docker compose up -d
```

### 2. Backend

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

cd backend
uv sync                    # installs all deps from uv.lock into a managed venv

cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY and VOYAGE_API_KEY at minimum

# Scrape TFE property data (optional — falls back to synthetic data)
uv run python -m app.data.scrape_tfe

# Embed and ingest into pgvector (run once, re-run after data changes)
uv run python -m app.rag.ingest

uv run uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
# NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
npm run dev   # → http://localhost:3000
```

### 4. Verify

```bash
# Info path
curl -N -s -X POST http://localhost:8000/chat \
  -H "content-type: application/json" \
  -d '{"messages":[{"role":"user","content":"Is there parking at Adina Bondi?"}]}'

# Booking search
curl -N -s -X POST http://localhost:8000/chat \
  -H "content-type: application/json" \
  -d '{"messages":[{"role":"user","content":"Beach hotel in Sydney next month, 2 nights, under $350"}]}'
```

---

## CI

### On pull request → `ci.yml`

| Job | Steps |
|---|---|
| `backend` | `uv run ruff check` → `uv run pyright` → `uv run pytest` |
| `frontend` | `npm ci` → `next build` |

### Required GitHub secrets (for CI tests)

| Secret | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Backend pytest |
| `VOYAGE_API_KEY` | Backend pytest |
| `DATABASE_URL` | Backend pytest |

---

## Deployment

Deployments are triggered directly from the platform dashboards — no CI automation needed.

### Backend → Railway

1. Create a new Railway project → **Deploy from GitHub repo**
2. Set root directory to `backend/`
3. Railway auto-detects the `Dockerfile` and builds on every push to `main`
4. Add env vars in Railway's **Variables** tab (copy from `backend/.env.example`)

### Frontend → Vercel

1. Import the GitHub repo in Vercel
2. Set framework to **Next.js**, root directory to `frontend/`
3. Add env var: `NEXT_PUBLIC_BACKEND_URL=https://your-railway-app.up.railway.app`
4. Vercel deploys on every push to `main` automatically

### Vector store → Supabase

| Service | Target |
|---|---|
| Backend | Railway (Dockerfile in `backend/`) |
| Frontend | Vercel (root set to `frontend/`) |
| Vector store | Supabase (free tier, `DATABASE_URL` connection string) |

---

## License

MIT — portfolio piece; reuse freely.
