"""
PropFlow Node 5: Create Agreement  (maps to "Agreement Agent" step)

Responsibility:
  After landlord approval (INTERRUPT #1 has resumed), draft a rental
  agreement by delegating to the existing agreement_service.auto_generate_agreement().
  That service handles Groq AI generation with template fallback — we don't
  duplicate any of that logic here.

  Optionally uploads the agreement PDF to Alibaba Cloud OSS so both parties
  get a signed-URL download link (the mandatory hackathon proof file).

  Sets agreement_status = 'PENDING_TENANT' so the frontend knows to prompt
  the tenant to sign (INTERRUPT #2).

Architecture:
  - Wraps agreement_service.auto_generate_agreement() — already production-tested
  - OSS upload is non-blocking (graceful degradation if creds not set)
  - Rule 6: Supabase calls inside run_in_executor via the service layer
"""

import asyncio
import logging
import uuid
from typing import Optional

from app.propflow.state import PropFlowState

logger = logging.getLogger(__name__)


async def create_agreement_node(state: PropFlowState) -> PropFlowState:
    """
    Node 5 — Agreement Agent.

    Steps:
      1. Guard: only runs when application_status == 'approved'
      2. Fetch landlord name and tenant data for agreement generation
      3. Fetch property data for agreement terms
      4. Delegate to agreement_service.auto_generate_agreement()
      5. Optionally upload PDF to Alibaba Cloud OSS
      6. Return updated state with agreement_id and agreement_status

    Args:
        state: PropFlowState with application_id, selected_property_id,
               tenant_id, landlord_id, and application_status='approved'.

    Returns:
        Updated state with agreement_id, agreement_status='PENDING_TENANT',
        agreement_pdf_oss_key (if OSS available), and current_stage.
    """
    application_id = state.get("application_id")
    property_id    = state.get("selected_property_id")
    tenant_id      = str(state["tenant_id"])
    landlord_id    = str(state.get("landlord_id", ""))

    # ── Guard ─────────────────────────────────────────────────────────────────
    # If the application was rejected, return cleanly with current_stage="rejected"
    # so the graph's conditional edge (_route_after_agreement) routes to END
    # instead of proceeding to Nomba DVA provisioning.
    if state.get("application_status") != "approved":
        msg = (
            f"create_agreement: expected application_status='approved', "
            f"got '{state.get('application_status')}' — routing to END (rejected)"
        )
        logger.warning(f"[create_agreement] {msg}")
        return {
            **state,
            "error_log": state.get("error_log", []) + [msg],
            "current_stage": "rejected",
        }

    logger.info(
        f"[create_agreement] application={str(application_id)[:8]}... "
        f"tenant={tenant_id[:8]}..."
    )

    loop = asyncio.get_event_loop()

    try:
        from app.database import supabase_admin
    except Exception as exc:
        return {
            **state,
            "error_log": state.get("error_log", []) + [f"create_agreement: DB import failed: {exc}"],
            "current_stage": "error",
        }

    # ── Step 2: Fetch tenant + landlord + property in parallel ───────────────
    tenant_data, property_data, landlord_name = await asyncio.gather(
        _fetch_tenant(tenant_id, loop, supabase_admin),
        _fetch_property(str(property_id), loop, supabase_admin),
        _fetch_landlord_name(landlord_id, loop, supabase_admin),
    )

    if not property_data:
        msg = f"create_agreement: property {property_id} not found"
        logger.error(f"[create_agreement] {msg}")
        return {
            **state,
            "error_log": state.get("error_log", []) + [msg],
            "current_stage": "error",
        }

    # ── Step 3: Delegate to agreement_service ────────────────────────────────
    # agreement_service.auto_generate_agreement() handles:
    #   - Groq AI agreement text generation (with template fallback)
    #   - Supabase INSERT into agreements table
    #   - Standard Nigerian lease dates (start = tomorrow, 12 months)
    try:
        from app.services.agreement_service import agreement_service

        agreement = await agreement_service.auto_generate_agreement(
            application_id=str(application_id),
            property_data=property_data,
            tenant_data=tenant_data,
            landlord_name=landlord_name,
            propflow_workflow_id=state.get("workflow_id"),
        )
    except Exception as exc:
        msg = f"create_agreement: agreement_service failed: {exc}"
        logger.error(f"[create_agreement] {msg}")
        return {
            **state,
            "error_log": state.get("error_log", []) + [msg],
            "current_stage": "error",
        }

    if not agreement:
        msg = "create_agreement: agreement_service returned None"
        logger.error(f"[create_agreement] {msg}")
        return {
            **state,
            "error_log": state.get("error_log", []) + [msg],
            "current_stage": "error",
        }

    agreement_id     = uuid.UUID(agreement["id"])
    agreement_status = agreement.get("status", "PENDING_TENANT")

    logger.info(
        f"[create_agreement] Agreement created: {agreement_id} "
        f"status={agreement_status} "
        f"source={agreement.get('agreement_source', 'unknown')}"
    )

    # ── Step 4: Upload PDF to Alibaba Cloud OSS (optional) ───────────────────
    # The PDF is generated from agreement["terms"] (the text content).
    # If OSS is not configured this is a no-op — workflow continues.
    oss_key = await _upload_agreement_to_oss(
        agreement_id=str(agreement_id),
        agreement_terms=agreement.get("terms", ""),
        tenant_name=tenant_data.get("full_name", "Tenant"),
        property_title=property_data.get("title", "Property"),
    )

    # propflow_workflow_id is embedded in generation_metadata by
    # agreement_service.auto_generate_agreement() — no separate UPDATE needed.

    return {
        **state,
        "agreement_id":           agreement_id,
        "agreement_status":       agreement_status,
        "agreement_pdf_oss_key":  oss_key,
        "current_stage":          "agreement_drafted",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_tenant(tenant_id: str, loop, supabase_admin) -> dict:
    """Fetch tenant user row for agreement generation."""
    try:
        result = await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("users")
                .select("id, full_name, email, phone_number")
                .eq("id", tenant_id)
                .single()
                .execute(),
        )
        return result.data or {"id": tenant_id, "full_name": "Tenant", "email": ""}
    except Exception as exc:
        logger.warning(f"[create_agreement] tenant fetch failed: {exc}")
        return {"id": tenant_id, "full_name": "Tenant", "email": ""}


