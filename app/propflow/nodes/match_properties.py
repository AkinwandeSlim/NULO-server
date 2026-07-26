"""
PropFlow Node 2: Match Properties  (maps to "Inquiry Agent - property search" step)

Responsibility:
  Query Supabase for approved, active properties matching the tenant's
  extracted intent. Returns up to 3 ranked candidates and selects the
  best match as selected_property_id.

Query strategy:
  1. Hard filters  — only approved, not deleted, not occupied
  2. Soft filters  — location ILIKE, bedrooms EQ, price LTE (all optional;
                     missing intent fields are skipped so narrow queries
                     don't return zero results)
  3. Ranking       — closest price to budget (ascending), then newest first
  4. Selection     — first result becomes selected_property_id; all results
                     stored in property_matches for the chat response

Architecture note (Rule 6):
  Supabase Python client is synchronous. All calls run inside
  asyncio.get_event_loop().run_in_executor() to avoid blocking the event loop.
"""

import asyncio
import logging
import uuid
from typing import Optional

from app.propflow.state import PropFlowState
from app.propflow.config import propflow_settings

logger = logging.getLogger(__name__)

# ── Location alias map ────────────────────────────────────────────────────────
# Common abbreviations / slang for Nigerian cities & neighbourhoods.
# Qwen extracts what the user typed ("PH", "VI"), but the DB stores full names
# ("Port Harcourt", "Victoria Island"). Map known aliases here so ILIKE
# searches find the right properties.
_LOCATION_ALIASES: dict[str, str] = {
    "ph": "Port Harcourt",
    "phc": "Port Harcourt",
    "p/h": "Port Harcourt",
    "portharcourt": "Port Harcourt",
    "vi": "Victoria Island",
    "v.i": "Victoria Island",
    "ajah": "Ajah",
    "lekki": "Lekki",
    "ikeja": "Ikeja",
    "yaba": "Yaba",
    "surulere": "Surulere",
    "gwarinpa": "Gwarinpa",
    "wuse": "Wuse",
    "asokoro": "Asokoro",
    "maitama": "Maitama",
    "jabi": "Jabi",
    "garki": "Garki",
    "abuja": "Abuja",
    "lagos": "Lagos",
    "island": "Victoria Island",
    "mainland": "Lagos Mainland",
    "ikoyi": "Ikoyi",
    "banana island": "Banana Island",
    "chevron": "Lekki",
    "sangotedo": "Lekki",
    "eleko": "Lekki",
    "abraham adesanya": "Ajah",
    "badore": "Ajah",
    "ilara": "Lekki",
    "osapa": "Lekki",
    "lakowe": "Lekki",
}

# Properties per query — show tenant a shortlist, not a wall of listings
_MAX_MATCHES = 3


async def match_properties_node(state: PropFlowState) -> PropFlowState:
    """
    Node 2 — property search.

    Steps:
      1. Extract search criteria from extracted_intent
      2. Run Supabase query with progressive filter relaxation
      3. Rank results by price proximity to budget
      4. Store top 3 in property_matches, set selected_property_id + landlord_id

    Args:
        state: PropFlowState with extracted_intent populated

    Returns:
        Updated state with property_matches, selected_property_id,
        landlord_id, and current_stage
    """
    intent = state.get("extracted_intent") or {}

    location: Optional[str] = intent.get("location")
    # Resolve location alias so "PH" → "Port Harcourt", "VI" → "Victoria Island", etc.
    if location:
        alias = _LOCATION_ALIASES.get(location.strip().lower())
        if alias:
            logger.info(f"[match_properties] Resolved location alias '{location}' -> '{alias}'")
            location = alias

    bedrooms: Optional[int] = intent.get("bedrooms")
    budget_monthly: Optional[float] = (
        intent.get("budget_monthly")
        or (intent.get("budget_annual", 0) / 12 if intent.get("budget_annual") else None)
    )

    logger.info(
        f"[match_properties] searching: location={location} "
        f"bedrooms={bedrooms} budget_monthly={budget_monthly}"
    )

    try:
        matches = await _query_properties(location, bedrooms, budget_monthly)
    except Exception as exc:
        logger.error(f"[match_properties] Supabase query failed: {exc}")
        error_log = state.get("error_log", [])
        return {
            **state,
            "property_matches": [],
            "error_log": error_log + [f"match_properties: {exc}"],
            "current_stage": "no_properties_found",
        }

    if not matches:
        logger.warning(
            f"[match_properties] No properties found for "
            f"location={location} bedrooms={bedrooms} budget={budget_monthly}"
        )
        return {
            **state,
            "property_matches": [],
            "current_stage": "no_properties_found",
            "error_log": state.get("error_log", []) + [
                f"No approved properties found matching: "
                f"location={location}, bedrooms={bedrooms}, "
                f"budget_monthly={budget_monthly}"
            ],
        }

    logger.info(
        f"[match_properties] {len(matches)} match(es) found for tenant. "
        f"Waiting for tenant to select."
    )

    # Do NOT auto-select — tenant picks from the list.
    # The graph pauses at INTERRUPT #1 (before create_application)
    # until tenant calls POST /api/v1/propflow/select/{workflow_id}
    return {
        **state,
        "property_matches": matches,
        "selected_property_id": None,   # Set via /select endpoint
        "landlord_id": None,            # Set via /select endpoint
        "current_stage": "awaiting_tenant_selection",
    }


async def _query_properties(
    location: Optional[str],
    bedrooms: Optional[int],
    budget_monthly: Optional[float],
) -> list:
    """
    Run a Supabase query and return ranked property dicts.
    Uses progressive filter relaxation: if the full query returns nothing,
    drop bedrooms; if still nothing, drop price ceiling.
    """
    from app.database import supabase_admin

    loop = asyncio.get_event_loop()

    def _run(loc, beds, budget):
        q = (
            supabase_admin
            .table("properties")
            .select(
                "id, title, location, city, state, price, beds, baths, "
                "property_type, images, landlord_id, payment_frequency, "
                "verification_status, status"
            )
            # verification_status='approved' — admin has verified this property
            .eq("verification_status", "approved")
            # status='vacant' — property is listed and not yet rented
            # (matches the marketplace route filter in app/routes/properties.py)
            .eq("status", "vacant")
            .is_("deleted_at", "null")
        )

        if loc:
            # ILIKE matches partial location names: "Lekki" matches "Lekki Phase 1"
            q = q.ilike("location", f"%{loc}%")

        if beds is not None:
            q = q.eq("beds", beds)

        if budget is not None:
            # price column stores monthly rent as integer NGN
            q = q.lte("price", int(budget * 1.20))  # 20% buffer above stated max

        return q.order("price", desc=False).limit(_MAX_MATCHES).execute()

    # Attempt 1: all filters
    result = await loop.run_in_executor(None, lambda: _run(location, bedrooms, budget_monthly))
    data = result.data or []

    # Attempt 2: relax bedrooms if empty
    if not data and bedrooms is not None:
        logger.info("[match_properties] Relaxing bedrooms filter")
        result = await loop.run_in_executor(None, lambda: _run(location, None, budget_monthly))
        data = result.data or []

    # Attempt 3: relax price if still empty
    if not data and budget_monthly is not None:
        logger.info("[match_properties] Relaxing price filter")
        result = await loop.run_in_executor(None, lambda: _run(location, None, None))
        data = result.data or []

    if not data:
        return []

    # Rank by price proximity to stated budget (closer = better)
    if budget_monthly:
        data.sort(key=lambda p: abs(p.get("price", 0) - budget_monthly))

    return data[:_MAX_MATCHES]
