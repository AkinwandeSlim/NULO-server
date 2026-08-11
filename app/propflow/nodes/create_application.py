"""
PropFlow Node 3: Create Application  (maps to "Inquiry Agent - submit" step)

Responsibility:
  Delegate to the shared application_service which handles:
    - Fetching tenant profile data from Supabase
    - Merging extracted_intent fields with profile data
    - INSERT into public.applications with propflow_workflow_id context
    - Duplicate guard
    - Incrementing property application_count

  Previously this node did all of the above with direct Supabase calls.
  Now it calls the shared service layer so that:
    1. Business logic is consistent between the route and PropFlow paths
    2. propflow_workflow_id is embedded in the application row automatically
    3. Downstream flows (approve/reject) can resume the workflow from the
       stored thread_id
"""

import logging
import uuid

from app.propflow.state import PropFlowState
from app.services.application_service import application_service

logger = logging.getLogger(__name__)


async def create_application_node(state: PropFlowState) -> PropFlowState:
    """
    Node 3 — create application via shared service layer.

    Steps:
      1. Fetch tenant profile for employment / income data
      2. Call application_service.submit_application() with
         intent + tenant_profile + propflow_workflow_id
      3. Return updated state with application_id

    Args:
        state: PropFlowState with selected_property_id, tenant_id,
               extracted_intent, and workflow_id populated.

    Returns:
        Updated state with application_id, application_status,
        and current_stage.
    """
    tenant_id   = str(state["tenant_id"])
    property_id = str(state["selected_property_id"])
    workflow_id = state.get("workflow_id", "")
    intent      = state.get("extracted_intent") or {}

    logger.info(
        f"[create_application] tenant={tenant_id[:8]}... "
        f"property={property_id[:8]}..."
    )

    # ── Step 1: Fetch tenant profile for employment / income ─────────────────
    tenant_profile = await _fetch_tenant_profile(tenant_id)

    # ── Step 1b: Trust Passport fields (explicit, win over profile/intent) ──
    trust_documents = state.get("trust_documents")
    trust_refs      = state.get("trust_references")
    trust_consent   = state.get("trust_consent")

    if trust_documents or trust_refs:
        logger.info(
            f"[TRUST] workflow={workflow_id} attaching docs={len(trust_documents or [])} "
            f"refs={len(trust_refs or {})} consent={bool(trust_consent)}"
        )

    # ── Step 2: Delegate to shared service ────────────────────────────────────
    application = await application_service.submit_application(
        tenant_id=tenant_id,
        property_id=property_id,
        # PropFlow-specific fields from intent + profile
        intent=intent,
        tenant_profile=tenant_profile,
        # Trust Passport — explicit tenant-provided data (the service only fills
        # from intent/profile when these args are falsy, so explicit wins).
        documents=trust_documents,
        references=trust_refs,
        consent_captured=bool(trust_consent),
        employment_status=state.get("trust_employment_status"),
        employer_name=state.get("trust_employer_name"),
        job_title=state.get("trust_job_title"),
        employment_duration=state.get("trust_employment_duration"),
        monthly_income=state.get("trust_monthly_income"),
        emergency_contact_name=state.get("trust_emergency_contact_name"),
        emergency_contact_phone=state.get("trust_emergency_contact_phone"),
        phone_number=state.get("trust_phone_number"),
        move_in_date=state.get("trust_move_in_date") or state.get("extracted_intent", {}).get("move_in_date"),
        lease_duration=state.get("trust_lease_duration"),
        number_of_occupants=state.get("trust_number_of_occupants"),
        has_pets=state.get("trust_has_pets"),
        pet_details=state.get("trust_pet_details"),
        message=state.get("trust_message"),
        # Context awareness — stored as propflow_thread_id in the application row
        propflow_workflow_id=workflow_id,
    )

    if not application:
        error_log = state.get("error_log", [])
        return {
            **state,
            "error_log": error_log + ["create_application: service returned None"],
            "current_stage": "error",
        }

    application_id = uuid.UUID(application["id"])
    app_status = application.get("status", "submitted")

    logger.info(f"[create_application] Created application {application_id} via service (status={app_status})")

    return {
        **state,
        "application_id":     application_id,
        "application_status": app_status,
        "current_stage":      "application_created",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_tenant_profile(tenant_id: str) -> dict:
    """
    Fetch tenant_profiles row for employment and income data.
    Uses REST (requests+verify=False) to avoid Windows socket issues.
    Returns safe empty dict on failure — node continues without it.
    """
    try:
        import os, requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        from app.config import settings
        url = settings.SUPABASE_URL
        key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_SERVICE_KEY
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        r = requests.get(
            f"{url}/rest/v1/tenant_profiles?id=eq.{tenant_id}"
            f"&select=employment_status,company_name,job_title,monthly_income_range,income_proof_verified",
            headers=headers, verify=False, timeout=10,
        )
        return r.json()[0] if r.ok and r.json() else {}
    except Exception as exc:
        logger.warning(f"[create_application] tenant_profiles fetch failed: {exc}")
        return {}
