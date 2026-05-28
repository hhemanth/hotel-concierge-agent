"""FastAPI entry point for the Guest Concierge Agent.

Endpoints:
  GET  /healthz   - liveness probe
  POST /chat      - SSE stream: token events, metadata event, [DONE]

SSE event format:
  data: {"type": "token",    "text": "..."}
  data: {"type": "metadata", "payload": {...}}
  data: [DONE]

Run locally:
  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
    logger.info("startup", phase="building_graph")
    app.state.graph = build_graph()
    logger.info("startup", phase="ready")
    yield
    logger.info("shutdown")


app = FastAPI(
    title="TFE Guest Concierge",
    description="Demo agent for hotel guest experience (synthetic data, mocked booking).",
    version="0.1.0",
    lifespan=lifespan,
)

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
    available_options: list[dict] = Field(default_factory=list, description="Hotel options from the previous turn, so selection ('Option 1') can be matched.")


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _stream_graph(
    graph,
    initial_state: AgentState,
    session_id: str,
    request_id: str,
) -> AsyncIterator[str]:
    """Drive the LangGraph graph and yield SSE data lines."""
    with request_context(request_id=request_id) as stats:
        logger.info("chat_request", session_id=session_id, n_messages=len(initial_state["messages"]))
        try:
            async for update in graph.astream(initial_state, stream_mode="updates"):
                # update: {node_name: state_delta}
                if "respond" not in update:
                    continue

                delta = update["respond"]
                reply = delta.get("response") or ""
                if reply:
                    yield _sse({"type": "token", "text": reply})

                metadata = delta.get("response_metadata") or {}
                yield _sse({"type": "metadata", "payload": metadata})

        except Exception as exc:
            logger.exception("graph_invocation_failed", error=str(exc))
            yield _sse({"type": "error", "message": "Agent failure — please try again."})

        finally:
            logger.info(
                "chat_response",
                session_id=session_id,
                cost_usd=round(stats.total_cost_usd, 6),
                n_calls=len(stats.calls),
            )

        yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    if not req.messages or req.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="Last message must be from the user.")

    session_id = req.session_id or "anon"
    request_id = uuid.uuid4().hex[:12]

    initial_state: AgentState = {
        "messages": [m.model_dump() for m in req.messages],
        "session_id": session_id,
        "retrieved_docs": [],
        "booking_in_progress": None,
        "intent": None,
        "response": None,
        "search_criteria": None,
        "available_options": req.available_options,
        "selected_option": None,
        "booking_result": None,
        "mentioned_properties": [],
        "response_metadata": None,
    }

    return StreamingResponse(
        _stream_graph(app.state.graph, initial_state, session_id, request_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
