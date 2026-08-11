"""
PropFlow Node 4: Enrich and Qualify  (maps to "Screening Agent" in the PRD narrative)

Responsibility:
  1. Fetch full tenant profile and property details from Supabase
  2. Retrieve landlord preferences from Mem0
  3. Call Qwen to generate a personalised 3-sentence landlord briefing
  4. Write the briefing to the applications table (landlord_briefing column)
  5. Write the screening outcome to Mem0 for both tenant and landlord namespaces
  6. Advance state to "awaiting_landlord_approval" (triggers INTERRUPT #1)

Mem0 integration:
  READ  landlord preferences (does this landlord favour employed tenants?
        have they rejected similar profiles before?)
  WRITE tenant screening outcome ("Tenant passed screening on DATE for
        PROPERTY, application ID = UUID")
  WRITE landlord behaviour ("Landlord received briefing for 2-bed Lekki
        tenant, quarterly payment preference, DATE")

The briefing written here is what the landlord sees in their push notification
and dashboard before they click Approve / Reject.
"""

import asyncio
import logging
from datetime import datetime

from app.propflow.state import PropFlowState
from app.propflow.services.mem0_client import mem0_service
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


async def enrich_and_qualify_node(state: PropFlowState) -> PropFlowState:
    """
    Node 4 -- Screening Agent.

    Steps:
      1. Fetch tenant profile + property details from Supabase (parallel)
      2. Search Mem0 for landlord preferences (read)
      3. Call Qwen to generate the landlord briefing (uses all context)
      4. Write briefing to applications table
      5. Write memories to Mem0 for both tenant and landlord namespaces
      6. Return state with landlord_briefing and current_stage set

    Args:
        state: PropFlowState with application_id, selected_property_id,
               tenant_id, landlord_id, extracted_intent populated

    Returns:
        Updated state with landlord_briefing, prior_landlord_memories,
        and current_stage = "awaiting_landlord_approval"
    """
    application_id = state.get("application_id")
    property_id = state.get("selected_property_id")
    tenant_id = str(state["tenant_id"])
    landlord_id = str(state.get("landlord_id", ""))

    logger.info(
        f"[enrich_qualify] application={str(application_id)[:8] if application_id else 'None'}... "
        f"tenant={tenant_id[:8]}..."
    )

    # ── Step 1: Fetch tenant + property data (run in parallel) ───────────────
    tenant_data, property_data = await asyncio.gather(
        _fetch_tenant_profile(tenant_id),
        _fetch_property_details(str(property_id) if property_id else None),
    )

    # ── Step 2: Mem0 read -- landlord preferences ────────────────────────────
    prior_landlord_memories = []
    if landlord_id:
        query = (
            f"tenant application {state['extracted_intent'].get('property_type', '')} "
            f"{state['extracted_intent'].get('location', '')} "
            f"{state['extracted_intent'].get('payment_frequency', '')}"
        )
        prior_landlord_memories = (
            await _run_mem0(
                mem0_service.search_landlord_memories,
                landlord_id=landlord_id,
                query=query,
                limit=5,
            )
            or []
        )
        if prior_landlord_memories:
            logger.info(
                f"[enrich_qualify] {len(prior_landlord_memories)} landlord "
                f"preference memories found"
            )

    # ── Step 3: Deterministic, evidence-only briefing ─────────────────────────
    # Trust Passport v1.1: the briefing is built from facts the tenant actually
    # provided (no Qwen prose, so nothing can be hallucinated). It states only
    # what is present and explicitly lists the gaps.
    trust_status = {
        "documents": state.get("document_verification_status") or {},
        "references": state.get("reference_verification_status") or {},
    }

    briefing = _build_landlord_briefing(
        tenant_data=tenant_data,
        property_data=property_data,
        intent=state.get("extracted_intent") or {},
        trust_fields=_collect_trust_fields(state),
        trust_status=trust_status,
    )

    logger.info(f"[enrich_qualify] Briefing generated: '{briefing[:80]}...'")

    # ── Step 4: Write briefing to applications table ──────────────────────────
    if application_id:
        await _update_application_briefing(str(application_id), briefing)

    # ── Step 5: Fire-and-forget post-submit side effects ──────────────────────
    # The tenant's "submitted" response must NOT wait for the landlord
    # notification (email + SMS go through external providers) or Mem0 writes.
    # The essential work — application row + briefing written to the DB — is
    # already done above. Launch the rest in the background; every step is
    # individually time-capped and non-fatal. (The landlord still sees the
    # application in their dashboard either way — the notification is a nudge.)
    _spawn_background(
        _run_post_submit_side_effects(
            tenant_id=tenant_id,
            landlord_id=landlord_id,
            application_id=application_id,
            property_id=property_id,
            property_data=property_data,
            tenant_data=tenant_data,
            state=dict(state),
        )
    )

    return {
        **state,
        "landlord_briefing": briefing,
        "prior_landlord_memories": prior_landlord_memories,
        "current_stage": "awaiting_landlord_approval",
    }


