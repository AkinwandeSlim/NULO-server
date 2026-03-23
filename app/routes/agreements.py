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
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, status
from app.database import supabase_admin
from app.middleware.auth import get_current_user, get_current_tenant, get_current_landlord
from app.services.notification_service import notification_service
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageTemplate
from reportlab.lib import colors
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

    try:
        r = supabase_admin.table("properties").select(
            "id, title, location, city, state, address, full_address, price, images"
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

        response = query.order("created_at", desc=True).execute()
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
                tenants_resp = supabase_admin.table("users").select(
                    "id, full_name, email, phone_number, avatar_url"
                ).in_("id", tenant_ids).execute()
                tenants_map = {u["id"]: u for u in tenants_resp.data}
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Batch fetch tenants failed: {e}")

        try:
            if landlord_ids:
                landlords_resp = supabase_admin.table("users").select(
                    "id, full_name, email, phone_number, avatar_url"
                ).in_("id", landlord_ids).execute()
                landlords_map = {u["id"]: u for u in landlords_resp.data}
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Batch fetch landlords failed: {e}")

        try:
            if property_ids:
                properties_resp = supabase_admin.table("properties").select(
                    "id, title, location, city, state, address, full_address, price, images"
                ).in_("id", property_ids).execute()
                properties_map = {p["id"]: p for p in properties_resp.data}
        except Exception as e:
            logger.warning(f"[AGREEMENTS] Batch fetch properties failed: {e}")

        # Attach pre-fetched data to each agreement
        enhanced = []
        for agreement in agreements:
            enhanced.append({
                **agreement,
                "tenant": tenants_map.get(agreement.get("tenant_id")),
                "landlord": landlords_map.get(agreement.get("landlord_id")),
                "property": properties_map.get(agreement.get("property_id")),
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

        response = supabase_admin.table("agreements").select("*").eq(
            "id", agreement_id
        ).execute()

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

        logger.info(f"✅ [AGREEMENTS] Returning agreement {agreement_id} to {user_type} {user_id}")
        return {
            "success": True,
            "agreement": enriched
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
# GENERATE PDF
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{agreement_id}/generate-pdf")
async def generate_pdf(
    agreement_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Generate professional PDF version of a fully signed agreement.
    Both tenant and landlord must have signed before PDF generation is allowed.
    Uses ReportLab to generate formatted PDF, uploads to Supabase Storage.
    Returns public download URL.
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

        if agreement["status"] != "SIGNED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agreement must be fully signed before generating PDF"
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
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def generate_agreement_terms(property_data: dict, agreement_data: dict) -> str:
    """
    Generate standard Nigerian residential lease agreement terms text.
    Called by agreement_service.auto_generate_agreement().
    """
    monthly_rent = property_data.get("price", 0)
    security_deposit = property_data.get("security_deposit", int(monthly_rent * 0.5))
    platform_fee = int(monthly_rent * 0.05)

    return f"""
RESIDENTIAL LEASE AGREEMENT

PROPERTY DETAILS:
Address: {property_data.get('full_address', property_data.get('address', 'N/A'))}
City: {property_data.get('city', 'N/A')}, {property_data.get('state', 'N/A')}
Monthly Rent: \u20a6{monthly_rent:,}
Security Deposit (Caution Fee): \u20a6{security_deposit:,}
Platform Fee: \u20a6{platform_fee:,}

LEASE TERMS:
Duration: {agreement_data.get('lease_duration', 12)} months
Start Date: {agreement_data.get('lease_start_date', 'N/A')}
End Date: {agreement_data.get('lease_end_date', 'N/A')}

TERMS AND CONDITIONS:
1. Rent is due annually in advance, on or before the lease start date.
2. Security deposit (caution fee) will be returned within 30 days of lease end, less any deductions for damages beyond normal wear and tear.
3. Platform fee is non-refundable and covers NuloAfrica transaction processing.
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


def _generate_agreement_pdf(agreement: dict) -> str:
    """
    Generate a professional PDF document for a signed agreement and upload to Supabase Storage.
    Uses ReportLab to create PDF with styling, margins, and professional layout.
    
    Returns: Public download URL from Supabase Storage, or None if generation fails
    """
    try:
        # Fetch rich data for the agreement
        tenant_data, landlord_data, property_data = _fetch_agreement_participants(agreement)
        
        # Create PDF in memory
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch
        )
        
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
        
        # Title
        elements.append(Paragraph("RESIDENTIAL LEASE AGREEMENT", title_style))
        elements.append(Spacer(1, 0.15 * inch))
        
        # Agreement ID and Date
        elements.append(Paragraph(f"<b>Agreement ID:</b> {agreement.get('id', 'N/A')}", body_style))
        elements.append(Paragraph(f"<b>Generated:</b> {datetime.now().strftime('%B %d, %Y')}", body_style))
        elements.append(Spacer(1, 0.2 * inch))
        
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
        
        # Signature Status
        elements.append(Paragraph("SIGNATURE STATUS", heading_style))
        
        tenant_signed_date = agreement.get('tenant_signed_at', None)
        landlord_signed_date = agreement.get('landlord_signed_at', None)
        
        tenant_stat = f"✓ Signed on {tenant_signed_date[:10]}" if tenant_signed_date else "✗ Pending"
        landlord_stat = f"✓ Signed on {landlord_signed_date[:10]}" if landlord_signed_date else "✗ Pending"
        
        elements.append(Paragraph(f"<b>Tenant Signature:</b> {tenant_stat}", body_style))
        elements.append(Paragraph(f"<b>Landlord Signature:</b> {landlord_stat}", body_style))
        elements.append(Spacer(1, 0.3 * inch))
        
        # Footer
        elements.append(Paragraph(
            "<hr/>",
            body_style
        ))
        elements.append(Paragraph(
            "This is a digitally generated agreement. Both parties have electronically signed this document.",
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
        
        # Upload to Supabase Storage (using public bucket for downloadable PDFs)
        file_name = f"agreements/{agreement['id']}.pdf"
        
        try:
            storage_response = supabase_admin.storage.from_('property-images').upload(
                file=pdf_buffer.getvalue(),
                path=file_name,
                file_options={"content-type": "application/pdf"}
            )
            logger.info(f"✅ [AGREEMENTS] PDF uploaded to property-images/{file_name}")
        except Exception as upload_error:
            logger.warning(f"⚠️ [AGREEMENTS] Storage upload warning: {upload_error}")
        
        # Generate public URL (property-images is public bucket)
        pdf_url = supabase_admin.storage.from_('property-images').get_public_url(file_name)
        
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