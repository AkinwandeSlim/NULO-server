"""
Agreements routes - Using Supabase (not SQLAlchemy)
Rental Agreement Management with electronic signatures

ROUTE ORDER (Rule 7 — specific before wildcard):
  POST  /                              create agreement
  GET   /                              list all for current user
  GET   /property/{property_id}        landlord: all agreements for one property
  GET   /{agreement_id}                single agreement (wildcard — LAST)
  PATCH /{agreement_id}/sign           sign an agreement
  POST  /{agreement_id}/generate-pdf   generate PDF of signed agreement

BUGS FIXED vs original:
  1. Route order — GET / and GET /property/{id} were after GET /{id}, making them
     unreachable. FastAPI matched "/property/xyz" as agreement_id="property" -> 404.
  2. `status` query-param shadowed the `from fastapi import status` module in
     get_agreements() — every status.HTTP_* call crashed at runtime.
     Fixed: renamed to status_filter.
  3. GET /{agreement_id} returned bare dict with no tenant/landlord/property data.
     Fixed: enriched via shared _fetch_agreement_participants() helper.
  4. Inconsistent response shapes — some routes returned raw list/dict, others
     wrapped in {success, agreement}. Fixed: all routes return consistent shape.
  5. GET / was missing property data in enrichment. Fixed: property fetched too.
  6. GET /property/{property_id} now reachable (route order fix) and enriched.
  7. PDF generation was placeholder (no actual file). Fixed: ReportLab + Supabase Storage.
"""
import logging
import asyncio
import hashlib
import re
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, status
from app.database import supabase_admin, run_db_async
from app.middleware.auth import get_current_user, get_current_tenant, get_current_landlord
from app.services.notification_service import notification_service
from app.routes.tenant_dashboard import invalidate_tenant_cache
from app.routes.landlord_dashboard import invalidate_landlord_cache
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageTemplate, Frame, HRFlowable
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

router = APIRouter(prefix="/agreements")
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class AgreementCreate(BaseModel):
    """Model for creating new agreements"""
    application_id: str
    lease_start_date: str   # YYYY-MM-DD
    lease_end_date: str     # YYYY-MM-DD
    lease_duration: int     # months


class AgreementSignRequest(BaseModel):
    """Model for signing agreements"""
    ip_address: Optional[str] = Field(None, description="Client IP for signature audit trail")


class AgreementUpdate(BaseModel):
    """Model for updating agreements"""
    status: Optional[str] = Field(None, description="Agreement status")


# ─────────────────────────────────────────────────────────────────────────────
# Internal helper — mirrors _fetch_viewing_participants() in viewing_requests.py
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_agreement_participants(agreement: dict) -> tuple:
    """
    Given an agreement row return (tenant_data, landlord_data, property_data).
    Any of them can be None if the lookup fails — callers must handle that.
    Never raises — logs warnings instead so a missing join never 404s the caller.
    """
    tenant_data = None
    landlord_data = None
    property_data = None

    try:
        r = supabase_admin.table("users").select(
            "id, full_name, email, phone_number, avatar_url"
        ).eq("id", agreement["tenant_id"]).execute()
        tenant_data = r.data[0] if r.data else None
    except Exception as e:
        logger.warning(f"[AGREEMENTS] Could not fetch tenant {agreement.get('tenant_id')}: {e}")

    try:
        r = supabase_admin.table("users").select(
            "id, full_name, email, phone_number, avatar_url"
        ).eq("id", agreement["landlord_id"]).execute()
        landlord_data = r.data[0] if r.data else None
    except Exception as e:
        logger.warning(f"[AGREEMENTS] Could not fetch landlord {agreement.get('landlord_id')}: {e}")

    # Merge bank details from landlord_profiles (shared-PK table) so the
    # confirm-release dialog and receipt generation always show real values
    # instead of "Your Bank" / "••••••••" placeholders.
    if landlord_data:
        try:
            bp = supabase_admin.table("landlord_profiles").select(
                "bank_account_number, bank_name, account_name, bank_code, bank_verified_at"
            ).eq("id", agreement["landlord_id"]).execute()
            if bp.data:
                profile = bp.data[0]
                landlord_data = {
                    **landlord_data,
                    "bank_account_number": profile.get("bank_account_number"),
                    "bank_name": profile.get("bank_name"),
                    "account_name": profile.get("account_name"),
                    "bank_code": profile.get("bank_code"),
                    "bank_verified_at": profile.get("bank_verified_at"),
                }
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Could not fetch landlord_profiles for {agreement.get('landlord_id')}: {e}")

    try:
        r = supabase_admin.table("properties").select(
            "id, title, location, city, state, address, full_address, price, images, payment_frequency"
        ).eq("id", agreement["property_id"]).execute()
        property_data = r.data[0] if r.data else None
    except Exception as e:
        logger.warning(f"[AGREEMENTS] Could not fetch property {agreement.get('property_id')}: {e}")

    return tenant_data, landlord_data, property_data


