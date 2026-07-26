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

    # ── Step 2: Delegate to shared service ────────────────────────────────────
    application = await application_service.submit_application(
        tenant_id=tenant_id,
        property_id=property_id,
        # PropFlow-specific fields from intent + profile
        intent=intent,
        tenant_profile=tenant_profile,
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
    Returns safe empty dict on failure — node continues without it.
    """
    import asyncio
    try:
        from app.database import supabase_admin
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("tenant_profiles")
                .select(
                    "employment_status, company_name, job_title, "
                    "monthly_income_range, income_proof_verified, "
                    "emergency_contact_name, emergency_contact_phone"
                )
                .eq("id", tenant_id)
                .single()
                .execute(),
        )
        return result.data or {}
    except Exception as exc:
        logger.warning(f"[create_application] tenant_profiles fetch failed: {exc}")
        return {}
