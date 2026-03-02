"""
Payment routes -- Paystack integration
======================================

Endpoints (specific before wildcard -- Architecture Rule 7):
    POST   /payments/initiate          Tenant initiates payment for a signed agreement
    POST   /payments/webhook           Paystack webhook (no auth -- HMAC verified internally)
    GET    /payments/my-payments       Tenant payment history
    GET    /payments/received          Landlord received payments
    GET    /payments/{transaction_id}  Single transaction detail (tenant or landlord)

Key rules:
    - transactions.status    : pending | held | released | refunded | failed
    - transaction_type       : rent_payment | security_deposit | guarantee_contribution
    - Amount sent to Paystack: KOBO (multiply NGN by 100)
    - Webhook is the ONLY source of truth for payment confirmation
    - Frontend callback page must NOT confirm payment -- webhook already did
    - Always return 200 from webhook -- Paystack retries on any other status
    - No Unicode arrows/em-dashes in this file (Architecture Rule 17)
"""

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.database import supabase_admin
from app.middleware.auth import get_current_landlord, get_current_tenant, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _paystack_secret() -> str:
    secret = os.getenv("PAYSTACK_SECRET_KEY", "")
    if not secret:
        logger.error("[PAY] PAYSTACK_SECRET_KEY is not set")
    return secret


def _paystack_headers() -> dict:
    return {
        "Authorization": f"Bearer {_paystack_secret()}",
        "Content-Type": "application/json",
    }


def _generate_ref(agreement_id: str) -> str:
    """
    Stable, unique reference for Paystack.
    Format: NULO-<first 8 chars of agreement_id uppercase>-<8 random hex chars>
    Must be UNIQUE per transaction -- never reuse refs.
    """
    return f"NULO-{agreement_id[:8].upper()}-{uuid4().hex[:8].upper()}"


def _total_due(agreement: dict) -> int:
    """
    Compute totalDue in NGN (same formula used on the agreement detail pages).
    Returns an integer. Paystack receives this * 100 (kobo).

    annual rent + deposit + platform_fee + service_charge (nullable)
    """
    rent = float(agreement.get("rent_amount", 0) or 0)
    deposit = float(agreement.get("deposit_amount", 0) or 0)
    platform_fee = float(agreement.get("platform_fee", 0) or 0)
    service_charge = float(agreement.get("service_charge", 0) or 0)
    annual_rent = rent * 12
    return int(annual_rent + deposit + platform_fee + service_charge)


# -----------------------------------------------------------------------------
# Request / response models
# -----------------------------------------------------------------------------

class PaymentInitiateRequest(BaseModel):
    agreement_id: str


# -----------------------------------------------------------------------------
# POST /payments/initiate
# -----------------------------------------------------------------------------

