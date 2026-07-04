# NuloAfrica Nomba disbursement routes (Phase 3)
# Rule 17: ASCII only -- no Unicode characters
# Rule 7: specific routes before wildcard /{id}
# Rule 5: BackgroundTasks before Depends()
# Rule 6: run_in_executor for all Supabase calls
# Rule 18: supabase_admin only
#
# Per PRD v2 Part 0: Phase 3 (disbursement) IS in scope.
# These routes cover bank account verification and outbound payouts.
# Payouts are MANUAL (landlord triggers via dashboard) for the hackathon;
# auto-disbursement is deferred to post-hackathon.

import asyncio
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.database import supabase_admin
from app.middleware.auth import get_current_user
from app.services.nomba_client import NombaAPIError, nomba_client
from app.services.nomba_helpers import (
    build_merchant_tx_ref,
    calculate_landlord_payout,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# ROUTE 1: Verify a landlord's bank account
# POST /api/v1/disbursements/lookup-bank
# Auth: landlord
# Body: { account_number, bank_code }
# Returns: { account_number, account_name, verified_at }
# ============================================================

@router.post("/disbursements/lookup-bank")
async def lookup_bank(
    body: dict,
    current_user=Depends(get_current_user),
):
    """
    Verify a recipient bank account before saving it to landlord_profiles.

    ALWAYS call this before storing bank details. The returned accountName
    is the verified name from the bank -- we use it as the source of truth
    for the transfer, never user-typed.

    On success: also persist bank_code, bank_name (display name), and bank_verified_at to landlords table.
    """
    account_number = (body.get("account_number") or "").strip()
    bank_code = (body.get("bank_code") or "").strip()
    if not account_number or not bank_code:
        raise HTTPException(400, "account_number and bank_code are required")

    try:
        # First, get banks list to get display name
        banks_list = await nomba_client.get_banks_list()
        # Find the bank with matching code
        bank_display_name = bank_code  # Fallback to code if not found
        for bank in banks_list:
            if bank.get("code") == bank_code:
                bank_display_name = bank.get("name", bank_code)
                break

        # Then lookup the account
        data = await nomba_client.lookup_bank_account(
            account_number=account_number,
            bank_code=bank_code,
        )
    except NombaAPIError as exc:
        logger.warning(
            "Bank lookup failed | user=%s | account=%s | bank=%s | error=%s",
            current_user["id"], account_number, bank_code, exc,
        )
        raise HTTPException(502, f"Bank lookup failed: {exc}")

    verified_account_name = data.get("accountName", "")
    if not verified_account_name:
        raise HTTPException(502, "Bank returned empty accountName")

    # Persist all correct fields to landlords row.
    # Use upsert() (not update()) because some landlords may not have a row
    # in the `landlords` table if their onboarding flow didn't create one --
    # we should be able to recover from that here rather than 500-ing the
    # entire disburse flow later. On the happy path this is a no-op for
    # existing rows (PostgREST treats upsert as update when the PK exists).
    now = datetime.now(timezone.utc).isoformat()
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("landlords")
            .upsert({
                "id": current_user["id"],
                "bank_account_number": account_number,
                "bank_name": bank_display_name,  # Human-readable display name
                "account_name": verified_account_name,
                "bank_code": bank_code,          # Bank code for API calls
                "bank_verified_at": now,
                "updated_at": now,
            })
            .execute(),
    )

    return {
        "account_number": account_number,
        "bank_code": bank_code,
        "bank_name": bank_display_name,
        "account_name": verified_account_name,
        "verified_at": now,
    }


# ============================================================
# ROUTE 2: Trigger a payout to the landlord
# POST /api/v1/agreements/{agreement_id}/disburse
# Auth: landlord on this agreement only
# Body: { source_transfer_id, retry_count? }
# Returns: { status, merchant_tx_ref, amount_ngn, message }
# ============================================================