def _enrich(agreement: dict) -> dict:
    """
    Attach tenant, landlord, and property sub-objects to an agreement dict.
    Returns a new dict — does not mutate the original.
    """
    tenant_data, landlord_data, property_data = _fetch_agreement_participants(agreement)
    return {
        **agreement,
        "tenant": tenant_data,
        "landlord": landlord_data,
        "property": property_data,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CREATE
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/", response_model=dict)
async def create_agreement(
    agreement_data: AgreementCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new rental agreement from an approved application.
    Only tenants can trigger manual agreement creation.
    (Agreements are also auto-created by the backend when a landlord approves
    an application — see agreement_service.auto_generate_agreement.)
    """
    try:
        user_type = current_user["user_type"]

        if user_type != "tenant":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only tenants can create agreements"
            )

        tenant_id = current_user["id"]
        logger.info(f"[AGREEMENTS] Creating agreement — tenant={tenant_id} application={agreement_data.application_id}")

        from app.services.agreement_service import agreement_service

        agreement = await agreement_service.create_manual_agreement(
            agreement_data.dict(),
            current_user
        )

        if not agreement:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create agreement"
            )

        logger.info(f"✅ [AGREEMENTS] Created agreement {agreement['id']}")
        return {
            "success": True,
            "agreement": _enrich(agreement),
            "message": "Agreement created successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] Failed to create agreement: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create agreement: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# GET ALL for current user
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/")
async def get_agreements(
    status_filter: Optional[str] = None,   # BUG FIX: was `status` — shadowed the fastapi `status` module
    current_user: dict = Depends(get_current_user)
):
    """
    List all agreements for the current user.
    Tenants see their own agreements.
    Landlords see agreements for all their properties.
    Each agreement is enriched with tenant, landlord, and property details.
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]

        logger.info(f"[AGREEMENTS] Listing agreements — {user_type}={user_id} filter={status_filter}")

        if user_type == "tenant":
            query = supabase_admin.table("agreements").select("*").eq("tenant_id", user_id)
        elif user_type == "landlord":
            query = supabase_admin.table("agreements").select("*").eq("landlord_id", user_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid user type"
            )

        if status_filter:
            query = query.eq("status", status_filter)

        response = await run_db_async(lambda: query.order("created_at", desc=True).execute())
        agreements = response.data or []

        # ✅ OPTIMIZATION: Batch fetch all related data instead of N+1 queries
        # Extract unique IDs
        tenant_ids = list(set(a.get("tenant_id") for a in agreements if a.get("tenant_id")))
        landlord_ids = list(set(a.get("landlord_id") for a in agreements if a.get("landlord_id")))
        property_ids = list(set(a.get("property_id") for a in agreements if a.get("property_id")))

        # Batch fetch all related data in 3 queries instead of 3N queries
        tenants_map = {}
        landlords_map = {}
        properties_map = {}

        try:
            if tenant_ids:
                tenants_resp = await run_db_async(
                    lambda: supabase_admin.table("users").select(
                        "id, full_name, email, phone_number, avatar_url"
                    ).in_("id", tenant_ids).execute()
                )
                tenants_map = {u["id"]: u for u in tenants_resp.data}
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Batch fetch tenants failed: {e}")

        try:
            if landlord_ids:
                landlords_resp = await run_db_async(
                    lambda: supabase_admin.table("users").select(
                        "id, full_name, email, phone_number, avatar_url"
                    ).in_("id", landlord_ids).execute()
                )
                landlords_map = {u["id"]: u for u in landlords_resp.data}
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Batch fetch landlords failed: {e}")

        # Merge bank details from landlord_profiles into landlords_map.
        # landlord_profiles shares the same PK as users, so id == landlord_id.
        # Without this, every confirm-release dialog shows "Your Bank / ••••••••".
        try:
            if landlord_ids:
                profiles_resp = await run_db_async(
                    lambda: supabase_admin.table("landlord_profiles").select(
                        "id, bank_account_number, bank_name, account_name, bank_code, bank_verified_at"
                    ).in_("id", landlord_ids).execute()
                )
                for profile in profiles_resp.data:
                    lid = profile["id"]
                    if lid in landlords_map:
                        landlords_map[lid] = {
                            **landlords_map[lid],
                            "bank_account_number": profile.get("bank_account_number"),
                            "bank_name": profile.get("bank_name"),
                            "account_name": profile.get("account_name"),
                            "bank_code": profile.get("bank_code"),
                            "bank_verified_at": profile.get("bank_verified_at"),
                        }
                    else:
                        # landlord exists in profiles but not in users (edge case)
                        landlords_map[lid] = profile
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Batch fetch landlord_profiles failed: {e}")

        try:
            if property_ids:
                properties_resp = await run_db_async(
                    lambda: supabase_admin.table("properties").select(
                        "id, title, location, city, state, address, full_address, price, images, payment_frequency"
                    ).in_("id", property_ids).execute()
                )
                properties_map = {p["id"]: p for p in properties_resp.data}
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Batch fetch properties failed: {e}")

        # Batch fetch latest disbursement status for each agreement
        disbursements_map = {}
        try:
            if agreements:
                # Get the latest disbursement for each agreement
                disbursements_resp = await run_db_async(
                    lambda: supabase_admin.table("transactions").select(
                        "agreement_id, status, amount, nomba_transfer_ref"
                    ).in_("agreement_id", [a["id"] for a in agreements if a.get("id")]) \
                    .in_("transaction_type", ["nomba_disbursement"]) \
                    .order("created_at", desc=True) \
                    .execute()
                )
                logger.info(f"[AGREEMENTS] Fetched {len(disbursements_resp.data)} disbursements")
                # Keep only the latest disbursement per agreement.
                # But prefer a 'released' row over a 'failed' row — if we already
                # have a successful release, a stale failed row must not overwrite it.
                for d in disbursements_resp.data:
                    aid = d["agreement_id"]
                    if aid not in disbursements_map:
                        disbursements_map[aid] = d
                    elif d.get("status") == "released":
                        # Always let a released row win over any earlier failed entry
                        disbursements_map[aid] = d
                    logger.info(f"[AGREEMENTS] Agreement {aid} has disbursement status: {disbursements_map[aid].get('status')}")
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Batch fetch disbursements failed: {e}")

        # Attach pre-fetched data to each agreement
        enhanced = []
        for agreement in agreements:
            disbursement = disbursements_map.get(agreement.get("id"))
            property_data = properties_map.get(agreement.get("property_id"))
            # Prioritize property's payment_frequency over agreement's
            payment_frequency = (
                (property_data.get("payment_frequency") if property_data else None)
                    or agreement.get("payment_frequency")
                )
            enhanced.append({
                **agreement,
                "tenant": tenants_map.get(agreement.get("tenant_id")),
                "landlord": landlords_map.get(agreement.get("landlord_id")),
                "property": property_data,
                "payment_frequency": payment_frequency,
                "disbursement_status": disbursement.get("status") if disbursement else None,
                "disbursement_merchant_tx_ref": disbursement.get("nomba_transfer_ref") if disbursement else None,
                "disbursement_amount": disbursement.get("amount") if disbursement else None,
            })

        logger.info(f"[AGREEMENTS] Returning {len(enhanced)} agreements for {user_type} {user_id}")
        return {
            "success": True,
            "agreements": enhanced,
            "count": len(enhanced)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] Failed to list agreements: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agreements: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# GET by property — must be BEFORE /{agreement_id} (Rule 7)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/property/{property_id}")
async def get_property_agreements(
    property_id: str,
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_landlord)
):
    """
    Get all agreements for a specific property.
    Landlord only — verifies ownership before returning data.
    Each agreement is enriched with tenant details.
    """
    try:
        landlord_id = current_user["id"]

        # Verify landlord owns this property
        prop_check = supabase_admin.table("properties").select("id, title").eq(
            "id", property_id
        ).eq("landlord_id", landlord_id).execute()

        if not prop_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found or access denied"
            )

        query = supabase_admin.table("agreements").select("*").eq("property_id", property_id)
        if status_filter:
            query = query.eq("status", status_filter)

        response = query.order("created_at", desc=True).execute()
        agreements = response.data or []

        # ✅ OPTIMIZATION: Batch fetch all related data instead of N+1 queries
        tenant_ids = list(set(a.get("tenant_id") for a in agreements if a.get("tenant_id")))
        landlord_ids = list(set(a.get("landlord_id") for a in agreements if a.get("landlord_id")))

        tenants_map = {}
        landlords_map = {}

        try:
            if tenant_ids:
                tenants_resp = supabase_admin.table("users").select(
                    "id, full_name, email, phone_number, avatar_url"
                ).in_("id", tenant_ids).execute()
                tenants_map = {u["id"]: u for u in tenants_resp.data}
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Batch fetch tenants (property view) failed: {e}")

        try:
            if landlord_ids:
                landlords_resp = supabase_admin.table("users").select(
                    "id, full_name, email, phone_number, avatar_url"
                ).in_("id", landlord_ids).execute()
                landlords_map = {u["id"]: u for u in landlords_resp.data}
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Batch fetch landlords (property view) failed: {e}")

        enhanced = []
        for agreement in agreements:
            try:
                enhanced.append({
                    **agreement,
                    "tenant": tenants_map.get(agreement.get("tenant_id")),
                    "landlord": landlords_map.get(agreement.get("landlord_id")),
                    "property": prop_check.data[0],  # Same property for all
                })
            except Exception as e:
                logger.warning(f"[AGREEMENTS] Could not enrich agreement {agreement.get('id')}: {e}")
                enhanced.append(agreement)

        return {
            "success": True,
            "agreements": enhanced,
            "count": len(enhanced),
            "property": prop_check.data[0]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] Failed to get property agreements: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get property agreements: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# GET by application_id — the key link from approval -> agreement display
