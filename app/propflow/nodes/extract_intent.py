"""
PropFlow Node 1: Extract Intent  (maps to "Inquiry Agent" in the PRD narrative)

Responsibility:
  Convert a raw tenant message (Nigerian Pidgin/English) into a structured
  JSON payload the rest of the state machine can act on.

Mem0 integration:
  READ  -- search tenant's past inquiries before calling Qwen, so the model
           has context about returning tenants ("last time they wanted VI,
           but now they're asking about Lekki -- budget probably same range")
  WRITE -- after successful extraction, store the confirmed preferences so
           future sessions start with richer context.

Confidence gate:
  extraction_confidence < INTENT_CONFIDENCE_THRESHOLD (0.7)
    -> current_stage = "needs_clarification"
    -> graph should route to a clarification response rather than continuing
  extraction_confidence >= 0.7
    -> current_stage = "intent_extracted"
    -> graph continues to match_properties
"""

import logging
from datetime import datetime
import asyncio
import time

from app.propflow.state import PropFlowState
from app.propflow.config import propflow_settings
from app.propflow.services.qwen_client import qwen_client
from app.propflow.services.mem0_client import mem0_service

logger = logging.getLogger(__name__)


def _fallback_extract_intent(text: str) -> dict:
    """
    Fast fallback intent extraction when Qwen is too slow (network issues).
    Uses regex to extract: location, bedrooms, budget.
    Confidence is 0.5 (low) to signal this is a fallback, not full extraction.
    """
    import re
    intent = {
        "property_type": None,
        "location": None,
        "bedrooms": None,
        "budget_monthly": None,
        "budget_annual": None,
        "move_in_date": None,
        "payment_frequency": None,
        "special_requests": [],
        "confidence": 0.5,  # Low confidence — fallback only
    }

    text_lower = text.lower()

    # Extract location: "in Lekki", "at Ajah", "VI", "Lagos"
    loc_match = re.search(r'(?:in|at|around)\s+([A-Za-z\s]+?)(?:\s+(?:for|with|budget|with|have)|\s*$)', text, re.I)
    if loc_match:
        intent["location"] = loc_match.group(1).strip()

    # Extract bedrooms: "2-bed", "2 bedroom", "3bed"
    bed_match = re.search(r'(\d+)\s*(?:bed|bedroom|br)', text, re.I)
    if bed_match:
        intent["bedrooms"] = int(bed_match.group(1))

    # Extract budget: "500k", "500,000", "1m"
    budget_match = re.search(r'(\d+(?:[,.]?\d+)?)\s*([km]?)', text, re.I)
    if budget_match:
        amount_str = budget_match.group(1).replace(',', '')
        multiplier = budget_match.group(2).lower()
        try:
            amount = float(amount_str)
            if multiplier == 'k':
                amount *= 1000
            elif multiplier == 'm':
                amount *= 1_000_000
            intent["budget_monthly"] = amount
        except (ValueError, TypeError):
            pass

    logger.info(f"[extract_intent] Fallback extraction: {intent}")
    return intent



