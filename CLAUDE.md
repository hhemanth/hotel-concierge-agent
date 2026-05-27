# Claude Code orientation — Guest Concierge Agent

This file orients Claude Code on the project so the first session can get productive immediately.

## Goal of the project

Build a working demo of a single LangGraph agent that handles both **guest information** (RAG-backed Q&A on hotel properties) and **multi-step bookings** (parameter extraction → availability → confirmation), deployable to Railway + Vercel, used as a portfolio piece for an AI Systems Engineer application to TFE Hotels.

**Honesty rule.** This is a demo on synthetic data. Mocks are clearly marked. Do not invent claims about TFE's real systems anywhere in code comments, README, or demo copy.

## Stack

| Layer        | Choice                                                           |
| ------------ | ---------------------------------------------------------------- |
| LLM          | Anthropic Claude (Sonnet for agent reasoning, Haiku for router + judge) |
| Agent framework | LangGraph                                                     |
| Embeddings   | Voyage AI `voyage-large-2-instruct`                              |
| Vector store | pgvector (Supabase in prod, local Postgres in dev)               |
| Backend      | FastAPI (Python 3.11)                                            |
| Frontend     | Next.js 14 app router (TypeScript, Tailwind)                     |
| Deploy       | Railway (backend + Postgres), Vercel (frontend)                  |

## File-by-file status

Use this as the source of truth for what's done vs what needs work. When you finish something marked TODO, update this file in the same commit.

### Root
- `README.md` — DONE
- `CLAUDE.md` — this file; keep it current
- `.gitignore` — DONE
- `.env.example` — DONE (root-level orchestration vars)
- `docker-compose.yml` — DONE (Postgres + pgvector for local dev)

### Backend
- `backend/Dockerfile` — DONE (Railway-ready, Python 3.11 slim)
- `backend/requirements.txt` — DONE (Voyage AI + fastmcp + langchain-mcp-adapters + beautifulsoup4)
- `backend/.env.example` — DONE (VOYAGE_API_KEY, SUPABASE_URL, EMBEDDING_MODEL)
- `backend/app/main.py` — DONE (FastAPI app, /chat, /healthz, CORS, request logging)
- `backend/app/observability.py` — DONE (structured logging + token/cost tracker)
- `backend/app/agent/state.py` — DONE (AgentState TypedDict)
- `backend/app/agent/graph.py` — DONE (graph wired, nodes registered, edges defined)
- `backend/app/agent/nodes/router.py` — **WORKING** (LLM-based intent classifier, simple prompt; refine prompts as needed)
- `backend/app/agent/nodes/retrieve.py` — **STUB** — TODO: wire to `rag/retriever.py` once ingest is done
- `backend/app/agent/nodes/extract_params.py` — **STUB** — TODO: use structured output (JSON mode) to extract booking params
- `backend/app/agent/nodes/booking.py` — **STUB** — TODO: implement check_availability call, option presentation, confirmation
- `backend/app/agent/nodes/respond.py` — **WORKING** (final response synthesis from state)
- `backend/app/tools/booking_api.py` — **WORKING** (in-memory mock with check_availability, create_booking, cancel_booking)
- `backend/app/rag/ingest.py` — **STUB** — TODO: read `data/*.json` + `data/faqs.md`, chunk, embed, upsert to pgvector
- `backend/app/rag/retriever.py` — **STUB** — TODO: cosine similarity search via pgvector
- `backend/app/data/properties.json` — DONE (4 synthetic properties)
- `backend/app/data/inventory.json` — DONE (mock availability)
- `backend/app/data/faqs.md` — DONE (synthetic FAQs)
- `backend/evals/test_conversations.json` — DONE (10 test cases)
- `backend/evals/run_evals.py` — **STUB** — TODO: run cases, score with LLM-as-a-Judge, output JSON report

### Supabase
- `supabase/migrations/001_docs_table.sql` — DONE (pgvector schema: docs table + ivfflat index, 1024-dim for Voyage AI)

### Frontend
- `frontend/package.json` — DONE
- `frontend/tsconfig.json` — DONE
- `frontend/next.config.js` — DONE
- `frontend/tailwind.config.ts` — DONE
- `frontend/postcss.config.js` — DONE
- `frontend/.env.example` — DONE
- `frontend/app/layout.tsx` — DONE
- `frontend/app/page.tsx` — **WORKING** (chat UI, calls /api/chat, displays history)
- `frontend/app/globals.css` — DONE
- `frontend/app/api/chat/route.ts` — DONE (proxies to backend)

## Order of work (suggested)

1. **Get the happy path running locally.** Spin up docker-compose, install backend deps, copy `.env.example → .env`, add an Anthropic API key. The backend should boot. Hit `GET /healthz` to confirm.
2. **Implement RAG ingest** (`backend/app/rag/ingest.py`) and run it once. This is the single biggest unblock for the info branch.
3. **Wire the retrieve node** to the new retriever. Test the info path end-to-end via curl on `/chat`.
4. **Implement extract_params + booking flow.** Use Anthropic's tool-use / JSON mode for parameter extraction. The mock booking API is already working.
5. **Run the eval suite.** Iterate prompts until pass rate is acceptable.
6. **Deploy.** Backend to Railway, frontend to Vercel.

## Conventions

- **Type hints everywhere.** This is Python 3.11 — use the modern union syntax (`str | None`).
- **No print statements.** Use the structured logger in `observability.py`.
- **Costs go through the tracker.** Every LLM call should record tokens + cost via `observability.track_llm_call(...)`. This is what makes the "production-grade" claim defensible.
- **Prompts live next to nodes.** Each node has its prompt(s) as a module-level constant at the top of the file. Don't scatter prompts.
- **No real PII.** If you're tempted to add a "demo user" with real-looking details, use Faker.
- **Tests for tools.** The mock booking API is tiny and pure — add unit tests for any new tool. The agent nodes are tested through the eval suite, not unit tests.

## When you finish work

Update the "File-by-file status" section above. The next session opens this file first.