# ── Background post-submit side effects ───────────────────────────────────────

def _spawn_background(coro) -> None:
    """
    Schedule a coroutine to run AFTER the submit response is returned.

    The task is owned by the event loop (not awaited here), so a slow SMTP/SMS
    provider can never delay the tenant. Its exceptions are consumed by the
    done-callback so a failure can't crash the loop or raise
    "Task exception was never retrieved".
    """
    task = asyncio.create_task(coro)
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


async def _run_post_submit_side_effects(
    *,
    tenant_id: str,
    landlord_id: str,
    application_id,
    property_id,
    property_data: dict,
    tenant_data: dict,
    state: dict,
) -> None:
    """
    Mem0 writes + landlord notification, run after the tenant's submit response.

    Kept OFF the critical path on purpose — the tenant shouldn't wait for email
    or SMS to go out. Best-effort: every step is individually caught and
    time-capped, and failures are logged, never fatal.
    """
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")

        # Tenant namespace: record that screening completed for this property
        await _run_mem0(
            mem0_service.add_tenant_memory,
            tenant_id=tenant_id,
            content=(
                f"Application submitted on {today} for "
                f"{property_data.get('title', 'a property')} "
                f"in {property_data.get('location', '')}. "
                f"Landlord briefing generated. Awaiting landlord approval."
            ),
            metadata={
                "workflow_id": state.get("workflow_id"),
                "stage": "awaiting_landlord_approval",
                "application_id": str(application_id) if application_id else None,
            },
        )

        # Landlord namespace: record that a briefing was sent for this tenant profile
        if landlord_id:
            intent = state.get("extracted_intent") or {}
            budget_val = intent.get('budget_monthly', 0)
            try:
                budget_display = f"at NGN {float(budget_val):,.0f}/month"
            except (TypeError, ValueError):
                budget_display = f"at NGN {budget_val}/month"
            await _run_mem0(
                mem0_service.add_landlord_memory,
                landlord_id=landlord_id,
                content=(
                    f"Received application on {today}: "
                    f"{tenant_data.get('full_name', 'a tenant')} "
                    f"for {property_data.get('title', 'property')}, "
                    f"requesting {intent.get('bedrooms', '?')}-bed "
                    f"{intent.get('property_type', 'unit')} "
                    f"{budget_display}, "
                    f"payment preference: {(intent.get('payment_frequency') or 'not specified').lower()}."
                ),
                metadata={
                    "workflow_id": state.get("workflow_id"),
                    "stage": "briefing_sent",
                    "application_id": str(application_id) if application_id else None,
                },
            )

        # Landlord notification (email + SMS + in-app). Capped so a stuck
        # SMTP/SMS provider can't keep the background task alive forever.
        if landlord_id and application_id and property_data:
            notif_service = NotificationService()
            await asyncio.wait_for(
                notif_service.notify_application_submitted(
                    application_id=str(application_id),
                    property_id=str(property_id) if property_id else "",
                    property_title=property_data.get("title", "Property"),
                    tenant_id=tenant_id,
                    tenant_name=tenant_data.get("full_name", "Applicant"),
                    tenant_email=tenant_data.get("email"),
                    # Prefer the phone the tenant typed on the card (Google OAuth
                    # users have none on their profile) — the landlord needs a
                    # reachable number.
                    tenant_phone=state.get("trust_phone_number") or tenant_data.get("phone_number"),
                    landlord_id=landlord_id,
                    landlord_name="",  # fetched internally by notification service
                    landlord_email=None,
                    landlord_phone=None,
                    # Trust Passport v1.1: reflect what the tenant actually chose
                    # (falls back to the profile only when the card left it blank).
                    monthly_income=state.get("trust_monthly_income") or tenant_data.get("monthly_income"),
                    employment_status=state.get("trust_employment_status") or tenant_data.get("occupation"),
                    propflow_thread_id=state.get("workflow_id"),
                ),
                timeout=20,
            )
            logger.info(
                f"[enrich_qualify] Notification sent to landlord {landlord_id[:8]}... "
                f"for application {str(application_id)[:8]}..."
            )
    except Exception as exc:
        logger.warning(f"[enrich_qualify] Post-submit side effects failed (non-fatal): {exc}")


# ── Mem0 execution helper ────────────────────────────────────────────────────