@router.post("/initiate", response_model=dict)
async def initiate_payment(
    body: PaymentInitiateRequest,
    current_user: dict = Depends(get_current_tenant),
):
    """
    Tenant initiates payment for a fully-signed agreement.

    Steps:
    1. Fetch agreement -- must be SIGNED or ACTIVE, must belong to this tenant
    2. Fetch tenant email (required by Paystack)
    3. Calculate totalDue in NGN, convert to kobo for Paystack
    4. Generate unique paystack_ref
    5. Insert transactions row with status='pending'
    6. Call Paystack /transaction/initialize
    7. Return authorization_url + reference to frontend
    8. Fire notify_payment_initiated (in-app only -- tenant is about to leave)
    """
    tenant_id = current_user["id"]

    # -- 1. Fetch and validate agreement --------------------------------------
    try:
        agr_resp = supabase_admin.table("agreements").select(
            "id, tenant_id, landlord_id, property_id, application_id, "
            "status, rent_amount, deposit_amount, platform_fee, service_charge"
        ).eq("id", body.agreement_id).single().execute()
    except Exception as e:
        logger.error(f"[PAY] Agreement fetch error: {e}")
        raise HTTPException(status_code=404, detail="Agreement not found")

    if not agr_resp.data:
        raise HTTPException(status_code=404, detail="Agreement not found")

    agreement = agr_resp.data

    if agreement["tenant_id"] != tenant_id:
        raise HTTPException(status_code=403, detail="You do not have access to this agreement")

    if agreement["status"] not in ("SIGNED", "ACTIVE"):
        raise HTTPException(
            status_code=400,
            detail=f"Agreement must be SIGNED or ACTIVE to proceed to payment. Current status: {agreement['status']}"
        )

    # -- 2. Fetch tenant details for Paystack ---------------------------------
    try:
        tenant_resp = supabase_admin.table("users").select(
            "full_name, email, phone_number"
        ).eq("id", tenant_id).single().execute()
    except Exception as e:
        logger.error(f"[PAY] Tenant fetch error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch tenant details")

    tenant = tenant_resp.data or {}
    tenant_email = tenant.get("email")
    if not tenant_email:
        raise HTTPException(status_code=400, detail="Tenant email is required for payment")

    # -- 3. Fetch property title for notifications -----------------------------
    property_title = "Property"
    try:
        prop_resp = supabase_admin.table("properties").select("title").eq(
            "id", agreement["property_id"]
        ).single().execute()
        if prop_resp.data:
            property_title = prop_resp.data.get("title", "Property")
    except Exception as e:
        logger.warning(f"[PAY] Could not fetch property title: {e}")

    # -- 4. Calculate amount ---------------------------------------------------
    amount_ngn = _total_due(agreement)
    amount_kobo = amount_ngn * 100

    if amount_kobo <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")

    # -- 5. Generate unique reference -----------------------------------------
    paystack_ref = _generate_ref(body.agreement_id)

    # -- 6. Insert pending transaction -----------------------------------------
    base_url = os.getenv("BASE_URL", "http://localhost:3000")
    callback_url = f"{base_url}/tenant/payments/callback?reference={paystack_ref}"

    try:
        txn_resp = supabase_admin.table("transactions").insert({
            "tenant_id": tenant_id,
            "landlord_id": agreement["landlord_id"],
            "property_id": agreement["property_id"],
            "application_id": agreement.get("application_id"),
            "amount": amount_ngn,
            "currency": "NGN",
            "status": "pending",
            "transaction_type": "rent_payment",
            "payment_gateway": "paystack",
            "paystack_ref": paystack_ref,
        }).execute()
    except Exception as e:
        logger.error(f"[PAY] Failed to insert transaction: {e}")
        raise HTTPException(status_code=500, detail="Failed to create payment record")

    if not txn_resp.data:
        raise HTTPException(status_code=500, detail="Failed to create payment record")

    transaction_id = txn_resp.data[0]["id"]

    # -- 7. Call Paystack initialize -------------------------------------------
    paystack_payload = {
        "email": tenant_email,
        "amount": amount_kobo,
        "reference": paystack_ref,
        "callback_url": callback_url,
        "metadata": {
            "transaction_id": transaction_id,
            "agreement_id": body.agreement_id,
            "property_title": property_title,
            "tenant_name": tenant.get("full_name", ""),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            ps_resp = await client.post(
                "https://api.paystack.co/transaction/initialize",
                headers=_paystack_headers(),
                json=paystack_payload,
            )
        ps_data = ps_resp.json()
    except Exception as e:
        # Roll back the pending transaction so tenant can retry cleanly
        try:
            supabase_admin.table("transactions").update(
                {"status": "failed", "notes": f"Paystack init error: {str(e)}"}
            ).eq("id", transaction_id).execute()
        except Exception:
            pass
        logger.error(f"[PAY] Paystack initialize failed: {e}")
        raise HTTPException(status_code=502, detail="Payment gateway error. Please try again.")

    if not ps_data.get("status"):
        # Mark as failed and surface Paystack's error message
        try:
            supabase_admin.table("transactions").update(
                {"status": "failed", "notes": json.dumps(ps_data)}
            ).eq("id", transaction_id).execute()
        except Exception:
            pass
        logger.error(f"[PAY] Paystack rejected init: {ps_data}")
        raise HTTPException(
            status_code=400,
            detail=ps_data.get("message", "Payment initialization failed")
        )

    authorization_url = ps_data["data"]["authorization_url"]
    access_code = ps_data["data"].get("access_code", "")

    # Store access_code for future reference
    try:
        supabase_admin.table("transactions").update(
            {"paystack_access_code": access_code}
        ).eq("id", transaction_id).execute()
    except Exception as e:
        logger.warning(f"[PAY] Could not save access_code: {e}")

    # -- 8. Fire in-app notifications (non-fatal) ------------------------------
    try:
        from app.services.notification_service import notification_service

        # Fetch landlord details for notification
        landlord_name = "Landlord"
        try:
            ll_resp = supabase_admin.table("users").select("full_name").eq(
                "id", agreement["landlord_id"]
            ).single().execute()
            if ll_resp.data:
                landlord_name = ll_resp.data.get("full_name", "Landlord")
        except Exception:
            pass

        await notification_service.notify_payment_initiated(
            transaction_id=transaction_id,
            agreement_id=body.agreement_id,
            property_title=property_title,
            amount_ngn=amount_ngn,
            tenant_id=tenant_id,
            tenant_name=tenant.get("full_name", "Tenant"),
            landlord_id=agreement["landlord_id"],
            landlord_name=landlord_name,
        )
    except Exception as e:
        logger.warning(f"[PAY] notify_payment_initiated failed (non-fatal): {e}")

    logger.info(
        f"[PAY] Payment initiated -- transaction {transaction_id}, "
        f"ref {paystack_ref}, amount NGN {amount_ngn}"
    )

    return {
        "success": True,
        "authorization_url": authorization_url,
        "reference": paystack_ref,
        "transaction_id": transaction_id,
        "amount_ngn": amount_ngn,
    }


# -----------------------------------------------------------------------------
# POST /payments/webhook
# -----------------------------------------------------------------------------

@router.post("/webhook")
async def paystack_webhook(request: Request):
    """
    Paystack webhook handler.

    CRITICAL RULES:
    - Always return 200. Paystack retries on any other status.
    - Verify HMAC signature FIRST. Reject silently (200) on failure -- do not
      return 4xx to Paystack as that triggers retries.
    - Only process 'charge.success' events.
    - This is the ONLY place that marks a payment as confirmed.
    - Frontend callback page must NOT confirm payment.
    """
    body_bytes = await request.body()
    signature_header = request.headers.get("x-paystack-signature", "")

    # -- HMAC verification -----------------------------------------------------
    secret = _paystack_secret()
    if secret:
        expected = hmac.new(
            secret.encode("utf-8"),
            body_bytes,
            hashlib.sha512,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature_header):
            logger.warning("[PAY][WEBHOOK] Invalid signature -- ignoring request")
            # Return 200 so Paystack does not retry (it's not a transient error)
            return {"status": "ok"}
    else:
        logger.warning("[PAY][WEBHOOK] PAYSTACK_SECRET_KEY not set -- skipping HMAC check")

    # -- Parse event -----------------------------------------------------------
    try:
        event = json.loads(body_bytes)
    except Exception:
        logger.warning("[PAY][WEBHOOK] Could not parse body as JSON")
        return {"status": "ok"}

    event_type = event.get("event", "")
    data = event.get("data", {})

    logger.info(f"[PAY][WEBHOOK] Received event: {event_type}")

    # Only handle successful charges
    if event_type != "charge.success":
        return {"status": "ok"}

    paystack_ref = data.get("reference", "")
    if not paystack_ref:
        logger.warning("[PAY][WEBHOOK] charge.success with no reference -- ignoring")
        return {"status": "ok"}

    # -- Fetch transaction by reference ----------------------------------------
    try:
        txn_resp = supabase_admin.table("transactions").select(
            "id, status, tenant_id, landlord_id, property_id, application_id, amount"
        ).eq("paystack_ref", paystack_ref).single().execute()
    except Exception as e:
        logger.error(f"[PAY][WEBHOOK] Failed to fetch transaction for ref {paystack_ref}: {e}")
        return {"status": "ok"}

    if not txn_resp.data:
        logger.warning(f"[PAY][WEBHOOK] No transaction found for ref {paystack_ref}")
        return {"status": "ok"}

    transaction = txn_resp.data

    # Idempotency -- do not process an already-released transaction twice
    if transaction["status"] == "released":
        logger.info(f"[PAY][WEBHOOK] Transaction {transaction['id']} already released -- skipping")
        return {"status": "ok"}

    now_iso = datetime.now(timezone.utc).isoformat()

    # -- Mark transaction as released -----------------------------------------
    try:
        supabase_admin.table("transactions").update({
            "status": "released",
            "released_at": now_iso,
            "notes": json.dumps({
                "paystack_event": event_type,
                "paystack_data": data,
                "processed_at": now_iso,
            }),
            "updated_at": now_iso,
        }).eq("id", transaction["id"]).execute()
    except Exception as e:
        logger.error(f"[PAY][WEBHOOK] Failed to update transaction {transaction['id']}: {e}")
        return {"status": "ok"}

    # -- Update agreement status to ACTIVE ------------------------------------
    try:
        supabase_admin.table("agreements").update({
            "status": "ACTIVE",
            "updated_at": now_iso,
        }).eq("tenant_id", transaction["tenant_id"]).eq(
            "property_id", transaction["property_id"]
        ).in_("status", ["SIGNED", "ACTIVE"]).execute()
    except Exception as e:
        logger.warning(f"[PAY][WEBHOOK] Could not update agreement status: {e}")

    # -- Update property status to occupied -----------------------------------
    try:
        supabase_admin.table("properties").update({
            "status": "occupied",
            "updated_at": now_iso,
        }).eq("id", transaction["property_id"]).execute()
    except Exception as e:
        logger.warning(f"[PAY][WEBHOOK] Could not update property status: {e}")

    # -- Fire payment confirmed notifications ----------------------------------
    try:
        from app.services.notification_service import notification_service

        # Fetch tenant details
        tenant_name = "Tenant"
        tenant_email = None
        tenant_phone = None
        try:
            t_resp = supabase_admin.table("users").select(
                "full_name, email, phone_number"
            ).eq("id", transaction["tenant_id"]).single().execute()
            if t_resp.data:
                tenant_name = t_resp.data.get("full_name", "Tenant")
                tenant_email = t_resp.data.get("email")
                tenant_phone = t_resp.data.get("phone_number")
        except Exception:
            pass

        # Fetch landlord details
        landlord_name = "Landlord"
        landlord_email = None
        landlord_phone = None
        try:
            ll_resp = supabase_admin.table("users").select(
                "full_name, email, phone_number"
            ).eq("id", transaction["landlord_id"]).single().execute()
            if ll_resp.data:
                landlord_name = ll_resp.data.get("full_name", "Landlord")
                landlord_email = ll_resp.data.get("email")
                landlord_phone = ll_resp.data.get("phone_number")
        except Exception:
            pass

        # Fetch property title
        property_title = "Property"
        try:
            p_resp = supabase_admin.table("properties").select("title").eq(
                "id", transaction["property_id"]
            ).single().execute()
            if p_resp.data:
                property_title = p_resp.data.get("title", "Property")
        except Exception:
            pass

        await notification_service.notify_payment_confirmed(
            transaction_id=transaction["id"],
            property_title=property_title,
            amount_ngn=int(transaction.get("amount", 0)),
            tenant_id=transaction["tenant_id"],
            tenant_name=tenant_name,
            tenant_email=tenant_email,
            tenant_phone=tenant_phone,
            landlord_id=transaction["landlord_id"],
            landlord_name=landlord_name,
            landlord_email=landlord_email,
            landlord_phone=landlord_phone,
        )
    except Exception as e:
        logger.error(f"[PAY][WEBHOOK] notify_payment_confirmed failed (non-fatal): {e}")

    logger.info(
        f"[PAY][WEBHOOK] Payment confirmed -- transaction {transaction['id']}, "
        f"ref {paystack_ref}"
    )

    return {"status": "ok"}


# -----------------------------------------------------------------------------
# GET /payments/my-payments  (tenant)
# -----------------------------------------------------------------------------

@router.get("/my-payments")
async def get_my_payments(
    current_user: dict = Depends(get_current_tenant),
):
    """Tenant's full payment history, newest first."""
    try:
        resp = supabase_admin.table("transactions").select(
            "*, property:properties(id, title, city, state, images)"
        ).eq("tenant_id", current_user["id"]).order("created_at", desc=True).execute()

        return {"success": True, "payments": resp.data or []}
    except Exception as e:
        logger.error(f"[PAY] get_my_payments error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch payment history")


# -----------------------------------------------------------------------------
# GET /payments/received  (landlord)
# -----------------------------------------------------------------------------

@router.get("/received")
async def get_received_payments(
    current_user: dict = Depends(get_current_landlord),
):
    """Landlord's received payments with tenant and property info."""
    try:
        resp = supabase_admin.table("transactions").select(
            "*, property:properties(id, title, city, state, images), "
            "tenant:users!tenant_id(id, full_name, email, phone_number)"
        ).eq("landlord_id", current_user["id"]).order("created_at", desc=True).execute()

        return {"success": True, "payments": resp.data or []}
    except Exception as e:
        logger.error(f"[PAY] get_received_payments error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch received payments")


# -----------------------------------------------------------------------------
# GET /payments/status  (by reference -- used by callback page)
# -----------------------------------------------------------------------------

@router.get("/status")
async def get_payment_status_by_reference(
    reference: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Used by /tenant/payments/callback to poll status after Paystack redirect.
    Accepts ?reference=NULO-XXXX-YYYY and returns the transaction status.
    Does NOT confirm payment -- that only happens in the webhook.
    """
    try:
        resp = supabase_admin.table("transactions").select(
            "id, status, amount, currency, paystack_ref, created_at, released_at, "
            "property:properties(id, title)"
        ).eq("paystack_ref", reference).single().execute()
    except Exception as e:
        logger.error(f"[PAY] get_payment_status error: {e}")
        raise HTTPException(status_code=404, detail="Payment not found")

    if not resp.data:
        raise HTTPException(status_code=404, detail="Payment not found")

    transaction = resp.data

    # Verify caller is the tenant or landlord on this transaction
    user_id = current_user["id"]
    if transaction.get("tenant_id") != user_id and transaction.get("landlord_id") != user_id:
        # Re-fetch with tenant_id/landlord_id for the access check
        try:
            full_resp = supabase_admin.table("transactions").select(
                "tenant_id, landlord_id"
            ).eq("paystack_ref", reference).single().execute()
            full = full_resp.data or {}
            if full.get("tenant_id") != user_id and full.get("landlord_id") != user_id:
                raise HTTPException(status_code=403, detail="Access denied")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=403, detail="Access denied")

    return {"success": True, "payment": transaction}


# -----------------------------------------------------------------------------
# GET /payments/{transaction_id}  -- must be LAST (wildcard)
# -----------------------------------------------------------------------------

@router.get("/{transaction_id}")
async def get_payment(
    transaction_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Single transaction detail. Accessible by the tenant or landlord on it."""
    try:
        resp = supabase_admin.table("transactions").select(
            "*, property:properties(id, title, city, state, images), "
            "tenant:users!tenant_id(id, full_name, email, phone_number)"
        ).eq("id", transaction_id).single().execute()
    except Exception as e:
        logger.error(f"[PAY] get_payment error: {e}")
        raise HTTPException(status_code=404, detail="Transaction not found")

    if not resp.data:
        raise HTTPException(status_code=404, detail="Transaction not found")

    transaction = resp.data
    user_id = current_user["id"]

    if transaction.get("tenant_id") != user_id and transaction.get("landlord_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return {"success": True, "payment": transaction}