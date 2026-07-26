"""
PropFlow State Machine Graph
LangGraph-based deterministic orchestrator for rental marketplace operations.

Graph Topology (with human-in-the-loop checkpoints):

  [START]
     │
     ▼
  extract_intent          ← Qwen: Pidgin/English → structured JSON
     │
     ├─ (needs_clarification) ──► [END]   ← low-confidence: ask tenant to clarify
     │
     ▼
  match_properties        ← Supabase: find candidate properties
     │
     ├─ (no_properties_found) ──► [END]   ← no matches: inform tenant
     │
     ▼
  create_application      ← Supabase: INSERT applications (status=submitted)
     │
     ▼
  enrich_and_qualify      ← Qwen: generate landlord briefing
     │
     ▼
  [INTERRUPT #1]          ← Human checkpoint: landlord approves/rejects
     │  (resumes with application_status=approved|rejected)
     ▼
  create_agreement        ← Supabase: INSERT agreements (status=PENDING_TENANT)
     │
     ├─ (rejected) ──► [END]   ← clean terminal for rejected applications
     │
     ▼
  [INTERRUPT #2]          ← Human checkpoint: tenant signs lease
     │  (resumes with agreement_status=SIGNED)
     ▼
  provision_nomba_dva     ← Nomba API: create DVA for this agreement
     │
     ├─ (dva_provisioning_failed) ──► [END]
     │
     ▼
  disburse_landlord       ← Nomba API: Path B transfer to landlord bank
     │
     ▼
  [END]
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy singleton — avoids crashing the FastAPI process at import time when
# langgraph is not yet installed (e.g. fresh virtualenv before pip install).
# ---------------------------------------------------------------------------

_graph_instance = None


def get_propflow_graph():
    """
    Return the compiled PropFlow graph, creating it on first call.

    Using a lazy singleton means:
    1. FastAPI startup won't fail if langgraph is missing.
    2. The graph is only built once per process (same as a module-level var).
    3. Tests can call this safely without side-effects on import.
    """
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = _build_graph()
    return _graph_instance


def _route_after_intent(state: dict) -> str:
    """
    Conditional edge after extract_intent.
    Low-confidence extraction must NOT continue to property matching.
    """
    stage = state.get("current_stage", "")
    if stage == "needs_clarification":
        return "end_clarification"
    return "match_properties"


def _route_after_match(state: dict) -> str:
    """
    Conditional edge after match_properties.
    No properties found must NOT continue to application creation.
    """
    stage = state.get("current_stage", "")
    if stage == "no_properties_found":
        return "end_no_properties"
    return "create_application"


def _route_after_agreement(state: dict) -> str:
    """
    Conditional edge after create_agreement (INTERRUPT #1 / INTERRUPT #2).
    Rejected applications must NOT proceed to DVA provisioning.
    """
    stage = state.get("current_stage", "")
    if stage == "rejected":
        return "end_rejected"
    return "provision_nomba_dva"


def _route_after_provision(state: dict) -> str:
    """
    Conditional edge after provision_nomba_dva.
    DVA provisioning failure must NOT attempt disbursement.
    """
    stage = state.get("current_stage", "")
    if stage == "dva_provisioning_failed":
        return "end_dva_failed"
    return "disburse_landlord"


def _build_graph():
    """Construct and compile the LangGraph state machine."""
    try:
        from langgraph.graph import StateGraph, END
    except ImportError as e:
        raise RuntimeError(
            "langgraph is not installed. Run: pip install langgraph>=0.2.0"
        ) from e

    from app.propflow.checkpointer import get_checkpointer

    from app.propflow.state import PropFlowState
    from app.propflow.nodes.extract_intent import extract_intent_node
    from app.propflow.nodes.match_properties import match_properties_node
    from app.propflow.nodes.create_application import create_application_node
    from app.propflow.nodes.enrich_qualify import enrich_and_qualify_node
    from app.propflow.nodes.create_agreement import create_agreement_node
    from app.propflow.nodes.provision_nomba import provision_nomba_dva_node
    from app.propflow.nodes.disburse_landlord import disburse_landlord_node

    workflow = StateGraph(PropFlowState)

    # ── Nodes ────────────────────────────────────────────────────────────────
    workflow.add_node("extract_intent",      extract_intent_node)
    workflow.add_node("match_properties",    match_properties_node)
    workflow.add_node("create_application",  create_application_node)
    workflow.add_node("enrich_and_qualify",  enrich_and_qualify_node)
    # INTERRUPT #1 sits between enrich_and_qualify and create_agreement.
    # Resumes via POST /api/v1/propflow/resume/{thread_id} with decision=approved.
    workflow.add_node("create_agreement",    create_agreement_node)
    # INTERRUPT #2 sits between create_agreement and provision_nomba_dva.
    # Resumes via POST /api/v1/propflow/resume/{thread_id} with decision=signed.
    workflow.add_node("provision_nomba_dva", provision_nomba_dva_node)
    workflow.add_node("disburse_landlord",   disburse_landlord_node)

    # ── Entry point ───────────────────────────────────────────────────────────
    workflow.set_entry_point("extract_intent")

    # ── Conditional edge: intent → match or END (clarification needed) ────────
    workflow.add_conditional_edges(
        "extract_intent",
        _route_after_intent,
        {
            "match_properties":   "match_properties",
            "end_clarification":  END,
        },
    )

    # ── Conditional edge: match → create_app or END (no properties) ───────────
    workflow.add_conditional_edges(
        "match_properties",
        _route_after_match,
        {
            "create_application":  "create_application",
            "end_no_properties":   END,
        },
    )

    # ── Linear edges up to INTERRUPT #1 ──────────────────────────────────────
    workflow.add_edge("create_application", "enrich_and_qualify")
    # Graph pauses HERE (interrupt_before create_agreement).
    # Landlord must approve before proceeding.
    workflow.add_edge("enrich_and_qualify", "create_agreement")

    # ── Conditional edge: create_agreement → provision_nomba_dva or END (rejected) ─
    # INTERRUPT #2: Graph pauses before provision_nomba_dva (tenant must sign).
    # If the application was rejected, the graph terminates cleanly at END instead
    # of proceeding to Nomba DVA provisioning.
    workflow.add_conditional_edges(
        "create_agreement",
        _route_after_agreement,
        {
            "provision_nomba_dva": "provision_nomba_dva",
            "end_rejected":        END,
        },
    )

    # ── Conditional edge: provision → disburse or END (DVA failed) ───────────
    workflow.add_conditional_edges(
        "provision_nomba_dva",
        _route_after_provision,
        {
            "disburse_landlord": "disburse_landlord",
            "end_dva_failed":    END,
        },
    )

    workflow.add_edge("disburse_landlord", END)

    # ── Interrupt checkpoints ─────────────────────────────────────────────────
    # interrupt_before tells LangGraph to pause BEFORE executing these nodes
    # and yield control back to the caller. The thread_id is stored in the
    # checkpointer (Postgres-backed in production, MemorySaver fallback in
    # development) so the workflow can be resumed via graph.ainvoke(
    #   None, config={"configurable": {"thread_id": thread_id}}
    # )
    checkpointer = get_checkpointer()
    compiled = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=[
            "create_application",     # INTERRUPT #1: tenant selects a property
            "create_agreement",       # INTERRUPT #2: landlord approval
            "provision_nomba_dva",    # INTERRUPT #3: tenant signs lease
            "disburse_landlord",      # INTERRUPT #4: landlord confirms payment received
        ],
    )

    logger.info("PropFlow graph compiled successfully with 4 interrupt checkpoints")
    return compiled


# ---------------------------------------------------------------------------
# Convenience wrapper — keeps call-sites clean.
# ---------------------------------------------------------------------------

def propflow_graph():
    """Alias for get_propflow_graph(). Returns the compiled singleton."""
    return get_propflow_graph()
