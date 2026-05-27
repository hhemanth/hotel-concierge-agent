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
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY and VOYAGE_API_KEY at minimum

# Scrape TFE property data (optional — falls back to synthetic data)
python3 -m app.data.scrape_tfe

# Embed and ingest into pgvector (run once, re-run after data changes)
python3 -m app.rag.ingest

uvicorn app.main:app --reload --port 8000
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

## CI/CD

### On pull request → `ci.yml`

| Job | Steps |
|---|---|
| `backend` | `ruff check` → `pyright` → `pytest` |
| `frontend` | `npm ci` → `next build` |

### On merge to main → `deploy.yml`

- **Backend** → Railway (`railway up --service backend`)
- **Frontend** → Vercel (`vercel --prod`)

Both deploy jobs run in parallel.

### Required GitHub secrets

| Secret | Used by |
|---|---|
| `ANTHROPIC_API_KEY` | Backend CI tests |
| `VOYAGE_API_KEY` | Backend CI tests |
| `DATABASE_URL` | Backend CI tests |
| `RAILWAY_TOKEN` | Railway deploy |
| `VERCEL_TOKEN` | Vercel deploy |
| `VERCEL_ORG_ID` | Vercel deploy |
| `VERCEL_PROJECT_ID` | Vercel deploy |

---

## Deployment

| Service | Target |
|---|---|
| Backend | Railway (Dockerfile in `backend/`) |
| Frontend | Vercel (root set to `frontend/`) |
| Vector store | Supabase (free tier, `DATABASE_URL` connection string) |

---

## License

MIT — portfolio piece; reuse freely.
