"""
Payment Provider abstraction -- base contract.
================================================

A thin, plugin-style interface over tenant-facing payment COLLECTION so the
platform can switch providers (Nomba / Paystack / mock) with a single
``PAYMENT_PROVIDER`` change in ``server/.env`` and NO call-site edits.

This mirrors the LLM provider layer in ``app/propflow/services/llm_provider.py``.

Scope (IMPORTANT)
-----------------
This abstraction covers **payment collection only** (virtual-account / NUBAN
provisioning + lookup + expiry + webhook signature verification).

**Disbursement (landlord payout) always stays on Nomba** regardless of the
configured provider, because Paystack has no escrow/disbursement equivalent.
See ``app/config.py`` ``PAYMENT_PROVIDER`` comment.

How to switch providers (the "simple file change")
--------------------------------------------------
Set ``PAYMENT_PROVIDER`` in ``server/.env`` and restart:

    PAYMENT_PROVIDER=nomba      # Nomba virtual accounts (default)
    PAYMENT_PROVIDER=paystack   # Paystack dedicated virtual accounts (test mode)
    PAYMENT_PROVIDER=mock       # Offline / tests -- always returns a mock NUBAN

Adding a provider = (1) implement ``PaymentProvider``, (2) register it in
``registry.build_payment_provider_registry``. No call-site changes required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class VirtualAccountResult:
    """Normalized virtual-account (NUBAN) details returned by a provider.

    Field names intentionally match the Nomba response shape used throughout
    ``payment_service.py`` so callers need no mapping logic.
    """

    bankAccountNumber: str = ""
    bankAccountName: str = ""
    bankName: Optional[str] = None
    accountRef: str = ""
    # True when this result came from a recovery GET (existing VA), not a create
    recovered: bool = False
    # True when the provider is offline and this is a synthetic mock NUBAN
    is_mock: bool = False
    # Raw provider response for advanced callers (optional)
    raw: Any = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return bool(self.bankAccountNumber)


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------

class PaymentProvider(Protocol):
    """Minimal contract every payment-collection provider must satisfy."""

    name: str

    @property
    def available(self) -> bool:
        """True when the provider is configured (credentials present)."""
        ...

    async def provision_virtual_account(
        self,
        account_ref: str,
        account_name: str,
        expected_amount: Optional[float] = None,
    ) -> VirtualAccountResult:
        """Create (or recover) a virtual NUBAN for a rental agreement.

        Implementations should attempt to recover an existing VA for
        ``account_ref`` first, then create one if none exists. On provider
        failure they may return a mock NUBAN (``is_mock=True``) so the flow
        degrades gracefully -- matching the existing Nomba mock-fallback.
        """
        ...

    async def get_virtual_account(self, account_ref: str) -> Optional[VirtualAccountResult]:
        """Look up an existing VA by reference. Returns None when not found."""
        ...

    async def expire_virtual_account(self, account_ref: str) -> bool:
        """Expire/deactivate a VA. Returns True on success."""
        ...

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        timestamp: Optional[str] = None,
    ) -> bool:
        """Verify an inbound webhook signature. Provider-specific scheme."""
        ...


__all__ = [
    "VirtualAccountResult",
    "PaymentProvider",
]
