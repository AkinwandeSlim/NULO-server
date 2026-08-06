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

# Known Nigerian cities → the token we search city/state/location with.
# The alias map above handles neighbourhoods ("garki", "lekki", "ph"); this
# map is for CITY-level extraction used by the fallback search. Nigerian
# tenants rarely write clean "Neighbourhood, City" strings — they write
# "Ajah Lagos", "Badagry Lagos", "First Junction PH", "GRA, Portharcourt",
# "Portharcourt", "GRA Portharcourt", etc. We tokenise the raw location and
# look for the first token that names a city, then search by that.
_CITY_WORDS: dict[str, str] = {
    "lagos": "Lagos",
    "lagos island": "Lagos",
    "victoria island": "Victoria Island",
    "abuja": "Abuja",
    "fct": "Abuja",
    "port harcourt": "Port Harcourt",
    "portharcourt": "Port Harcourt",
    "ph": "Port Harcourt",
    "phc": "Port Harcourt",
    "p/h": "Port Harcourt",
    "rivers": "Port Harcourt",     # state containing Port Harcourt
    "enugu": "Enugu",
    "kano": "Kano",
    "ibadan": "Ibadan",
    "owerri": "Owerri",
    "benin": "Benin City",
    "abia": "Umuahia",
}

# Multi-word city names we must match as a phrase before falling back to
# single-word token matching (e.g. "Port Harcourt" would otherwise split).
_MULTI_WORD_CITIES = [
    "port harcourt",
    "lagos island",
    "victoria island",
    "benin city",
]


