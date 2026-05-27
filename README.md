# TFE Hotels — Guest Concierge Agent

A working demo of a production-grade AI agent for hotel guest experience: text chat that handles both **information questions** (RAG over property data, FAQs, amenities) and **multi-step booking actions** (find availability, present options, confirm reservation) in a single LangGraph agent.

**Built as a portfolio piece for an AI Systems Engineer application to TFE Hotels.**

## Honest framing

- Property data is **synthetic**, modelled after publicly available information about TFE's brands (Vibe Hotels, Adina, Travelodge).
- The booking back-end is **mocked** — no real reservations are made, no money moves.
- Every architectural choice (LangGraph routing, RAG retrieval, agentic tool use, evals, observability) is what I'd build inside TFE's environment with real PMS/booking systems wired in on day one.

## What it demonstrates

- **API-first, event-driven backend** — FastAPI + structured logging + per-request cost tracking
- **Agentic AI** — LangGraph state machine with a router and two branches (info / booking)
- **Multi-step task orchestration** — booking flow handles parameter extraction, availability check, option presentation, confirmation, and modification across turns
- **Production-grade evals** — LLM-as-a-Judge over a fixed set of test conversations, with pass-rate tracked over time
- **Integration-ready** — mock tools are deliberately shaped like real PMS/booking APIs so swapping them for real systems is a configuration change, not a rewrite

## Architecture

```
                 ┌─────────────────────────────────┐
                 │  USER MESSAGE                   │
                 └────────────┬────────────────────┘
                              ▼
                    ┌──────────────────┐
                    │ router (LLM)     │  ← classifies intent
                    └────┬─────────┬───┘
         info / FAQ      │         │  booking / change / cancel
                         ▼         ▼
               ┌──────────────┐  ┌─────────────────────────┐
               │ retrieve     │  │ extract_params (dates,  │
               │ (RAG over    │  │  city, guests, budget)  │
               │  property    │  └──────────┬──────────────┘
               │  pages, FAQs)│             ▼
               └──────┬───────┘  ┌─────────────────────────┐
                      ▼          │ missing_info? ──► ask_user
               ┌──────────────┐  │   (END turn, await reply)
               │ respond      │  └──────────┬──────────────┘
               └──────┬───────┘             ▼  (complete)
                      │          ┌─────────────────────────┐
                      │          │ check_availability      │
                      │          │ (mock booking tool)     │
                      │          └──────────┬──────────────┘
                      │                     ▼
                      │          ┌─────────────────────────┐
                      │          │ present_options ──► user│
                      │          │  picks / modifies       │
                      │          └──────────┬──────────────┘
                      │                     ▼
                      │          ┌─────────────────────────┐
                      │          │ confirm_booking (mock)  │
                      │          └──────────┬──────────────┘
                      ▼                     ▼
                    ┌──────────────────────────┐
                    │ RESPONSE TO USER         │
                    └──────────────────────────┘
```

## Repository layout

```
backend/                  # Python, FastAPI, LangGraph
  app/
    main.py               # FastAPI: /chat, /healthz, /metrics
    agent/                # LangGraph definition
    tools/                # Mock booking API
    rag/                  # Embeddings + retriever (pgvector via Supabase)
    data/                 # Synthetic property data
  evals/                  # LLM-as-a-Judge test suite
  Dockerfile              # Railway target
  requirements.txt
frontend/                 # Next.js 14 app router
  app/
    page.tsx              # Chat UI
    api/chat/route.ts     # Proxy to backend
  package.json
docker-compose.yml        # Local dev: Postgres + pgvector
CLAUDE.md                 # Orientation for Claude Code agents
```

## Quick start (local)

```bash
# 1. Spin up Postgres+pgvector locally
docker compose up -d

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then add ANTHROPIC_API_KEY
python -m app.rag.ingest        # one-shot: embed data/ into pgvector
uvicorn app.main:app --reload --port 8000

# 3. Frontend
cd ../frontend
npm install
cp .env.example .env.local       # NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
npm run dev                       # http://localhost:3000

# 4. Evals (optional but recommended before any commit that touches the agent)
cd ../backend
python -m evals.run_evals
```

## Deployment target

- **Backend** → Railway (Dockerfile + Railway-managed Postgres-with-pgvector)
- **Frontend** → Vercel
- **Observability** → Railway built-in metrics + structured JSON logs (forward to Logtail / Axiom if desired)

## What's done vs TODO

See `CLAUDE.md` for the per-file map of what's already implemented vs what to fill in.

## License

MIT — this is a portfolio piece; reuse freely.
