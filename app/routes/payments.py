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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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


def _fetch_property_details(property_id: str) -> dict:
    """
    Fetch property details efficiently.
    Returns property dict or None if not found.
    """
    try:
        resp = supabase_admin.table("properties").select(
            "id, title, location, city, state, address, full_address, price, images"
        ).eq("id", property_id).single().execute()
        return resp.data if resp.data else None
    except Exception as e:
        logger.warning(f"[PAY] Could not fetch property {property_id}: {e}")
        return None


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


def _create_payment_breakdown(agreement: dict, tenant_id: str, paystack_ref: str) -> dict:
    """
    Create a single transaction with detailed payment breakdown.
    Returns transaction record with breakdown metadata.
    """
    rent = float(agreement.get("rent_amount", 0) or 0)
    deposit = float(agreement.get("deposit_amount", 0) or 0)
    platform_fee = float(agreement.get("platform_fee", 0) or 0)
    service_charge = float(agreement.get("service_charge", 0) or 0)
    
    annual_rent = rent * 12
    total_amount = int(annual_rent + deposit + platform_fee + service_charge)
    
    # Create breakdown metadata
    breakdown = {
        "monthly_rent": rent,
        "annual_rent": annual_rent,
        "security_deposit": deposit,
        "platform_fee": platform_fee,
        "service_charge": service_charge,
        "total_amount": total_amount
    }
    
    return {
        "tenant_id": tenant_id,
        "landlord_id": agreement["landlord_id"],
        "property_id": agreement["property_id"],
        "agreement_id": agreement["id"],
        "application_id": agreement.get("application_id"),
        "amount": total_amount,
        "currency": "NGN",
        "status": "pending",
        "transaction_type": "rent_payment",  # Keep as rent_payment for compatibility
        "payment_gateway": "paystack",
        "paystack_ref": paystack_ref,
        "notes": json.dumps({
            "payment_breakdown": breakdown,
            "agreement_id": agreement["id"],
            "breakdown_type": "detailed"
        })
    }


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

    # -- 6. Insert transaction with breakdown -----------------------------------------
    base_url = os.getenv("BASE_URL", "http://localhost:3000")
    callback_url = f"{base_url}/tenant/payments/callback?reference={paystack_ref}"

    try:
        # Create single transaction with detailed breakdown
        transaction_record = _create_payment_breakdown(agreement, tenant_id, paystack_ref)
        
        # Insert the transaction
        txn_resp = supabase_admin.table("transactions").insert(transaction_record).execute()
        
        if not txn_resp.data:
            raise HTTPException(status_code=500, detail="Failed to create payment record")
        
        transaction_id = txn_resp.data[0]["id"]
        
        # Log the payment breakdown
        breakdown = json.loads(transaction_record["notes"]).get("payment_breakdown", {})
        logger.info(f"[PAY] Created payment with breakdown for agreement {body.agreement_id}")
        logger.info(f"[PAY]   - Monthly Rent: ₦{breakdown.get('monthly_rent', 0):,}")
        logger.info(f"[PAY]   - Annual Rent (×12): ₦{breakdown.get('annual_rent', 0):,}")
        logger.info(f"[PAY]   - Security Deposit: ₦{breakdown.get('security_deposit', 0):,}")
        logger.info(f"[PAY]   - Platform Fee: ₦{breakdown.get('platform_fee', 0):,}")
        logger.info(f"[PAY]   - Service Charge: ₦{breakdown.get('service_charge', 0):,}")
        logger.info(f"[PAY]   - Total Amount: ₦{breakdown.get('total_amount', 0):,}")
            
    except Exception as e:
        logger.error(f"[PAY] Failed to insert payment transaction: {e}")
        raise HTTPException(status_code=500, detail="Failed to create payment record")

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
            "id, status, tenant_id, landlord_id, property_id, application_id, amount, notes"
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
        # Preserve existing breakdown notes if present
        existing_notes = {}
        try:
            existing_notes = json.loads(transaction.get("notes", "{}"))
        except:
            existing_notes = {}
        
        supabase_admin.table("transactions").update({
            "status": "released",
            "released_at": now_iso,
            "notes": json.dumps({
                "paystack_event": event_type,
                "paystack_data": data,
                "processed_at": now_iso,
                "payment_breakdown": existing_notes.get("payment_breakdown", {}),
                "breakdown_type": existing_notes.get("breakdown_type", "simple")
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
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("tenant_id", transaction["tenant_id"]).eq(
            "property_id", transaction["property_id"]
        ).in_("status", ["SIGNED", "ACTIVE"]).execute()
    except Exception as e:
        logger.warning(f"[PAY][WEBHOOK] Could not update agreement status: {e}")

    # -- Update property status to occupied -----------------------------------
    try:
        supabase_admin.table("properties").update({
            "status": "occupied",
            "updated_at": datetime.now(timezone.utc).isoformat(),
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

# GET /payments/my-payments  (tenant)
# -----------------------------------------------------------------------------

@router.get("/my-payments")
async def get_my_payments(
    current_user: dict = Depends(get_current_tenant),
):
    """Tenant's full payment history, newest first - OPTIMIZED with batch loading."""
    try:
        # Get transactions for this tenant
        resp = supabase_admin.table("transactions").select(
            "id, tenant_id, landlord_id, property_id, agreement_id, application_id, "
            "amount, currency, status, transaction_type, payment_gateway, "
            "paystack_ref, paystack_access_code, held_at, released_at, refunded_at, "
            "notes, created_at, updated_at"
        ).eq("tenant_id", current_user["id"]).order("created_at", desc=True).execute()

        transactions = resp.data or []
        
        if not transactions:
            return {"success": True, "payments": []}
        
        # OPTIMIZATION: Batch-fetch all properties and landlords instead of N+1 queries
        property_ids = list({t["property_id"] for t in transactions if t.get("property_id")})
        landlord_ids = list({t["landlord_id"] for t in transactions if t.get("landlord_id")})
        
        # Batch-fetch properties
        properties_map = {}
        if property_ids:
            props_resp = supabase_admin.table("properties").select(
                "id, title, location, city, state, address, full_address, price, images"
            ).in_("id", property_ids).execute()
            properties_map = {p["id"]: p for p in (props_resp.data or [])}
        
        # Batch-fetch landlords
        landlords_map = {}
        if landlord_ids:
            landlords_resp = supabase_admin.table("users").select(
                "id, full_name, email, phone_number, avatar_url"
            ).in_("id", landlord_ids).execute()
            landlords_map = {l["id"]: l for l in (landlords_resp.data or [])}
        
        # Enrich transactions with pre-fetched data (no more DB queries)
        enriched_transactions = []
        for txn in transactions:
            enriched_txn = {
                **txn,
                "property": properties_map.get(txn.get("property_id")),
                "landlord": landlords_map.get(txn.get("landlord_id"))
            }
            enriched_transactions.append(enriched_txn)

        return {"success": True, "payments": enriched_transactions}
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
    """Landlord's received payments with tenant and property info - OPTIMIZED with batch loading."""
    try:
        # Get transactions for this landlord
        resp = supabase_admin.table("transactions").select(
            "id, tenant_id, landlord_id, property_id, agreement_id, application_id, "
            "amount, currency, status, transaction_type, payment_gateway, "
            "paystack_ref, paystack_access_code, held_at, released_at, refunded_at, "
            "notes, created_at, updated_at"
        ).eq("landlord_id", current_user["id"]).order("created_at", desc=True).execute()

        transactions = resp.data or []
        
        if not transactions:
            return {"success": True, "payments": []}
        
        # OPTIMIZATION: Batch-fetch all properties and tenants instead of N+1 queries
        property_ids = list({t["property_id"] for t in transactions if t.get("property_id")})
        tenant_ids = list({t["tenant_id"] for t in transactions if t.get("tenant_id")})
        
        # Batch-fetch properties
        properties_map = {}
        if property_ids:
            props_resp = supabase_admin.table("properties").select(
                "id, title, location, city, state, address, full_address, price, images"
            ).in_("id", property_ids).execute()
            properties_map = {p["id"]: p for p in (props_resp.data or [])}
        
        # Batch-fetch tenants
        tenants_map = {}
        if tenant_ids:
            tenants_resp = supabase_admin.table("users").select(
                "id, full_name, email, phone_number, avatar_url"
            ).in_("id", tenant_ids).execute()
            tenants_map = {t["id"]: t for t in (tenants_resp.data or [])}
        
        # Enrich transactions with pre-fetched data (no more DB queries)
        enriched_transactions = []
        for txn in transactions:
            enriched_txn = {
                **txn,
                "property": properties_map.get(txn.get("property_id")),
                "tenant": tenants_map.get(txn.get("tenant_id"))
            }
            enriched_transactions.append(enriched_txn)

        return {"success": True, "payments": enriched_transactions}
    except Exception as e:
        logger.error(f"[PAY] get_received_payments error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch received payments")

@router.get("/status")
async def get_payment_status_by_reference(
    reference: str = Query(...),
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
            "property_id, tenant_id, landlord_id, application_id, transaction_type, "
            "payment_gateway, held_at, refunded_at, notes"
        ).eq("paystack_ref", reference).single().execute()
    except Exception as e:
        logger.error(f"[PAY] get_payment_status error: {e}")
        raise HTTPException(status_code=404, detail="Payment not found")

    if not resp.data:
        raise HTTPException(status_code=404, detail="Payment not found")

    transaction = resp.data
    user_id = current_user["id"]

    # Verify caller is the tenant or landlord on this transaction
    if transaction.get("tenant_id") != user_id and transaction.get("landlord_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # -- Fetch property details for better response --------------------------------
    property_data = None
    if transaction.get("property_id"):
        property_data = _fetch_property_details(transaction["property_id"])
        if property_data:
            transaction["property"] = property_data

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
            "*, property_id, tenant_id, landlord_id"
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


# -----------------------------------------------------------------------------
# POST /payments/confirm-webhook-manually  (DEV ONLY - simulate webhook)
# -----------------------------------------------------------------------------

@router.post("/confirm-webhook-manually")
async def confirm_payment_manually(
    reference: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    """
    DEV ONLY: Manually confirm a payment to simulate Paystack webhook.
    This is needed because Paystack webhooks don't work with localhost.
    """
    # Fetch transaction
    try:
        txn_resp = supabase_admin.table("transactions").select(
            "id, status, tenant_id, landlord_id, property_id, application_id, amount"
        ).eq("paystack_ref", reference).single().execute()
    except Exception as e:
        logger.error(f"[PAY] Manual confirm failed for ref {reference}: {e}")
        raise HTTPException(status_code=404, detail="Transaction not found")

    if not txn_resp.data:
        raise HTTPException(status_code=404, detail="Transaction not found")

    transaction = txn_resp.data

    # Check if already released
    if transaction["status"] == "released":
        return {"success": True, "message": "Payment already confirmed"}

    # Verify caller is the tenant or landlord
    user_id = current_user["id"]
    if transaction.get("tenant_id") != user_id and transaction.get("landlord_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Update transaction to released
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        supabase_admin.table("transactions").update({
            "status": "released",
            "released_at": now_iso,
            "notes": "Manually confirmed via dev endpoint",
            "updated_at": now_iso,
        }).eq("id", transaction["id"]).execute()
    except Exception as e:
        logger.error(f"[PAY] Manual confirm update failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to confirm payment")

    # Update agreement status to ACTIVE
    try:
        supabase_admin.table("agreements").update({
            "status": "ACTIVE",
            "updated_at": now_iso,
        }).eq("tenant_id", transaction["tenant_id"]).eq(
            "property_id", transaction["property_id"]
        ).in_("status", ["SIGNED", "ACTIVE"]).execute()
    except Exception as e:
        logger.warning(f"[PAY] Manual confirm could not update agreement: {e}")

    logger.info(f"[PAY] Payment manually confirmed - transaction {transaction['id']}, ref {reference}")

    return {"success": True, "message": "Payment confirmed successfully"}