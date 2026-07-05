# NuloAfrica Nomba payment routes
# Rule 17: ASCII only -- no Unicode characters
# Rule 7: specific routes before wildcard /{id}
# Rule 5: BackgroundTasks before Depends()
# Rule 6: run_in_executor for all Supabase calls
# Rule 18: supabase_admin only

import asyncio
import logging
import re
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.database import supabase_admin
from app.middleware.auth import get_current_user
from app.services.nomba_client import NombaAPIError, nomba_client
from app.services.nomba_helpers import (
    calculate_expected_amount,
    calculate_next_due_date,
    classify_payment,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# ROUTE 1: Provision virtual account for a signed agreement
# POST /api/v1/agreements/{agreement_id}/provision-nomba
# ============================================================

@router.post("/agreements/{agreement_id}/provision-nomba")
async def provision_nomba(
    agreement_id: str,
    background_tasks: BackgroundTasks,     # Rule 5: before Depends
    current_user=Depends(get_current_user),
):
    # Fetch agreement -- Rule 6: run_in_executor
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .select("*")
            .eq("id", agreement_id)
            .single()
            .execute(),
    )
    agreement = result.data
    if not agreement:
        raise HTTPException(404, "Agreement not found")

    # Auth: only tenant or landlord on this agreement
    if current_user["id"] not in (
        agreement["tenant_id"], agreement["landlord_id"]
    ):
        raise HTTPException(403, "Not authorized")

    if agreement["status"] != "SIGNED":
        raise HTTPException(
            400, "Agreement must be in SIGNED status before provisioning"
        )

    # Idempotent: already provisioned
    if agreement.get("virtual_account_number"):
        return {
            "status": "already_provisioned",
            "virtual_account_number": agreement["virtual_account_number"],
            "virtual_account_name": agreement["virtual_account_name"],
            "expected_amount": float(agreement.get("expected_payment_amount") or 0),
            "frequency": agreement.get("payment_frequency"),
        }

    # Get landlord name + property hint -- Rule 1: .eq('id', ...) for shared PK tables
    # Banking convention: account name = beneficiary (landlord), not payer (tenant)
    # Query users table for full_name (shared PK pattern), fallback to landlord_profiles
    user_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("users")
            .select("full_name, email")
            .eq("id", agreement["landlord_id"])
            .single()
            .execute(),
    )
    user = user_result.data or {}

    # Fetch property title for disambiguation (landlord may have multiple properties)
    property_title = ""
    if agreement.get("property_id"):
        prop_result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin
                .table("properties")
                .select("title")
                .eq("id", agreement["property_id"])
                .single()
                .execute(),
        )
        if prop_result.data and prop_result.data.get("title"):
            property_title = prop_result.data["title"][:20].strip()

    # Build account name: landlord name with optional property hint
    # Nomba prefixes with "Nomba / " automatically, so we just provide the name part
    landlord_name = (
        user.get("full_name")
        or user.get("email")
        or "NuloAfrica Landlord"
    ).strip()

    if property_title:
        raw_name = f"{landlord_name} {property_title}"
    else:
        raw_name = landlord_name

    # Sanitize: only allow ASCII letters/digits and single spaces.
    # Nomba rejects ANY special character (including '-' and '.'), so we
    # strip everything that is not A-Z/0-9/space, then collapse runs of
    # spaces to a single space and trim.
    sanitized = []
    for char in raw_name.strip():
        if char.isascii() and (char.isalnum() or char == " "):
            sanitized.append(char)
    clean_name = " ".join("".join(sanitized).split())  # collapse whitespace

    # Nomba spec: accountName must be 8-64 chars.
    # Strip whitespace, pad short names, truncate long names.
    account_name = clean_name[:64]
    if len(account_name) < 8:
        # Pad to satisfy the 8-char minimum (e.g. "Adaeze Okafor" -> "Adaeze Okafor NuloAfrica")
        account_name = (account_name + " NuloAfrica")[:64]

    # Nomba spec: accountRef must be 16-64 chars. agreement.id is a UUID
    # (36 chars) so it always satisfies this -- no padding needed.
    if not (16 <= len(agreement_id) <= 64):
        raise HTTPException(
            400,
            f"agreement_id must be 16-64 chars (got {len(agreement_id)})",
        )

    frequency = agreement.get("payment_frequency") or "MONTHLY"
    expected_amount = calculate_expected_amount(
        float(agreement["rent_amount"]), frequency
    )

    # Sub-account is REQUIRED for VA provisioning. Without it, the VA would be
    # scoped to the parent account, and Nomba's webhook redirect service would
    # look up the parent's webhook URL config -- which is NOT registered for
    # our hackathon submission. Result: silent 404 "No redirect configuration"
    # on every inbound payment. Hard-fail fast here so callers see the issue
    # instead of producing broken VAs.
    if not nomba_client.sub_account_id:
        raise HTTPException(
            500,
            "NOMBA_SUB_ACCOUNT_ID is not set; cannot provision a sub-account-"
            "scoped VA (Path B). Configure the env var and retry.",
        )

    # Nomba spec: accountRef must be 16-64 chars. We append "-SUB" (4 chars)
    # to a UUID (36 chars) for a total of 41 chars -- well within the spec.
    # The suffix lets us tag which VAs are sub-account-scoped at lookup time
    # (see disbursements.py auto-pick of the sub-account transfer endpoint).
    sub_account_ref = f"{agreement_id}-SUB"

    # Log exact payload being sent to Nomba for debug visibility
    logger.info(
        "Nomba VA provision attempt (Path B sub-account) | agreement=%s | "
        "account_ref=%s | account_name=%r (len=%d) | expected_local=%.2f",
        agreement_id, sub_account_ref, account_name, len(account_name), expected_amount,
    )

    # RECOVERY: If a previous provisioning call succeeded on Nomba's side
    # but failed on ours (e.g. server crash between Nomba 200 and our DB
    # write), the VA is orphaned on Nomba with our accountRef. Nomba will
    # then reject the next create with "accountRef already exists". We
    # try to fetch the existing VA first and use it.
    #
    # Path B (sub-account) stores accountRef = {uuid}-SUB on Nomba, so the
    # recovery GET must use the suffixed ref. get_virtual_account() returns
    # None cleanly on 404 (nomba_client.py:443-444), so if Nomba 404s on the
    # suffixed ref via the parent-header GET, recovery simply falls through
    # to the Path-B creation call below. The header stays as the parent
    # per the PRD's golden rule (header is always the parent).
    data = None
    try:
        existing = await nomba_client.get_virtual_account(sub_account_ref)
        if existing and not existing.get("expired", False):
            logger.info(
                "Recovered existing Nomba VA for agreement=%s | nuban=%s",
                agreement_id, existing.get("bankAccountNumber"),
            )
            data = existing
    except NombaAPIError as exc:
        # GET failed for a non-404 reason -- log but try create anyway,
        # create will fail with the real reason if there's a problem.
        logger.warning(
            "GET virtual_account failed during recovery | agreement=%s | err=%s",
            agreement_id, exc,
        )

    if data is None:
        try:
            # Path B: provision under the sub-account. accountRef is the
            # suffixed value (sub_account_ref) so the on-Nomba record matches
            # the aliasAccountReference that webhooks will echo back.
            # create_virtual_account_for_subaccount does not take
            # expected_amount (body is exactly {accountRef, accountName});
            # expected_amount is still persisted locally to
            # agreements.expected_payment_amount below.
            data = await nomba_client.create_virtual_account_for_subaccount(
                sub_account_id=nomba_client.sub_account_id,
                account_ref=sub_account_ref,
                account_name=account_name,
            )
        except NombaAPIError as exc:
            # Surface the FULL Nomba error in the response so callers can see
            # the actual validation message (the underlying response_body is
            # already attached to the NombaAPIError string in the client).
            logger.error(
                "Nomba provisioning failed | agreement=%s | full_error=%s",
                agreement_id, exc,
            )
            raise HTTPException(502, f"Nomba provisioning failed: {exc}")

    next_due = None
    if agreement.get("lease_start_date"):
        start = date.fromisoformat(str(agreement["lease_start_date"]))
        next_due = calculate_next_due_date(start, frequency)

    # Write to agreements table
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .update({
                "virtual_account_number": data["bankAccountNumber"],
                "virtual_account_name": data["bankAccountName"],
                "nomba_account_ref": data["accountRef"],
                "expected_payment_amount": expected_amount,
                "payment_frequency": frequency,
                "next_payment_due_date": str(next_due) if next_due else None,
                "reconciliation_status": "PENDING",
                "total_received_amount": 0,
            })
            .eq("id", agreement_id)
            .execute(),
    )

    logger.info(
        "Virtual account provisioned | agreement=%s | nuban=%s | freq=%s | expected=%.2f",
        agreement_id, data["bankAccountNumber"], frequency, expected_amount,
    )

    background_tasks.add_task(
        _notify_tenant_account_ready, agreement_id, data
    )

    return {
        "status": "provisioned",
        "virtual_account_number": data["bankAccountNumber"],
        "virtual_account_name": data["bankAccountName"],
        "bank_name": data.get("bankName"),
        "expected_amount": expected_amount,
        "frequency": frequency,
        "next_due_date": str(next_due) if next_due else None,
    }


