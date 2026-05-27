"""LangGraph wiring for the Guest Concierge Agent.

Topology:
    START → router → (info → retrieve → respond)
                  → (booking → extract_params → booking_step → respond)
                  → (smalltalk → respond)
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import booking, extract_params, respond, retrieve, router
from app.agent.state import AgentState


def _route_after_router(state: AgentState) -> Literal["retrieve", "extract_params", "respond"]:
    intent = state.get("intent")
    if intent == "info":
        return "retrieve"
    if intent == "booking":
        return "extract_params"
    return "respond"  # smalltalk / unknown — bypass tooling


def _route_after_extract(state: AgentState) -> Literal["booking_step", "respond"]:
    """Route after parameter extraction.

    - search mode: always route to booking_step (it will handle the vague query).
    - direct mode: route to booking_step only when all four required params are present;
                   otherwise route to respond so the agent can ask for missing info.
    """
    booking_state = state.get("booking_in_progress") or {}
    mode = (state.get("search_criteria") or {}).get("mode", "direct")

    if mode == "search":
        return "booking_step"

    # Direct mode: all four fields required
    required = ("city", "check_in", "check_out", "guests")
    if all(booking_state.get(k) for k in required):
        return "booking_step"

    return "respond"  # missing info — ask the user


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("router", router.run)
    g.add_node("retrieve", retrieve.run)
    g.add_node("extract_params", extract_params.run)
    g.add_node("booking_step", booking.run)
    g.add_node("respond", respond.run)

    g.add_edge(START, "router")

    g.add_conditional_edges(
        "router",
        _route_after_router,
        {"retrieve": "retrieve", "extract_params": "extract_params", "respond": "respond"},
    )

    g.add_edge("retrieve", "respond")

    g.add_conditional_edges(
        "extract_params",
        _route_after_extract,
        {"booking_step": "booking_step", "respond": "respond"},
    )

    g.add_edge("booking_step", "respond")
    g.add_edge("respond", END)

    return g.compile()