@router.post("/agreements/{agreement_id}/disburse")
async def disburse_to_landlord(
    agreement_id: str,
    body: dict,
    background_tasks: BackgroundTasks,    # Rule 5: before Depends
    current_user=Depends(get_current_user),
):
    """
    Disburse a collected payment to the landlord's verified bank account.

    The flow (FIXED):
    1. Look up the agreement (must be SIGNED + landlord_id == current_user)
    2. Look up the source transfer (must be reconciled as FULL_PAYMENT)
    3. Look up landlord's bank details (must be bank_verified_at IS NOT NULL)
    4. Calculate landlord payout = received - platform_fee
    5. Generate merchantTxRef from the source transfer id
    6. INSERT transactions row FIRST (status = pending) to avoid race condition
    7. Call nomba_client.transfer_to_bank() -- may return 201 (async)
    8. Update transactions row with nomba_transfer_id and final status
    9. Background: notify landlord of payout progress
    """
    source_transfer_id = (body.get("source_transfer_id") or "").strip()
    # Test-only override: allow disbursement of UNDERPAYMENT (or any) transfers.
    # Production must always pass FULL_PAYMENT; this flag is for hackathon tests
    # where we want to disburse a partial collection for verification.
    force = bool(body.pop("force", False))
    retry_count = int(body.get("retry_count") or 0)
    if not source_transfer_id:
        raise HTTPException(400, "source_transfer_id is required")

    # 1. Fetch agreement
    agreement_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .select("id, landlord_id, tenant_id, platform_fee, expected_payment_amount")
            .eq("id", agreement_id)
            .maybe_single()
            .execute(),
    )
    # .maybe_single() returns None for 0 rows. Normalize to a dict.
    agreement = (
        agreement_result
        if isinstance(agreement_result, dict)
        else (agreement_result.data if agreement_result else None)
    )
    if not agreement:
        raise HTTPException(404, "Agreement not found")
    if current_user["id"] != agreement["landlord_id"]:
        raise HTTPException(403, "Only the landlord on this agreement can disburse")

    # 2. Fetch source transfer
    transfer_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .select("id, amount_received, reconciliation_result, agreement_id, currency, account_ref")
            .eq("id", source_transfer_id)
            .maybe_single()
            .execute(),
    )
    # .maybe_single() returns None for 0 rows. Normalize to a dict.
    transfer = (
        transfer_result
        if isinstance(transfer_result, dict)
        else (transfer_result.data if transfer_result else None)
    )
    if not transfer:
        raise HTTPException(404, "Source transfer not found")
    if transfer.get("agreement_id") != agreement_id:
        raise HTTPException(400, "Source transfer does not belong to this agreement")
    if transfer.get("reconciliation_result") != "FULL_PAYMENT":
        if not force:
            raise HTTPException(
                400,
                f"Source transfer reconciliation_result is "
                f"{transfer.get('reconciliation_result')}, must be FULL_PAYMENT "
                f"(pass force=true in body to override for testing)",
            )
        logger.warning(
            "Disbursing UNDERPAYMENT (force=true) | agreement=%s | "
            "source_transfer=%s | result=%s | received=%.2f | expected=%.2f",
            agreement_id, source_transfer_id, transfer.get("reconciliation_result"),
            float(transfer.get("amount_received") or 0),
            float(agreement.get("expected_payment_amount") or 0),
        )

    # Idempotency: check if a disbursement already exists for this source transfer
    existing_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .select("id, nomba_transfer_ref, status, amount")
            .eq("source_transfer_id", source_transfer_id)
            .in_("transaction_type", ["nomba_disbursement"])
            .execute(),
    )
    if existing_result.data:
        existing = existing_result.data[0]
        if existing.get("status") in ("released", "pending"):
            return {
                "status": existing.get("status", "already_processed"),
                "merchant_tx_ref": existing.get("nomba_transfer_ref"),
                "amount_ngn": float(existing.get("amount") or 0),
                "message": "Disbursement already in progress or complete",
            }

    # 3. Fetch landlord bank details
    landlord_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("landlords")
            .select("id, bank_account_number, bank_name, account_name, bank_code, bank_verified_at")
            .eq("id", agreement["landlord_id"])
            .maybe_single()
            .execute(),
    )
    # .maybe_single() returns None for 0 rows. Normalize to a dict.
    landlord = (
        landlord_result
        if isinstance(landlord_result, dict)
        else (landlord_result.data if landlord_result else None)
    )
    if not landlord:
        raise HTTPException(404, "Landlord record not found")
    if not landlord.get("bank_verified_at"):
        raise HTTPException(
            400,
            "Landlord bank account has not been verified. "
            "Call POST /disbursements/lookup-bank first.",
        )
    for field in ("bank_account_number", "bank_code", "account_name"):
        if not landlord.get(field):
            raise HTTPException(
                400, f"Landlord bank details incomplete: {field} is missing",
            )

    # 4. Calculate payout amount
    platform_fee = float(agreement.get("platform_fee") or 0)
    amount_received = float(transfer["amount_received"])
    payout_amount = calculate_landlord_payout(amount_received, platform_fee)
    if payout_amount <= 0:
        raise HTTPException(
            400,
            f"Payout amount is 0 (received={amount_received}, platform_fee={platform_fee})",
        )

    # 5. Generate idempotency key
    merchant_tx_ref = build_merchant_tx_ref(source_transfer_id, retry_count)
    now = datetime.now(timezone.utc).isoformat()

    # 6. INSERT transactions row FIRST (status = pending) to avoid race condition
    insert_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .insert({
                "agreement_id": agreement_id,
                "tenant_id": agreement["tenant_id"],
                "landlord_id": agreement["landlord_id"],
                "property_id": None,
                "application_id": None,
                "amount": payout_amount,
                "currency": transfer.get("currency", "NGN"),
                "transaction_type": "nomba_disbursement",
                "status": "pending",
                "payment_gateway": "nomba",
                "held_at": now,
                "released_at": None,
                "nomba_transfer_ref": merchant_tx_ref,
                "nomba_transfer_id": None,
                "source_transfer_id": source_transfer_id,
                "notes": f"payout={payout_amount} status=initial_pending",
            })
            .execute(),
    )
    tx_row = insert_result.data[0] if insert_result.data else {}

    # 7. Call Nomba
    # Detect sub-account source: the nomba_account_ref we stored has a "-SUB"
    # suffix when the VA was provisioned under the sub-account. Disbursements
    # from those VAs MUST go through the sub-account transfer endpoint, since
    # the parent wallet has 0 spendable balance even though the balance API
    # reports funds (verified live 2026-07-04 with INSUFFICIENT_BALANCE).
    account_ref = transfer.get("account_ref") or ""
    is_sub_account_va = account_ref.upper().endswith("-SUB")
    sub_account_id = os.environ.get("NOMBA_SUB_ACCOUNT_ID") if is_sub_account_va else None

    try:
        if is_sub_account_va:
            if not sub_account_id:
                raise NombaAPIError(
                    "Source transfer is from a sub-account VA (ref has -SUB) but "
                    "NOMBA_SUB_ACCOUNT_ID is not configured in the environment"
                )
            logger.info(
                "Disbursing from sub-account | sub=%s | account_ref=%s | ref=%s",
                sub_account_id, account_ref, merchant_tx_ref,
            )
            nomba_data = await nomba_client.transfer_to_bank_from_subaccount(
                sub_account_id=sub_account_id,
                amount_naira=payout_amount,
                account_number=landlord["bank_account_number"],
                account_name=landlord["account_name"],
                bank_code=landlord["bank_code"],
                merchant_tx_ref=merchant_tx_ref,
                narration=f"Rent disbursement agreement={agreement_id[:8]}",
            )
        else:
            nomba_data = await nomba_client.transfer_to_bank(
                amount_naira=payout_amount,
                account_number=landlord["bank_account_number"],
                account_name=landlord["account_name"],
                bank_code=landlord["bank_code"],
                merchant_tx_ref=merchant_tx_ref,
                narration=f"Rent disbursement agreement={agreement_id[:8]}",
            )
    except NombaAPIError as exc:
        logger.error(
            "Disbursement failed | agreement=%s | ref=%s | error=%s",
            agreement_id, merchant_tx_ref, exc,
        )
        # Update transaction status to failed if Nomba call fails
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin
                .table("transactions")
                .update({"status": "failed", "notes": f"Nomba call failed: {exc}"})
                .eq("id", tx_row["id"])
                .execute(),
        )
        raise HTTPException(502, f"Nomba disbursement failed: {exc}")

    # 8. Update transactions row with nomba_transfer_id and final status
    # transactions_status_check allows pending/held/released/refunded/failed.
    # A settled payout is RELEASED (funds left the parent account to the
    # landlord); REFUND auto-reverses to failed; NEW/PENDING_BILLING stay pending.
    nomba_status = nomba_data.get("status", "PENDING").upper()
    if nomba_status == "SUCCESS":
        tx_status = "released"
    elif nomba_status == "REFUND":
        tx_status = "failed"
    else:
        tx_status = "pending"
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .update({
                "status": tx_status,
                "nomba_transfer_id": nomba_data.get("id"),
                "released_at": now if tx_status == "released" else None,
                "notes": f"payout={payout_amount} status={nomba_status}",
            })
            .eq("id", tx_row["id"])
            .execute(),
    )

    # 9. Background: notify landlord
    background_tasks.add_task(
        _notify_landlord_payout, agreement_id, merchant_tx_ref, payout_amount, nomba_status
    )

    return {
        "status": tx_status,
        "merchant_tx_ref": merchant_tx_ref,
        "amount_ngn": payout_amount,
        "nomba_status": nomba_status,
        "transaction_id": tx_row.get("id"),
    }


