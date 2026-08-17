"""
Nomba payment provider -- wraps the existing ``nomba_client`` singleton.

This is the default, production provider. It delegates every call to
``app/services/nomba_client.py`` and normalizes responses into
``VirtualAccountResult``. No behaviour change vs. the pre-abstraction code.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from app.services.nomba_client import nomba_client
from app.services.payments.base import VirtualAccountResult

logger = logging.getLogger(__name__)


class NombaPaymentProvider:
    """Nomba virtual-account (NUBAN) collection provider."""

    name = "nomba"

    @property
    def available(self) -> bool:
        # Nomba is "available" when a sub-account is configured (Path B).
        # Without it, provisioning falls back to a mock NUBAN (existing behaviour).
        return bool(nomba_client.sub_account_id)

    async def provision_virtual_account(
        self,
        account_ref: str,
        account_name: str,
        expected_amount: Optional[float] = None,
    ) -> VirtualAccountResult:
        # ── Recovery: try GET existing VA first ──────────────────────────────
        if nomba_client.sub_account_id:
            try:
                existing = await nomba_client.get_virtual_account(account_ref)
                if existing and not existing.get("expired", False):
                    logger.info(
                        "[NOMBA PROVIDER] Recovered existing VA ref=%s nuban=%s",
                        account_ref, existing.get("bankAccountNumber"),
                    )
                    return VirtualAccountResult(
                        bankAccountNumber=existing["bankAccountNumber"],
                        bankAccountName=existing["bankAccountName"],
                        accountRef=existing["accountRef"],
                        recovered=True,
                        raw=existing,
                    )
            except Exception as exc:
                logger.warning(
                    "[NOMBA PROVIDER] Recovery GET failed (non-fatal) ref=%s err=%s",
                    account_ref, exc,
                )

        # ── Create on Nomba ──────────────────────────────────────────────────
        try:
            if not nomba_client.sub_account_id:
                raise RuntimeError("NOMBA_SUB_ACCOUNT_ID not configured")

            nomba_data = await nomba_client.create_virtual_account_for_subaccount(
                sub_account_id=nomba_client.sub_account_id,
                account_ref=account_ref,
                account_name=account_name,
            )

            if not nomba_data or not nomba_data.get("bankAccountNumber"):
                raise RuntimeError("Nomba returned empty VA response")

            return VirtualAccountResult(
                bankAccountNumber=nomba_data["bankAccountNumber"],
                bankAccountName=nomba_data["bankAccountName"],
                bankName=nomba_data.get("bankName"),
                accountRef=nomba_data.get("accountRef", account_ref),
                recovered=False,
                raw=nomba_data,
            )

        except Exception as exc:
            # ── Mock fallback (matches pre-abstraction behaviour) ────────────
            logger.warning(
                "[NOMBA PROVIDER] Nomba unavailable (%s) -- using mock NUBAN", exc,
            )
            mock_nuban = f"9391{uuid.uuid4().hex[:6].upper()}"
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
            existing = await nomba_client.get_virtual_account(account_ref)
            if not existing:
                return None
            return VirtualAccountResult(
                bankAccountNumber=existing.get("bankAccountNumber", ""),
                bankAccountName=existing.get("bankAccountName", ""),
                accountRef=existing.get("accountRef", account_ref),
                recovered=True,
                raw=existing,
            )
        except Exception as exc:
            logger.warning("[NOMBA PROVIDER] get_virtual_account failed ref=%s err=%s", account_ref, exc)
            return None

    async def expire_virtual_account(self, account_ref: str) -> bool:
        try:
            return await nomba_client.expire_virtual_account(account_ref)
        except Exception as exc:
            logger.warning("[NOMBA PROVIDER] expire_virtual_account failed ref=%s err=%s", account_ref, exc)
            return False

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        timestamp: Optional[str] = None,
    ) -> bool:
        return nomba_client.verify_webhook_signature(payload, signature, timestamp)


__all__ = ["NombaPaymentProvider"]