# ============================================================
# ROUTE 2: Nomba webhook receiver
# POST /api/v1/webhooks/nomba/transfer
# ============================================================

@router.post("/webhooks/nomba/transfer")
async def nomba_webhook(request: Request):
    """
    Receive Nomba payment webhooks.

    Implementation order (never change):
    1. Read headers first (nomba-signature + nomba-timestamp)
    2. Parse JSON body
    3. Verify signature -- return 401 if invalid, nothing written to DB
    4. Check idempotency (requestId) -- return 200 if duplicate
    5. Write transfer record to virtual_account_transfers
    6. Dispatch reconciliation if event_type=payment_success AND type=vact_transfer
    7. Always return 200 after step 5+ (reconciliation errors must not cause retries)

    Retry policy: Nomba retries non-2xx up to 5 times (2min, 5min, 11min, 24min, 53min).
    A 500 from a reconciliation bug will cause 5 duplicate attempts over ~95 minutes.
    """
    signature = request.headers.get("nomba-signature", "")
    nomba_timestamp = request.headers.get("nomba-timestamp", "")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    # Step 3: Verify signature
    if not signature or not nomba_client.verify_webhook_signature(
        payload, signature, nomba_timestamp
    ):
        logger.warning(
            "Invalid webhook signature | sig_prefix=%s | ts=%s",
            signature[:20] if signature else "MISSING",
            nomba_timestamp,
        )
        raise HTTPException(401, "Invalid signature")

    request_id = payload.get("requestId")
    event_type = payload.get("event_type")

    if not request_id:
        raise HTTPException(400, "Missing requestId")

    # Step 4: Idempotency
    existing = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .select("id")
            .eq("nomba_request_id", request_id)
            .execute(),
    )
    if existing.data:
        logger.info("Duplicate webhook ignored | requestId=%s", request_id)
        return {"status": "already_processed"}

    # Step 5: Extract payload fields
    data = payload.get("data", {})
    transaction = data.get("transaction", {})
    customer = data.get("customer", {})

    transaction_type = transaction.get("type", "")
    account_ref = transaction.get("aliasAccountReference", "")
    amount_received = transaction.get("transactionAmount", 0)

    # Step 6: Write transfer record (with idempotency try/except)
    transfer_row = None
    try:
        transfer_insert = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin
                .table("virtual_account_transfers")
                .insert({
                    "nomba_request_id": request_id,
                    "nomba_transaction_id": transaction.get("transactionId"),
                    "account_ref": account_ref,
                    "account_number": transaction.get("aliasAccountNumber"),
                    "amount_received": float(amount_received),
                    "sender_name": customer.get("senderName"),
                    "sender_bank": customer.get("bankName"),
                    "currency": "NGN",
                    "event_type": event_type,
                    "transaction_type": transaction_type,
                    "raw_payload": payload,
                    "signature_valid": True,
                })
                .execute(),
        )
        transfer_row = (
            transfer_insert.data[0] if transfer_insert.data else {}
        )
    except Exception as exc:
        # Check if this is a unique constraint violation on nomba_request_id
        # If so, treat as already processed
        logger.warning(
            "Insert failed for requestId=%s (possible duplicate): %s",
            request_id, exc,
        )
        # Get existing row to proceed with reconciliation/payout handling
        existing_result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin
                .table("virtual_account_transfers")
                .select("*")
                .eq("nomba_request_id", request_id)
                .maybe_single()
                .execute(),
        )
        transfer_row = existing_result.data
        if not transfer_row:
            logger.error("Could not retrieve existing row for requestId=%s", request_id)
            return {"status": "error"}
        logger.info("Using existing row for requestId=%s", request_id)

    # Step 7: Reconcile only for virtual account funding
    if event_type == "payment_success" and transaction_type == "vact_transfer":
        try:
            await _reconcile_payment(
                transfer_row, account_ref, float(amount_received)
            )
        except Exception as exc:
            logger.error(
                "Reconciliation error | requestId=%s | error=%s",
                request_id, exc,
            )
            # Do NOT re-raise -- must return 200 to prevent retry storm

    # Step 8: Handle payout events (Phase 3 -- disbursement)
    # event_type in {payout_success, payout_failed, payout_refund}
    # transaction_type == "transfer" for all payout events
    if event_type in ("payout_success", "payout_failed", "payout_refund"):
        try:
            await _handle_payout_event(
                payload, event_type, request_id
            )
        except Exception as exc:
            logger.error(
                "Payout event handler error | requestId=%s | event=%s | error=%s",
                request_id, event_type, exc,
            )
            # Do NOT re-raise -- must return 200 to prevent retry storm

    return {"status": "ok"}