async def _run_mem0(fn, *args, timeout: float = 10, **kwargs):
    """
    Run a synchronous Mem0 call off the event loop with a hard timeout.

    Mem0 (local chroma + Qwen embedder) makes blocking network calls; if the
    embedder is slow or unresponsive it would otherwise freeze the whole resume
    and blow past the client's submit timeout. Non-fatal by design — returns
    None on any failure and callers degrade gracefully (memory is best-effort).
    """
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: fn(*args, **kwargs)),
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning(f"[enrich_qualify] Mem0 call timed out/failed (non-fatal): {exc}")
        return None


# ── Trust status helper ──────────────────────────────────────────────────────

def _build_trust_line(trust_status: dict) -> str:
    """
    Build a deterministic "Trust status: …" line from the evidenced status maps.

    The maps are keyed by storage path (documents) and reference key
    (references). We summarize by counting statuses so the line never invents a
    label or claims more than is evidenced. Statuses are exactly what the
    Trust Passport recorded: 'provided' (uploaded), 'verified' (independently
    validated), 'confirmed' (reference responded).
    """
    docs = trust_status.get("documents") or {}
    refs = trust_status.get("references") or {}

    parts = []
    if docs:
        provided = sum(1 for s in docs.values() if s == "provided")
        verified = sum(1 for s in docs.values() if s == "verified")
        confirmed = sum(1 for s in docs.values() if s == "confirmed")
        bits = [f"{provided} provided"] if provided else []
        if verified:
            bits.append(f"{verified} verified")
        if confirmed:
            bits.append(f"{confirmed} confirmed")
        if bits:
            parts.append(f"Identity & income evidence: {', '.join(bits)}")

    if refs:
        supplied = len(refs)
        confirmed = sum(1 for s in refs.values() if s == "confirmed")
        ref_line = f"{supplied} supplied"
        if confirmed:
            ref_line += f", {confirmed} confirmed"
        parts.append(f"References: {ref_line}")

    return "Trust status: " + " · ".join(parts) if parts else ""


# ── Deterministic briefing builders ──────────────────────────────────────────

def _collect_trust_fields(state: PropFlowState) -> dict:
    """Pull the tenant's Trust Passport answers out of state for the briefing."""
    return {
        "employment_status": state.get("trust_employment_status"),
        "employer_name": state.get("trust_employer_name"),
        "monthly_income": state.get("trust_monthly_income"),
        "move_in_date": state.get("trust_move_in_date"),
        "lease_duration": state.get("trust_lease_duration"),
        "number_of_occupants": state.get("trust_number_of_occupants"),
        "has_pets": state.get("trust_has_pets"),
        "pet_details": state.get("trust_pet_details"),
    }


def _build_landlord_briefing(
    *,
    tenant_data: dict,
    property_data: dict,
    intent: dict,
    trust_fields: dict,
    trust_status: dict,
) -> str:
    """
    Deterministic, evidence-only landlord briefing.

    Assembles ONLY facts that are present in the application/state. If a key
    trust signal is missing (employment, income, move-in date) it is listed in
    a closing "Not provided" line rather than guessed. No generative model is
    involved, so the landlord can rely on every line being verifiable.
    """
    name = tenant_data.get("full_name") or "The applicant"
    prop_title = property_data.get("title") or "the property"
    location = property_data.get("location") or ""
    price = property_data.get("price") or 0

    header = f"{name} applied for {prop_title}"
    if location:
        header += f" in {location}"
    if price:
        header += f" ({_fmt_ngn(price)}/month)"
    header += "."

    facts = []

    # What the tenant asked for in chat (from the real conversation, not invented).
    requested = []
    if intent.get("bedrooms"):
        requested.append(f"{intent['bedrooms']}-bed")
    if intent.get("property_type"):
        requested.append(str(intent["property_type"]))
    if intent.get("location"):
        requested.append(f"in {intent['location']}")
    if requested:
        facts.append("Requested: " + " ".join(requested))

    # Employment & income — only what the tenant actually chose.
    emp = trust_fields.get("employment_status")
    employer = trust_fields.get("employer_name")
    income = trust_fields.get("monthly_income")
    if emp:
        label = str(emp).replace("-", " ").title()
        if employer:
            label += f" at {employer}"
        facts.append(f"Employment: {label}")
    if income:
        txt = f"Income: {_fmt_ngn(income)}"
        if price:
            txt += f" ({float(income) / float(price):.1f}x monthly rent)"
        facts.append(txt)

    # Tenancy details.
    tenancy = []
    move_in = trust_fields.get("move_in_date")
    if move_in:
        try:
            move_txt = datetime.strptime(str(move_in), "%Y-%m-%d").strftime("%d %b %Y")
        except (TypeError, ValueError):
            move_txt = str(move_in)
        tenancy.append(f"move-in {move_txt}")
    if trust_fields.get("lease_duration"):
        tenancy.append(f"{trust_fields['lease_duration']} lease")
    if trust_fields.get("number_of_occupants"):
        tenancy.append(f"{trust_fields['number_of_occupants']} occupant(s)")
    if trust_fields.get("has_pets"):
        pet_details = trust_fields.get("pet_details")
        tenancy.append(f"pets: {pet_details or 'yes'}")
    if tenancy:
        facts.append("Tenancy: " + ", ".join(tenancy))

    trust_line = _build_trust_line(trust_status)
    if trust_line:
        facts.append(trust_line)

    parts = [header]
    if facts:
        parts.append("What we know: " + " · ".join(facts))
    else:
        parts.append("No additional details were provided by the tenant.")

    # Honest gaps — never guess.
    missing = []
    if not emp:
        missing.append("employment status")
    if not income:
        missing.append("income")
    if not move_in:
        missing.append("move-in date")
    if missing:
        parts.append(f"Not provided by tenant: {', '.join(missing)}.")

    return "\n".join(parts)


