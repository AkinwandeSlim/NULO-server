"""
Payment provider registry -- resolves the active collection provider.

Reads ``PAYMENT_PROVIDER`` from ``app.config.settings`` (``server/.env``):

    PAYMENT_PROVIDER=nomba      # default
    PAYMENT_PROVIDER=paystack   # Paystack dedicated VAs (test mode)
    PAYMENT_PROVIDER=mock       # offline / tests

Adding a provider = implement ``PaymentProvider`` + one entry in
``build_payment_provider_registry``. No call-site changes required.

REMEMBER: disbursement (landlord payout) always stays on Nomba regardless of
this setting -- see ``app/config.py`` ``PAYMENT_PROVIDER`` comment.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.config import settings
from app.services.payments.base import PaymentProvider
from app.services.payments.mock_provider import MockPaymentProvider
from app.services.payments.nomba_provider import NombaPaymentProvider
from app.services.payments.paystack_provider import PaystackPaymentProvider

logger = logging.getLogger(__name__)


def build_payment_provider_registry() -> dict[str, PaymentProvider]:
    """
    Construct the provider registry. Adding a provider = add config fields +
    one entry here. No call-site changes required.
    """
    registry: dict[str, PaymentProvider] = {
        "nomba": NombaPaymentProvider(),
        "paystack": PaystackPaymentProvider(),
        "mock": MockPaymentProvider(),
    }
    return registry


# Module-level registry (built once).
_registry: Optional[dict[str, PaymentProvider]] = None


def get_payment_provider_registry() -> dict[str, PaymentProvider]:
    global _registry
    if _registry is None:
        _registry = build_payment_provider_registry()
    return _registry


def get_payment_provider(name: Optional[str] = None) -> PaymentProvider:
    """
    Return the active collection provider. When ``name`` is None, uses
    ``PAYMENT_PROVIDER`` from settings. Unknown names fall back to Nomba (the
    historical default) so a typo never crashes the app.
    """
    registry = get_payment_provider_registry()
    wanted = (name or getattr(settings, "PAYMENT_PROVIDER", "nomba") or "nomba").strip().lower()

    provider = registry.get(wanted)
    if provider is None:
        logger.warning(
            "Unknown PAYMENT_PROVIDER '%s' -- falling back to 'nomba'", wanted
        )
        provider = registry.get("nomba") or MockPaymentProvider()

    return provider


__all__ = [
    "build_payment_provider_registry",
    "get_payment_provider_registry",
    "get_payment_provider",
]