async def extract_intent_node(state: PropFlowState) -> PropFlowState:
    """
    Node 1 — Inquiry Agent.

    Steps:
      1. Search Mem0 for prior memories about this tenant (read)
      2. Call Qwen to extract structured intent, injecting memory context
      3. Apply confidence gate
      4. Write confirmed preferences back to Mem0 (write)
      5. Return updated state

    Args:
        state: PropFlowState with raw_inquiry_text and tenant_id populated

    Returns:
        Updated state with extracted_intent, extraction_confidence,
        prior_tenant_memories, is_returning_tenant, and current_stage
    """
    tenant_id = str(state["tenant_id"])
    raw_text = state["raw_inquiry_text"]

    logger.info(
        f"[extract_intent] tenant={tenant_id[:8]}... "
        f"text='{raw_text[:80]}...'"
    )

    # ── Step 1: Mem0 read -- prior tenant context ─────────────────────────────
    prior_memories = mem0_service.search_tenant_memories(
        tenant_id=tenant_id,
        query=raw_text,
        limit=5,
    )
    is_returning = len(prior_memories) > 0

    if is_returning:
        logger.info(
            f"[extract_intent] Returning tenant detected -- "
            f"{len(prior_memories)} prior memories found"
        )
    else:
        logger.info("[extract_intent] First-time tenant -- no prior memories")

    # ── Step 2: Qwen intent extraction ───────────────────────────────────────
    # Pass this thread's transcript so a follow-up message resolves against what
    # the tenant asked earlier (conversational refinement, e.g. budget/area).
    # The last history entry is the CURRENT message (raw_inquiry_text) — strip it
    # so Qwen only sees prior turns and the live message as the "latest".
    history = list(state.get("conversation_history") or [])
    if history and history[-1].get("role") == "user":
        history = history[:-1]

    logger.info(f"[extract_intent] Starting Qwen intent extraction...")
    start_qwen = time.time()
    try:
        extracted_intent = await asyncio.wait_for(
            qwen_client.extract_intent(
                text=raw_text,
                prior_memories=prior_memories,
                conversation_history=history or None,
            ),
            timeout=45.0  # Timeout after 45s to leave room for rest of graph
        )
        elapsed_qwen = time.time() - start_qwen
        logger.info(f"[extract_intent] Qwen extraction completed in {elapsed_qwen:.1f}s")
    except asyncio.TimeoutError:
        elapsed_qwen = time.time() - start_qwen
        logger.error(f"[extract_intent] Qwen extraction timed out after {elapsed_qwen:.1f}s — using fallback")
        # Fallback: use regex-based intent extraction if Qwen is too slow
        extracted_intent = _fallback_extract_intent(raw_text)

    confidence = float(extracted_intent.get("confidence", 0.0))

    # ── Step 3: Confidence gate ───────────────────────────────────────────────
    threshold = propflow_settings.INTENT_CONFIDENCE_THRESHOLD

    if confidence < threshold:
        logger.warning(
            f"[extract_intent] Low confidence ({confidence:.2f} < {threshold}) "
            f"-- routing to clarification"
        )
        # Do NOT write to Mem0 -- unconfirmed extraction should not pollute memory
        return {
            **state,
            "extracted_intent": extracted_intent,
            "extraction_confidence": confidence,
            "prior_tenant_memories": prior_memories,
            "is_returning_tenant": is_returning,
            "current_stage": "needs_clarification",
            "error_log": state.get("error_log", []) + [
                f"Low confidence intent extraction: {confidence:.2f}. "
                f"Tenant message may be ambiguous."
            ],
        }

    # ── Step 4: Mem0 write -- store confirmed preferences ────────────────────
    # Build a concise, factual memory string that's useful in future sessions
    memory_parts = []

    if extracted_intent.get("property_type"):
        memory_parts.append(f"prefers {extracted_intent['property_type']}")
    if extracted_intent.get("location"):
        memory_parts.append(f"in {extracted_intent['location']}")
    if extracted_intent.get("bedrooms"):
        memory_parts.append(f"{extracted_intent['bedrooms']} bedroom(s)")
    if extracted_intent.get("budget_monthly"):
        try:
            budget_str = f"NGN {float(extracted_intent['budget_monthly']):,.0f}/month"
        except (TypeError, ValueError):
            budget_str = f"NGN {extracted_intent['budget_monthly']}/month"
        memory_parts.append(f"budget {budget_str}")
    if extracted_intent.get("payment_frequency"):
        memory_parts.append(
            f"payment preference: {extracted_intent['payment_frequency'].lower()}"
        )
    if extracted_intent.get("move_in_date"):
        memory_parts.append(f"wants to move in by {extracted_intent['move_in_date']}")

    if memory_parts:
        memory_content = (
            f"Tenant inquiry on {datetime.utcnow().strftime('%Y-%m-%d')}: "
            f"Tenant {', '.join(memory_parts)}."
        )
        mem0_service.add_tenant_memory(
            tenant_id=tenant_id,
            content=memory_content,
            metadata={
                "workflow_id": state["workflow_id"],
                "stage": "intent_extracted",
                "confidence": confidence,
            },
        )

    logger.info(
        f"[extract_intent] Success -- location={extracted_intent.get('location')} "
        f"bedrooms={extracted_intent.get('bedrooms')} "
        f"budget_monthly={extracted_intent.get('budget_monthly')} "
        f"confidence={confidence:.2f}"
    )

    return {
        **state,
        "extracted_intent": extracted_intent,
        "extraction_confidence": confidence,
        "prior_tenant_memories": prior_memories,
        "is_returning_tenant": is_returning,
        "current_stage": "intent_extracted",
    }