def _fmt_ngn(value) -> str:
    """Format a value as NGN, safe against non-numeric input."""
    try:
        return f"NGN {float(value):,.0f}"
    except (TypeError, ValueError):
        return f"NGN {value}"


# ── Supabase helper functions ─────────────────────────────────────────────────
# These use asyncio.get_event_loop().run_in_executor() per Architecture Rule #6:
# "All Supabase calls in async FastAPI routes must use run_in_executor()"
# The Supabase Python client is synchronous -- calling it directly blocks the loop.

async def _fetch_tenant_profile(tenant_id: str) -> dict:
    """Fetch tenant profile via REST (requests+verify=False — avoids Windows socket issues with supabase-py).

    Returns safe defaults on failure so the workflow continues even if Supabase is flaky.
    """
    try:
        import os, requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        from app.config import settings
        url = settings.SUPABASE_URL
        key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_SERVICE_KEY
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}

        # users table
        ru = requests.get(f"{url}/rest/v1/users?id=eq.{tenant_id}&select=id,full_name,email,phone_number",
                          headers=headers, verify=False, timeout=10)
        user_data = ru.json()[0] if ru.ok and ru.json() else {}

        # tenant_profiles (columns confirmed to exist)
        rp = requests.get(f"{url}/rest/v1/tenant_profiles?id=eq.{tenant_id}&select=employment_status,company_name,job_title,monthly_income_range",
                          headers=headers, verify=False, timeout=10)
        profile_data = rp.json()[0] if rp.ok and rp.json() else {}

        return {
            "id": tenant_id,
            "full_name": user_data.get("full_name", "Applicant"),
            "email": user_data.get("email", ""),
            "phone_number": user_data.get("phone_number", ""),
            "occupation": profile_data.get("job_title") or profile_data.get("employment_status", ""),
            "employer": profile_data.get("company_name", ""),
            "monthly_income": profile_data.get("monthly_income_range", ""),
        }
    except Exception as exc:
        logger.warning(f"[enrich_qualify] tenant profile fetch failed: {exc}")

    return {"id": tenant_id, "full_name": "Applicant", "email": ""}


async def _fetch_property_details(property_id: str | None) -> dict:
    """Fetch property details via REST. Safe fallback on failure."""
    if not property_id:
        return {"title": "Listed property", "location": "", "price": 0}
    try:
        import os, requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        from app.config import settings
        url = settings.SUPABASE_URL
        key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_SERVICE_KEY
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}

        r = requests.get(f"{url}/rest/v1/properties?id=eq.{property_id}&select=id,title,location,price,beds,property_type,landlord_id",
                         headers=headers, verify=False, timeout=10)
        if r.ok and r.json():
            data = r.json()[0]
            data["bedrooms"] = data.pop("beds", None)
            return data
    except Exception as exc:
        logger.warning(f"[enrich_qualify] property fetch failed: {exc}")

    return {"title": "Listed property", "location": "", "price": 0}


async def _update_application_briefing(application_id: str, briefing: str) -> None:
    """Write briefing to applications table via REST."""
    try:
        import os, requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        from app.config import settings
        url = settings.SUPABASE_URL
        key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_SERVICE_KEY
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}

        r = requests.patch(f"{url}/rest/v1/applications?id=eq.{application_id}",
                           json={"landlord_briefing": briefing},
                           headers=headers, verify=False, timeout=10)
        if r.ok:
            logger.info(f"[enrich_qualify] Briefing written to applications table: {application_id[:8]}...")
    except Exception as exc:
        logger.warning(f"[enrich_qualify] Failed to write briefing to DB: {exc}")
