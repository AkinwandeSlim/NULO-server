"""
Payment provider abstraction package.

Public API:
    from app.services.payments import get_payment_provider, VirtualAccountResult

See ``base.py`` for the full design doc and ``registry.py`` for provider
selection via the ``PAYMENT_PROVIDER`` env var.
"""

from app.services.payments.base import PaymentProvider, VirtualAccountResult
from app.services.payments.mock_provider import MockPaymentProvider
from app.services.payments.nomba_provider import NombaPaymentProvider
from app.services.payments.paystack_provider import PaystackPaymentProvider
from app.services.payments.registry import (
    build_payment_provider_registry,
    get_payment_provider,
    get_payment_provider_registry,
)

__all__ = [
    "PaymentProvider",
    "VirtualAccountResult",
    "NombaPaymentProvider",
    "PaystackPaymentProvider",
    "MockPaymentProvider",
    "build_payment_provider_registry",
    "get_payment_provider_registry",
    "get_payment_provider",
]