# ============================================================
# ROUTE 3: Payment status for an agreement
# GET /api/v1/agreements/{agreement_id}/payment-status
# NOTE: Rule 7 -- this must be registered BEFORE any wildcard /{id} route
# ============================================================

@router.get("/agreements/{agreement_id}/payment-status")
async def payment_status(
    agreement_id: str,
    current_user=Depends(get_current_user),
):
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .select(
                "id, payment_frequency, expected_payment_amount, "
                "total_received_amount, reconciliation_status, "
                "next_payment_due_date, virtual_account_number, "
                "virtual_account_name, tenant_id, landlord_id"
            )
            .eq("id", agreement_id)
            .single()
            .execute(),
    )
    agreement = result.data
    if not agreement:
        raise HTTPException(404, "Agreement not found")

    if current_user["id"] not in (
        agreement["tenant_id"], agreement["landlord_id"]
    ):
        raise HTTPException(403, "Not authorized")

    # Query the transfer history. The webhook stores the SUFFIXED accountRef
    # ({uuid}-SUB) for Path-B sub-account-scoped VAs, so we must query with
    # the suffixed value -- not the bare agreement_id. Use the same UUID
    # extraction regex as _reconcile_payment to defensively strip any suffix
    # from agreement_id before re-appending "-SUB".
    #
    # Legacy parent-scoped VAs used the bare UUID as accountRef. Their rows
    # are intentionally NOT surfaced here -- parent VAs are deprecated and we
    # are not preserving their history in this endpoint.
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
                "id, amount_received, sender_name, sender_bank, "
                "reconciliation_result, created_at"
            )
            .eq("account_ref", suffixed_account_ref)
            .order("created_at", desc=True)
            .execute(),
    )

    return {
        "agreement_id": agreement_id,
        "frequency": agreement["payment_frequency"],
        "expected_amount": float(agreement.get("expected_payment_amount") or 0),
        "total_received": float(agreement.get("total_received_amount") or 0),
        "reconciliation_status": agreement["reconciliation_status"],
        "next_due_date": agreement["next_payment_due_date"],
        "virtual_account_number": agreement["virtual_account_number"],
        "virtual_account_name": agreement["virtual_account_name"],
        "transfer_history": transfers.data or [],
    }
    # PRD Part 6 -- snake_case keys to match existing FastAPI response conventions


