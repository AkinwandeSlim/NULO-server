"""
Nulo Africa -- Paystack compatibility shim
=========================================

All Paystack payment endpoints are DEPRECATED for the hackathon.
Inbound Paystack webhooks are dead-lettered with HTTP 410 Gone so
any straggler retries from Paystack fail fast instead of triggering
duplicate side-effects in our DB.

The replacement payment flow uses Nomba virtual accounts:
    - VA creation:    POST /api/v1/nomba/provision-nomba
    - Inbound notify: POST /api/v1/nomba/webhook
    - Disbursement:   POST /api/v1/agreements/{id}/disburse
    - Tenant history: GET  /api/v1/payments/my-payments  (Nomba-backed)
    - Landlord:       GET  /api/v1/payments/received     (Nomba-backed)

The original Paystack route module is preserved at
`app/routes/payments-backup.py` for reference during the demo and
post-hackathon migration. It is NOT registered in main.py.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/payments", tags=["Payment (Deprecated - Paystack)"])


# -----------------------------------------------------------------------------
# Dead-letter responses
# -----------------------------------------------------------------------------
# All Paystack endpoints return 410 Gone with a clear migration message.
# Returning 410 (not 404) tells Paystack's retry logic to stop trying
# without re-queueing -- this is the standard "permanently removed" status.

_PAYSTACK_GONE_BODY = {
    "error": "paystack_deprecated",
    "message": (
        "Paystack payment endpoints are no longer in use. "
        "This hackathon uses Nomba virtual accounts for collections. "
        "Inbound Paystack webhooks are dead-lettered with 410 Gone."
    ),
    "migration": {
        "collections": "POST /api/v1/nomba/provision-nomba (creates a NUBAN per agreement)",
        "webhook": "POST /api/v1/nomba/webhook (the new inbound notification)",
        "disbursement": "POST /api/v1/agreements/{agreement_id}/disburse",
    },
}


def _paystack_gone() -> JSONResponse:
    """Return a uniform 410 Gone response for all deprecated Paystack paths."""
    return JSONResponse(status_code=410, content=_PAYSTACK_GONE_BODY)


# -----------------------------------------------------------------------------
# Paystack endpoints -- all 410 Gone
# -----------------------------------------------------------------------------

@router.post("/initiate")
async def initiate_payment_deprecated():
    """Deprecated: Paystack payment initiation. Use the NUBAN on the agreement page."""
    return _paystack_gone()


@router.post("/webhook")
async def paystack_webhook_deprecated():
    """
    Paystack inbound webhook -- 410 Gone.

    Important: we deliberately do NOT raise HTTPException. We return a
    410 response so the body shape stays predictable and Paystack's
    retry logic sees a final failure (not 5xx which would queue retry).
    """
    return _paystack_gone()


@router.get("/my-payments")
async def my_payments_deprecated():
    """Deprecated: replaced by /tenant/payments (Nomba-backed, on the frontend)."""
    return _paystack_gone()


@router.get("/received")
async def received_payments_deprecated():
    """Deprecated: replaced by /landlord/payments (Nomba + release button)."""
    return _paystack_gone()


@router.get("/status")
async def payment_status_deprecated():
    """Deprecated: use GET /api/v1/nomba/payment_status?account_ref=<uuid-SUB>."""
    return _paystack_gone()


@router.get("/{transaction_id}")
async def get_transaction_deprecated(transaction_id: str):
    """Deprecated: tenant / landlord payment detail pages now use the NUBAN view."""
    return _paystack_gone()


@router.post("/{transaction_id}/resume")
async def resume_payment_deprecated(transaction_id: str):
    """Deprecated: there is nothing to resume with NUBAN -- payment is automatic on inbound transfer."""
    return _paystack_gone()


@router.post("/test-webhook")
async def test_webhook_deprecated():
    """Deprecated: use the Nomba webhook simulator at server/scripts/simulate_live_webhook.py."""
    return _paystack_gone()


@router.post("/confirm-webhook-manually")
async def confirm_webhook_manually_deprecated():
    """Deprecated: webhook reconciliation runs from the Nomba inbound path now."""
    return _paystack_gone()
