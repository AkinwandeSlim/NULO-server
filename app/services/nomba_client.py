# NuloAfrica Nomba API client
# Rule 17: ASCII only -- no Unicode characters anywhere in this file

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import time
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


class NombaAPIError(Exception):
    pass


class NombaClient:
    """
    Nomba API client with token caching and webhook signature verification.

    VERIFIED API FACTS (do not change these without re-testing):
    - Token issue endpoint: POST /v1/auth/token/issue (client_credentials, first run only)
    - Token refresh endpoint: POST /v1/auth/token/refresh (use refresh_token, all subsequent).
      Confirmed real via the live API reference OpenAPI schema (RefreshTokenRequest /
      IssueTokenResponse) -- request body is {grant_type, refresh_token}, response
      includes access_token, refresh_token, expiresAt.
    - Required headers on every API call: Authorization: Bearer {token}, accountId: {PARENT_ACCOUNT_ID}
    - Token lifetime: 30 minutes. CONFIRMED by Victor Shoaga (Nomba engineer) in
      the hackathon support channel (2026-07-01) -- the first real, named, dated
      source for this fact. Earlier drafts of this PRD/code stated 60 minutes with
      no backing source; that figure is incorrect.
    - Refresh strategy: refresh at the 25-minute mark (5-min safety buffer before
      the 30-minute expiry). Implemented in _store_token_data(): parsed expiresAt
      minus 5 minutes, with time.time() + 1500 (25 min) as the fallback when the
      field is missing or unparseable.
    - Virtual account creation: POST /v1/accounts/virtual  (no sub-account in path --
      the spec scopes this endpoint to the parent accountId header only. Sub-account
      routing for virtual account payments is configured in the Nomba dashboard, not
      in this call. The ONLY fields in the spec body are accountRef + accountName --
      currency and expectedAmount do NOT exist in the OpenAPI spec. We track
      expected_amount locally in agreements.expected_payment_amount instead.)
    - expectedAmount: NOT in the spec. Decimal Naira expectation is OUR concern,
      stored in our DB, not sent to Nomba.
    - Bank transfers (disbursement): POST /v2/transfers/bank  (PARENT account,
      no subAccountId in path). Architecture decision (2026-07-02): no sub-account
      anywhere in the integration. Money in (NUBAN -> parent) and money out
      (parent -> landlord bank) both go through the parent account. This keeps
      the integration simple and removes the "sub-account transfers must be
      enabled by Nomba" external dependency.
    - Rate limit: 5 bank transfers to the same recipient per minute (per live docs).
    - data.status enum (per live docs): SUCCESS | PENDING_BILLING | NEW | REFUND.
      PENDING_BILLING and NEW are both processing states, not errors.
    - transfer amount (/v2/transfers/bank, from PARENT account): JSON number,
      decimal Naira -- confirmed against the live OpenAPI spec
      (BankAccountTransferRequest.amount, type: number, format: double). Same
      convention as expectedAmount. Do NOT multiply by 100 -- that rule is for
      /checkout/order only, not Virtual Accounts or Transfers.
    - Webhook signature: HMAC-SHA256 over colon-joined string of 9 fields (NOT raw body)
    - Webhook signature output: base64 encoded (NOT hex)
    - Webhook header: nomba-signature (lowercase)
    - nomba-timestamp header is required for signature reconstruction
    - Signature comparison is EXACT-CASE via hmac.compare_digest(). Do not lowercase
      either side -- base64 is case-sensitive, and lowercasing weakens the comparison.
      The PRD's hand-verified test vector matches with an exact-case compare; no source
      has ever confirmed Nomba's own code lowercases anything.
    """

    def __init__(self):
        # Use .get() with placeholders so the module can be imported in
        # environments without env vars (e.g. unit tests). Real validation
        # happens in _issue_token() / create_virtual_account() at call time.
        env = os.environ.get("NOMBA_ENV", "test")
        if env == "live":
            self.client_id = os.environ.get("NOMBA_LIVE_CLIENT_ID", "")
            self.client_secret = os.environ.get("NOMBA_LIVE_CLIENT_SECRET", "")
            self.base_url = "https://api.nomba.com/v1"
        else:
            self.client_id = os.environ.get("NOMBA_TEST_CLIENT_ID", "")
            self.client_secret = os.environ.get("NOMBA_TEST_CLIENT_SECRET", "")
            self.base_url = "https://sandbox.nomba.com/v1"

        self.parent_account_id = os.environ.get("NOMBA_PARENT_ACCOUNT_ID", "")
        # Sub-account removed from architecture on 2026-07-02. Money in (NUBAN) and
        # money out (transfer) both go through the parent account. The env var
        # is still read for backward compat, but is unused -- warn if set.
        self.sub_account_id = os.environ.get("NOMBA_SUB_ACCOUNT_ID", "")
        if self.sub_account_id:
            logger.warning(
                "NOMBA_SUB_ACCOUNT_ID is set but is no longer used by the integration. "
                "All operations now go through NOMBA_PARENT_ACCOUNT_ID. "
                "You can safely remove the env var."
            )
        self.webhook_secret = os.environ.get("NOMBA_WEBHOOK_SECRET", "")

        self._token = None
        self._refresh_token_value = None   # stored from token issue/refresh response
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def _issue_token(self):
        """
        Issue a brand-new token using client credentials.
        Only called when no refresh_token exists yet (first run), or when a
        refresh attempt fails because the refresh_token itself has expired.
        Always called under self._lock.
        Docs: POST /v1/auth/token/issue
        """
        resp = requests.post(
            f"{self.base_url}/auth/token/issue",
            headers={
                "Content-Type": "application/json",
                "accountId": self.parent_account_id,
            },
            json={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()

        # Nomba can return HTTP 200 with a non-00 code for bad credentials
        if body.get("code") != "00":
            raise NombaAPIError(
                f"Token issue failed: {body.get('description', 'Unknown error')}"
            )

        data = body["data"]
        self._store_token_data(data)
        logger.info("Nomba token issued (client_credentials)")

    async def _refresh_token(self):
        """
        Refresh the access token using the stored refresh_token.
        Preferred over re-issuing to avoid repeated client_secret exposure.
        Docs: POST /v1/auth/token/refresh
        Always called under self._lock.
        Falls back to _issue_token() if no refresh_token is stored, or if
        the refresh call itself fails (refresh_token expired/invalid).
        """
        if not self._refresh_token_value:
            # No refresh token yet -- fall back to full issue
            await self._issue_token()
            return

        resp = requests.post(
            f"{self.base_url}/auth/token/refresh",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "accountId": self.parent_account_id,
            },
            json={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token_value,
            },
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()

        if body.get("code") != "00":
            # Refresh token may be expired -- fall back to full re-issue
            logger.warning(
                "Nomba token refresh failed (%s) -- falling back to re-issue",
                body.get("description"),
            )
            self._refresh_token_value = None
            await self._issue_token()
            return

        data = body["data"]
        self._store_token_data(data)
        logger.info("Nomba access token refreshed via refresh_token")

    def _store_token_data(self, data: dict):
        """
        Parse and store token response fields.

        Token lifetime is 30 minutes (CONFIRMED by Victor Shoaga, Nomba engineer,
        in the hackathon support channel -- PRD Part 1.1 v3 changelog).
        Refresh 5 minutes before expiry.
        """
        self._token = data["access_token"]
        # Always update refresh_token -- Nomba may rotate it
        self._refresh_token_value = data.get("refresh_token", self._refresh_token_value)

        expires_at_str = data.get("expiresAt", "")
        if expires_at_str:
            try:
                dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                self._expires_at = dt.timestamp() - 300  # 5-min buffer before actual expiry
            except Exception:
                # Fallback: 30 min lifetime - 5 min buffer = 25 min
                self._expires_at = time.time() + 1500
        else:
            # Fallback: 30 min lifetime - 5 min buffer = 25 min
            self._expires_at = time.time() + 1500

    async def _get_token(self) -> str:
        """
        Return cached access token or obtain a new one.
        Thread-safe via asyncio.Lock -- double-check pattern prevents
        concurrent refresh race when multiple requests hit an expired token.
        On first call: issues a new token via client_credentials.
        On subsequent calls: uses refresh_token endpoint (avoids re-exposing client_secret).
        """
        if self._token and time.time() < self._expires_at:
            return self._token
        async with self._lock:
            # Double-check inside lock
            if self._token and time.time() < self._expires_at:
                return self._token
            # Dispatches to _issue_token() or _refresh_token() as appropriate
            await self._refresh_token()
        return self._token

    async def _headers(self) -> dict:
        token = await self._get_token()
        return {
            "Authorization": f"Bearer {token}",
            "accountId": self.parent_account_id,
            "Content-Type": "application/json",
        }

    async def create_virtual_account(
        self,
        account_ref: str,
        account_name: str,
        expected_amount: float | None = None,  # kept for caller convenience; NOT sent to Nomba
    ) -> dict:
        """
        Create a Nomba virtual NUBAN for a rental agreement.

        PER OPENAPI SPEC (kudi-inc/vendor-openapi-spec openapi3_0_v_1_0_0.json):
        - Path:  POST /v1/accounts/virtual   (NO sub-account in URL, body, or query)
        - Header: accountId = PARENT account (always)
        - Body:   { "accountRef": "...", "accountName": "..." }   ONLY these two fields
        - Sub-account routing of inbound payments is configured in the Nomba dashboard,
          not via this API call. The parent account is implicitly the scope here.

        account_ref: agreement.id (UUID), 16-64 chars per spec -- your UUID satisfies this.
        account_name: 8-64 chars per spec -- pad/validate before calling.
        expected_amount: KEPT AS A PARAMETER for caller convenience (so the route
                         can compute it once and pass it through) but NOT sent to
                         Nomba -- the spec has no such field. We store the expected
                         amount locally in agreements.expected_payment_amount and
                         use it for reconciliation only.

        AMOUNT CONVENTION (for OUR reconciliation only, not for Nomba):
          Decimal Naira (float) -- stored as numeric(12,2) in agreements.
        """
        # Per OpenAPI spec: ONLY accountRef and accountName. currency and
        # expectedAmount are NOT in the spec and must NOT be sent. Nomba will
        # default to NGN; we track expected payment amount in our own DB.
        payload = {
            "accountRef": account_ref,
            "accountName": account_name,
        }

        # expected_amount is intentionally NOT included in payload (spec field
        # does not exist). We keep the parameter so the calling route has a
        # single value to compute and store locally.

        headers = await self._headers()
        # No sub-account in URL. Header is parent. Body is the two fields.
        resp = requests.post(
            f"{self.base_url}/accounts/virtual",
            headers=headers,
            json=payload,
            timeout=15,
        )

        logger.info(
            "create_virtual_account | ref=%s | parent=%s | status=%s | expected_local=%.2f (not sent)",
            account_ref, self.parent_account_id, resp.status_code,
            expected_amount if expected_amount is not None else 0.0,
        )
        resp.raise_for_status()

        body = resp.json()
        if body.get("code") != "00":
            raise NombaAPIError(body.get("description", "Nomba error"))
        return body["data"]
        # Returns per spec: createdAt, accountHolderId, accountRef, bvn, accountName,
        # bankName, bankAccountNumber, bankAccountName, currency, callbackUrl, expired

    def verify_webhook_signature(
        self,
        payload: dict,
        signature: str,
        nomba_timestamp: str,
    ) -> bool:
        """
        Verify Nomba webhook signature.

        CRITICAL: This is NOT a raw-body hash.
        Nomba hashes a colon-joined string of 9 specific fields.
        Output is base64 encoded, not hex.
        Comparison is EXACT-CASE via hmac.compare_digest(). Base64 is
        case-sensitive -- lowercasing either side only weakens the check.

        Verified test vector (hand-computed, exact-case match, no lowering needed):
        secret=HkatexKDZg7CLWy96q5sfrVHSvtoz92B
        expected=Kt9095hQxfgmVbx6iz7G2tPhHdbdXgLlyY/mf35sptw=
        Source: https://developer.nomba.com/docs/api-basics/webhook
        """
        try:
            data = payload.get("data", {})
            merchant = data.get("merchant", {})
            transaction = data.get("transaction", {})

            event_type = payload.get("event_type", "")
            request_id = payload.get("requestId", "")
            user_id = merchant.get("userId", "")
            wallet_id = merchant.get("walletId", "")
            transaction_id = transaction.get("transactionId", "")
            transaction_type = transaction.get("type", "")
            transaction_time = transaction.get("time", "")
            response_code = transaction.get("responseCode", "") or ""

            if response_code == "null":
                response_code = ""

            hashing_payload = (
                f"{event_type}:{request_id}:{user_id}:{wallet_id}:"
                f"{transaction_id}:{transaction_type}:{transaction_time}:"
                f"{response_code}:{nomba_timestamp}"
            )

            logger.debug("Webhook hash input: %s", hashing_payload)

            digest = hmac.new(
                self.webhook_secret.encode(),
                hashing_payload.encode(),
                hashlib.sha256,
            ).digest()
            expected = base64.b64encode(digest).decode()

            return hmac.compare_digest(signature, expected)

        except Exception as exc:
            logger.error("Signature verification exception: %s", exc)
            return False


    async def lookup_bank_account(
        self,
        account_number: str,
        bank_code: str,
    ) -> dict:
        """
        Verify a recipient bank account before initiating any transfer.
        ALWAYS call this before transfer_to_bank() -- it confirms the account
        exists and returns the verified account holder name.

        Endpoint: POST /v1/transfers/bank/lookup
        Docs: https://developer.nomba.com/docs/products/transfers/bank-account-lookup

        Returns: { "accountNumber": "...", "accountName": "M.A Animashaun" }
        Store the returned accountName -- pass it back into transfer_to_bank()
        rather than using user-supplied name.
        """
        headers = await self._headers()
        resp = requests.post(
            f"{self.base_url}/transfers/bank/lookup",
            headers=headers,
            json={
                "accountNumber": account_number,
                "bankCode": bank_code,
            },
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "00":
            raise NombaAPIError(
                f"Bank lookup failed: {body.get('description', 'Unknown error')}"
            )
        logger.info(
            "Bank lookup OK | account=%s | bank=%s | name=%s",
            account_number, bank_code, body["data"].get("accountName"),
        )
        return body["data"]

    async def transfer_to_bank(
        self,
        amount_naira: float,
        account_number: str,
        account_name: str,
        bank_code: str,
        merchant_tx_ref: str,
        narration: str,
        sender_name: str = "NuloAfrica",
    ) -> dict:
        """
        Disburse funds to a landlord's bank account from the PARENT account.

        PER LIVE NOMBA DOCS (developer.nomba.com -- "Transfer to banks"):
        - Path:  POST /v2/transfers/bank   (PARENT account, no subAccountId in path)
        - Header: accountId = PARENT account (always)
        - Body:   amount, accountNumber, accountName, bankCode, merchantTxRef,
                  senderName, narration
        - Rate limit: 5 transfers to same recipient per minute
        - No external dependency on sub-account activation (we use parent)

        - amount: decimal Naira, JSON number. Do NOT multiply by 100.
        - merchant_tx_ref: idempotency key. Reuse on retries. Only generate new ref
                  after a REFUND status, never for PENDING.
        - Response: HTTP 200 or 201, body.data.status is one of:
                  SUCCESS | PENDING_BILLING | NEW | REFUND
                  201 with status=PENDING_BILLING or NEW = processing async, NOT an error.
                  The caller (route) must inspect data.status to decide what to do.

        ARCHITECTURE NOTE (simplified 2026-07-02):
        Tenant payments land in PARENT via virtual accounts. We disburse from PARENT
        via this method. No sub-account involvement anywhere. The platform fee
        is the residual that stays in parent after disbursement -- our logic,
        not Nomba's.
        """
        # Enforce idempotency key -- a missing ref silently fails on Nomba's side
        if not merchant_tx_ref or not isinstance(merchant_tx_ref, str):
            raise NombaAPIError(
                "merchant_tx_ref is required and must be a non-empty string"
            )

        # CONFIRMED: amount is decimal Naira (JSON number), not kobo.
        amount = round(float(amount_naira), 2)

        # v2 per live docs. PARENT account, no subAccountId in path.
        transfer_url = f"{self.base_url.rsplit('/v1', 1)[0]}/v2/transfers/bank"

        headers = await self._headers()
        resp = requests.post(
            transfer_url,
            headers=headers,
            json={
                "amount": amount,
                "accountNumber": account_number,
                "accountName": account_name,
                "bankCode": bank_code,
                "merchantTxRef": merchant_tx_ref,
                "senderName": sender_name,
                "narration": narration,
            },
            timeout=30,
        )

        logger.info(
            "transfer_to_bank | ref=%s | amount_ngn=%.2f | status=%s",
            merchant_tx_ref, amount, resp.status_code,
        )

        # Per live docs, both 200 and 201 are valid response codes. The CALLER
        # must check body.data.status (SUCCESS | PENDING_BILLING | NEW | REFUND)
        # to decide what to do. We just surface the data.
        if resp.status_code in (200, 201):
            body = resp.json()
            data = body.get("data", {}) or {}
            logger.info(
                "Transfer response | ref=%s | nomba_status=%s | body_code=%s",
                merchant_tx_ref, data.get("status"), body.get("code"),
            )
            return data

        # Any other status is an HTTP-level error -- let raise_for_status surface it
        resp.raise_for_status()
        # Unreachable, but keeps static checkers happy
        return {}

    async def requery_transfer(
        self,
        merchant_tx_ref: str,
    ) -> dict:
        """
        Poll the status of a previously-initiated transfer.

        PER LIVE NOMBA DOCS ("Requery Endpoints" section):
        - For parent-account transfers: GET /v1/transactions/accounts/single
                                       ?transactionRef=API-TRANSFER-XXX-XXX
        - Up to ~3 minutes of NIBSS processing delay -- use interval-based polling.
        - Returns the same shape as the transfer response (body.data.status etc.).

        Use case: PENDING_BILLING or NEW transfer whose webhook never arrived
        (network blip, etc.). Poll this endpoint up to ~3 min, then either
        retry safely (REFUND) or finalise the disbursement (SUCCESS).
        """
        if not merchant_tx_ref or not isinstance(merchant_tx_ref, str):
            raise NombaAPIError("merchant_tx_ref is required")

        # Parent-account requery -- the path we use since we disburse from parent
        url = f"{self.base_url}/transactions/accounts/single"
        params = {"transactionRef": merchant_tx_ref}

        headers = await self._headers()
        resp = requests.get(url, headers=headers, params=params, timeout=15)

        logger.info(
            "requery_transfer | ref=%s | status=%s",
            merchant_tx_ref, resp.status_code,
        )

        if resp.status_code == 200:
            body = resp.json()
            data = body.get("data", {}) or {}
            logger.info(
                "Requery result | ref=%s | nomba_status=%s",
                merchant_tx_ref, data.get("status"),
            )
            return data

        resp.raise_for_status()
        return {}

    async def create_checkout_order(
        self,
        order_reference: str,
        amount_naira: float,
        customer_email: str,
        callback_url: str,
        customer_id: str = None,
        currency: str = "NGN",
    ) -> dict:
        """
        Create a Nomba Checkout hosted payment page (Phase 2 -- alternative to virtual accounts).

        PER TRAINING DOCUMENTATION:
        - Checkout ONLY uses KOBO for amount (NOT decimal Naira). Always multiply by 100!
        - Returns checkoutUrl to redirect the tenant to.
        - Webhook event type: payment_success

        :param order_reference: Your unique order reference (must be unique per checkout attempt)
        :param amount_naira: Amount in NGN (will be converted to kobo automatically)
        :param customer_email: Tenant's email
        :param callback_url: URL to redirect to after payment (frontend page)
        :param customer_id: Optional: your internal customer ID
        :param currency: Default "NGN"
        :return: { "code": "00", "data": { "checkoutUrl": "...", ... } }
        """
        # Convert Naira to kobo for Checkout ONLY
        amount_kobo = int(round(amount_naira * 100))
        if amount_kobo <= 0:
            raise NombaAPIError("amount_naira must be greater than zero")

        payload = {
            "order": {
                "orderReference": order_reference,
                "amount": amount_kobo,
                "currency": currency,
                "callbackUrl": callback_url,
                "customerEmail": customer_email,
            }
        }
        if customer_id:
            payload["order"]["customerId"] = customer_id

        headers = await self._headers()
        resp = requests.post(
            f"{self.base_url}/checkout/order",
            headers=headers,
            json=payload,
            timeout=30,
        )

        logger.info(
            "Nomba Checkout create | ref=%s | amount_ngn=%.2f | status=%s",
            order_reference, amount_naira, resp.status_code,
        )

        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "00":
            raise NombaAPIError(
                f"Nomba Checkout failed: {body.get('description', 'Unknown error')}"
            )
        return body.get("data", {})

    async def get_checkout_order_status(
        self,
        order_reference: str,
    ) -> dict:
        """
        Get the status of a previously-created checkout order.

        Use this as a fallback if you miss the webhook for any reason.
        """
        headers = await self._headers()
        resp = requests.get(
            f"{self.base_url}/checkout/order/{order_reference}",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "00":
            raise NombaAPIError(
                f"Nomba Checkout status failed: {body.get('description', 'Unknown error')}"
            )
        return body.get("data", {})

    async def get_banks_list(self) -> dict:
        """
        Get list of supported banks with their codes and display names.
        Endpoint: GET /v1/transfers/banks
        Returns list of { "code": "058", "name": "Guaranty Trust Bank" }
        """
        headers = await self._headers()
        resp = requests.get(
            f"{self.base_url}/transfers/banks",
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "00":
            raise NombaAPIError(f"Failed to get banks list: {body.get('description')}")
        return body["data"]


# Module-level singleton -- import this in your routers
nomba_client = NombaClient()