# ============================================================
# ROUTE 4: Health check -- judges hit this to verify integration
# GET /api/v1/health/nomba
# ============================================================

@router.get("/health/nomba")
async def nomba_health():
    try:
        token = await nomba_client._get_token()
        auth_ok = bool(token)
    except Exception as exc:
        return {
            "status": "error",
            "nomba_auth": False,
            "error": str(exc),
        }
    return {
        "status": "ok",
        "nomba_auth": auth_ok,
        "webhook_url": "https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer",
        "environment": "test" if "sandbox" in nomba_client.base_url else "live",
    }


# ============================================================
# Internal: Reconciliation engine
# ============================================================

async def _reconcile_payment(
    transfer_row: dict,
    account_ref: str,
    amount_received: float,
):
    """
    Match inbound transfer to agreement. Update status and totals.
    account_ref = aliasAccountReference from webhook = agreement.id
    (or agreement.id with an optional suffix like "-SUB" when the VA was
    provisioned via the sub-account endpoint for test routing purposes).
    """
    if not account_ref:
        logger.warning("No aliasAccountReference in webhook -- cannot reconcile")
        return

    # Extract a UUID from the account_ref. Nomba's accountRef field allows
    # 16-64 chars, so callers can append suffixes (e.g., "-SUB") for testing
    # routing under the sub-account endpoint while still mapping back to the
    # agreement's UUID. agreements.id is uuid-typed, so we need a clean UUID
    # for the .eq("id", ...) query.
    uuid_match = re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        account_ref, re.IGNORECASE,
    )
    agreement_id = uuid_match.group(0) if uuid_match else account_ref
    if agreement_id != account_ref:
        logger.info(
            "Extracted UUID from accountRef | raw=%s | uuid=%s",
            account_ref, agreement_id,
        )

    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .select(
                "id, tenant_id, landlord_id, application_id, property_id, "
                "rent_amount, expected_payment_amount, payment_frequency, "
                "total_received_amount, reconciliation_status"
            )
            .eq("id", agreement_id)
            .execute(),
    )

    if not result.data:
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin
                .table("virtual_account_transfers")
                .update({"reconciliation_result": "MISDIRECTED"})
                .eq("id", transfer_row.get("id"))
                .execute(),
        )
        logger.warning("MISDIRECTED payment | accountRef=%s", account_ref)
        return

    agreement = result.data[0]
    expected = float(agreement.get("expected_payment_amount") or 0)
    prev_total = float(agreement.get("total_received_amount") or 0)
    new_total = round(prev_total + amount_received, 2)
    prev_status = agreement["reconciliation_status"]
    new_status = classify_payment(amount_received, expected)

    variance_pct = (
        round(((amount_received - expected) / expected) * 100, 2)
        if expected > 0 else 0.0
    )

    # Update agreement
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .update({
                "total_received_amount": new_total,
                "reconciliation_status": new_status,
            })
            .eq("id", agreement["id"])
            .execute(),
    )

    # Update transfer record
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .update({
                "agreement_id": agreement["id"],
                "reconciliation_result": new_status,
            })
            .eq("id", transfer_row.get("id"))
            .execute(),
    )

    # Reconciliation audit log
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("payment_reconciliation_log")
            .insert({
                "agreement_id": agreement["id"],
                "transfer_id": transfer_row.get("id"),
                "previous_status": prev_status,
                "new_status": new_status,
                "expected_amount": expected,
                "received_amount": amount_received,
                "variance_pct": variance_pct,
                "notes": f"frequency={agreement['payment_frequency']}",
            })
            .execute(),
    )

    # transactions table entry
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .insert({
                "agreement_id": agreement["id"],
                "tenant_id": agreement["tenant_id"],
                "landlord_id": agreement["landlord_id"],
                # application_id and property_id are NOT NULL on transactions.
                # Pull from the agreement (which is the source of truth) so the
                # row stays traceable for invoices, receipts, and reconciliation
                # reports. For agreements created outside the standard
                # application-approval flow, .get() returns None and the insert
                # will fail loudly rather than silently dropping the link.
                "application_id": agreement.get("application_id"),
                "property_id": agreement.get("property_id"),
                "amount": amount_received,
                "transaction_type": "nomba_collection",
                # transactions_status_check allows only
                # pending/held/released/refunded/failed. Inbound collection is
                # HELD in the parent account until disbursement releases it
                # (Migration 004: held_at = reconciled, released_at = paid out).
                "status": "held",
                "payment_gateway": "nomba",
                "currency": "NGN",
                "notes": (
                    f"frequency={agreement['payment_frequency']} "
                    f"status={new_status}"
                ),
            })
            .execute(),
    )

    logger.info(
        "Reconciled | agreement=%s | received=%.2f | expected=%.2f | status=%s",
        agreement["id"], amount_received, expected, new_status,
    )