# ============================================================
# ROUTE 3: Check the status of a payout
# GET /api/v1/disbursements/{merchant_tx_ref}
# Auth: landlord on the related agreement OR admin
# ============================================================

@router.get("/disbursements/{merchant_tx_ref}")
async def get_disbursement_status(
    merchant_tx_ref: str,
    current_user=Depends(get_current_user),
):
    """
    Return the current status of a payout by its merchant_tx_ref.

    Status flows:
    PENDING (in-flight) -> SUCCESS (settled) [webhook]
                        -> FAILED  (Nomba rejected) [webhook]
                        -> REFUND  (Nomba auto-refunded) [webhook]
    """
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .select(
                "id, agreement_id, landlord_id, amount, status, "
                "nomba_transfer_id, nomba_transfer_ref, source_transfer_id, "
                "created_at, released_at, refunded_at"
            )
            .eq("nomba_transfer_ref", merchant_tx_ref)
            # Use maybe_single(): .single() raises PGRST116 on 0 rows and
            # returns 500 to the client. We expect None when the merchant_tx_ref
            # has never been generated (e.g. queried before any disburse ran)
            # and convert that to a 404 below.
            .maybe_single()
            .execute(),
    )
    # .maybe_single() returns None for 0 rows. Normalize to a dict.
    tx = (
        result
        if isinstance(result, dict)
        else (result.data if result else None)
    )
    if not tx:
        raise HTTPException(404, "Disbursement not found")
    if current_user["id"] not in (tx.get("landlord_id"),) \
            and current_user.get("role") != "admin":
        raise HTTPException(403, "Not authorized")

    return {
        "merchant_tx_ref": merchant_tx_ref,
        "status": tx.get("status"),
        "amount_ngn": float(tx.get("amount") or 0),
        "nomba_transfer_id": tx.get("nomba_transfer_id"),
        "source_transfer_id": tx.get("source_transfer_id"),
        "agreement_id": tx.get("agreement_id"),
        "created_at": tx.get("created_at"),
        "released_at": tx.get("released_at"),
        "refunded_at": tx.get("refunded_at"),
    }


# ============================================================
# Background notification helper
# ============================================================

async def _notify_landlord_payout(
    agreement_id: str,
    merchant_tx_ref: str,
    amount_ngn: float,
    nomba_status: str,
):
    """Notify landlord that a payout is processing / completed / failed."""
    logger.info(
        "Payout notification | agreement=%s | ref=%s | amount=%.2f | nomba_status=%s",
        agreement_id, merchant_tx_ref, amount_ngn, nomba_status,
    )
    # Plug into existing notification_service here
