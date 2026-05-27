"""Retrieve node: pull relevant chunks from the vector store for the
user's latest question.

STUB — wire to `app.rag.retriever.search()` once that's implemented.
"""

from __future__ import annotations

from app.agent.state import AgentState, RetrievedDoc
from app.observability import logger
from app.rag.retriever import search


async def run(state: AgentState) -> dict:
    messages = state.get("messages", [])
    if not messages:
        return {"retrieved_docs": []}

    query = messages[-1]["content"]
    try:
        docs: list[RetrievedDoc] = await search(query, top_k=5)
    except Exception as e:
        # If pgvector isn't set up yet, don't fail the request — return empty
        # and let the respond node either ask a follow-up or apologise.
        logger.warning("retrieve_failed", error=str(e))
        docs = []

    logger.info("retrieved", n=len(docs), query=query[:80])
    return {"retrieved_docs": docs}
