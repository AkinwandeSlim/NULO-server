"""
PropFlow Node 6: Provision Nomba DVA  (maps to "Payment Agent - DVA setup" step)

Responsibility:
  Create Nomba virtual account for this specific lease agreement.
  Delegates to the shared PaymentService which tries Nomba sandbox first
  and falls back to a mock NUBAN if Nomba is unavailable.

Refactored (post-hackathon):
  - Removed all direct Supabase and Nomba calls
  - Now uses PaymentService.provision_virtual_account() for consistent behavior
    with the manual route (routes/nomba.py)
  - Nomba sandbox (sub-account VA creation) is tried first
  - Mock NUBAN (9391-xxxxxx) is only used as a last resort
  - propflow_workflow_id is passed through for context-aware resume
"""

import logging

from app.propflow.state import PropFlowState
from app.services.payment_service import PaymentServiceError, payment_service

logger = logging.getLogger(__name__)


async def provision_nomba_dva_node(state: PropFlowState) -> PropFlowState:
    """
    Node 6 -- Payment Agent: DVA provisioning.

    Delegates entirely to PaymentService.provision_virtual_account().
    The service handles:
      1. Fetching agreement details
      2. Idempotency check (already provisioned?)
      3. Landlord name + property title for account naming
      4. Sanitized account name (ASCII, 8-64 chars)
      5. Expected amount calculation from rent + frequency
      6. Nomba sandbox VA creation (sub-account-scoped, Path B)
      7. Mock NUBAN fallback if Nomba is unavailable
      8. DB write (virtual_account_number, expected_payment_amount, etc.)
      9. propflow_workflow_id storage for context-aware resume

    Args:
        state: PropFlowState with agreement_id, workflow_id populated

    Returns:
        Updated state with nomba_virtual_account_number,
        expected_payment_amount, and current_stage
    """
    agreement_id = state.get("agreement_id")
    workflow_id = state.get("workflow_id")

    if not agreement_id:
        error_log = state.get("error_log", [])
        return {
            **state,
            "error_log": error_log + ["provision_nomba_dva: No agreement_id in state"],
            "current_stage": "dva_provisioning_failed",
        }

    logger.info(
        "[provision_nomba_dva] Starting DVA provisioning agreement=%s",
        agreement_id,
    )

    try:
        # Delegate to shared PaymentService
        # Tries Nomba sandbox first, falls back to mock if unavailable
        result = await payment_service.provision_virtual_account(
            agreement_id=agreement_id,
            propflow_workflow_id=workflow_id,
        )

        virtual_account_number = result["virtual_account_number"]
        expected_amount = result["expected_amount"]
        provision_status = result["status"]

        logger.info(
            "[provision_nomba_dva] DVA %s agreement=%s nuban=%s expected=%.2f",
            provision_status, agreement_id, virtual_account_number, expected_amount,
        )

        return {
            **state,
            "nomba_virtual_account_number": virtual_account_number,
            "expected_payment_amount": expected_amount,
            "current_stage": "nomba_provisioned",
        }

    except PaymentServiceError as exc:
        logger.error(
            "[provision_nomba_dva] PaymentService error: %s",
            exc,
        )
        error_log = state.get("error_log", [])
        return {
            **state,
            "error_log": error_log + [f"DVA provisioning error: {str(exc)}"],
            "current_stage": "dva_provisioning_failed",
        }

    except Exception as exc:
        logger.error(
            "[provision_nomba_dva] Unexpected error: %s",
            exc,
        )
        error_log = state.get("error_log", [])
        return {
            **state,
            "error_log": error_log + [f"DVA provisioning error: {str(exc)}"],
            "current_stage": "dva_provisioning_failed",
        }