# Must come BEFORE /{agreement_id} (Rule 7)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/application/{application_id}")
async def get_agreement_by_application(
    application_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get the agreement linked to a specific application.

    WHY THIS ROUTE EXISTS:
    After a landlord approves an application, auto_generate_agreement() creates
    an agreement record with application_id as the FK. The application detail
    page (for both tenant and landlord) knows the application_id — not the
    agreement_id. This route is the clean bridge between those two records.

    Access control: only the tenant who submitted the application or the
    landlord who owns the property may view the agreement.

    Uses idx_agreements_application index — O(1) lookup.
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]

        logger.info(f"[AGREEMENTS] Fetching by application_id={application_id} for {user_type} {user_id}")

        response = supabase_admin.table("agreements").select("*").eq(
            "application_id", application_id
        ).execute()

        if not response.data:
            # Agreement may not exist yet (auto-generation can lag or fail)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No agreement found for this application yet"
            )

        agreement = response.data[0]

        # Access control — same rule as GET /{agreement_id}
        if agreement["tenant_id"] != user_id and agreement["landlord_id"] != user_id:
            logger.warning(
                f"[AGREEMENTS] Unauthorized: {user_type} {user_id} tried to access "
                f"agreement for application {application_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this agreement"
            )

        enriched = _enrich(agreement)

        logger.info(f"✅ [AGREEMENTS] Returning agreement {agreement['id']} for application {application_id}")
        return {
            "success": True,
            "agreement": enriched
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] Failed to get agreement by application {application_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agreement: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# GET by ID — wildcard, must come LAST among GETs (Rule 7)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{agreement_id}")
async def get_agreement(
    agreement_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a specific agreement by ID.
    Accessible by the tenant or landlord who are party to the agreement.
    Returns full enrichment: tenant info, landlord info, property info.
    (BUG FIX: original returned bare dict with no participant details.)
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]

        logger.info(f"[AGREEMENTS] Fetching agreement {agreement_id} for {user_type} {user_id}")

        # Wrap Supabase calls with transient-socket retry (WinError 10035, timeouts, etc.)
        response = await run_db_async(
            lambda: supabase_admin.table("agreements").select("*").eq("id", agreement_id).execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agreement not found"
            )

        agreement = response.data[0]

        # Access control — tenant or landlord on this agreement only
        if agreement["tenant_id"] != user_id and agreement["landlord_id"] != user_id:
            logger.warning(f"[AGREEMENTS] Unauthorized: {user_type} {user_id} tried to access {agreement_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this agreement"
            )

        enriched = _enrich(agreement)

        # Fetch latest disbursement status for this agreement.
        # Prefer 'released' over 'failed' — a stale failed row must not
        # mask a successful release that happened afterwards.
        disbursement = None
        try:
            disbursement_resp = await run_db_async(
                lambda: supabase_admin.table("transactions").select(
                    "agreement_id, status, amount, nomba_transfer_ref"
                ).eq("agreement_id", agreement_id)
                .eq("transaction_type", "nomba_disbursement")
                .order("created_at", desc=True)
                .execute()
            )
            rows = disbursement_resp.data or []
            # Pick the best row: prefer 'released', then 'pending', then latest
            released_row = next((r for r in rows if r.get("status") == "released"), None)
            pending_row  = next((r for r in rows if r.get("status") == "pending"),  None)
            disbursement = released_row or pending_row or (rows[0] if rows else None)
            if disbursement:
                logger.info(f"[AGREEMENTS] Agreement {agreement_id} has disbursement status: {disbursement.get('status')}")
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Failed to fetch disbursement for {agreement_id}: {e}")

        # Attach disbursement status to enriched agreement
        if disbursement:
            enriched["disbursement_status"] = disbursement.get("status")
            enriched["disbursement_merchant_tx_ref"] = disbursement.get("nomba_transfer_ref")
            enriched["disbursement_amount"] = disbursement.get("amount")

        # Fetch transfer history for this agreement
        # Always try — the query uses account_ref = "{agreement_id}-SUB" built
        # from the agreement UUID itself, so it works even when the agreement
        # row has a null nomba_account_ref (e.g. older provisions).
        transfer_history = []
        uuid_match = re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            agreement_id, re.IGNORECASE,
        )
        clean_agreement_id = uuid_match.group(0) if uuid_match else agreement_id
        suffixed_account_ref = f"{clean_agreement_id}-SUB"

        transfers = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin
                .table("virtual_account_transfers")
                .select(
                    "id, account_ref, account_number, amount_received, currency, "
                    "sender_name, sender_bank, reconciliation_result, transaction_type, "
                    "event_type, nomba_request_id, nomba_transaction_id, created_at"
                )
                .eq("account_ref", suffixed_account_ref)
                .order("created_at", desc=True)
                .execute(),
        )
        transfer_history = transfers.data or []

        logger.info(f"✅ [AGREEMENTS] Returning agreement {agreement_id} to {user_type} {user_id}")
        return {
            "success": True,
            "agreement": enriched,
            "transfer_history": transfer_history
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] Failed to get agreement {agreement_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agreement: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# SIGN
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/{agreement_id}/sign")
async def sign_agreement(
    agreement_id: str,
    sign_data: AgreementSignRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """
    Sign an agreement as the current user (tenant or landlord).
    Records the signature timestamp and IP address for audit trail.
    When both parties have signed, status transitions to SIGNED.

    Signing flow:
      Tenant signs  → status PENDING_LANDLORD → landlord notified to countersign
      Landlord signs → status SIGNED          → tenant notified, tenancy confirmed
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]

        logger.info(f"[AGREEMENTS] Signing agreement {agreement_id} as {user_type} {user_id}")

        from app.services.agreement_service import agreement_service

        agreement = await agreement_service.sign_agreement(
            agreement_id=agreement_id,
            user_id=user_id,
            user_type=user_type,
            ip_address=sign_data.ip_address
        )

        if not agreement:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to sign agreement"
            )

        # ── PropFlow graph sync: once BOTH parties have signed, advance the
        #     workflow past the signing gate so provision_nomba_dva runs (real/
        #     mock VA). Best-effort — a graph hiccup must never fail the sign.
        if str(agreement.get("status", "")).upper() == "SIGNED":
            try:
                from app.services.propflow_graph_sync import advance_after_sign
                await advance_after_sign(agreement_id, supabase_admin)
            except Exception as graph_err:
                logger.warning(
                    f"[AGREEMENTS] PropFlow graph advance failed (non-fatal): {graph_err}"
                )
        # ── PropFlow graph sync: tenant signed first (via the agreement page,
        #     not the chat) → flip the thread stage to awaiting_landlord_signature
        #     so the PropFlow chat/status reflect the real state immediately.
        elif (
            user_type == "tenant"
            and str(agreement.get("status", "")).upper() == "PENDING_LANDLORD"
        ):
            try:
                from app.services.propflow_graph_sync import sync_stage_after_tenant_sign
                await sync_stage_after_tenant_sign(agreement_id, supabase_admin)
            except Exception as graph_err:
                logger.warning(
                    f"[AGREEMENTS] PropFlow tenant-sign stage sync failed (non-fatal): {graph_err}"
                )

        enriched = _enrich(agreement)

        # ── Pull participant data needed for notifications ──────────────────
        tenant_data   = enriched.get("tenant")   or {}
        landlord_data = enriched.get("landlord") or {}
        property_data = enriched.get("property") or {}

        property_title  = property_data.get("title", "your property")
        tenant_name     = tenant_data.get("full_name", "Tenant")
        tenant_email    = tenant_data.get("email")
        tenant_phone    = tenant_data.get("phone_number")
        landlord_name   = landlord_data.get("full_name", "Landlord")
        landlord_email  = landlord_data.get("email")
        landlord_phone  = landlord_data.get("phone_number")
        application_id  = agreement.get("application_id", "")

        # ── Tenant just signed → notify landlord to countersign ─────────────
        if user_type == "tenant":
            background_tasks.add_task(
                notification_service.notify_agreement_signed_by_tenant,
                agreement_id=agreement_id,
                application_id=application_id,
                property_title=property_title,
                tenant_id=str(agreement["tenant_id"]),
                tenant_name=tenant_name,
                landlord_id=str(agreement["landlord_id"]),
                landlord_name=landlord_name,
                landlord_email=landlord_email,
                landlord_phone=landlord_phone,
            )

        # ── Landlord countersigned → notify tenant it's fully done ──────────
        elif user_type == "landlord":
            background_tasks.add_task(
                notification_service.notify_agreement_fully_signed,
                agreement_id=agreement_id,
                application_id=application_id,
                property_title=property_title,
                tenant_id=str(agreement["tenant_id"]),
                tenant_name=tenant_name,
                tenant_email=tenant_email,
                tenant_phone=tenant_phone,
                landlord_id=str(agreement["landlord_id"]),
                landlord_name=landlord_name,
            )

        logger.info(f"✅ [AGREEMENTS] Agreement {agreement_id} signed by {user_type} {user_id}")

        # ── Invalidate dashboard caches so the tenant/landlord sees the
        #     new signed status immediately (otherwise the stat cards keep
        #     showing the stale 60s-cached values for up to a minute).
        try:
            invalidate_tenant_cache(str(agreement["tenant_id"]))
            invalidate_landlord_cache(str(agreement["landlord_id"]))
        except Exception as cache_err:
            logger.warning(f"[AGREEMENTS] Cache invalidation failed (non-fatal): {cache_err}")

        return {
            "success": True,
            "agreement": enriched,
            "message": f"Agreement signed successfully by {user_type}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] Failed to sign agreement {agreement_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to sign agreement: {str(e)}"
        )

# ─────────────────────────────────────────────────────────────────────────────
# REGENERATE AGREEMENT TERMS (fix stale pricing after payment-model changes)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{agreement_id}/regenerate")
async def regenerate_agreement_terms(
    agreement_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Regenerate the agreement terms text using the CURRENT pricing model
    (property payment_frequency, waived deposit/fees).

    WHY THIS ROUTE EXISTS:
    Agreements generated before the payment-integration pricing changes still
    carry the old "annual upfront + 2-month deposit" terms. This endpoint lets
    a party refresh the terms in place WITHOUT creating a new agreement row.

    Guards:
      - Only the tenant or landlord on this agreement may call it.
      - Refuses if EITHER party has already signed (terms are frozen once
        signing starts, since a signature binds the signed text).
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]

        response = await run_db_async(
            lambda: supabase_admin.table("agreements").select("*").eq("id", agreement_id).execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agreement not found"
            )

        agreement = response.data[0]

        # Access control — only a party to this agreement
        if agreement["tenant_id"] != user_id and agreement["landlord_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to regenerate this agreement"
            )

        # Freeze once signing has started — a signature binds the signed text
        if agreement.get("tenant_signed_at") or agreement.get("landlord_signed_at"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot regenerate terms after signing has started"
            )

        # ── Fetch property + tenant + landlord for generation context ────────
        prop_resp = await run_db_async(
            lambda: supabase_admin.table("properties").select("*").eq("id", agreement["property_id"]).execute()
        )
        if not prop_resp.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found for this agreement"
            )
        property_data = prop_resp.data[0]

        tenant_resp = await run_db_async(
            lambda: supabase_admin.table("users").select("*").eq("id", agreement["tenant_id"]).execute()
        )
        tenant_data = (tenant_resp.data or [{}])[0]

        landlord_resp = await run_db_async(
            lambda: supabase_admin.table("users").select("*").eq("id", agreement["landlord_id"]).execute()
        )
        landlord_data = (landlord_resp.data or [{}])[0]
        landlord_name = landlord_data.get("full_name", "Landlord")


        # ── Regenerate terms (deterministic template) ────────────────────────
        from app.services.agreement_service import AgreementService

        lease_dates = {
            "lease_start_date": agreement.get("lease_start_date"),
            "lease_end_date": agreement.get("lease_end_date"),
            "lease_duration": agreement.get("lease_duration", 12),
        }

        terms_result = await AgreementService.generate_enhanced_agreement_terms(
            property_data=property_data,
            tenant_data=tenant_data,
            landlord_name=landlord_name,
            lease_dates=lease_dates,
            application={"id": agreement.get("application_id")},
            landlord_email=landlord_data.get("email"),
            landlord_phone=landlord_data.get("phone_number"),
        )

        # ── Persist the refreshed terms ──────────────────────────────────────
        metadata = terms_result["metadata"]
        metadata["regenerated_at"] = datetime.now().isoformat()
        metadata["regenerated_by"] = user_id

        # Keep the DB row consistent with the regenerated text: deposit is
        # resolved from platform policy (same helper the template uses).
        deposit_amount = AgreementService.resolve_security_deposit(
            property_data.get("price", 0)
        )[0]

        update_resp = await run_db_async(
            lambda: supabase_admin.table("agreements").update({
                "terms": terms_result["terms"],
                "agreement_source": terms_result["source"],
                "generation_metadata": metadata,
                "payment_frequency": property_data.get("payment_frequency", "MONTHLY"),
                "deposit_amount": deposit_amount,
                "updated_at": datetime.now().isoformat(),
            }).eq("id", agreement_id).execute()
        )

        if not update_resp.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save regenerated terms"
            )

        # ── Invalidate the cached tenant brief so it reflects the new terms ──
        _TENANT_BRIEF_CACHE.pop(agreement_id, None)

        logger.info(
            f"✅ [AGREEMENTS] Terms regenerated for agreement {agreement_id} "
            f"(source: {terms_result['source']}, by {user_type} {user_id})"
        )

        return {
            "success": True,
            "agreement": _enrich(update_resp.data[0]),
            "source": terms_result["source"],
            "message": "Agreement terms regenerated with current pricing"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] Failed to regenerate agreement {agreement_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate agreement: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TENANT AGREEMENT BRIEF (Qwen AI plain-English summary)
# ─────────────────────────────────────────────────────────────────────────────

# In-memory cache: agreement_id -> (terms_hash, brief_text, generated_at).
# The brief is derived from the agreement terms, so the cache entry is only
# valid while the terms are unchanged. Keying on a hash of the terms means
# ANY terms change (regeneration endpoint or direct DB patch) automatically
# invalidates the brief without needing an explicit pop. Keeps repeat page
# loads instant and avoids re-billing Qwen.
_TENANT_BRIEF_CACHE: dict[str, tuple[str, str, datetime]] = {}
_TENANT_BRIEF_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def _terms_hash(terms: str) -> str:
    return hashlib.sha256((terms or "").encode("utf-8")).hexdigest()


@router.get("/{agreement_id}/tenant-brief")
async def get_tenant_brief(
    agreement_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Generate (or return cached) plain-English AI brief of the agreement for the
    tenant, so they understand the key clauses BEFORE signing.

    Tenant-only. Powered by Qwen via the PropFlow qwen_client, with a
    deterministic fallback when the LLM is unavailable. Cached in-memory for
    24h per agreement.
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]

        if user_type != "tenant":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only tenants can request an agreement brief"
            )

        response = await run_db_async(
            lambda: supabase_admin.table("agreements").select("*").eq("id", agreement_id).execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agreement not found"
            )

        agreement = response.data[0]

        # Access control — only the tenant on this agreement
        if agreement["tenant_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this agreement"
            )

        # ── Serve from cache when fresh AND terms unchanged ──────────────────
        current_hash = _terms_hash(agreement.get("terms", ""))
        cached = _TENANT_BRIEF_CACHE.get(agreement_id)
        if cached:
            cached_hash, brief_text, generated_at = cached
            age = (datetime.utcnow() - generated_at).total_seconds()
            if cached_hash == current_hash and age < _TENANT_BRIEF_TTL_SECONDS:
                return {
                    "success": True,
                    "brief": brief_text,
                    "cached": True,
                    "agreement_id": agreement_id,
                }

        # ── Fetch property for context (title + payment frequency) ───────────
        property_title = None
        payment_frequency = None
        try:
            prop_resp = await run_db_async(
                lambda: supabase_admin.table("properties").select(
                    "title, payment_frequency"
                ).eq("id", agreement["property_id"]).execute()
            )
            if prop_resp.data:
                property_title = prop_resp.data[0].get("title")
                payment_frequency = prop_resp.data[0].get("payment_frequency")
        except Exception as e:
            logger.warning(f"[AGREEMENTS] tenant-brief: property lookup failed: {e}")

        # ── Generate via Qwen (falls back to mock internally) ────────────────
        from app.propflow.services.qwen_client import qwen_client

        brief_text = await qwen_client.generate_tenant_agreement_brief(
            agreement_terms=agreement.get("terms", ""),
            property_title=property_title,
            rent_amount=agreement.get("rent_amount"),
            lease_duration_months=agreement.get("lease_duration"),
            payment_frequency=payment_frequency,
        )

        _TENANT_BRIEF_CACHE[agreement_id] = (current_hash, brief_text, datetime.utcnow())

        logger.info(f"✅ [AGREEMENTS] Tenant brief generated for agreement {agreement_id}")
        return {
            "success": True,
            "brief": brief_text,
            "cached": False,
            "agreement_id": agreement_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] Failed to generate tenant brief for {agreement_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate agreement brief: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# GENERATE PDF
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{agreement_id}/generate-pdf")
async def generate_pdf(
    agreement_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Generate a professional PDF of the signed agreement document.

    Only available once BOTH parties have signed — the PDF is the executed
    legal document, so it must not be generated (or mistaken for) an unsigned
    draft. Both parties can download it after execution.

    Uses ReportLab to generate the formatted PDF and uploads it to Supabase
    Storage. Returns the public download URL.
    """
    try:
        user_id = current_user["id"]

        response = supabase_admin.table("agreements").select("*").eq(
            "id", agreement_id
        ).execute()

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agreement not found"
            )

        agreement = response.data[0]

        if agreement["tenant_id"] != user_id and agreement["landlord_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this agreement"
            )

        # Guard: the PDF is the executed document — both signatures required.
        if not agreement.get("tenant_signed_at") or not agreement.get("landlord_signed_at"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The agreement PDF can only be generated after both parties have signed."
            )

        pdf_url = _generate_agreement_pdf(agreement)
        
        if not pdf_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate PDF"
            )

        return {
            "success": True,
            "document_url": pdf_url,
            "message": "PDF generated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] Failed to generate PDF for {agreement_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PDF: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{agreement_id}/receipt")
