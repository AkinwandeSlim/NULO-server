"""
Test / preview router for the agreement PDF generator.

This module exists so the QA team (and any developer iterating on the
branded PDF layout) can trigger PDF generation WITHOUT going through the
full sign-agreement flow. It accepts a small JSON payload, synthesises a
minimal agreement record in memory, and runs it through the same
``_generate_agreement_pdf`` helper that the real signed-agreement path uses.

NO AUTH. NO DB WRITES. The only side effect is uploading a PDF to the
``ownership-docs`` bucket (the same bucket the real flow uses) so the
generated preview is reachable at the returned public URL exactly like a
genuine agreement PDF would be.

NB: deliberately not wired into ``app.main`` with a ``/api/v1`` prefix —
the route is exposed under ``/api/test`` so it's obviously a debug /
preview surface and cannot be mistaken for production traffic.
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Re-use the real generator — same code path, same brand chrome, same
# upload behaviour. This is the whole point of the endpoint: to give the
# QA team a fast feedback loop on the visual design.
from app.routes.agreements import _generate_agreement_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test", tags=["Test & Preview"])


# ─────────────────────────────────────────────────────────────────────────────
# Request model
# ─────────────────────────────────────────────────────────────────────────────

class TestAgreementRequest(BaseModel):
    """Minimal payload for the PDF preview endpoint.

    Every field is optional; sensible defaults are used so an empty POST
    body still produces a nicely-branded PDF the QA team can use to verify
    the layout end-to-end.
    """
    tenant_name: Optional[str] = Field(
        default="Aisha Okonkwo",
        description="Tenant's full name as it should appear on the agreement",
    )
    tenant_email: Optional[str] = Field(
        default="aisha.okonkwo@example.ng",
        description="Tenant email — printed in the parties block",
    )
    tenant_phone: Optional[str] = Field(
        default="+234 803 555 0123",
        description="Tenant phone — printed in the parties block",
    )
    landlord_name: Optional[str] = Field(
        default="Emeka Holdings Ltd",
        description="Landlord / property owner name",
    )
    property_title: Optional[str] = Field(
        default="2-Bedroom Apartment in Lekki Phase 1",
        description="Property marketing title",
    )
    property_address: Optional[str] = Field(
        default="14 Admiralty Way, Lekki Phase 1, Lagos, Nigeria",
        description="Full street address used in the property details block",
    )
    monthly_rent: Optional[int] = Field(
        default=750_000,
        description="Monthly rent in Naira (integer)",
    )
    lease_duration_months: Optional[int] = Field(
        default=12,
        description="Lease term in months",
    )
    # Optional signature controls — useful for verifying the
    # PENDING / SIGNED branches of the execution block without running the
    # real sign flow.
    tenant_signed: Optional[bool] = Field(
        default=True,
        description="If true, the tenant execution block shows SIGNED + a date",
    )
    landlord_signed: Optional[bool] = Field(
        default=True,
        description="If true, the landlord execution block shows SIGNED + a date",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Route
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/generate-agreement-simple")
async def generate_agreement_simple(payload: TestAgreementRequest):
    """Generate a branded PDF preview and return its public URL.

    Example::

        POST /api/test/generate-agreement-simple
        Content-Type: application/json

        {
          "tenant_name": "Jane Doe",
          "landlord_name": "Mr Smith",
          "monthly_rent": 500000
        }

    Response::

        {
          "success": true,
          "document_url": "https://...supabase.co/.../agreements/<id>.pdf",
          "preview_id": "<id>",
          "message": "Preview PDF generated. Open the URL in a browser to download."
        }
    """
    try:
        # ── Synthesise a minimal agreement record in memory ───────────────
        # We DON'T insert into the agreements table — this is a pure
        # preview. The PDF generator only reads the fields below, so
        # passing them as a plain dict is enough.
        preview_id = str(uuid.uuid4())
        now = datetime.now()
        lease_start = now.date()
        lease_end = (now + timedelta(days=30 * payload.lease_duration_months)).date()

        # Security deposit = 2 months (matches the rest of the app's
        # "caution fee = 2 months" rule from the QA checklist).
        deposit = int(payload.monthly_rent * 2)
        platform_fee = int(payload.monthly_rent * 0.05)

        agreement = {
            "id": preview_id,
            "tenant_id": "preview-tenant",
            "landlord_id": "preview-landlord",
            "property_id": "preview-property",
            "status": "SIGNED",
            "rent_amount": payload.monthly_rent,
            "deposit_amount": deposit,
            "platform_fee": platform_fee,
            "lease_start_date": lease_start.isoformat(),
            "lease_end_date": lease_end.isoformat(),
            "lease_duration": payload.lease_duration_months,
            "tenant_signed_at": (
                now.isoformat() if payload.tenant_signed else None
            ),
            "landlord_signed_at": (
                now.isoformat() if payload.landlord_signed else None
            ),
            # Inline minimal data dicts that match what the real
            # _fetch_agreement_participants() returns — the PDF
            # generator only reads these top-level fields, so the
            # inline form is sufficient.
            "_tenant": {
                "full_name":    payload.tenant_name,
                "email":        payload.tenant_email,
                "phone_number": payload.tenant_phone,
            },
            "_landlord": {
                "full_name": payload.landlord_name,
            },
            "_property": {
                "title":        payload.property_title,
                "full_address": payload.property_address,
                "address":      payload.property_address,
                "price":        payload.monthly_rent,
            },
        }

        logger.info(
            f"🧪 [TEST-PDF] Generating preview for agreement {preview_id} "
            f"(tenant={payload.tenant_name!r}, rent=₦{payload.monthly_rent:,})"
        )

        pdf_url = _generate_agreement_pdf(agreement)

        if not pdf_url:
            raise HTTPException(
                status_code=500,
                detail="PDF generation returned no URL — check server logs.",
            )

        return {
            "success": True,
            "document_url": pdf_url,
            "preview_id": preview_id,
            "message": (
                "Preview PDF generated successfully. Open the URL in a "
                "browser to download and inspect."
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [TEST-PDF] Preview generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
