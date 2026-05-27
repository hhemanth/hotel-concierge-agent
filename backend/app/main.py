"""FastAPI entry point for the Guest Concierge Agent.

Endpoints:
  GET  /healthz   - liveness probe
  POST /chat      - send a user message, get an agent reply (and cost/token stats)

Run locally:
  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agent.graph import build_graph
from app.agent.state import AgentState
from app.observability import configure_logging, logger, request_context

load_dotenv()


# ---------------------------------------------------------------------------
# Lifespan: build the graph once at startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("startup", event="building_graph")
    app.state.graph = build_graph()
    logger.info("startup", event="ready")
    yield
    logger.info("shutdown")


app = FastAPI(
    title="TFE Guest Concierge",
    description="Demo agent for hotel guest experience (synthetic data, mocked booking).",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., description="Full conversation history; last item must be a user turn.")
    session_id: str | None = Field(None, description="Stable id to persist booking state across turns.")


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    stats: dict
    booking_state: dict | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if not req.messages or req.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="Last message must be from the user.")

    session_id = req.session_id or "anon"
    with request_context() as stats:
        logger.info("chat_request", session_id=session_id, n_messages=len(req.messages))

        initial_state: AgentState = {
            "messages": [m.model_dump() for m in req.messages],
            "session_id": session_id,
            "retrieved_docs": [],
            "booking_in_progress": None,
            "intent": None,
            "response": None,
        }

        try:
            final_state = await app.state.graph.ainvoke(initial_state)
        except Exception as e:
            logger.exception("graph_invocation_failed", error=str(e))
            raise HTTPException(status_code=500, detail="Agent failure — check logs.")

        reply = final_state.get("response") or "Sorry, I couldn't put a reply together. Try rephrasing?"
        logger.info(
            "chat_response",
            session_id=session_id,
            intent=final_state.get("intent"),
            cost_usd=round(stats.total_cost_usd, 6),
            n_calls=len(stats.calls),
        )

        return ChatResponse(
            reply=reply,
            session_id=session_id,
            stats=stats.to_dict(),
            booking_state=final_state.get("booking_in_progress"),
        )
