"""
Paystack payment provider -- dedicated virtual accounts (test mode).

Paystack's dedicated-account API provisions a unique NUBAN per customer,
which maps cleanly onto our per-agreement virtual-account model.

API reference (https://paystack.com/docs/api/dedicated-virtual-account/):
    POST   /dedicated_account          create a dedicated VA
    GET    /dedicated_account?account_number=...   lookup
    DELETE /dedicated_account/:id      deactivate

Webhook verification: Paystack sends ``x-paystack-signature`` =
HMAC-SHA512(raw_body, PAYSTACK_SECRET_KEY).

NOTE: Paystack has NO escrow/disbursement equivalent, so this provider is
used for tenant COLLECTION only. Landlord payout always stays on Nomba
(see ``app/config.py`` ``PAYMENT_PROVIDER`` comment).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from typing import Optional

import httpx

from app.services.payments.base import VirtualAccountResult

logger = logging.getLogger(__name__)

PAYSTACK_API_URL = os.environ.get("PAYSTACK_API_URL", "https://api.paystack.co")


class PaystackPaymentProvider:
    """Paystack dedicated-virtual-account collection provider."""

    name = "paystack"

    def __init__(self) -> None:
        self.secret_key = os.environ.get("PAYSTACK_SECRET_KEY", "")
        self.api_url = PAYSTACK_API_URL.rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self.secret_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    async def provision_virtual_account(
        self,
        account_ref: str,
        account_name: str,
        expected_amount: Optional[float] = None,
    ) -> VirtualAccountResult:
        # -- Recovery: try GET existing dedicated VA first --
        existing = await self.get_virtual_account(account_ref)
        if existing and existing.ok:
            logger.info(
                "[PAYSTACK PROVIDER] Recovered existing dedicated VA ref=%s nuban=%s",
                account_ref, existing.bankAccountNumber,
            )
            existing.recovered = True
            return existing

        # -- Create dedicated VA on Paystack --
        try:
            if not self.available:
                raise RuntimeError("PAYSTACK_SECRET_KEY not configured")

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.api_url}/dedicated_account",
                    headers=self._headers(),
                    json={
                        # Paystack keys the dedicated VA off a customer.
                        # We use the agreement ref as the customer identifier.
                        "customer": account_ref,
                        "preferred_bank": "058",  # GTBank (matches Nomba demo bank)
                    },
                )
                resp.raise_for_status()
                body = resp.json()

            data = body.get("data") or {}
            nuban = data.get("account_number", "")
            if not nuban:
                raise RuntimeError("Paystack returned empty dedicated VA response")

            return VirtualAccountResult(
                bankAccountNumber=nuban,
                bankAccountName=data.get("account_name", account_name),
                bankName=(data.get("bank") or {}).get("name"),
                accountRef=str(data.get("id", account_ref)),
                recovered=False,
                raw=body,
            )

        except Exception as exc:
            # -- Mock fallback (same graceful-degradation pattern as Nomba) --
            logger.warning(
                "[PAYSTACK PROVIDER] Paystack unavailable (%s) -- using mock NUBAN", exc,
            )
            mock_nuban = f"9392{uuid.uuid4().hex[:6].upper()}"
            return VirtualAccountResult(
                bankAccountNumber=mock_nuban,
                bankAccountName=account_name,
                bankName="NuloAfrica (Sandbox)",
                accountRef=account_ref,
                recovered=False,
                is_mock=True,
            )

    async def get_virtual_account(self, account_ref: str) -> Optional[VirtualAccountResult]:
        try:
            if not self.available:
                return None
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.api_url}/dedicated_account",
                    headers=self._headers(),
                    params={"account_number": account_ref},
                )
                if resp.status_code != 200:
                    return None
                body = resp.json()

            data = body.get("data") or {}
            nuban = data.get("account_number", "")
            if not nuban:
                return None
            return VirtualAccountResult(
                bankAccountNumber=nuban,
                bankAccountName=data.get("account_name", ""),
                accountRef=str(data.get("id", account_ref)),
                recovered=True,
                raw=body,
            )
        except Exception as exc:
            logger.warning("[PAYSTACK PROVIDER] get_virtual_account failed ref=%s err=%s", account_ref, exc)
            return None

    async def expire_virtual_account(self, account_ref: str) -> bool:
        try:
            if not self.available:
                return False
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    f"{self.api_url}/dedicated_account/{account_ref}",
                    headers=self._headers(),
                )
                return resp.status_code in (200, 204)
        except Exception as exc:
            logger.warning("[PAYSTACK PROVIDER] expire_virtual_account failed ref=%s err=%s", account_ref, exc)
            return False

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        timestamp: Optional[str] = None,
    ) -> bool:
        """Paystack: x-paystack-signature = HMAC-SHA512(raw_body, secret)."""
        if not self.secret_key or not signature:
            return False
        digest = hmac.new(
            self.secret_key.encode(), payload, hashlib.sha512
        ).hexdigest()
        return hmac.compare_digest(digest, signature)


__all__ = ["PaystackPaymentProvider"]

