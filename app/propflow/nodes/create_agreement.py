"""
PropFlow Node 5: Create Agreement  (maps to "Agreement Agent" step)

Responsibility:
  After landlord approval (INTERRUPT #1 has resumed), draft a rental
  agreement by delegating to the existing agreement_service.auto_generate_agreement().
  That service handles Groq AI generation with template fallback — we don't
  duplicate any of that logic here.

  Optionally uploads the agreement PDF to Supabase Storage (ownership-docs
  bucket) so both parties can view the draft via a public URL.

  Sets agreement_status = 'PENDING_TENANT' so the frontend knows to prompt
  the tenant to sign (INTERRUPT #2).

Architecture:
  - Wraps agreement_service.auto_generate_agreement() — already production-tested
  - Supabase Storage upload is non-blocking (graceful degradation if unavailable)
  - Supabase reads offloaded to the thread pool via run_db_async (retry-aware),
    so a transient connection hiccup (HTTP/2 ConnectionTerminated, WinError
    10035, ...) is retried instead of aborting agreement creation.
"""

import asyncio
import logging
import uuid
from typing import Optional

from app.propflow.state import PropFlowState
from app.propflow.services.supabase_storage_client import storage_client

logger = logging.getLogger(__name__)


async def create_agreement_node(state: PropFlowState) -> PropFlowState:
    """
    Node 5 — Agreement Agent.

    Steps:
      1. Guard: only runs when application_status == 'approved'
      2. Fetch landlord name and tenant data for agreement generation
      3. Fetch property data for agreement terms
      4. Delegate to agreement_service.auto_generate_agreement()
      5. Optionally upload PDF to Supabase Storage
      6. Return updated state with agreement_id and agreement_status

    Args:
        state: PropFlowState with application_id, selected_property_id,
               tenant_id, landlord_id, and application_status='approved'.

    Returns:
        Updated state with agreement_id, agreement_status='PENDING_TENANT',
        agreement_pdf_storage_key + agreement_pdf_url (if storage available),
        and current_stage.
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

    try:
        from app.database import supabase_admin, run_db_async
    except Exception as exc:
        return {
            **state,
            "error_log": state.get("error_log", []) + [f"create_agreement: DB import failed: {exc}"],
            "current_stage": "error",
        }

    # ── Step 2: Fetch tenant + landlord + property in parallel ───────────────
    # Supabase reads are offloaded to the thread pool via run_db_async, which
    # retries transient socket/connection hiccups (e.g. HTTP/2
    # ConnectionTerminated on a stale keep-alive) before surfacing an error.
    # A transient failure here no longer kills agreement creation.
    tenant_data, property_data, landlord_data = await asyncio.gather(
        _fetch_tenant(tenant_id, supabase_admin, run_db_async),
        _fetch_property(str(property_id), supabase_admin, run_db_async),
        _fetch_landlord(landlord_id, supabase_admin, run_db_async),
    )
    landlord_name = landlord_data.get("full_name", "Landlord")

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
            landlord_email=landlord_data.get("email"),
            landlord_phone=landlord_data.get("phone_number"),
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

    # ── Step 4: Upload PDF to Supabase Storage (optional) ────────────────────
    # The PDF is generated from agreement["terms"] (the text content) and
    # stored in the public `ownership-docs` bucket. If storage is unavailable
    # this is a no-op — the workflow continues (draft simply not stored).
    storage_path = await _upload_agreement_to_supabase(
        agreement_id=str(agreement_id),
        agreement_terms=agreement.get("terms", ""),
        tenant_name=tenant_data.get("full_name", "Tenant"),
        property_title=property_data.get("title", "Property"),
    )

    # Build a public URL from the stored path so tenants/landlords can view
    # the draft PDF (ownership-docs is a public bucket → permanent URL).
    agreement_pdf_url = None
    if storage_path:
        agreement_pdf_url = storage_client.get_download_url(storage_path)

    # propflow_workflow_id is embedded in generation_metadata by
    # agreement_service.auto_generate_agreement() — no separate UPDATE needed.

    return {
        **state,
        "agreement_id":              agreement_id,
        "agreement_status":          agreement_status,
        "agreement_pdf_storage_key": storage_path,
        "agreement_pdf_url":         agreement_pdf_url,
        "current_stage":             "agreement_drafted",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_tenant(tenant_id: str, supabase_admin, run_db_async) -> dict:
    """Fetch tenant user row for agreement generation."""
    try:
        result = await run_db_async(
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


async def _fetch_property(property_id: str, supabase_admin, run_db_async) -> Optional[dict]:
    """Fetch property data for agreement terms."""
    try:
        result = await run_db_async(
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


async def _fetch_landlord(landlord_id: str, supabase_admin, run_db_async) -> dict:
    """Fetch landlord user row (name + contact details) for the agreement header."""
    if not landlord_id:
        return {"full_name": "Landlord"}
    try:
        result = await run_db_async(
            lambda: supabase_admin
                .table("users")
                .select("id, full_name, email, phone_number")
                .eq("id", landlord_id)
                .single()
                .execute(),
        )
        data = result.data or {}
        if not data.get("full_name"):
            data["full_name"] = "Landlord"
        return data
    except Exception as exc:
        logger.warning(f"[create_agreement] landlord fetch failed: {exc}")
        return {"full_name": "Landlord"}


async def _upload_agreement_to_supabase(
    agreement_id: str,
    agreement_terms: str,
    tenant_name: str,
    property_title: str,
) -> Optional[str]:
    """
    Generate a minimal PDF from the agreement terms text and upload it to
    Supabase Storage (ownership-docs bucket).
    Returns the storage path on success, None if storage is unavailable or
    the upload fails.

    PDF generation uses reportlab (already in requirements.txt).
    Mirrors the signed-PDF generator in app/routes/agreements.py which also
    writes to ownership-docs/agreements/{id}.pdf — PropFlow drafts use a
    sub-path with a timestamp/uuid suffix so they never clobber the final
    signed document.
    """
    try:
        from app.propflow.services.supabase_storage_client import storage_client

        # Generate PDF bytes from agreement text using reportlab
        pdf_bytes = _build_pdf(agreement_terms, tenant_name, property_title)
        if not pdf_bytes:
            return None

        path = await storage_client.upload_agreement_pdf(
            agreement_id=agreement_id,
            pdf_bytes=pdf_bytes,
        )
        if path:
            logger.info(
                f"[create_agreement] Draft PDF uploaded to Supabase Storage: {path}"
            )
        return path

    except Exception as exc:
        logger.warning(
            f"[create_agreement] Supabase Storage upload failed (non-fatal): {exc}"
        )
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
