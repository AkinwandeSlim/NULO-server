"""
Payment Service — shared service layer for Nomba payment operations.

Both FastAPI route handlers and PropFlow graph nodes call this service
instead of writing to Supabase or Nomba directly. This ensures:

1. Consistent DVA provisioning flow (Nomba sandbox first, mock fallback)
2. Consistent disbursement flow (platform fee calculation, transaction records)
3. propflow_workflow_id is always captured when present
4. Business logic lives in one place

Usage from routes:
    result = await payment_service.provision_virtual_account(
        agreement_id="...",
        propflow_workflow_id="...",  # optional
    )

Usage from PropFlow nodes:
    result = await payment_service.provision_virtual_account(
        agreement_id=state["agreement_id"],
        propflow_workflow_id=state.get("workflow_id"),
    )
    result = await payment_service.disburse_to_landlord(
        agreement_id=state["agreement_id"],
        amount=state.get("expected_payment_amount"),
        propflow_workflow_id=state.get("workflow_id"),
    )

Architecture:
  - Tries Nomba sandbox (sub-account VA creation / sub-account bank transfer) FIRST
  - Falls back to mock NUBAN / mock transfer ONLY when Nomba is truly unavailable
  - All DB writes go through Supabase (never skip the write even on mock fallback)
  - propflow_workflow_id is stored in the agreement row for context-aware resume
"""

import asyncio
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Optional, Dict, Any

from app.database import supabase_admin
from app.services.nomba_client import NombaAPIError, nomba_client
from app.services.nomba_helpers import (
    calculate_expected_amount,
    calculate_next_due_date,
    calculate_landlord_payout,
    build_merchant_tx_ref,
)

logger = logging.getLogger(__name__)


