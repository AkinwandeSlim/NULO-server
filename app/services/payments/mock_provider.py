"""
Mock payment provider -- offline / tests.

Always returns a synthetic mock NUBAN so the payment flow can run end-to-end
with no external credentials. Mirrors ``MockProvider`` in the LLM layer.
"""

from __future__ import annotations

import uuid
from typing import Optional

from app.services.payments.base import VirtualAccountResult


class MockPaymentProvider:
    """Offline provider that always returns a mock NUBAN."""

    name = "mock"

    @property
    def available(self) -> bool:
        return True

    async def provision_virtual_account(
        self,
        account_ref: str,
        account_name: str,
        expected_amount: Optional[float] = None,
    ) -> VirtualAccountResult:
        mock_nuban = f"9390{uuid.uuid4().hex[:6].upper()}"
        return VirtualAccountResult(
            bankAccountNumber=mock_nuban,
            bankAccountName=account_name,
            bankName="NuloAfrica (Sandbox)",
            accountRef=account_ref,
            recovered=False,
            is_mock=True,
        )

    async def get_virtual_account(self, account_ref: str) -> Optional[VirtualAccountResult]:
        return None

    async def expire_virtual_account(self, account_ref: str) -> bool:
        return True

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        timestamp: Optional[str] = None,
    ) -> bool:
        # Mock provider accepts any signature (offline testing only).
        return True


__all__ = ["MockPaymentProvider"]
