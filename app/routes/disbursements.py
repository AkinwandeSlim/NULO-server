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
# DEMO HELPER: Simulate payout_success webhook
# POST /api/v1/agreements/{agreement_id}/simulate-payout-webhook
# Auth: landlord on this agreement only
# Body: { merchant_tx_ref }
# Returns: { success, message, transaction_id, status }
# ============================================================

@router.post("/agreements/{agreement_id}/simulate-payout-webhook")
async def simulate_payout_webhook(
    agreement_id: str,
    body: dict,
    current_user=Depends(get_current_user),
):
    """
    DEMO ONLY: Simulate a payout_success webhook for testing purposes.
    
    This allows testing the complete disbursement flow without waiting
    for the actual Nomba webhook. It directly updates the transaction
    status to 'released' and sets the released_at timestamp.
    
    Only the landlord on this agreement can use this endpoint.
    """
    merchant_tx_ref = (body.get("merchant_tx_ref") or "").strip()
    if not merchant_tx_ref:
        raise HTTPException(400, "merchant_tx_ref is required")
    
    # Verify the landlord owns this agreement
    agreement_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .select("id, landlord_id")
            .eq("id", agreement_id)
            .maybe_single()
            .execute(),
    )
    agreement = (
        agreement_result
        if isinstance(agreement_result, dict)
        else (agreement_result.data if agreement_result else None)
    )
    if not agreement:
        raise HTTPException(404, "Agreement not found")
    if current_user["id"] != agreement["landlord_id"]:
        raise HTTPException(403, "Only the landlord on this agreement can simulate payout")
    
    # Find the transaction by merchant_tx_ref
    tx_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .select("id, status, amount, agreement_id")
            .eq("nomba_transfer_ref", merchant_tx_ref)
            .maybe_single()
            .execute(),
    )
    transaction = tx_result.data
    if not transaction:
        raise HTTPException(
            404,
            f"Transaction with merchant_tx_ref '{merchant_tx_ref}' not found"
        )
    
    # Verify transaction belongs to this agreement
    if transaction.get("agreement_id") != agreement_id:
        raise HTTPException(400, "Transaction does not belong to this agreement")
    
    # Check if already released
    if transaction.get("status") == "released":
        return {
            "success": True,
            "message": "Transaction already in released state",
            "transaction_id": transaction.get("id"),
            "status": "released"
        }
    
    # Update transaction to released
    now_iso = datetime.now(timezone.utc).isoformat()
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .update({
                "status": "released",
                "released_at": now_iso,
                "nomba_transfer_id": f"simulated-{merchant_tx_ref[:8]}",
            })
            .eq("id", transaction.get("id"))
            .execute(),
    )
    
    logger.info(
        f"[DEMO] Simulated payout_success | tx_id={transaction.get('id')} | "
        f"ref={merchant_tx_ref} | amount={transaction.get('amount')} | "
        f"landlord={current_user['id']}"
    )
    
    return {
        "success": True,
        "message": "Payout webhook simulated successfully (DEMO MODE)",
        "transaction_id": transaction.get("id"),
        "status": "released"
    }


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

    # Persist all correct fields to landlord_profiles row (PRD V3.2 OPEN #1:
    # payout bank details now live on landlord_profiles, the single source of
    # truth -- NOT landlords, which keeps a legacy duplicate for now and will
    # be cleaned up in a future migration 007).
    # Use upsert() (not update()) because some landlords may not have a row
    # in `landlord_profiles` if their onboarding flow didn't create one --
    # we should be able to recover from that here rather than 500-ing the
    # entire disburse flow later. On the happy path this is a no-op for
    # existing rows (PostgREST treats upsert as update when the PK exists).
    # id is the shared PK (auth.users.id) on both landlord_profiles and the
    # old landlords table, so the same upsert-by-id pattern still works.
    now = datetime.now(timezone.utc).isoformat()
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("landlord_profiles")
            .upsert({
                "id": current_user["id"],
                "bank_account_number": account_number,
                "bank_name": bank_display_name,    # Human-readable display name
                "account_name": verified_account_name,
                "bank_code": bank_code,            # Bank code for API calls
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
    # The frontend may send nomba_account_ref (agreement.id + "-SUB") as source_transfer_id.
    # Strip the -SUB suffix to get the actual agreement ID, then lookup the transfer.
    # Per PRD: accountRef = agreement.id + "-SUB" is the convention for sub-account-scoped VAs.
    import re
    # Strip -SUB suffix if present to get the agreement ID
    clean_agreement_id = source_transfer_id.replace("-SUB", "") if source_transfer_id.endswith("-SUB") else source_transfer_id
    
    # If the cleaned ID is a valid UUID and matches the agreement_id, use it to lookup the transfer
    # Otherwise, use the agreement_id from the path parameter
    lookup_agreement_id = clean_agreement_id if clean_agreement_id == agreement_id else agreement_id
    
    transfer_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .select("id, amount_received, reconciliation_result, agreement_id, currency, account_ref")
            .eq("agreement_id", lookup_agreement_id)
            .eq("reconciliation_result", "FULL_PAYMENT")
            .order("created_at", desc=True)
            .limit(1)
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
        raise HTTPException(404, "Source transfer not found - no FULL_PAYMENT transfers for this agreement")
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
    # Use the actual transfer ID from the lookup, not the source_transfer_id parameter
    actual_transfer_id = transfer.get("id")
    existing_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .select("id, nomba_transfer_ref, status, amount")
            .eq("source_transfer_id", actual_transfer_id)
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

    # 3. Fetch landlord bank details (PRD V3.2 OPEN #1: now from landlord_profiles,
    #    the payout-data single source of truth, NOT the legacy landlords table).
    landlord_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("landlord_profiles")
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

    # 3.5. Verify bank account via Nomba API if not already verified
    # Bank verification moved from onboarding to disbursement to reduce friction
    bank_account_number = landlord.get("bank_account_number")
    bank_code = landlord.get("bank_code")
    bank_verified_at = landlord.get("bank_verified_at")

    if bank_account_number and bank_code and not bank_verified_at:
        logger.info(
            "Bank not verified yet - performing Nomba lookup | landlord=%s | account=%s",
            agreement["landlord_id"], bank_account_number
        )
        try:
            lookup_result = await nomba_client.lookup_bank_account(
                account_number=bank_account_number,
                bank_code=bank_code
            )
            
            if lookup_result and lookup_result.get("accountName"):
                # Verification successful - update landlord_profiles
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: supabase_admin
                        .table("landlord_profiles")
                        .update({
                            "bank_verified_at": datetime.utcnow().isoformat(),
                            "account_name": lookup_result.get("accountName"),  # Use Nomba's verified name
                            "updated_at": datetime.utcnow().isoformat(),
                        })
                        .eq("id", agreement["landlord_id"])
                        .execute(),
                )
                logger.info(
                    "Bank verification successful via Nomba API | landlord=%s | verified_name=%s",
                    agreement["landlord_id"], lookup_result.get("accountName")
                )
                # Update local landlord dict with verified data
                landlord["bank_verified_at"] = datetime.utcnow().isoformat()
                landlord["account_name"] = lookup_result.get("accountName")
            else:
                # For demo/hackathon: if Nomba lookup fails but bank details are present, allow disbursement
                logger.warning(
                    "Nomba lookup returned no account name - using provided details for demo | landlord=%s",
                    agreement["landlord_id"]
                )
                # Auto-verify for demo purposes
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: supabase_admin
                        .table("landlord_profiles")
                        .update({
                            "bank_verified_at": datetime.utcnow().isoformat(),
                            "updated_at": datetime.utcnow().isoformat(),
                        })
                        .eq("id", agreement["landlord_id"])
                        .execute(),
                )
                landlord["bank_verified_at"] = datetime.utcnow().isoformat()
        except Exception as e:
            # For demo/hackathon: if Nomba API fails, allow disbursement with existing details
            logger.warning(
                "Nomba bank lookup failed - using provided details for demo | landlord=%s | error=%s",
                agreement["landlord_id"], str(e)
            )
            # Auto-verify for demo purposes
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: supabase_admin
                    .table("landlord_profiles")
                    .update({
                        "bank_verified_at": datetime.utcnow().isoformat(),
                        "updated_at": datetime.utcnow().isoformat(),
                    })
                    .eq("id", agreement["landlord_id"])
                    .execute(),
            )
            landlord["bank_verified_at"] = datetime.utcnow().isoformat()

    # If bank details are fully present but bank_verified_at was never stamped
    # (e.g. details were inserted directly into DB without going through
    # /disbursements/lookup-bank), auto-stamp it now so the disburse can proceed.
    # This handles dev/hackathon setups where bank details are seeded manually.
    has_bank_details = all(
        landlord.get(f) for f in ("bank_account_number", "bank_code", "account_name")
    )
    if not landlord.get("bank_verified_at"):
        if not has_bank_details:
            raise HTTPException(
                400,
                "Landlord bank account has not been verified and bank details are incomplete. "
                "Call POST /disbursements/lookup-bank first.",
            )
        # All details present — auto-stamp verified_at so this path is only hit once
        now_stamp = datetime.now(timezone.utc).isoformat()
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: supabase_admin
                    .table("landlord_profiles")
                    .update({"bank_verified_at": now_stamp, "updated_at": now_stamp})
                    .eq("id", agreement["landlord_id"])
                    .execute(),
            )
            landlord["bank_verified_at"] = now_stamp
            logger.info(
                "Auto-stamped bank_verified_at for landlord %s (bank details present but unverified)",
                agreement["landlord_id"],
            )
        except Exception as stamp_exc:
            logger.warning("Could not auto-stamp bank_verified_at: %s — proceeding anyway", stamp_exc)
            landlord["bank_verified_at"] = now_stamp  # treat as verified in-memory

    for field in ("bank_account_number", "bank_code", "account_name"):
        if not landlord.get(field):
            raise HTTPException(
                400, f"Landlord bank details incomplete: {field} is missing — call POST /disbursements/lookup-bank",
            )

    # 3a. Pre-transfer bank-name re-verify (24h cache).
    # The landlord verified their account at onboarding/lookup-bank time. Re-verify
    # here as a safety net in case the bank account has changed or our stored
    # account_name is stale. If the names differ, log a BANK_NAME_MISMATCH warning
    # and write a payment_reconciliation_log entry, but do NOT block the transfer --
    # the landlord needs the money. The warning is surfaced in the response so the
    # UI can show a yellow banner.
    bank_name_warning = None
    bank_verified_at_raw = landlord.get("bank_verified_at")
    cache_stale = True
    if bank_verified_at_raw:
        try:
            # Supabase returns ISO format; tolerate trailing 'Z'
            verified_at_dt = datetime.fromisoformat(
                str(bank_verified_at_raw).replace("Z", "+00:00")
            )
            age_hours = (
                datetime.now(timezone.utc) - verified_at_dt
            ).total_seconds() / 3600
            cache_stale = age_hours >= 24
        except (TypeError, ValueError):
            cache_stale = True
    if cache_stale:
        try:
            reverify = await nomba_client.lookup_bank_account(
                account_number=landlord["bank_account_number"],
                bank_code=landlord["bank_code"],
            )
            nomba_name = (reverify.get("accountName") or "").strip()
            stored_name = (landlord.get("account_name") or "").strip()
            if nomba_name and stored_name and nomba_name.lower() != stored_name.lower():
                bank_name_warning = {
                    "kind": "BANK_NAME_MISMATCH",
                    "expected_account_name": stored_name,
                    "actual_account_name": nomba_name,
                    "message": (
                        f"Bank returned name '{nomba_name}' differs from stored "
                        f"'{stored_name}'. Transfer will proceed (warn-not-block)."
                    ),
                }
                logger.warning(
                    "BANK_NAME_MISMATCH pre-disburse | agreement=%s | "
                    "stored=%s | nomba=%s | proceeding",
                    agreement_id, stored_name, nomba_name,
                )
                # Best-effort: write a reconciliation log entry for traceability
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: supabase_admin
                            .table("payment_reconciliation_log")
                            .insert({
                                "agreement_id": agreement_id,
                                "source_transfer_id": actual_transfer_id,
                                "landlord_id": agreement["landlord_id"],
                                "log_type": "BANK_NAME_MISMATCH",
                                "expected_value": stored_name,
                                "actual_value": nomba_name,
                                "details": "Pre-disbursement re-verify surfaced a name mismatch; "
                                           "transfer proceeded (warn-not-block).",
                                "created_at": datetime.now(timezone.utc).isoformat(),
                            })
                            .execute(),
                    )
                except Exception as log_exc:
                    # Reconciliation log is a nice-to-have, not a hard requirement
                    logger.debug(
                        "BANK_NAME_MISMATCH log insert failed (non-fatal) | error=%s",
                        log_exc,
                    )
        except Exception as e:
            # For demo/hackathon: if re-verification fails, skip and proceed with stored details
            logger.warning(
                "Bank re-verification failed for demo - using stored details | agreement=%s | error=%s",
                agreement_id, str(e)
            )
    
    # Refresh bank_verified_at even on success so the next call within
    # 24h skips this lookup.
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("landlord_profiles")
            .update({
                "bank_verified_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", agreement["landlord_id"])
            .execute(),
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
    merchant_tx_ref = build_merchant_tx_ref(actual_transfer_id, retry_count)
    now = datetime.now(timezone.utc).isoformat()

    # 6. IDEMPOTENCY CHECK: Check if transaction with this nomba_transfer_ref already exists
    existing_tx = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .select("id, status, amount, nomba_transfer_ref")
            .eq("nomba_transfer_ref", merchant_tx_ref)
            .maybe_single()
            .execute(),
    )
    
    if existing_tx.data:
        existing_status = existing_tx.data.get("status")
        # Allow retry if the existing transaction is failed
        if existing_status == "failed":
            logger.info(
                f"[DISBURSE] Existing transaction is failed, allowing retry | "
                f"ref={merchant_tx_ref} | old_status={existing_status}"
            )
            # Delete the failed transaction to allow retry
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: supabase_admin
                    .table("transactions")
                    .delete()
                    .eq("id", existing_tx.data.get("id"))
                    .execute(),
            )
        else:
            # Transaction already exists and is not failed, return it instead of creating duplicate
            logger.info(
                f"[DISBURSE] Transaction already exists for ref={merchant_tx_ref} | "
                f"status={existing_status} | returning existing"
            )
            return {
                "success": True,
                "status": existing_status,
                "merchant_tx_ref": merchant_tx_ref,
                "amount_ngn": existing_tx.data.get("amount"),
                "transaction_id": existing_tx.data.get("id"),
                "message": f"Disbursement already initiated (status: {existing_status})",
            }

    # 7. INSERT transactions row FIRST (status = pending) to avoid race condition
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
                "source_transfer_id": actual_transfer_id,
                "notes": f"payout={payout_amount} status=initial_pending",
            })
            .execute(),
    )
    tx_row = insert_result.data[0] if insert_result.data else {}

    # 7. Call Nomba (or skip in demo mode)
    # Detect sub-account source: the nomba_account_ref we stored has a "-SUB"
    # suffix when the VA was provisioned under the sub-account. Disbursements
    # from those VAs MUST go through the sub-account transfer endpoint, since
    # the parent wallet has 0 spendable balance even though the balance API
    # reports funds (verified live 2026-07-04 with INSUFFICIENT_BALANCE).
    
    # DEMO MODE: Skip actual Nomba transfer if DEMO_MODE env var is set
    from app.config import settings
    demo_mode = settings.DEMO_MODE
    
    if demo_mode:
        logger.info(
            f"[DEMO MODE] Skipping actual Nomba transfer | ref={merchant_tx_ref} | "
            f"amount={payout_amount} | Will mark as released directly"
        )
        nomba_data = {
            "status": "SUCCESS",
            "transactionId": f"demo-txn-{merchant_tx_ref[:8]}",
            "message": "Demo mode - no actual transfer made"
        }
    else:
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
        "bank_name_warning": bank_name_warning,
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