def _extract_city_token(location: str) -> str:
    """Pull the CITY out of a messy Nigerian location string.

    Examples:
      'Garki, Abuja'           -> 'Abuja'
      'Ajah, Lagos'            -> 'Lagos'
      'Ajah Lagos'             -> 'Lagos'
      'Badagry Lagos'          -> 'Lagos'
      'First Junction PH'      -> 'Port Harcourt'
      'GRA, Portharcourt'      -> 'Port Harcourt'
      'GRA Portharcourt'       -> 'Port Harcourt'
      'Portharcourt'           -> 'Port Harcourt'
      'Central Business District, Abuja' -> 'Abuja'
      'Wuse II, Abuja'         -> 'Abuja'
      'Lekki Phase 1'          -> 'Lekki'   (no city token -> keep neighbourhood)

    Falls back to the last comma-separated segment, else the last word, else
    the whole string — so we never return an empty token.
    """
    if not location:
        return location

    lowered = location.strip().lower()

    # 1. Multi-word city phrase check ("port harcourt" wins over 'harcourt')
    for phrase in _MULTI_WORD_CITIES:
        if phrase in lowered:
            return _CITY_WORDS[phrase]

    # 2. Tokenise on comma / slash / space and look for a single-word city
    tokens = re.split(r"[,\s/]+", lowered)
    for tok in tokens:
        if tok in _CITY_WORDS:
            return _CITY_WORDS[tok]

    # 3. No city token found — use the last comma-separated segment, else the
    #    last word (neighbourhood-level fallback, e.g. "Lekki Phase 1" -> "1"
    #    is useless, so prefer the first token of the last comma segment).
    if "," in location:
        candidate = location.split(",")[-1].strip()
    else:
        candidate = location
    return candidate


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

    Strategy — broader query with composite scoring rather than hard filter
    relaxation.  We fetch approved + vacant properties in the requested area
    and rank them by how well they match the tenant's stated intent:
      - exact bedroom match gets a large bonus
      - being within budget gets a bonus (closer to budget = better)
      - being over budget incurs a penalty proportional to the overrun
    This means the tenant always sees the *most relevant* properties even
    when no perfect match exists, rather than showing wildly mismatched
    listings that happen to be in the right neighbourhood.

    Falls back from neighbourhood → city if the location-specific query
    returns nothing, so "Lekki Phase 1" → "Lekki" → "Lagos".
    """
    try:
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        from app.config import settings
        url = settings.SUPABASE_URL
        key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_SERVICE_KEY
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    except Exception as exc:
        logger.error(f"[match_properties] Config load failed: {exc}")
        return []

    select_cols = (
        "id,title,location,city,state,price,beds,baths,"
        "property_type,images,landlord_id,payment_frequency,"
        "verification_status,status"
    )

    def _raw_query(loc_filter: str | None) -> list:
        """Fetch approved + vacant properties matching an optional location ILIKE."""
        params = (
            f"select={select_cols}"
            f"&verification_status=eq.approved"
            f"&status=eq.vacant"
            f"&deleted_at=is.null"
        )
        if loc_filter:
            params += f"&location=ilike.*{loc_filter}*"
        params += "&order=created_at.desc&limit=20"
        try:
            r = requests.get(
                f"{url}/rest/v1/properties?{params}",
                headers=headers, verify=False, timeout=10,
            )
            return r.json() if r.ok and r.json() else []
        except Exception as exc:
            logger.warning(f"[match_properties] REST query failed: {exc}")
            return []

    # ── Attempt 1: neighbourhood-level search ────────────────────────────────
    data = _raw_query(location)

    # ── Attempt 2: if location has a comma (e.g. "Lekki Phase 1, Lagos"),
    # try just the first token (e.g. "Lekki") ─────────────────────────────────
    if not data and location and "," in location:
        broader = location.split(",")[0].strip()
        logger.info(f"[match_properties] Narrowing location '{location}' -> '{broader}'")
        data = _raw_query(broader)

    # ── Attempt 3: try city-level if neighbourhood returned nothing ───────────
    # Extract the CITY token from a messy location string. The previous code
    # searched the full string (e.g. "Garki, Abuja" or "Ajah Lagos") against
    # city/location, which matched NOTHING because the DB stores city="Abuja"
    # / "Lagos" (never "Garki, Abuja" / "Ajah Lagos"). This is why "2-bed in
    # Garki, Abuja" returned zero even though Gwarinpa/Maitama/Wuse II 2-beds
    # exist — and why "Ajah Lagos", "First Junction PH", "GRA, Portharcourt"
    # all returned zero too.
    if not data and location:
        city_token = _extract_city_token(location)
        logger.info(f"[match_properties] City-level fallback for '{location}' -> city '{city_token}'")
        select_alt = select_cols.replace("location,city,state", "city,location,state")
        params = (
            f"select={select_alt}"
            f"&verification_status=eq.approved"
            f"&status=eq.vacant"
            f"&deleted_at=is.null"
            f"&or=(city.ilike.*{city_token}*,state.ilike.*{city_token}*,location.ilike.*{city_token}*)"
            f"&order=created_at.desc&limit=20"
        )
        try:
            r = requests.get(
                f"{url}/rest/v1/properties?{params}",
                headers=headers, verify=False, timeout=10,
            )
            data = r.json() if r.ok and r.json() else []
        except Exception as exc:
            logger.warning(f"[match_properties] City fallback failed: {exc}")

    if not data:
        return []

    # ── Composite scoring ──────────────────────────────────────────────────
    def _score(p: dict) -> float:
        s = 0.0

        # Bedroom match (biggest signal — most tenants have a hard requirement)
        p_beds = p.get("beds") or 0
        if bedrooms is not None:
            b_diff = abs(p_beds - bedrooms)
            if b_diff == 0:
                s += 100               # exact match
            elif b_diff == 1:
                s += 40                # close enough
            else:
                s -= 20 * (b_diff - 1)   # penalty per extra bedroom beyond 1-off

        # Price proximity
        p_price = p.get("price") or 0
        if budget_monthly is not None and p_price > 0:
            ratio = p_price / budget_monthly
            if ratio <= 1.0:
                # Within budget — closer to max budget = better value for landlord
                s += 50
                s += 20 * ratio          # prefer properties closer to stated budget
            else:
                # Over budget — penalty scales with overrun
                over_pct = ratio - 1.0
                if over_pct <= 0.2:
                    s += 10               # slight over budget, still acceptable
                else:
                    s -= 40 * over_pct    # steep penalty for way over budget

        return s

    scored = [(p, _score(p)) for p in data]
    scored.sort(key=lambda x: x[1], reverse=True)

    logger.info(
        f"[match_properties] {len(data)} candidates scored; best: "
        f"{scored[0][0].get('title','?')} ({scored[0][1]:.0f} pts)"
    )

    return [p for p, _ in scored[:_MAX_MATCHES]]