async def _notify_tenant_account_ready(agreement_id: str, data: dict):
    """Background task: notify tenant their virtual account is ready."""
    logger.info(
        "Notify tenant | agreement=%s | nuban=%s",
        agreement_id, data.get("bankAccountNumber"),
    )
    # Plug into existing notification_service here following existing patterns


# ============================================================
# Phase 3 (disbursement) -- payout webhook handler
# ============================================================

async def _handle_payout_event(
    payload: dict,
    event_type: str,
    request_id: str,
):
    """
    Handle payout-related webhook events (Phase 3 -- PRD v2 Part 1.4).

    event_type in {payout_success, payout_failed, payout_refund}
    transaction_type == "transfer"

    For payout_success: mark the related transactions row as 'completed',
                        set nomba_transfer_id and released_at.
    For payout_failed:  mark the related transactions row as 'failed'.
    For payout_refund:  mark the related transactions row as 'refunded',
                        set refunded_at. The original merchantTxRef is
                        NOT reusable -- caller must generate a new ref
                        using build_merchant_tx_ref(..., retry_count+1)
                        before retrying transfer_to_bank().

    The lookup key is data.merchantTxRef (== our nomba_transfer_ref
    in the transactions table). Idempotent: if the row is already in
    the target status, no-op.
    """
    data = payload.get("data", {}) or {}
    merchant_tx_ref = data.get("merchantTxRef")
    if not merchant_tx_ref:
        logger.warning(
            "Payout event with no merchantTxRef | requestId=%s | event=%s",
            request_id, event_type,
        )
        return

    # Map event -> transactions.status + timestamp field to set
    status_map = {
        "payout_success": ("released", "released_at"),
        "payout_failed":  ("failed",    None),
        "payout_refund":  ("refunded",  "refunded_at"),
    }
    new_status, ts_field = status_map[event_type]
    now_iso = None
    if ts_field:
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()

    update_payload = {
        "status": new_status,
        "nomba_transfer_id": data.get("id") or None,
    }
    if ts_field and now_iso:
        update_payload[ts_field] = now_iso

    # Idempotency: only update if not already in target status
    # Use maybe_single() to avoid raising on no rows (handles race condition)
    current_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .select("id, status")
            .eq("nomba_transfer_ref", merchant_tx_ref)
            .maybe_single()  # Fixed: use maybe_single() instead of single()
            .execute(),
    )
    current = current_result.data
    if not current:
        logger.warning(
            "Payout event for unknown merchantTxRef | ref=%s | event=%s",
            merchant_tx_ref, event_type,
        )
        return
    if current.get("status") == new_status:
        logger.info(
            "Payout event already in target status | ref=%s | status=%s",
            merchant_tx_ref, new_status,
        )
        return

    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .update(update_payload)
            .eq("nomba_transfer_ref", merchant_tx_ref)
            .execute(),
    )

    logger.info(
        "Payout event processed | ref=%s | event=%s | new_status=%s",
        merchant_tx_ref, event_type, new_status,
    )