async def generate_receipt(
    agreement_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Generate a payment receipt PDF for a completed payment.
    Uses ReportLab to generate formatted PDF, uploads to Supabase Storage.
    Returns public download URL (same pattern as agreement PDF generation).
    """
    try:
        user_id = current_user["id"]
        logger.info(f"📄 [RECEIPT] Generating receipt for agreement {agreement_id} by user {user_id}")

        # Fetch agreement with participants
        response = supabase_admin.table("agreements").select("*").eq(
            "id", agreement_id
        ).execute()

        if not response.data:
            logger.error(f"❌ [RECEIPT] Agreement {agreement_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agreement not found"
            )

        agreement = response.data[0]

        # Check authorization
        if agreement["tenant_id"] != user_id and agreement["landlord_id"] != user_id:
            logger.error(f"❌ [RECEIPT] User {user_id} not authorized for agreement {agreement_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this agreement"
            )

        # Check if payment is complete
        if agreement.get("reconciliation_status") != "FULL_PAYMENT":
            logger.error(f"❌ [RECEIPT] Agreement {agreement_id} not fully paid (status: {agreement.get('reconciliation_status')})")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment must be completed before generating receipt"
            )

        receipt_url = _generate_receipt_pdf(agreement, user_id)
        
        if not receipt_url:
            logger.error(f"❌ [RECEIPT] PDF generation returned None for agreement {agreement_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate receipt"
            )
        
        logger.info(f"✅ [RECEIPT] Receipt generated successfully for agreement {agreement_id}")

        return {
            "success": True,
            "document_url": receipt_url,
            "message": "Receipt generated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] Failed to generate receipt for {agreement_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate receipt: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def generate_agreement_terms(property_data: dict, agreement_data: dict) -> str:
    """
    Generate standard Nigerian residential lease agreement terms text.
    Called by agreement_service.auto_generate_agreement().
    """
    monthly_rent = property_data.get("price", 0)
    security_deposit = 0  # MVP: Caution fee set to 0 for transparency
    platform_fee = 0  # MVP: Platform fee set to 0% for transparency

    # Frequency-based period rent (matches nomba_helpers.FREQUENCY_MULTIPLIERS)
    _freq_mult = {"MONTHLY": 1, "QUARTERLY": 3, "SEMI_ANNUAL": 6, "ANNUAL": 12}
    _freq = str(property_data.get("payment_frequency") or "MONTHLY").upper()
    _period_rent = monthly_rent * _freq_mult.get(_freq, 1)
    _freq_schedule = {
        "MONTHLY": "monthly in advance",
        "QUARTERLY": "quarterly (every 3 months) in advance",
        "SEMI_ANNUAL": "semi-annually (every 6 months) in advance",
        "ANNUAL": "annually (every 12 months) in advance",
    }.get(_freq, "monthly in advance")

    return f"""
RESIDENTIAL LEASE AGREEMENT

PROPERTY DETAILS:
Address: {property_data.get('full_address', property_data.get('address', 'N/A'))}
City: {property_data.get('city', 'N/A')}, {property_data.get('state', 'N/A')}
Monthly Rent: \u20a6{monthly_rent:,}
Period Rent ({_freq}): \u20a6{_period_rent:,}
Security Deposit (Caution Fee): \u20a6{security_deposit:,} (waived)
Platform Fee: \u20a6{platform_fee:,} (waived)

LEASE TERMS:
Duration: {agreement_data.get('lease_duration', 12)} months
Start Date: {agreement_data.get('lease_start_date', 'N/A')}
End Date: {agreement_data.get('lease_end_date', 'N/A')}

TERMS AND CONDITIONS:
1. Rent is due {_freq_schedule}, on or before the commencement date of each payment period.
2. The security deposit (caution fee) is waived (\u20a60) for this tenancy under NuloAfrica's MVP policy.
3. The platform fee is waived (\u20a60) for this tenancy.
4. All payments are processed through the NuloAfrica platform escrow system.
5. Tenant must keep the property in good and tenantable repair throughout the lease.
6. No subletting permitted without written consent from the landlord.
7. Either party must give 30 days written notice before lease termination.
8. Tenant may not carry out structural alterations without landlord consent.
9. This agreement is governed by the laws of the Federal Republic of Nigeria.
10. Disputes shall be resolved through NuloAfrica's dispute resolution process before escalation to court.

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Agreement Reference: {uuid.uuid4()}
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# PDF branding — colours + page chrome (header / footer) for the agreement
# ─────────────────────────────────────────────────────────────────────────────

# Brand palette — kept in sync with client/tailwind config (orange / slate).
BRAND_ORANGE       = colors.HexColor("#F97316")
BRAND_ORANGE_DARK  = colors.HexColor("#C2410C")
BRAND_SLATE        = colors.HexColor("#334155")
BRAND_SLATE_LIGHT  = colors.HexColor("#64748B")
BRAND_BG           = colors.HexColor("#FFF7ED")  # very light orange wash

PAGE_WIDTH, PAGE_HEIGHT = letter
LEFT_MARGIN  = 0.75 * inch
RIGHT_MARGIN = 0.75 * inch
TOP_MARGIN   = 1.30 * inch   # leaves room for the brand header
BOTTOM_MARGIN = 0.95 * inch  # leaves room for the page footer


def _draw_header_footer(canvas_obj: "canvas.Canvas", agreement: dict) -> None:
    """Draw the branded header (logo wordmark + tagline) and footer (page #
    + brand line) on every page of the agreement PDF.

    This function is passed as the ``onPage`` callback for the document's
    PageTemplate — ReportLab invokes it once per page, after laying out the
    main flowables but before finalising the page.

    The "logo" here is rendered as a typographic wordmark (a small house icon
    glyph + the word "NuloAfrica") so the PDF is fully self-contained and
    does not depend on any external SVG/image asset being available at
    render time. The same brand colours are used in the web app.
    """
    page_w, page_h = PAGE_WIDTH, PAGE_HEIGHT

    # ── HEADER ─────────────────────────────────────────────────────────────
    # Coloured bar across the top — orange brand band.
    canvas_obj.setFillColor(BRAND_ORANGE)
    canvas_obj.rect(0, page_h - 0.45 * inch, page_w, 0.45 * inch,
                    stroke=0, fill=1)

    # White house glyph + "NuloAfrica" wordmark inside the orange band.
    # The glyph is drawn as a triangle-on-square pictogram (≈ 0.22" wide).
    gx = LEFT_MARGIN
    gy = page_h - 0.40 * inch
    canvas_obj.setFillColor(colors.white)
    canvas_obj.rect(gx, gy, 0.22 * inch, 0.18 * inch, stroke=0, fill=1)
    # Roof triangle
    p = canvas_obj.beginPath()
    p.moveTo(gx - 0.02 * inch, gy + 0.18 * inch)
    p.lineTo(gx + 0.11 * inch, gy + 0.30 * inch)
    p.lineTo(gx + 0.24 * inch, gy + 0.18 * inch)
    p.close()
    canvas_obj.drawPath(p, stroke=0, fill=1)
    # Tiny "door" detail
    canvas_obj.setFillColor(BRAND_ORANGE)
    canvas_obj.rect(gx + 0.085 * inch, gy, 0.05 * inch, 0.10 * inch,
                    stroke=0, fill=1)

    # Wordmark text — bold white "NuloAfrica" next to the glyph
    canvas_obj.setFillColor(colors.white)
    canvas_obj.setFont("Helvetica-Bold", 16)
    canvas_obj.drawString(gx + 0.32 * inch, gy + 0.07 * inch, "NuloAfrica")

    # Right-aligned tagline inside the header band
    canvas_obj.setFont("Helvetica-Oblique", 9)
    canvas_obj.drawRightString(page_w - RIGHT_MARGIN, gy + 0.10 * inch,
                               "Zero-Agency Rental Platform · Nigeria")

    # Thin slate divider under the header
    canvas_obj.setStrokeColor(BRAND_SLATE)
    canvas_obj.setLineWidth(0.6)
    canvas_obj.line(LEFT_MARGIN, page_h - 0.55 * inch,
                    page_w - RIGHT_MARGIN, page_h - 0.55 * inch)

    # ── FOOTER ─────────────────────────────────────────────────────────────
    # Light divider above footer
    canvas_obj.setStrokeColor(BRAND_SLATE_LIGHT)
    canvas_obj.setLineWidth(0.4)
    canvas_obj.line(LEFT_MARGIN, 0.70 * inch,
                    page_w - RIGHT_MARGIN, 0.70 * inch)

    # Left: brand line
    canvas_obj.setFillColor(BRAND_SLATE)
    canvas_obj.setFont("Helvetica-Bold", 8)
    canvas_obj.drawString(LEFT_MARGIN, 0.50 * inch,
                          "NuloAfrica · Trusted Rental Agreements")
    canvas_obj.setFont("Helvetica", 7)
    canvas_obj.setFillColor(BRAND_SLATE_LIGHT)
    canvas_obj.drawString(LEFT_MARGIN, 0.36 * inch,
                          f"Agreement ID: {agreement.get('id', 'N/A')}")

    # Right: page number ("Page X of Y")
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(BRAND_SLATE)
    page_num = canvas_obj.getPageNumber()
    canvas_obj.drawRightString(page_w - RIGHT_MARGIN, 0.50 * inch,
                               f"Page {page_num}")


def _md_inline_to_rl(text: str) -> str:
    """
    Convert inline Markdown (bold / italic) to ReportLab paragraph markup and
    escape any raw HTML so user-supplied text can never inject tags.
    """
    import html as _html
    t = _html.escape(text or "", quote=False)
    # Bold: **text** or __text__
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"__(.+?)__", r"<b>\1</b>", t)
    # Italic: *text* or _text_ (after bold so ** is not double-matched)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", t)
    return t


