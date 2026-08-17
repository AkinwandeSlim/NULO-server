"""
PropFlow Node 7: Disburse Landlord  (maps to "Payment Agent - landlord payout" step)

Responsibility:
  Transfer collected rent payments to landlord's bank account.
  Delegates to the shared PaymentService which tries Nomba sandbox first
  and falls back to a mock transfer if Nomba is unavailable.

Refactored (post-hackathon):
  - Removed all direct Supabase and Nomba calls
  - Removed hardcoded 2% platform fee — PaymentService uses agreement.platform_fee
  - Now uses PaymentService.disburse_to_landlord() for consistent behavior
    with the auto-disbursement in routes/nomba.py
  - Nomba sandbox (sub-account transfer, Path B) is tried first
  - Mock fallback only used as a last resort
  - propflow_workflow_id is passed through for context-aware resume
"""

import logging

from app.propflow.state import PropFlowState
from app.services.payment_service import PaymentServiceError, payment_service

logger = logging.getLogger(__name__)


async def disburse_landlord_node(state: PropFlowState) -> PropFlowState:
    """
    Node 7 -- Payment Agent: landlord disbursement.

    Delegates to PaymentService.disburse_to_landlord().
    The service handles:
      1. Fetching agreement + landlord bank details
      2. Bank detail verification
      3. Payout calculation (total_received - platform_fee)
      4. Idempotency check (already disbursed?)
      5. Nomba sandbox transfer (sub-account, Path B) or parent transfer
      6. Mock transfer fallback if Nomba is unavailable
      7. Transaction record + agreement status update

    Node-level logic:
      - Skips disbursement unless reconciliation_status == FULL_PAYMENT
      - Bypasses FULL_PAYMENT check if using a demo (9390/9391/9392) NUBAN

    Args:
        state: PropFlowState with agreement_id, expected_payment_amount,
               nomba_virtual_account_number, reconciliation_status

    Returns:
        Updated state with disbursement_merchant_tx_ref and current_stage
    """
    agreement_id = state.get("agreement_id")
    reconciliation_status = state.get("reconciliation_status")
    expected_payment_amount = state.get("expected_payment_amount")
    virtual_account_number = state.get("nomba_virtual_account_number")
    workflow_id = state.get("workflow_id")

    if not agreement_id:
        error_log = state.get("error_log", [])
        return {
            **state,
            "error_log": error_log + ["disburse_landlord: No agreement_id in state"],
            "current_stage": "disbursement_failed",
        }

    # Only disburse on FULL_PAYMENT (skip check in demo mode)
    # Mock/demo NUBAN prefixes: 9390 (mock provider), 9391 (Nomba fallback),
    # 9392 (Paystack fallback) -- see app/services/payments/*_provider.py
    is_demo_nuban = virtual_account_number and str(virtual_account_number).startswith(
        ("9390", "9391", "9392")
    )
    if reconciliation_status != "FULL_PAYMENT" and not is_demo_nuban:
        logger.info(
            "[disburse_landlord] Skipping disbursement agreement=%s status=%s",
            agreement_id, reconciliation_status,
        )
        return {
            **state,
            "current_stage": "awaiting_full_payment",
        }

    if is_demo_nuban:
        logger.info(
            "[disburse_landlord] Demo NUBAN detected - bypassing FULL_PAYMENT check"
        )

    logger.info(
        "[disburse_landlord] Starting disbursement agreement=%s amount=%s",
        agreement_id, expected_payment_amount,
    )

    try:
        # Delegate to shared PaymentService
        # Tries Nomba sandbox first, falls back to mock if unavailable
        result = await payment_service.disburse_to_landlord(
            agreement_id=agreement_id,
            amount=expected_payment_amount,
            propflow_workflow_id=workflow_id,
        )

        disbursement_status = result["status"]
        merchant_tx_ref = result.get("merchant_tx_ref")
        disbursement_amount = result.get("disbursement_amount")
        platform_fee = result.get("platform_fee")

        logger.info(
            "[disburse_landlord] Disbursement %s agreement=%s amount=%s ref=%s",
            disbursement_status, agreement_id, disbursement_amount, merchant_tx_ref,
        )

        # Map service status to node stage
        if disbursement_status in ("completed", "mock_disbursed"):
            current_stage = "disbursement_complete"
        elif disbursement_status == "skipped":
            current_stage = "awaiting_full_payment"
        else:
            current_stage = "disbursement_failed"

        return {
            **state,
            "disbursement_merchant_tx_ref": merchant_tx_ref,
            "disbursement_amount": disbursement_amount,
            "platform_fee": platform_fee,
            "current_stage": current_stage,
        }

    except PaymentServiceError as exc:
        logger.error(
            "[disburse_landlord] PaymentService error: %s",
            exc,
        )
        error_log = state.get("error_log", [])
        return {
            **state,
            "error_log": error_log + [f"Nomba disbursement error: {str(exc)}"],
            "current_stage": "disbursement_failed",
        }

    except Exception as exc:
        logger.error(
            "[disburse_landlord] Unexpected error: %s",
            exc,
        )
        error_log = state.get("error_log", [])
        return {
            **state,
            "error_log": error_log + [f"Disbursement error: {str(exc)}"],
            "current_stage": "disbursement_failed",
        }
