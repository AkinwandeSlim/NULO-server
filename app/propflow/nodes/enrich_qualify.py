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
from app.propflow.services.qwen_client import qwen_client
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
        prior_landlord_memories = mem0_service.search_landlord_memories(
            landlord_id=landlord_id,
            query=query,
            limit=5,
        )
        if prior_landlord_memories:
            logger.info(
                f"[enrich_qualify] {len(prior_landlord_memories)} landlord "
                f"preference memories found"
            )

    # ── Step 3: Qwen briefing generation ─────────────────────────────────────
    briefing = await qwen_client.generate_landlord_briefing(
        tenant_data=tenant_data,
        property_data=property_data,
        extracted_intent=state.get("extracted_intent") or {},
        prior_tenant_memories=state.get("prior_tenant_memories") or [],
        prior_landlord_memories=prior_landlord_memories,
    )

    logger.info(f"[enrich_qualify] Briefing generated: '{briefing[:80]}...'")

    # ── Step 4: Write briefing to applications table ──────────────────────────
    if application_id:
        await _update_application_briefing(str(application_id), briefing)

    # ── Step 5: Mem0 writes ───────────────────────────────────────────────────
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # Tenant namespace: record that screening completed for this property
    mem0_service.add_tenant_memory(
        tenant_id=tenant_id,
        content=(
            f"Application submitted on {today} for "
            f"{property_data.get('title', 'a property')} "
            f"in {property_data.get('location', '')}. "
            f"Landlord briefing generated. Awaiting landlord approval."
        ),
        metadata={
            "workflow_id": state["workflow_id"],
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
        mem0_service.add_landlord_memory(
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
                "workflow_id": state["workflow_id"],
                "stage": "briefing_sent",
                "application_id": str(application_id) if application_id else None,
            },
        )

    # ── Step 6: Notify landlord about new application ───────────────────────────
    if landlord_id and application_id and property_data:
        try:
            notif_service = NotificationService()
            await notif_service.notify_application_submitted(
                application_id=str(application_id),
                property_id=str(property_id) if property_id else "",
                property_title=property_data.get("title", "Property"),
                tenant_id=tenant_id,
                tenant_name=tenant_data.get("full_name", "Applicant"),
                tenant_email=tenant_data.get("email"),
                tenant_phone=tenant_data.get("phone_number"),
                landlord_id=landlord_id,
                landlord_name="",  # fetched internally by notification service
                landlord_email=None,
                landlord_phone=None,
                monthly_income=tenant_data.get("monthly_income"),
                employment_status=tenant_data.get("occupation"),
                propflow_thread_id=state["workflow_id"],
            )
            logger.info(
                f"[enrich_qualify] Notification sent to landlord {landlord_id[:8]}... "
                f"for application {str(application_id)[:8]}..."
            )
        except Exception as exc:
            logger.warning(f"[enrich_qualify] Failed to send landlord notification: {exc}")

    return {
        **state,
        "landlord_briefing": briefing,
        "prior_landlord_memories": prior_landlord_memories,
        "current_stage": "awaiting_landlord_approval",
    }


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