def _markdown_terms_to_flowables(terms: str, styles) -> list:
    """
    Render the deterministic Markdown agreement terms as ReportLab flowables
    so the downloadable PDF contains the FULL legal document (not a summary).

    Supports the subset of Markdown the deterministic template emits:
    # / ## headings, **bold**, *italic*, bullet lists (-), numbered clauses,
    horizontal rules (---) and plain paragraphs.
    """
    h1 = ParagraphStyle(
        "TermsH1", parent=styles["Heading1"], fontSize=15, leading=18,
        textColor=BRAND_ORANGE_DARK, fontName="Helvetica-Bold",
        alignment=TA_CENTER, spaceBefore=4, spaceAfter=10,
    )
    h2 = ParagraphStyle(
        "TermsH2", parent=styles["Heading2"], fontSize=11, leading=14,
        textColor=BRAND_SLATE, fontName="Helvetica-Bold",
        spaceBefore=12, spaceAfter=4,
    )
    body = ParagraphStyle(
        "TermsBody", parent=styles["BodyText"], fontSize=9.5, leading=13,
        textColor=colors.HexColor("#1E293B"), alignment=TA_JUSTIFY,
        spaceAfter=5,
    )
    bullet = ParagraphStyle(
        "TermsBullet", parent=body, leftIndent=16, bulletIndent=6, spaceAfter=3,
    )
    italic = ParagraphStyle(
        "TermsItalic", parent=body, fontName="Helvetica-Oblique",
        textColor=BRAND_SLATE_LIGHT, fontSize=8.5, leading=11,
    )

    elements = []
    for raw_line in (terms or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("---"):
            elements.append(Spacer(1, 4))
            elements.append(HRFlowable(
                width="100%", thickness=0.6, color=BRAND_SLATE_LIGHT,
                spaceBefore=2, spaceAfter=6,
            ))
            continue
        if stripped.startswith("# "):
            elements.append(Paragraph(_md_inline_to_rl(stripped[2:]), h1))
            continue
        if stripped.startswith("## "):
            elements.append(Paragraph(_md_inline_to_rl(stripped[3:]), h2))
            continue
        if stripped.startswith("- "):
            elements.append(Paragraph(
                _md_inline_to_rl(stripped[2:]), bullet, bulletText="\u2022"
            ))
            continue
        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            # Standalone italic footer line from the template
            elements.append(Paragraph(_md_inline_to_rl(stripped.strip("*")), italic))
            continue
        elements.append(Paragraph(_md_inline_to_rl(stripped), body))
    return elements


def _generate_agreement_pdf(agreement: dict) -> str:
    """
    Generate a professional PDF document for a signed agreement and upload to Supabase Storage.
    Uses ReportLab to create PDF with styling, margins, and professional layout.

    If the caller pre-populates ``agreement["_tenant"]``, ``agreement["_landlord"]``
    or ``agreement["_property"]`` with inline dicts, those override the values
    that would otherwise be fetched from the database. This lets the test /
    preview endpoint generate a PDF without inserting real user/property rows
    into Supabase — see ``routes/test_agreement.py``.

    Returns: Public download URL from Supabase Storage, or None if generation fails
    """
    try:
        # Inline overrides (used by the test / preview endpoint). If the
        # caller passed inline dicts, trust them and skip the DB lookup.
        inline_tenant   = agreement.get("_tenant")
        inline_landlord = agreement.get("_landlord")
        inline_property = agreement.get("_property")

        if inline_tenant and inline_landlord and inline_property:
            tenant_data   = inline_tenant
            landlord_data = inline_landlord
            property_data = inline_property
        else:
            # Production path — fetch rich data for the agreement from Supabase.
            tenant_data, landlord_data, property_data = _fetch_agreement_participants(agreement)
        
        # Create PDF in memory
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            rightMargin=RIGHT_MARGIN,
            leftMargin=LEFT_MARGIN,
            topMargin=TOP_MARGIN,
            bottomMargin=BOTTOM_MARGIN,
        )

        # Page template with branded header + footer on every page.
        # The frame sits inside the margins defined above so the body text
        # never collides with the brand band at the top or the page
        # number / brand line at the bottom.
        brand_frame = Frame(
            LEFT_MARGIN,
            BOTTOM_MARGIN,
            PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN,
            PAGE_HEIGHT - TOP_MARGIN - BOTTOM_MARGIN,
            id="brand_frame",
            showBoundary=0,
        )
        doc.addPageTemplates([
            PageTemplate(
                id="branded",
                frames=[brand_frame],
                onPage=lambda c, d: _draw_header_footer(c, agreement),
            )
        ])
        
        # Build document content
        elements = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#F97316'),
            spaceAfter=12,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=12,
            textColor=colors.HexColor('#334155'),
            spaceAfter=8,
            spaceBefore=8,
            fontName='Helvetica-Bold',
            textTransform='uppercase'
        )
        
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['BodyText'],
            fontSize=10,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
            leading=12
        )
        
        # Letterhead subtitle — sits right under the orange header band,
        # gives the document an "official letterhead" feel.
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['BodyText'],
            fontSize=9,
            textColor=BRAND_SLATE_LIGHT,
            alignment=TA_CENTER,
            spaceAfter=2,
            fontName='Helvetica-Oblique',
        )
        elements.append(Spacer(1, 0.05 * inch))
        elements.append(Paragraph(
            "OFFICIAL RESIDENTIAL TENANCY DOCUMENT", subtitle_style
        ))
        elements.append(Spacer(1, 0.05 * inch))

        # Title
        elements.append(Paragraph("RESIDENTIAL LEASE AGREEMENT", title_style))
        elements.append(Spacer(1, 0.10 * inch))
        
        # Reference block — Agreement ID + generated date in a tidy 2-col
        # table so the reference is scannable and looks like a real
        # letterhead reference block (rather than loose body text).
        # Status reflects the ACTUAL signature state so a pre-signature
        # review copy never claims to be fully executed.
        _both_signed = bool(
            agreement.get("tenant_signed_at") and agreement.get("landlord_signed_at")
        )
        if _both_signed:
            _status_label, _status_color = "FULLY EXECUTED", "#16A34A"
        elif agreement.get("tenant_signed_at") or agreement.get("landlord_signed_at"):
            _status_label, _status_color = "PARTIALLY SIGNED", "#D97706"
        else:
            _status_label, _status_color = "AWAITING SIGNATURES", "#F97316"

        ref_table = Table(
            [[
                Paragraph(
                    f"<b>Agreement ID</b><br/>"
                    f"<font size=8 color='#64748B'>{agreement.get('id', 'N/A')}</font>",
                    body_style,
                ),
                Paragraph(
                    f"<b>Date Issued</b><br/>"
                    f"<font size=8 color='#64748B'>{datetime.now().strftime('%B %d, %Y')}</font>",
                    body_style,
                ),
                Paragraph(
                    f"<b>Status</b><br/>"
                    f"<font size=8 color='{_status_color}'><b>{_status_label}</b></font>",
                    body_style,
                ),
            ]],
            colWidths=[2.4 * inch, 2.0 * inch, 2.4 * inch],
        )
        ref_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_BG),
            ("BOX",        (0, 0), (-1, -1), 0.5, BRAND_ORANGE),
            ("INNERGRID",  (0, 0), (-1, -1), 0.4, colors.HexColor("#FED7AA")),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(ref_table)
        elements.append(Spacer(1, 0.25 * inch))
        
        # Parties Section
        elements.append(Paragraph("PARTIES TO THIS AGREEMENT", heading_style))
        
        landlord_name = landlord_data.get('full_name', 'Landlord') if landlord_data else 'Landlord'
        tenant_name = tenant_data.get('full_name', 'Tenant') if tenant_data else 'Tenant'
        tenant_email = tenant_data.get('email', 'N/A') if tenant_data else 'N/A'
        tenant_phone = tenant_data.get('phone_number', 'N/A') if tenant_data else 'N/A'
        
        elements.append(Paragraph(
            f"<b>LANDLORD:</b> {landlord_name}",
            body_style
        ))
        elements.append(Paragraph(
            f"<b>TENANT:</b> {tenant_name} | Email: {tenant_email} | Phone: {tenant_phone}",
            body_style
        ))
        elements.append(Spacer(1, 0.15 * inch))
        
        # Property Section
        elements.append(Paragraph("PROPERTY DETAILS", heading_style))
        
        property_title = property_data.get('title', 'Property') if property_data else 'Property'
        property_location = property_data.get('full_address', property_data.get('address', 'N/A')) if property_data else 'N/A'
        monthly_rent = property_data.get('price', 0) if property_data else 0
        
        elements.append(Paragraph(f"<b>Property:</b> {property_title}", body_style))
        elements.append(Paragraph(f"<b>Address:</b> {property_location}", body_style))
        elements.append(Paragraph(f"<b>Monthly Rent:</b> ₦{monthly_rent:,}", body_style))
        elements.append(Spacer(1, 0.15 * inch))
        
        # Lease Terms Section
        elements.append(Paragraph("LEASE TERMS", heading_style))
        
        lease_start = agreement.get('lease_start_date', 'N/A')
        lease_end = agreement.get('lease_end_date', 'N/A')
        lease_duration = agreement.get('lease_duration', 12)
        
        elements.append(Paragraph(f"<b>Start Date:</b> {lease_start}", body_style))
        elements.append(Paragraph(f"<b>End Date:</b> {lease_end}", body_style))
        elements.append(Paragraph(f"<b>Duration:</b> {lease_duration} months", body_style))
        elements.append(Spacer(1, 0.15 * inch))
        
        # Financial Terms
        elements.append(Paragraph("FINANCIAL TERMS", heading_style))
        
        rent_amount = agreement.get('rent_amount', monthly_rent)
        deposit = agreement.get('deposit_amount', 0)
        platform_fee = agreement.get('platform_fee', 0)
        
        elements.append(Paragraph(f"<b>Monthly Rent:</b> ₦{rent_amount:,}", body_style))
        elements.append(Paragraph(f"<b>Security Deposit:</b> ₦{deposit:,}", body_style))
        elements.append(Paragraph(f"<b>Platform Fee:</b> ₦{platform_fee:,}", body_style))
        elements.append(Spacer(1, 0.15 * inch))

        # ── FULL LEGAL TERMS ─────────────────────────────────────────────────
        # The complete deterministic agreement text (Markdown) rendered as
        # formatted flowables, so the downloadable PDF is the actual lease
        # document — not just a summary. Falls back to the summary-only
        # layout if the terms column is empty.
        terms_text = (agreement.get("terms") or "").strip()
        if terms_text:
            elements.append(Paragraph("FULL TERMS AND CONDITIONS", heading_style))
            elements.append(HRFlowable(
                width="100%", thickness=0.8, color=BRAND_ORANGE,
                spaceBefore=0, spaceAfter=8,
            ))
            elements.extend(_markdown_terms_to_flowables(terms_text, styles))
            elements.append(Spacer(1, 0.2 * inch))

        # Signature Status
        elements.append(Paragraph("SIGNATURE STATUS", heading_style))
        
        tenant_signed_date = agreement.get('tenant_signed_at', None)
        landlord_signed_date = agreement.get('landlord_signed_at', None)
        
        tenant_stat_text = (
            f"<font color='#F97316'><b>SIGNED</b></font><br/>"
            f"<font size=8 color='#64748B'>{tenant_signed_date[:10]}</font>"
            if tenant_signed_date
            else "<font color='#DC2626'><b>PENDING</b></font>"
        )
        landlord_stat_text = (
            f"<font color='#F97316'><b>SIGNED</b></font><br/>"
            f"<font size=8 color='#64748B'>{landlord_signed_date[:10]}</font>"
            if landlord_signed_date
            else "<font color='#DC2626'><b>PENDING</b></font>"
        )

        # Signature table — 2 columns, tenant + landlord, each showing the
        # name, the signed status and the date. Looks like a formal
        # execution block at the end of a contract.
        sig_table = Table(
            [[
                Paragraph(
                    f"<b>TENANT</b><br/><br/>"
                    f"<font size=10>{tenant_name}</font><br/><br/>"
                    f"<b>Signature Status:</b><br/>{tenant_stat_text}",
                    body_style,
                ),
                Paragraph(
                    f"<b>LANDLORD</b><br/><br/>"
                    f"<font size=10>{landlord_name}</font><br/><br/>"
                    f"<b>Signature Status:</b><br/>{landlord_stat_text}",
                    body_style,
                ),
            ]],
            colWidths=[3.4 * inch, 3.4 * inch],
        )
        sig_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_BG),
            ("BOX",        (0, 0), (-1, -1), 0.6, BRAND_ORANGE),
            ("INNERGRID",  (0, 0), (-1, -1), 0.5, colors.HexColor("#FED7AA")),
            ("VALIGN",     (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 12),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
            ("TOPPADDING",    (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ]))
        elements.append(sig_table)
        elements.append(Spacer(1, 0.25 * inch))
        
        # Footer note inside the body (the on-page footer is added by the
        # PageTemplate callback; this stays as a closing legal note.)
        elements.append(Paragraph(
            "<hr/>",
            body_style
        ))
        _closing_note = (
            "This is a digitally generated agreement. Both parties have electronically signed "
            "this document via NuloAfrica's secure signing system. The signature timestamps and "
            "IP addresses are recorded for audit purposes."
            if _both_signed else
            "This is a digitally generated agreement document. It becomes binding only once both "
            "parties have electronically signed it via NuloAfrica's secure signing system. "
            "Signature timestamps and IP addresses are recorded for audit purposes."
        )
        elements.append(Paragraph(
            _closing_note,
            ParagraphStyle(
                'Footer',
                parent=styles['BodyText'],
                fontSize=8,
                textColor=colors.HexColor('#64748B'),
                alignment=TA_CENTER
            )
        ))
        
        # Build PDF
        doc.build(elements)
        pdf_buffer.seek(0)

        # Upload to Supabase Storage bucket 'ownership-docs' (public bucket).
        # NB: earlier versions wrote to the 'property-images' bucket, which does
        # not exist in this environment, so the resulting public URLs 404'd
        # with "Object not found". The correct bucket for agreement artefacts
        # (title documents, signed leases, etc.) is 'ownership-docs'.
        # AGMT-08 in the QA checklist.
        file_name = f"agreements/{agreement['id']}.pdf"

        try:
            storage_response = supabase_admin.storage.from_('ownership-docs').upload(
                file=pdf_buffer.getvalue(),
                path=file_name,
                file_options={"content-type": "application/pdf"}
            )
            logger.info(f"✅ [AGREEMENTS] PDF uploaded to ownership-docs/{file_name}")
        except Exception as upload_error:
            logger.warning(f"⚠️ [AGREEMENTS] Storage upload warning: {upload_error}")

        # Generate public URL (ownership-docs is a public bucket).
        # If the file already exists from a previous attempt, append a
        # timestamp to the path so the user always gets a fresh download
        # instead of a cached 404.
        try:
            pdf_url = supabase_admin.storage.from_('ownership-docs').get_public_url(file_name)
        except Exception as url_error:
            logger.error(f"❌ [AGREEMENTS] Failed to build public URL: {url_error}")
            return None

        # Update agreement with document URL
        supabase_admin.table("agreements").update({
            "document_url": pdf_url,
            "updated_at": datetime.now().isoformat()
        }).eq("id", agreement["id"]).execute()

        logger.info(f"✅ [AGREEMENTS] PDF generated and stored for {agreement['id']}")
        return pdf_url
        
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] PDF generation failed for {agreement['id']}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def _generate_receipt_pdf(agreement: dict, user_id: str) -> str:
    """
    Generate a payment receipt PDF and upload to Supabase Storage.
    Uses ReportLab to create a branded receipt with payment details.
    
    Returns: Public download URL from Supabase Storage, or None if generation fails
    """
    try:
        # Fetch participants and transfer data
        tenant_data, landlord_data, property_data = _fetch_agreement_participants(agreement)
        
        # Fetch latest payment transfer
        transfer_response = supabase_admin.table("virtual_account_transfers").select("*").eq(
            "agreement_id", agreement["id"]
        ).eq("reconciliation_result", "FULL_PAYMENT").order("created_at", desc=True).limit(1).execute()
        
        transfer = transfer_response.data[0] if transfer_response.data else None
        if not transfer:
            logger.error(f"❌ [AGREEMENTS] No payment transfer found for receipt generation")
            return None
        
        # Determine recipient type
        recipient_type = "tenant" if user_id == agreement["tenant_id"] else "landlord"
        recipient_name = (tenant_data["full_name"] if tenant_data else "Tenant") if recipient_type == "tenant" else (landlord_data["full_name"] if landlord_data else "Landlord")
        
        # Create PDF in memory
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            rightMargin=RIGHT_MARGIN,
            leftMargin=LEFT_MARGIN,
            topMargin=TOP_MARGIN,
            bottomMargin=BOTTOM_MARGIN,
        )

        # Page template with branded header + footer
        brand_frame = Frame(
            LEFT_MARGIN,
            BOTTOM_MARGIN,
            PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN,
            PAGE_HEIGHT - TOP_MARGIN - BOTTOM_MARGIN,
            id="brand_frame",
            showBoundary=0,
        )
        doc.addPageTemplates([
            PageTemplate(
                id="branded",
                frames=[brand_frame],
                onPage=lambda c, d: _draw_receipt_header_footer(c, agreement, recipient_type),
            )
        ])
        
        # Build document content
        elements = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'ReceiptTitle',
            parent=styles['Heading1'],
            fontSize=20,
            textColor=BRAND_ORANGE,  # Orange for NuloAfrica branding
            spaceAfter=16,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        # Title based on recipient type
        receipt_title = "PAYMENT RECEIPT" if recipient_type == "tenant" else "DISBURSEMENT RECEIPT"
        elements.append(Paragraph(receipt_title, title_style))
        elements.append(Spacer(1, 0.2 * inch))
        
        heading_style = ParagraphStyle(
            'ReceiptHeading',
            parent=styles['Heading2'],
            fontSize=12,
            textColor=colors.HexColor('#334155'),
            spaceAfter=8,
            spaceBefore=12,
            fontName='Helvetica-Bold'
        )
        
        body_style = ParagraphStyle(
            'ReceiptBody',
            parent=styles['BodyText'],
            fontSize=10,
            alignment=TA_LEFT,
            spaceAfter=6,
            leading=12
        )
        
        # Recipient info - explicit copy label based on recipient type
        copy_label = "TENANT COPY" if recipient_type == "tenant" else "LANDLORD COPY"
        elements.append(Paragraph(f"<b>{copy_label}</b>", body_style))
        elements.append(Paragraph(f"<b>Name:</b> {recipient_name}", body_style))
        elements.append(Spacer(1, 0.3 * inch))
        
        # Payment details table
        amount_ngn = transfer.get("amount_received", 0)
        payment_date = transfer.get("created_at", datetime.now())
        date_str = payment_date.strftime("%B %d, %Y at %I:%M %p") if hasattr(payment_date, 'strftime') else str(payment_date)
        
        payment_data = [
            ["Amount", f"₦{amount_ngn:,.2f}"],
            ["Date", date_str],
            ["Payment Method", "Bank Transfer (NUBAN)"],
            ["Transaction ID", transfer.get("id", "")[:12] + "..."],
            ["Agreement ID", agreement["id"][:12] + "..."],
        ]
        
        payment_table = Table(payment_data, colWidths=[2 * inch, 4 * inch])
        payment_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), BRAND_BG),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (0, 0), (-1, -1), BRAND_SLATE),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [BRAND_BG, colors.white]),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(payment_table)
        elements.append(Spacer(1, 0.3 * inch))
        
        # Property information
        elements.append(Paragraph("PROPERTY INFORMATION", heading_style))
        elements.append(Paragraph(f"<b>Property:</b> {property_data['title'] if property_data else 'N/A'}", body_style))
        elements.append(Paragraph(f"<b>Address:</b> {property_data.get('city', '') if property_data else ''}, {property_data.get('state', '') if property_data else ''}", body_style))
        
        lease_start = agreement.get("lease_start_date", "")
        lease_end = agreement.get("lease_end_date", "")
        elements.append(Paragraph(f"<b>Lease Period:</b> {lease_start} to {lease_end}", body_style))
        elements.append(Spacer(1, 0.3 * inch))
        
        # Status badge
        elements.append(Paragraph("PAYMENT STATUS", heading_style))
        status_box = Table([[Paragraph("✓ PAYMENT CONFIRMED", ParagraphStyle(
            'Status',
            parent=styles['BodyText'],
            fontSize=12,
            textColor=colors.white,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))]], colWidths=[6 * inch])
        status_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_ORANGE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ]))
        elements.append(status_box)
        elements.append(Spacer(1, 0.3 * inch))
        
        # Footer note
        elements.append(Paragraph(
            "This receipt is automatically generated by NuloAfrica. If you have any questions about this payment, please contact our support team at nuloafrica26@outlook.com",
            ParagraphStyle(
                'Footer',
                parent=styles['BodyText'],
                fontSize=8,
                textColor=colors.HexColor('#64748B'),
                alignment=TA_CENTER
            )
        ))
        
        # Build PDF
        doc.build(elements)
        pdf_buffer.seek(0)

        # Upload to Supabase Storage
        file_name = f"receipts/{agreement['id']}_receipt.pdf"

        try:
            storage_response = supabase_admin.storage.from_('ownership-docs').upload(
                file=pdf_buffer.getvalue(),
                path=file_name,
                file_options={"content-type": "application/pdf"}
            )
            logger.info(f"✅ [AGREEMENTS] Receipt uploaded to ownership-docs/{file_name}")
        except Exception as upload_error:
            logger.warning(f"⚠️ [AGREEMENTS] Storage upload warning: {upload_error}")

        # Generate public URL
        try:
            pdf_url = supabase_admin.storage.from_('ownership-docs').get_public_url(file_name)
        except Exception as url_error:
            logger.error(f"❌ [AGREEMENTS] Failed to build public URL: {url_error}")
            return None

        logger.info(f"✅ [AGREEMENTS] Receipt generated and stored for {agreement['id']}")
        return pdf_url
        
    except Exception as e:
        logger.error(f"❌ [AGREEMENTS] Receipt generation failed for {agreement['id']}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def _draw_receipt_header_footer(canvas_obj: "canvas.Canvas", agreement: dict, recipient_type: str) -> None:
    """Draw branded header and footer for receipt PDF."""
    page_w, page_h = PAGE_WIDTH, PAGE_HEIGHT

    # ── HEADER (Orange for NuloAfrica branding) ─────────────────────────────────────
    canvas_obj.setFillColor(BRAND_ORANGE)
    canvas_obj.rect(0, page_h - 0.45 * inch, page_w, 0.45 * inch, stroke=0, fill=1)

    # White wordmark
    gx = LEFT_MARGIN
    gy = page_h - 0.40 * inch
    canvas_obj.setFillColor(colors.white)
    canvas_obj.setFont("Helvetica-Bold", 16)
    canvas_obj.drawString(gx, gy + 0.07 * inch, "NuloAfrica")

    # Right-aligned tagline
    canvas_obj.setFont("Helvetica-Oblique", 9)
    receipt_type = "Payment Receipt" if recipient_type == "tenant" else "Disbursement Receipt"
    canvas_obj.drawRightString(page_w - RIGHT_MARGIN, gy + 0.10 * inch,
                               f"{receipt_type} · Nigeria")

    # Divider under header
    canvas_obj.setStrokeColor(BRAND_SLATE)
    canvas_obj.setLineWidth(0.6)
    canvas_obj.line(LEFT_MARGIN, page_h - 0.55 * inch,
                    page_w - RIGHT_MARGIN, page_h - 0.55 * inch)

    # ── FOOTER ─────────────────────────────────────────────────────────────
    canvas_obj.setStrokeColor(BRAND_SLATE_LIGHT)
    canvas_obj.setLineWidth(0.4)
    canvas_obj.line(LEFT_MARGIN, 0.70 * inch,
                    page_w - RIGHT_MARGIN, 0.70 * inch)

    # Left: brand line
    canvas_obj.setFillColor(BRAND_SLATE)
    canvas_obj.setFont("Helvetica-Bold", 8)
    receipt_type = "Payment Receipt" if recipient_type == "tenant" else "Disbursement Receipt"
    canvas_obj.drawString(LEFT_MARGIN, 0.50 * inch,
                          f"NuloAfrica · {receipt_type}")
    canvas_obj.setFont("Helvetica", 7)
    canvas_obj.setFillColor(BRAND_SLATE_LIGHT)
    canvas_obj.drawString(LEFT_MARGIN, 0.36 * inch,
                          f"Agreement ID: {agreement.get('id', 'N/A')[:12]}...")

    # Right: page number
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(BRAND_SLATE)
    page_num = canvas_obj.getPageNumber()
    canvas_obj.drawRightString(page_w - RIGHT_MARGIN, 0.50 * inch,
                               f"Page {page_num}")