async def _fetch_property(property_id: str, loop, supabase_admin) -> Optional[dict]:
    """Fetch property data for agreement terms."""
    try:
        result = await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("properties")
                .select(
                    "id, title, location, full_address, address, "
                    "property_type, price, payment_frequency, landlord_id"
                )
                .eq("id", property_id)
                .single()
                .execute(),
        )
        return result.data or None
    except Exception as exc:
        logger.error(f"[create_agreement] property fetch failed: {exc}")
        return None


async def _fetch_landlord_name(landlord_id: str, loop, supabase_admin) -> str:
    """Fetch landlord full name for the agreement header."""
    if not landlord_id:
        return "Landlord"
    try:
        result = await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("users")
                .select("full_name")
                .eq("id", landlord_id)
                .single()
                .execute(),
        )
        return (result.data or {}).get("full_name") or "Landlord"
    except Exception as exc:
        logger.warning(f"[create_agreement] landlord name fetch failed: {exc}")
        return "Landlord"


async def _upload_agreement_to_oss(
    agreement_id: str,
    agreement_terms: str,
    tenant_name: str,
    property_title: str,
) -> Optional[str]:
    """
    Generate a minimal PDF from the agreement terms text and upload to OSS.
    Returns the OSS key on success, None if OSS is unavailable or upload fails.

    PDF generation uses reportlab (already in requirements.txt).
    This is the mandatory Alibaba Cloud proof: oss_client.py stores the file,
    and the judge can request a signed URL to verify the upload.
    """
    try:
        from app.propflow.services.oss_client import oss_client
        if not oss_client.available:
            logger.info("[create_agreement] OSS not configured — skipping PDF upload")
            return None

        # Generate PDF bytes from agreement text using reportlab
        pdf_bytes = _build_pdf(agreement_terms, tenant_name, property_title)
        if not pdf_bytes:
            return None

        oss_key = oss_client.upload_agreement_pdf(
            agreement_id=agreement_id,
            pdf_bytes=pdf_bytes,
        )
        if oss_key:
            logger.info(f"[create_agreement] PDF uploaded to OSS: {oss_key}")
        return oss_key

    except Exception as exc:
        logger.warning(f"[create_agreement] OSS upload failed (non-fatal): {exc}")
        return None


def _build_pdf(terms: str, tenant_name: str, property_title: str) -> Optional[bytes]:
    """
    Build a simple PDF from agreement terms using reportlab.
    Returns raw PDF bytes, or None if reportlab is unavailable.
    """
    try:
        import io
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        styles = getSampleStyleSheet()
        story = []

        # Title
        story.append(Paragraph("TENANCY AGREEMENT", styles["Title"]))
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(f"Property: {property_title}", styles["Heading2"]))
        story.append(Paragraph(f"Tenant: {tenant_name}", styles["Heading2"]))
        story.append(Spacer(1, 6 * mm))

        # Agreement terms — split into paragraphs on double newline
        for block in terms.split("\n\n"):
            text = block.replace("\n", "<br/>").strip()
            if text:
                story.append(Paragraph(text, styles["Normal"]))
                story.append(Spacer(1, 3 * mm))

        doc.build(story)
        return buffer.getvalue()

    except ImportError:
        logger.warning("[create_agreement] reportlab not installed — PDF skipped")
        return None
    except Exception as exc:
        logger.warning(f"[create_agreement] PDF build failed: {exc}")
        return None