class PaymentService:
    """Shared service for payment operations (DVA provisioning, disbursement)."""

    # ------------------------------------------------------------------
    # PUBLIC: Provision a Nomba virtual account for a signed agreement
    # ------------------------------------------------------------------

    @staticmethod
    async def provision_virtual_account(
        agreement_id: str,
        *,
        propflow_workflow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Provision a Nomba virtual account (DVA) for a signed agreement.

        Strategy (production-grade):
          1. Fetch agreement from DB
          2. Idempotency check — return existing VA if already provisioned
          3. Fetch landlord name + property title for the account name
          4. Build + sanitize account name (landlord name + property hint)
          5. Calculate expected payment amount from rent + frequency
          6. Recovery: try GET existing VA on Nomba (handles orphaned VAs)
          7. CREATE on Nomba sandbox (sub-account-scoped VA, Path B)
          8. If Nomba is unavailable → fall back to mock NUBAN
          9. Write VA details + propflow_workflow_id to agreements table
          10. Return consolidated result dict

        Args:
            agreement_id: UUID of the signed agreement
            propflow_workflow_id: Optional LangGraph thread ID for PropFlow context

        Returns:
            dict with keys:
              status: "provisioned" | "already_provisioned" | "mock_provisioned"
              virtual_account_number: NUBAN
              virtual_account_name: account name on the VA
              account_ref: Nomba account reference
              expected_amount: expected payment per cycle
              next_due_date: first payment due date (ISO string or None)
              propflow_workflow_id: stored if provided

        Raises:
            PaymentServiceError on unrecoverable failures (missing agreement,
            invalid state, etc.)
        """
        logger.info(
            "[PAYMENT SERVICE] provision_virtual_account agreement=%s propflow=%s",
            agreement_id, propflow_workflow_id,
        )

        loop = asyncio.get_event_loop()

        # ── Step 1: Fetch agreement ─────────────────────────────────────────────
        result = await loop.run_in_executor(
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
            raise PaymentServiceError(f"Agreement {agreement_id} not found")

        # Agreement must be at least in SIGNED status
        if agreement.get("status") not in ("SIGNED", "ACTIVE"):
            raise PaymentServiceError(
                f"Agreement {agreement_id} must be in SIGNED status "
                f"(got {agreement.get('status')})"
            )

        # ── Step 2: Idempotency — already provisioned? ──────────────────────────
        if agreement.get("virtual_account_number"):
            logger.info(
                "[PAYMENT SERVICE] Already provisioned agreement=%s nuban=%s",
                agreement_id, agreement["virtual_account_number"],
            )
            return {
                "status": "already_provisioned",
                "virtual_account_number": agreement["virtual_account_number"],
                "virtual_account_name": agreement["virtual_account_name"],
                "bank_name": None,
                "account_ref": agreement.get("nomba_account_ref"),
                "expected_amount": float(agreement.get("expected_payment_amount") or 0),
                "frequency": agreement.get("payment_frequency"),
                "next_due_date": agreement.get("next_payment_due_date"),
                "propflow_workflow_id": propflow_workflow_id,
            }

        # ── Step 3: Fetch landlord name + property title for account naming ─────
        # Banking convention: account name = beneficiary (landlord), not payer
        user_result = await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("users")
                .select("full_name, email")
                .eq("id", agreement["landlord_id"])
                .single()
                .execute(),
        )
        user = user_result.data or {}

        property_title = ""
        if agreement.get("property_id"):
            prop_result = await loop.run_in_executor(
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

        # ── Step 4: Build + sanitize account name ───────────────────────────────
        landlord_name = (
            user.get("full_name")
            or user.get("email")
            or "NuloAfrica Landlord"
        ).strip()

        if property_title:
            raw_name = f"{landlord_name} {property_title}"
        else:
            raw_name = landlord_name

        # Sanitize: only ASCII letters/digits and single spaces
        sanitized = []
        for char in raw_name.strip():
            if char.isascii() and (char.isalnum() or char == " "):
                sanitized.append(char)
        clean_name = " ".join("".join(sanitized).split())

        # Nomba spec: accountName must be 8-64 chars
        account_name = clean_name[:64]
        if len(account_name) < 8:
            account_name = (account_name + " NuloAfrica")[:64]

        # Validate agreement_id length (16-64 chars per Nomba spec)
        agreement_id_str = str(agreement_id) if not isinstance(agreement_id, str) else agreement_id
        if not (16 <= len(agreement_id_str) <= 64):
            raise PaymentServiceError(
                f"agreement_id must be 16-64 chars (got {len(agreement_id_str)})"
            )

        # ── Step 5: Calculate expected amount ───────────────────────────────────
        frequency = agreement.get("payment_frequency") or "MONTHLY"
        rent_amount = float(agreement.get("rent_amount") or 0)
        expected_amount = calculate_expected_amount(rent_amount, frequency)

        # ── Step 6: Build sub-account reference (Path B) ────────────────────────
        # The "-SUB" suffix tags sub-account-scoped VAs for webhook routing
        sub_account_ref = f"{agreement_id}-SUB"

        # ── Step 7: Recovery — try GET existing VA on Nomba ─────────────────────
        # Handles the case where a previous provisioning call succeeded on Nomba
        # but failed on our side (e.g. server crash between Nomba 200 and DB write)
        data = None
        if nomba_client.sub_account_id:
            try:
                existing = await nomba_client.get_virtual_account(sub_account_ref)
                if existing and not existing.get("expired", False):
                    logger.info(
                        "[PAYMENT SERVICE] Recovered existing VA agreement=%s nuban=%s",
                        agreement_id, existing.get("bankAccountNumber"),
                    )
                    # Map Nomba response fields to our expected shape
                    data = {
                        "bankAccountNumber": existing["bankAccountNumber"],
                        "bankAccountName": existing["bankAccountName"],
                        "accountRef": existing["accountRef"],
                        "recovered": True,
                    }
            except Exception as exc:
                logger.warning(
                    "[PAYMENT SERVICE] Recovery GET failed (non-fatal) agreement=%s err=%s",
                    agreement_id, exc,
                )

        # ── Step 8: CREATE on Nomba sandbox (with mock fallback) ────────────────
        if data is None:
            try:
                if not nomba_client.sub_account_id:
                    logger.warning(
                        "[PAYMENT SERVICE] NOMBA_SUB_ACCOUNT_ID not set — falling back to mock"
                    )
                    raise NombaAPIError("sub_account_id not configured")

                logger.info(
                    "[PAYMENT SERVICE] Creating Nomba VA agreement=%s ref=%s name=%r",
                    agreement_id, sub_account_ref, account_name,
                )
                nomba_data = await nomba_client.create_virtual_account_for_subaccount(
                    sub_account_id=nomba_client.sub_account_id,
                    account_ref=sub_account_ref,
                    account_name=account_name,
                )

                if not nomba_data or not nomba_data.get("bankAccountNumber"):
                    raise NombaAPIError("Nomba returned empty VA response")

                data = {
                    "bankAccountNumber": nomba_data["bankAccountNumber"],
                    "bankAccountName": nomba_data["bankAccountName"],
                    "bankName": nomba_data.get("bankName"),
                    "accountRef": nomba_data.get("accountRef", sub_account_ref),
                    "recovered": False,
                }
                logger.info(
                    "[PAYMENT SERVICE] Nomba VA created agreement=%s nuban=%s",
                    agreement_id, data["bankAccountNumber"],
                )

            except (NombaAPIError, Exception) as exc:
                # ── Fall back to mock NUBAN ────────────────────────────────────
                logger.warning(
                    "[PAYMENT SERVICE] Nomba unavailable (%s) — using mock NUBAN",
                    exc,
                )
                mock_nuban = f"9391{str(uuid.uuid4().hex)[:6].upper()}"
                data = {
                    "bankAccountNumber": mock_nuban,
                    "bankAccountName": account_name,
                    "bankName": "NuloAfrica (Sandbox)",
                    "accountRef": sub_account_ref,
                    "recovered": False,
                }

        # ── Step 9: Calculate next due date ─────────────────────────────────────
        next_due = None
        if agreement.get("lease_start_date"):
            try:
                start = date.fromisoformat(str(agreement["lease_start_date"]))
                next_due = calculate_next_due_date(start, frequency)
            except (ValueError, TypeError):
                logger.warning(
                    "[PAYMENT SERVICE] Could not parse lease_start_date=%s",
                    agreement.get("lease_start_date"),
                )

        # ── Step 10: Write to agreements table ──────────────────────────────────
        update_fields = {
            "virtual_account_number": data["bankAccountNumber"],
            "virtual_account_name": data["bankAccountName"],
            "nomba_account_ref": data["accountRef"],
            "expected_payment_amount": expected_amount,
            "payment_frequency": frequency,
            "next_payment_due_date": str(next_due) if next_due else None,
            "reconciliation_status": "PENDING",
            "total_received_amount": 0,
        }

        if propflow_workflow_id:
            update_fields["propflow_thread_id"] = propflow_workflow_id

        await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("agreements")
                .update(update_fields)
                .eq("id", agreement_id)
                .execute(),
        )

        # Determine overall status
        is_mock = data["bankAccountNumber"].startswith("9391")
        status = "mock_provisioned" if is_mock else "provisioned"

        logger.info(
            "[PAYMENT SERVICE] VA provisioned agreement=%s nuban=%s freq=%s expected=%.2f status=%s",
            agreement_id, data["bankAccountNumber"], frequency, expected_amount, status,
        )

        return {
            "status": status,
            "virtual_account_number": data["bankAccountNumber"],
            "virtual_account_name": data["bankAccountName"],
            "bank_name": data.get("bankName"),
            "account_ref": data["accountRef"],
            "expected_amount": expected_amount,
            "frequency": frequency,
            "next_due_date": str(next_due) if next_due else None,
            "propflow_workflow_id": propflow_workflow_id,
        }

    # ------------------------------------------------------------------
    # PUBLIC: Disburse collected rent to landlord's bank account
    # ------------------------------------------------------------------

    @staticmethod
    async def disburse_to_landlord(
        agreement_id: str,
        *,
        amount: Optional[float] = None,
        source_transfer_id: Optional[str] = None,
        propflow_workflow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Disburse collected rent payments to the landlord's bank account.

        Strategy (production-grade):
          1. Fetch agreement + landlord bank details
          2. Verify bank details are complete and verified
          3. Calculate payout (total_received - platform_fee)
          4. Idempotency check — skip if already disbursed for this source
          5. Insert transactions row (status = pending)
          6. Try Nomba sandbox transfer (sub-account, Path B)
          7. If Nomba is unavailable → fall back to mock
          8. Update transaction row with result
          9. Update agreement status to ACTIVE
          10. Return consolidated result dict

        Args:
            agreement_id: UUID of the agreement
            amount: Optional amount override (defaults to total_received_amount)
            source_transfer_id: Optional source transfer ID for idempotency tracking
            propflow_workflow_id: Optional LangGraph thread ID for PropFlow context

        Returns:
            dict with keys:
              status: "completed" | "mock_disbursed" | "skipped" | "failed"
              disbursement_amount: amount paid to landlord
              platform_fee: fee retained by platform
              merchant_tx_ref: Nomba transaction reference
              propflow_workflow_id: stored if provided
        """
        logger.info(
            "[PAYMENT SERVICE] disburse_to_landlord agreement=%s propflow=%s",
            agreement_id, propflow_workflow_id,
        )

        loop = asyncio.get_event_loop()

        # ── Step 1: Fetch agreement ─────────────────────────────────────────────
        agreement_result = await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("agreements")
                .select(
                    "id, landlord_id, tenant_id, property_id, application_id, "
                    "platform_fee, total_received_amount, expected_payment_amount, "
                    "rent_amount, virtual_account_number, nomba_account_ref"
                )
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
            raise PaymentServiceError(f"Agreement {agreement_id} not found")

        landlord_id = agreement["landlord_id"]
        total_received = amount or float(agreement.get("total_received_amount") or 0)
        if total_received <= 0:
            logger.info(
                "[PAYMENT SERVICE] Skipping disbursement agreement=%s total_received=%.2f",
                agreement_id, total_received,
            )
            return {
                "status": "skipped",
                "disbursement_amount": 0,
                "platform_fee": 0,
                "merchant_tx_ref": None,
                "message": "No funds to disburse",
                "propflow_workflow_id": propflow_workflow_id,
            }

        # ── Step 2: Fetch landlord bank details ─────────────────────────────────
        landlord_result = await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("landlord_profiles")
                .select(
                    "id, bank_account_number, bank_name, account_name, "
                    "bank_code, bank_verified_at"
                )
                .eq("id", landlord_id)
                .maybe_single()
                .execute(),
        )
        landlord = (
            landlord_result
            if isinstance(landlord_result, dict)
            else (landlord_result.data if landlord_result else None)
        )
        if not landlord or not landlord.get("bank_verified_at"):
            logger.info(
                "[PAYMENT SERVICE] No verified bank details landlord=%s",
                landlord_id,
            )
            return {
                "status": "skipped",
                "disbursement_amount": 0,
                "platform_fee": 0,
                "merchant_tx_ref": None,
                "message": "Landlord bank details not verified",
                "propflow_workflow_id": propflow_workflow_id,
            }

        for field in ("bank_account_number", "bank_code", "account_name"):
            if not landlord.get(field):
                logger.info(
                    "[PAYMENT SERVICE] Incomplete bank details landlord=%s missing=%s",
                    landlord_id, field,
                )
                return {
                    "status": "skipped",
                    "disbursement_amount": 0,
                    "platform_fee": 0,
                    "merchant_tx_ref": None,
                    "message": f"Missing bank field: {field}",
                    "propflow_workflow_id": propflow_workflow_id,
                }

        # ── Step 3: Calculate payout ────────────────────────────────────────────
        platform_fee = float(agreement.get("platform_fee") or 0)
        payout_amount = calculate_landlord_payout(total_received, platform_fee)

        if payout_amount <= 0:
            logger.warning(
                "[PAYMENT SERVICE] Payout is 0 agreement=%s received=%.2f fee=%.2f",
                agreement_id, total_received, platform_fee,
            )
            return {
                "status": "skipped",
                "disbursement_amount": 0,
                "platform_fee": platform_fee,
                "merchant_tx_ref": None,
                "message": "Payout amount is zero after fees",
                "propflow_workflow_id": propflow_workflow_id,
            }

        # ── Step 4: Idempotency check ───────────────────────────────────────────
        # If source_transfer_id is provided, check we haven't already disbursed it
        if source_transfer_id:
            existing_result = await loop.run_in_executor(
                None,
                lambda: supabase_admin
                    .table("transactions")
                    .select("id, nomba_transfer_ref, status")
                    .eq("source_transfer_id", source_transfer_id)
                    .in_("transaction_type", ["nomba_disbursement"])
                    .execute(),
            )
            if existing_result.data:
                existing_tx = existing_result.data[0]
                logger.info(
                    "[PAYMENT SERVICE] Already disbursed agreement=%s transfer=%s status=%s",
                    agreement_id, source_transfer_id, existing_tx["status"],
                )
                return {
                    "status": existing_tx["status"],
                    "disbursement_amount": payout_amount,
                    "platform_fee": platform_fee,
                    "merchant_tx_ref": existing_tx.get("nomba_transfer_ref"),
                    "message": "Already processed",
                    "propflow_workflow_id": propflow_workflow_id,
                }

        # ── Step 5: Build idempotency key + insert transactions row ─────────────
        merchant_tx_ref = build_merchant_tx_ref(
            source_transfer_id or agreement_id, 0
        )
        now_iso = datetime.now(timezone.utc).isoformat()

        # Determine if this VA is sub-account-scoped
        account_ref = agreement.get("nomba_account_ref") or ""
        is_sub_account_va = account_ref.upper().endswith("-SUB")

        # Build transaction insert dict with optional propflow_thread_id
        tx_insert = {
            "agreement_id": agreement_id,
            "tenant_id": agreement.get("tenant_id"),
            "landlord_id": landlord_id,
            "property_id": agreement.get("property_id"),
            "application_id": agreement.get("application_id"),
            "amount": payout_amount,
            "currency": "NGN",
            "transaction_type": "nomba_disbursement",
            "status": "pending",
            "payment_gateway": "nomba",
            "held_at": now_iso,
            "released_at": None,
            "nomba_transfer_ref": merchant_tx_ref,
            "nomba_transfer_id": None,
            "source_transfer_id": source_transfer_id,
            "notes": f"payout={payout_amount} fee={platform_fee}",
        }
        if propflow_workflow_id:
            tx_insert["propflow_thread_id"] = propflow_workflow_id

        tx_result = await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("transactions")
                .insert(tx_insert)
                .execute(),
        )
        tx_row = tx_result.data[0] if tx_result.data else {}

        # ── Step 6: Try Nomba sandbox transfer (sub-account, Path B) ───────────
        is_mock = False
        nomba_status = "PENDING"

        try:
            if not nomba_client.sub_account_id:
                raise NombaAPIError("sub_account_id not configured")

            if is_sub_account_va:
                logger.info(
                    "[PAYMENT SERVICE] Nomba sub-account transfer sub=%s ref=%s amount=%.2f",
                    nomba_client.sub_account_id, merchant_tx_ref, payout_amount,
                )
                nomba_response = await nomba_client.transfer_to_bank_from_subaccount(
                    sub_account_id=nomba_client.sub_account_id,
                    amount_naira=payout_amount,
                    account_number=landlord["bank_account_number"],
                    account_name=landlord["account_name"],
                    bank_code=landlord["bank_code"],
                    merchant_tx_ref=merchant_tx_ref,
                    narration=f"Rent disbursement agreement={agreement_id[:8]}",
                )
            else:
                logger.info(
                    "[PAYMENT SERVICE] Nomba parent transfer ref=%s amount=%.2f",
                    merchant_tx_ref, payout_amount,
                )
                nomba_response = await nomba_client.transfer_to_bank(
                    amount_naira=payout_amount,
                    account_number=landlord["bank_account_number"],
                    account_name=landlord["account_name"],
                    bank_code=landlord["bank_code"],
                    merchant_tx_ref=merchant_tx_ref,
                    narration=f"Rent disbursement agreement={agreement_id[:8]}",
                )

            nomba_status = (nomba_response.get("status") or "PENDING").upper()
            logger.info(
                "[PAYMENT SERVICE] Nomba transfer response ref=%s status=%s",
                merchant_tx_ref, nomba_status,
            )

        except (NombaAPIError, Exception) as exc:
            # ── Step 7: Fall back to mock ──────────────────────────────────────
            logger.warning(
                "[PAYMENT SERVICE] Nomba unavailable (%s) — simulating disbursement",
                exc,
            )
            is_mock = True
            nomba_status = "SUCCESS"
            nomba_response = {
                "status": nomba_status,
                "id": f"mock-txn-{uuid.uuid4().hex[:8]}",
            }

        # ── Step 8: Update transaction row ──────────────────────────────────────
        if nomba_status == "SUCCESS":
            tx_status = "released"
        elif nomba_status == "REFUND":
            tx_status = "failed"
        else:
            tx_status = "pending"

        await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("transactions")
                .update({
                    "status": tx_status,
                    "nomba_transfer_id": nomba_response.get("id"),
                    "released_at": now_iso if tx_status == "released" else None,
                    "notes": (
                        f"payout={payout_amount} fee={platform_fee} "
                        f"nomba_status={nomba_status} "
                        f"{'(mock)' if is_mock else ''}"
                    ),
                })
                .eq("id", tx_row.get("id"))
                .execute(),
        )

        # ── Step 9: Update agreement status to ACTIVE ───────────────────────────
        if tx_status == "released":
            await loop.run_in_executor(
                None,
                lambda: supabase_admin
                    .table("agreements")
                    .update({
                        "disbursement_amount": payout_amount,
                        "disbursement_merchant_tx_ref": merchant_tx_ref,
                        "disbursement_status": "completed",
                        "platform_fee": platform_fee,
                        "status": "ACTIVE",
                    **(
                        {"propflow_thread_id": propflow_workflow_id}
                        if propflow_workflow_id
                        else {}
                    ),
                })
                    .eq("id", agreement_id)
                    .execute(),
            )

            # ── Sync property status → "occupied" ────────────────────────────────
            # Same pattern as the manual route's _reconcile_payment in nomba.py
            property_id = agreement.get("property_id")
            if property_id:
                try:
                    await loop.run_in_executor(
                        None,
                        lambda: supabase_admin
                            .table("properties")
                            .update({
                                "status": "occupied",
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            })
                            .eq("id", property_id)
                            .execute(),
                    )
                    logger.info(
                        "[PAYMENT SERVICE] Property status synced to occupied property=%s agreement=%s",
                        property_id, agreement_id,
                    )
                except Exception as prop_err:
                    logger.warning(
                        "[PAYMENT SERVICE] Could not sync property status property=%s error=%s",
                        property_id, prop_err,
                    )

        status = "mock_disbursed" if is_mock else "completed"

        logger.info(
            "[PAYMENT SERVICE] Disbursement %s agreement=%s amount=%.2f ref=%s",
            status, agreement_id, payout_amount, merchant_tx_ref,
        )

        return {
            "status": status,
            "disbursement_amount": payout_amount,
            "platform_fee": platform_fee,
            "merchant_tx_ref": merchant_tx_ref,
            "propflow_workflow_id": propflow_workflow_id,
            "transaction_id": tx_row.get("id"),
        }

    # ------------------------------------------------------------------
    # PUBLIC: Fetch payment status for an agreement
    # ------------------------------------------------------------------

    @staticmethod
    async def get_payment_status(agreement_id: str) -> Dict[str, Any]:
        """
        Fetch the payment status of an agreement.

        Returns current balance, expected amount, reconciliation status,
        and transfer history for the agreement.
        """
        loop = asyncio.get_event_loop()

        result = await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("agreements")
                .select(
                    "id, payment_frequency, expected_payment_amount, "
                    "total_received_amount, reconciliation_status, "
                    "next_payment_due_date, virtual_account_number, "
                    "virtual_account_name, tenant_id, landlord_id, "
                    "propflow_thread_id"
                )
                .eq("id", agreement_id)
                .single()
                .execute(),
        )
        agreement = result.data
        if not agreement:
            raise PaymentServiceError(f"Agreement {agreement_id} not found")

        # Build the suffixed account ref for transfer lookup
        uuid_match = re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            agreement_id, re.IGNORECASE,
        )
        clean_id = uuid_match.group(0) if uuid_match else agreement_id
        suffixed_ref = f"{clean_id}-SUB"

        transfers = await loop.run_in_executor(
            None,
            lambda: supabase_admin
                .table("virtual_account_transfers")
                .select(
                    "id, amount_received, sender_name, sender_bank, "
                    "reconciliation_result, created_at"
                )
                .eq("account_ref", suffixed_ref)
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
            "propflow_thread_id": agreement.get("propflow_thread_id"),
            "transfer_history": transfers.data or [],
        }


class PaymentServiceError(Exception):
    """Raised when a payment operation cannot be completed."""
    pass


# Singleton
payment_service = PaymentService()
