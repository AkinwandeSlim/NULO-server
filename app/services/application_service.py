"""
Application Service — shared service layer for application operations.

Both FastAPI route handlers and PropFlow graph nodes call this service
instead of writing to Supabase directly. This ensures:

1. Consistent side-effects (application_count increment, notifications)
2. propflow_workflow_id is always captured when present
3. Business logic lives in one place

Usage from routes:
    application = await application_service.submit_application(
        tenant_id=...,
        property_id=...,
        ... all ApplicationCreate fields ...,
    )

Usage from PropFlow nodes:
    application = await application_service.submit_application(
        tenant_id=state["tenant_id"],
        property_id=state["selected_property_id"],
        intent=state.get("extracted_intent"),
        tenant_profile=tenant_profile,
        propflow_workflow_id=state.get("workflow_id"),
    )
"""

import asyncio
import logging
from typing import Optional, Dict, Any

from app.database import supabase_admin

logger = logging.getLogger(__name__)


class ApplicationService:
    """Shared service for application CRUD operations."""

    @staticmethod
    async def submit_application(
        *,
        tenant_id: str,
        property_id: str,
        # Fields from ApplicationCreate (used by the route)
        viewing_id: Optional[str] = None,
        message: Optional[str] = None,
        employment_status: Optional[str] = None,
        employer_name: Optional[str] = None,
        job_title: Optional[str] = None,
        employment_duration: Optional[str] = None,
        monthly_income: Optional[int] = None,
        move_in_date: Optional[str] = None,
        lease_duration: Optional[str] = None,
        number_of_occupants: Optional[int] = None,
        dependents: Optional[int] = 0,
        has_pets: Optional[bool] = False,
        pet_details: Optional[str] = "",
        references: Optional[dict] = None,
        documents: Optional[list] = None,
        emergency_contact_name: Optional[str] = "",
        emergency_contact_phone: Optional[str] = "",
        # Tenant contact number (PropFlow Trust Passport). Google OAuth tenants
        # have no phone on their profile, so the card collects it and we save it
        # to users.phone_number — the field the landlord page and notifications read.
        phone_number: Optional[str] = None,
        # Trust Passport — tenant consent to share details with this landlord.
        # Persisted for the audit trail (column added by migration 020).
        consent_captured: Optional[bool] = False,
        # Fields from PropFlow extracted_intent (used by PropFlow)
        intent: Optional[Dict[str, Any]] = None,
        tenant_profile: Optional[Dict[str, Any]] = None,
        # Context awareness — if present, stored in the row so downstream
        # routes (approve/reject) can resume the workflow automatically.
        propflow_workflow_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new application with consistent side-effects.

        Accepts fields from both the manual route (ApplicationCreate) and
        PropFlow (extracted_intent + tenant_profile). When called from PropFlow,
        the intent/profile fields are merged into the application dict.

        Returns the created application row dict, or None on failure.
        """
        logger.info(f"[APP SERVICE] submit_application tenant={tenant_id[:8]}... property={property_id[:8]}...")

        loop = asyncio.get_event_loop()

        # ── Duplicate guard ────────────────────────────────────────────────────
        try:
            existing = await loop.run_in_executor(
                None,
                lambda: supabase_admin
                    .table("applications")
                    .select("id, status")
                    .eq("user_id", tenant_id)
                    .eq("property_id", property_id)
                    .execute(),
            )
            if existing.data:
                app = existing.data[0]
                logger.warning(f"[APP SERVICE] Duplicate application: {app['id']} status={app['status']}")
                # Return the existing application — caller decides whether to proceed
                return app
        except Exception as exc:
            logger.warning(f"[APP SERVICE] Duplicate check failed (non-fatal): {exc}")

        # ── Merge fields from PropFlow intent + tenant_profile ─────────────────
        # When PropFlow calls this service, the intent and tenant_profile are
        # used to populate fields that the manual route supplies via the request body.
        if intent or tenant_profile:
            intent = intent or {}
            tenant_profile = tenant_profile or {}

            # ── Trust Passport v1.1: never fabricate ─────────────────────────
            # Only carry over values that are REAL: explicitly chosen on the
            # Trust Passport card, genuinely extracted from the conversation,
            # or already saved in the tenant's profile. In particular:
            #   • lease_duration is never defaulted (no invented "12 months")
            #   • employment_status is never defaulted (no invented "employed")
            #   • monthly_income NEVER falls back to the search budget — budget
            #     is what the tenant wants to pay, not what they earn.
            #   • no auto-authored "Message to Landlord" — only a real typed
            #     message is stored.
            if not move_in_date and intent.get("move_in_date"):
                move_in_date = intent["move_in_date"]
            if not lease_duration and intent.get("lease_duration_months"):
                lease_duration = str(int(intent["lease_duration_months"]))
            if not employment_status:
                employment_status = tenant_profile.get("employment_status")
            if not employer_name:
                employer_name = tenant_profile.get("company_name") or ""
            if not monthly_income:
                # Income only from a real source: the tenant's saved profile
                # range (previously self-reported). Never from the search budget.
                monthly_income = _parse_income_range(
                    tenant_profile.get("monthly_income_range")
                )
            # number_of_occupants: store only what the tenant chose.

        # ── Build insert dict ──────────────────────────────────────────────────
        app_dict = {
            "user_id": tenant_id,
            "property_id": property_id,
            "viewing_id": viewing_id,
            "status": "submitted",
            "message": message or "",
            "move_in_date": move_in_date,
            # NULL (not a fabricated default) when the tenant chose nothing —
            # the landlord page hides these, and the DB CHECK constraint on
            # employment_status rejects empty strings, so we store None.
            "lease_duration": lease_duration or None,
            "employment_status": employment_status or None,
            "employer_name": employer_name or "",
            "job_title": job_title or "",
            "employment_duration": employment_duration or "",
            "monthly_income": monthly_income or 0,
            "number_of_occupants": number_of_occupants,
            "dependents": dependents or 0,
            "has_pets": has_pets or False,
            "pet_details": pet_details or "",
            "references": references or {},
            "documents": documents or [],
            "emergency_contact_name": emergency_contact_name or "",
            "emergency_contact_phone": emergency_contact_phone or "",
            "viewed_by_landlord": False,
        }

        # Consent is only persisted when explicitly captured (PropFlow Trust
        # Passport). Manual submissions leave it NULL so inserts don't fail if
        # migration 020 hasn't been applied yet.
        if consent_captured:
            app_dict["consent_captured"] = True

        # Store PropFlow workflow ID for context-aware resume capability
        if propflow_workflow_id:
            app_dict["propflow_thread_id"] = propflow_workflow_id

        # ── INSERT ─────────────────────────────────────────────────────────────
        try:
            result = await loop.run_in_executor(
                None,
                lambda: supabase_admin.table("applications").insert(app_dict).execute(),
            )
        except Exception as exc:
            logger.error(f"[APP SERVICE] INSERT failed: {exc}")
            return None

        if not result.data:
            logger.error("[APP SERVICE] INSERT returned no data")
            return None

        application = result.data[0]
        logger.info(f"[APP SERVICE] Created application {application['id'][:8]}...")

        # ── Increment application_count on property (best-effort) ──────────────
        try:
            await loop.run_in_executor(
                None,
                lambda: supabase_admin
                    .rpc("increment_application_count", {"property_id_input": property_id})
                    .execute(),
            )
        except Exception as exc:
            logger.debug(f"[APP SERVICE] increment_application_count skipped: {exc}")

        # ── Persist tenant contact number (best-effort) ────────────────────────
        # The applications table has no phone column — phone lives on users, which
        # is what the landlord page joins for. Only write when the tenant actually
        # provided one on the card; never overwrite a real number with empty.
        if phone_number:
            try:
                await loop.run_in_executor(
                    None,
                    lambda: supabase_admin
                        .table("users")
                        .update({"phone_number": phone_number})
                        .eq("id", tenant_id)
                        .execute(),
                )
                logger.info(f"[APP SERVICE] Updated users.phone_number for tenant {tenant_id[:8]}...")
            except Exception as exc:
                logger.warning(f"[APP SERVICE] users.phone_number update failed (non-fatal): {exc}")

        return application


def _parse_income_range(income_range: Optional[str]) -> Optional[int]:
    """Convert '200k-400k' or '500000' to an integer midpoint."""
    if not income_range:
        return None
    try:
        parts = income_range.lower().replace("k", "000").split("-")
        if len(parts) == 2:
            low, high = int(parts[0].strip()), int(parts[1].strip())
            return (low + high) // 2
        return int(parts[0].strip())
    except (ValueError, IndexError):
        return None


# Singleton
application_service = ApplicationService()
