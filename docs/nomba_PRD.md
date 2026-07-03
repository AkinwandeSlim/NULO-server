# NuloAfrica x Nomba — Hackathon Integration PRD
## The Only Document Your Copilot Needs

> **Version:** Final v2 (amount format, sub-account routing, and disbursement architecture confirmed against developer.nomba.com live OpenAPI spec — see changelog at end of Part 0)
> **Hackathon:** DevCareer Nomba Hackathon 2026, July 1–7
> **Submission deadline:** July 7, 2026, 11:59 PM WAT
> **Track:** Virtual Accounts as Infrastructure
> **Strategy:** Backend-first, depth over breadth, everything Thunder Client-tested before any frontend work
> **Live backend:** https://api.nuloafrica.com (Render, GitHub: AkinwandeSlim/NULO-server, branch: main)

---

## PART 0 — Context & Decisions Already Made

### What NuloAfrica is
Zero agency-fee rental marketplace for Nigerian cities (Lagos, Abuja, Port Harcourt).
Stack: Next.js 16 + React 19 frontend, FastAPI + Python backend, Supabase (PostgreSQL), Paystack (existing), Twilio + SMTP notifications.

### What we are building (hackathon scope)
Multi-frequency rental payment infrastructure using Nomba Virtual Accounts, covering the full money lifecycle: collect → reconcile → disburse.
Nigerian landlords want annual rent upfront (70% market). Tenants want monthly.
We solve this by assigning a dedicated Nomba virtual account per signed agreement, supporting 4 payment frequencies, reconciling every inbound transfer automatically, then disbursing the landlord's share out of the same collection sub-account.
All virtual accounts route through ONE fixed collection sub-account (`NOMBA_SUB_ACCOUNT_ID`) — not the parent account, and not one sub-account per landlord. This is deliberate: it pools every tenant payment separately from the parent account's general balance, and the same sub-account is where landlord payouts are disbursed FROM. It was created once, manually, via the Nomba Dashboard, ahead of the hackathon — it is not provisioned at runtime.

### Phase 3 (Disbursement) — CONFIRMED in scope
Collection + reconciliation alone under-demonstrates the API relative to a full collect → reconcile → disburse cycle, which is the more complete showcase for a depth-over-breadth track. Bank account lookup, platform-fee split, and `transfer_to_bank()` (paying landlords out of the collection sub-account) are part of the submission. See "Immediate action item" above for the one external dependency this introduces.

### What is NOT in scope for these 3 days
- Landlord analytics dashboard (deferred to post-hackathon)
- Payment schedule calendar UI (deferred)
- Full frontend polish (deferred)
- Nightly reconciliation cron (deferred)
- Tokenized cards / direct debits / mandates (not needed for this track)

### Decisions locked — do not re-open these
1. Backend-first. No frontend work until all endpoints pass Thunder Client tests.
2. Nomba sits alongside Paystack. Do not replace or break the existing Paystack flow.
3. `nomba_collection` added to `transactions.transaction_type` CHECK constraint. No JSONB hacks.
4. `agreement.id` (your UUID) is used as `accountRef` when creating virtual accounts. Stable, no Nomba ID storage needed.
5. `NOMBA_WEBHOOK_SECRET=NombaHackathon2026` — this is the hackathon organiser's signing key, not your Nomba dashboard key. Use it in your handler.
6. Submit webhook URL only after local simulation passes all 6 test scenarios. URL: `https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer`
7. **Phase 3 (disbursement) IS in scope.** The hackathon judges depth on the full money lifecycle, not just collection — collect → reconcile → disburse is the complete demonstration of the API, and stopping at reconciliation leaves the "watched-for" technical process half-shown. `lookup_bank_account()` and `transfer_to_bank()` (Part 4), Migration 004 (Part 3), and Part 1.5/1.6 are all in scope for the submission.

### Immediate action item — do this first, today
`POST /v2/transfers/bank/{subAccountId}` requires Nomba to manually enable sub-account transfers on your account (Part 1.6). This is the one dependency outside your control with real lead time. Ping the hackathon team now, before writing `disbursements.py` routes — if it's not enabled by the time you need to demo it, that's a hard blocker no amount of code fixes around, and you'd rather know on Day 1 than Day 3.

### Open items — ALL RESOLVED (confirmed against live OpenAPI spec)
1. **Amount unit, virtual accounts:** `expectedAmount` is a JSON number, decimal Naira (`type: number, format: double`). Not kobo, not a string. Training doc's kobo rule applies to Checkout (`/checkout/order`) only.
2. **Amount unit, transfers:** `POST /v2/transfers/bank/{subAccountId}` also uses `amount` as a JSON number, decimal Naira — same convention as `expectedAmount`. A previous draft of `nomba_client.py` multiplied this by 100 (a real bug, since fixed) — worth a ₦1 sandbox test before any real disbursement regardless, since a schema type doesn't 100% guarantee backend behavior.
3. **Signature comparison:** exact-case via `hmac.compare_digest()`. Do not lowercase either side — base64 is case-sensitive, and an earlier draft's `.lower()` on both sides (citing an unverified "Nomba sample code" claim) weakened the check without a real source.
4. **Token refresh:** `POST /v1/auth/token/refresh` is a real, separate endpoint (confirmed in the live API reference sidebar and OpenAPI schema) — use it instead of re-issuing via `client_credentials` every time, to avoid repeated `client_secret` exposure.

### Changelog
- v1: initial verified facts, amount format marked as an open Day-1 test item.
- v2: amount format resolved without a sandbox test (confirmed via OpenAPI spec instead); sub-account architecture confirmed (single collection sub-account, not per-landlord, not the parent); disbursement (Phase 3) endpoints added and verified; refresh-token endpoint confirmed real; signature comparison bug fixed.

---

## PART 1 — Verified API Facts

These are confirmed against developer.nomba.com live docs and/or verified by hand-computing test vectors.

### 1.1 Authentication
```
Endpoint:  POST https://api.nomba.com/v1/auth/token/issue   (first run / refresh_token expired)
Headers:   Content-Type: application/json
           accountId: <NOMBA_PARENT_ACCOUNT_ID>
Body:      {
             "grant_type": "client_credentials",
             "client_id": "<NOMBA_CLIENT_ID>",
             "client_secret": "<NOMBA_CLIENT_SECRET>"
           }
Response:  { "data": { "access_token": "...", "refresh_token": "...", "expiresAt": "ISO8601 UTC" } }
```
```
Endpoint:  POST https://api.nomba.com/v1/auth/token/refresh   (all subsequent refreshes)
Headers:   Authorization: Bearer <current token>
           Content-Type: application/json
           accountId: <NOMBA_PARENT_ACCOUNT_ID>
Body:      { "grant_type": "refresh_token", "refresh_token": "<stored refresh_token>" }
Response:  same shape as token/issue -- store the new access_token, refresh_token, expiresAt
```
CONFIRMED real (live API reference sidebar lists it as "Refresh an expired token", and its OpenAPI schema matches this shape) -- prefer this over re-issuing via `client_credentials` on every refresh, to avoid repeatedly exposing your client_secret. Fall back to `/auth/token/issue` if a refresh attempt fails (refresh_token itself may have expired).

**Required headers on every subsequent API call:**
| Header | Value |
|---|---|
| Authorization | Bearer {access_token} |
| accountId | {NOMBA_PARENT_ACCOUNT_ID} — always the parent account, even when the URL path targets the collection sub-account (virtual account creation, disbursement transfers) |
| Content-Type | application/json |

**Token caching rule:** Cache `access_token` in memory. Refresh at 55-minute mark (token is valid 60 minutes). Never request a new token per API call — one cached token shared across all calls. Use `asyncio.Lock` around refresh to prevent race conditions when concurrent calls hit an expired token simultaneously.

### 1.2 Virtual Account Creation
```
Endpoint:  POST https://api.nomba.com/v1/accounts/virtual/{NOMBA_SUB_ACCOUNT_ID}
Headers:   Authorization: Bearer {token}
           accountId: {NOMBA_PARENT_ACCOUNT_ID}   -- parent account, even here
           Content-Type: application/json
Body:      {
             "accountRef": "{agreement.id}",      -- YOUR stable UUID, not a Nomba ID
             "accountName": "{tenant display name}",
             "currency": "NGN",
             "expectedAmount": 50000.00            -- CONFIRMED: JSON number, decimal Naira (not kobo, not string)
           }
Response:  {
             "code": "00",
             "description": "Success",
             "data": {
               "accountRef": "...",
               "accountName": "...",
               "bankName": "...",
               "bankAccountNumber": "9391076543",   -- NUBAN to show tenant
               "bankAccountName": "Nomba/...",
               "currency": "NGN",
               "callbackUrl": "..."
             }
           }
```
Routed through the single collection sub-account, not the bare parent endpoint. `accountRef = agreement.id` still distinguishes individual virtual accounts within it.

**What to store from the response:**
- `data.bankAccountNumber` → `agreements.virtual_account_number` (show this to the tenant for transfers)
- `data.bankAccountName` → `agreements.virtual_account_name`
- `data.accountRef` → `agreements.nomba_account_ref` (your UUID echoed back, confirm it matches)

### 1.3 Webhook — Complete Verified Spec

**This is the most important section. Every detail is verified against the official Nomba production docs.**

**Headers Nomba sends YOU:**
```
nomba-signature: base64-encoded HMAC-SHA256
nomba-sig-value: same as nomba-signature
nomba-signature-algorithm: HmacSHA256
nomba-signature-version: 1.0.0
nomba-timestamp: 2026-07-01T10:00:00Z   ← YOU NEED THIS for signature verification
```

**Signature algorithm — NOT raw body hash. This is a structured string hash:**
```python
# Step 1: Parse the JSON body
# Step 2: Extract these 9 fields
# Step 3: Join with colons exactly in this order
# Step 4: HMAC-SHA256 the result, base64 encode it

hashing_payload = (
    f"{event_type}:{request_id}:{user_id}:{wallet_id}:"
    f"{transaction_id}:{transaction_type}:{transaction_time}:"
    f"{response_code}:{nomba_timestamp}"
)
# nomba_timestamp comes from the nomba-timestamp REQUEST HEADER, not the payload body
# response_code: use "" if null or empty, never the string "null"

digest = hmac.new(secret.encode(), hashing_payload.encode(), hashlib.sha256).digest()
signature = base64.b64encode(digest).decode()
# Compare with nomba-signature header using hmac.compare_digest(), never ==
```

**Test vector — verified by hand, computed match confirmed:**
```
event_type:     payment_success
request_id:     45f2dc2d-d559-4773-bba3-2d5ec17b2e20
user_id:        b7b10e81-e57d-41d0-8fdc-f4e23a132bbf
wallet_id:      6756ff80aafe04a795f18b38
transaction_id: API-VACT_TRA-B7B10-0435b274-807a-4bc7-8abe-9dbb4548fd7a
type:           vact_transfer
time:           2025-09-29T10:51:44Z
response_code:  (empty string)
timestamp:      2025-09-29T10:51:44Z
secret:         HkatexKDZg7CLWy96q5sfrVHSvtoz92B

Expected signature: Kt9095hQxfgmVbx6iz7G2tPhHdbdXgLlyY/mf35sptw=
Computed by us:     Kt9095hQxfgmVbx6iz7G2tPhHdbdXgLlyY/mf35sptw= ✓ MATCH
```

**Webhook payload shape (real production example from Nomba docs):**
```json
{
  "event_type": "payment_success",
  "requestId": "49e11b44-909b-4f83-82b4-9a83aXXXXXX",
  "data": {
    "merchant": {
      "walletId": "693e907aad9ea59616XXXX",
      "walletBalance": 539.4,
      "userId": "613bb620-c8e5-45f6-9c00-XXXXXXXX"
    },
    "terminal": {},
    "transaction": {
      "aliasAccountNumber": "967913XXX",
      "fee": 0.6,
      "sessionId": "1000042602061021531516XXXXXX",
      "type": "vact_transfer",
      "transactionId": "API-VACT_TRA-613BB-eeae578a-cdd4-459c-8bd5-XXXXXX",
      "aliasAccountName": "Peter/Peter Enterprise",
      "responseCode": "",
      "originatingFrom": "api",
      "transactionAmount": 120,
      "narration": "Transfer from JOHN GRASS",
      "time": "2026-02-06T10:21:56Z",
      "aliasAccountReference": "122320250916PM",
      "aliasAccountType": "VIRTUAL"
    },
    "customer": {
      "bankCode": "305",
      "senderName": "JOHN GRASS",
      "bankName": "Paycom (Opay)",
      "accountNumber": "81689XXX"
    }
  }
}
```

**Key field mappings for your reconciliation engine:**
| Payload field | What it is | Your use |
|---|---|---|
| `event_type` | Always `"payment_success"` for all payment types | Check this first |
| `data.transaction.type` | `"vact_transfer"` = virtual account funded | Dispatch to reconciliation only when this is `vact_transfer` |
| `data.transaction.aliasAccountReference` | **This is your `accountRef` / `agreement.id`** | Look up the agreement in your DB |
| `data.transaction.transactionAmount` | Amount received | Compare to `agreements.expected_payment_amount` |
| `data.transaction.aliasAccountNumber` | The NUBAN that was funded | Cross-check against `agreements.virtual_account_number` |
| `data.transaction.transactionId` | Nomba's internal transaction ID | Store for audit trail |
| `data.customer.senderName` | Who sent the money | Store for tenant record |
| `requestId` | Top-level idempotency key | Store in unique index, reject duplicates |
| `nomba-timestamp` header | Used in signature construction | Read from headers, not body |

**Retry policy:** Non-2xx response triggers up to 5 retries: 2 min → ~5 min → ~11 min → 24 min → ~53 min.
**Always return 200** once you've verified the signature and stored the `requestId` — even if reconciliation has an error, log it and return 200. Let reconciliation failures be async problems, not retry storms.

### 1.4 Event Types Nomba Sends
| event_type | transaction.type | Meaning |
|---|---|---|
| `payment_success` | `vact_transfer` | Virtual account was funded ← **yours** |
| `payment_success` | other | Card/other payment, ignore |
| `payout_success` | `transfer` | Outbound transfer settled |
| `payment_failed` | — | Payment attempt failed |
| `payout_failed` | — | Outbound transfer failed |
| `payout_refund` | — | Payout reversed |

---

## PART 1.5 / 1.6 — Disbursement Endpoints (Phase 3 — confirmed in scope, Part 0)

### 1.5 Bank Account Lookup
```
Endpoint:  POST https://api.nomba.com/v1/transfers/bank/lookup
Headers:   Authorization: Bearer {token}
           accountId: {NOMBA_PARENT_ACCOUNT_ID}
           Content-Type: application/json
Body:      { "accountNumber": "0554772814", "bankCode": "058" }
Response:  { "code": "00", "description": "Success",
             "data": { "accountNumber": "0554772814", "accountName": "M.A Animashaun" } }
```
Always call this before `transfer_to_bank()` and show the returned `accountName` to the landlord for confirmation — never trust a user-supplied name for the transfer itself. Bank codes come from `GET /v1/transfers/banks` (cache the response, codes rarely change).

### 1.6 Transfer to Bank (from the collection sub-account)
```
Endpoint:  POST https://api.nomba.com/v2/transfers/bank/{NOMBA_SUB_ACCOUNT_ID}   -- v2, NOT v1
Headers:   Authorization: Bearer {token}
           accountId: {NOMBA_PARENT_ACCOUNT_ID}
           Content-Type: application/json
Body:      {
             "amount": 50000.00,                  -- CONFIRMED: JSON number, decimal Naira (same convention as expectedAmount)
             "accountNumber": "0554772814",
             "accountName": "M.A Animashaun",      -- use the name from the lookup response
             "bankCode": "058",
             "merchantTxRef": "NULO-DISB-XXXXXXXX",-- YOUR idempotency key, unique per transfer, never reused for a PENDING transfer
             "senderName": "NuloAfrica",
             "narration": "Rent disbursement"
           }
Response:  201 = accepted, processing async (NOT an error) -- final outcome via transfer.success / payout_failed webhook
           data.status: SUCCESS | PENDING | REFUND
             SUCCESS -> done
             PENDING -> do NOT retry, wait for webhook
             REFUND  -> transaction failed and was auto-refunded, safe to retry with a NEW merchantTxRef
```
**Feature dependency:** Nomba's docs carry an explicit notice that sub-account transfers must be enabled by Nomba before this endpoint works on your account. Confirm this is active well before Day 3 — it's an external dependency outside your control.

---

## PART 2 — Environment Variables

Set ALL of these in Render dashboard before any deployment. Never hardcode. Never commit.

```bash
# Nomba account identifiers
NOMBA_PARENT_ACCOUNT_ID=<from credentials provided>
NOMBA_SUB_ACCOUNT_ID=<from credentials provided>   # single collection sub-account.
                                                     # Used in TWO places: virtual account
                                                     # creation (Part 1.2) AND disbursement
                                                     # transfers (Part 1.6). Not per-landlord.

# TEST credentials (use these for all local + sandbox work)
NOMBA_TEST_CLIENT_ID=<from test credentials>
NOMBA_TEST_CLIENT_SECRET=<from test credentials>

# LIVE credentials (switch to these only for final pre-submission verification)
NOMBA_LIVE_CLIENT_ID=<from live credentials>
NOMBA_LIVE_CLIENT_SECRET=<from live credentials>

# Toggle: "test" or "live"
NOMBA_ENV=test

# Hackathon webhook signing key (from submission form — NOT your dashboard key)
NOMBA_WEBHOOK_SECRET=NombaHackathon2026

# Existing vars (already set, confirm they're present)
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
```

---

## PART 3 — Database Migrations

Run in this exact order against Supabase. All verified against your current schema (`newupdatDB.csv`) — zero Nomba columns exist today, these are all net-new.

### Migration 001 — Add payment_frequency to properties
```sql
-- File: docs/sql/migrations/001_add_payment_frequency_to_properties.sql
ALTER TABLE properties
  ADD COLUMN IF NOT EXISTS payment_frequency VARCHAR(50) NOT NULL DEFAULT 'MONTHLY'
  CHECK (payment_frequency IN ('MONTHLY', 'ANNUAL', 'SEMI_ANNUAL', 'QUARTERLY'));
```

### Migration 002 — Add Nomba columns to agreements
```sql
-- File: docs/sql/migrations/002_add_nomba_columns_to_agreements.sql
ALTER TABLE agreements
  ADD COLUMN IF NOT EXISTS payment_frequency VARCHAR(50) DEFAULT 'MONTHLY'
    CHECK (payment_frequency IN ('MONTHLY', 'ANNUAL', 'SEMI_ANNUAL', 'QUARTERLY')),
  ADD COLUMN IF NOT EXISTS expected_payment_amount NUMERIC(12,2),
  ADD COLUMN IF NOT EXISTS payment_schedule JSONB,
  ADD COLUMN IF NOT EXISTS virtual_account_number TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS virtual_account_name TEXT,
  ADD COLUMN IF NOT EXISTS nomba_account_ref TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS next_payment_due_date DATE,
  ADD COLUMN IF NOT EXISTS total_received_amount NUMERIC(12,2) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS reconciliation_status TEXT DEFAULT 'PENDING'
    CHECK (reconciliation_status IN
      ('PENDING','FULL_PAYMENT','UNDERPAYMENT','OVERPAYMENT','MISDIRECTED','DUPLICATE'));

-- Extend existing positive-amounts constraint to cover new column
ALTER TABLE agreements DROP CONSTRAINT IF EXISTS check_positive_amounts;
ALTER TABLE agreements ADD CONSTRAINT check_positive_amounts
  CHECK (
    rent_amount > 0
    AND deposit_amount >= 0
    AND platform_fee >= 0
    AND (expected_payment_amount IS NULL OR expected_payment_amount > 0)
  );
```

### Migration 003 — New Nomba tables + extend transactions
```sql
-- File: docs/sql/migrations/003_create_nomba_tables.sql

-- Log every inbound transfer (audit trail + idempotency source)
CREATE TABLE IF NOT EXISTS virtual_account_transfers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agreement_id UUID REFERENCES agreements(id),
  nomba_request_id TEXT UNIQUE NOT NULL,        -- event.requestId, idempotency key
  nomba_transaction_id TEXT,                    -- data.transaction.transactionId
  account_ref TEXT NOT NULL,                    -- data.transaction.aliasAccountReference
  account_number TEXT,                          -- data.transaction.aliasAccountNumber
  amount_received NUMERIC(12,2) NOT NULL,       -- data.transaction.transactionAmount
  sender_name TEXT,                             -- data.customer.senderName
  sender_bank TEXT,                             -- data.customer.bankName
  currency TEXT DEFAULT 'NGN',
  event_type TEXT NOT NULL,
  transaction_type TEXT,                        -- data.transaction.type (vact_transfer etc)
  raw_payload JSONB NOT NULL,
  signature_valid BOOLEAN NOT NULL,
  reconciliation_result TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_vat_agreement
  ON virtual_account_transfers(agreement_id);
CREATE INDEX IF NOT EXISTS idx_vat_request_id
  ON virtual_account_transfers(nomba_request_id);
CREATE INDEX IF NOT EXISTS idx_vat_account_ref
  ON virtual_account_transfers(account_ref);

-- Audit trail for every reconciliation decision
CREATE TABLE IF NOT EXISTS payment_reconciliation_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agreement_id UUID REFERENCES agreements(id),
  transfer_id UUID REFERENCES virtual_account_transfers(id),
  previous_status TEXT,
  new_status TEXT NOT NULL,
  expected_amount NUMERIC(12,2),
  received_amount NUMERIC(12,2),
  variance_pct NUMERIC(6,2),
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Extend transactions.transaction_type CHECK to include nomba_collection
-- DECISION: new enum value, not JSONB notes — keeps SQL analytics clean
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_transaction_type_check;
ALTER TABLE transactions ADD CONSTRAINT transactions_transaction_type_check
  CHECK (transaction_type IN (
    'rent_payment',
    'security_deposit',
    'guarantee_contribution',
    'nomba_collection'          -- NEW
  ));

-- Verify all migrations ran correctly
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'agreements'
AND column_name IN (
  'payment_frequency','expected_payment_amount','virtual_account_number',
  'nomba_account_ref','reconciliation_status','total_received_amount'
);
```

### Migration 004 — required for Phase 3 (disbursement), confirmed in scope (Part 0)
CONFIRMED against `newupdatDB.csv` (live schema export). This replaces an earlier draft of this migration that proposed two brand-new tables (`landlord_bank_accounts`, `disbursements`) — unnecessary once checked against the real schema:
- `landlords` already has `bank_account_number`, `bank_name`, `account_name` — no need for a separate bank-details table. It's just missing `bank_code`, which Nomba's lookup/transfer endpoints require and a bank *name* string can't supply.
- `transactions` already has `landlord_id`, `amount`, `status`, `held_at`/`released_at`/`refunded_at` — an escrow lifecycle already built for Paystack that disbursement fits naturally (`held_at` = reconciled as `FULL_PAYMENT`, `released_at` = `transfer_to_bank()` succeeds). Per Decision #3, `nomba_collection` was added to `transactions.transaction_type` rather than creating a new table for the inbound side — this does the same for the outbound side, for consistency.

**Before running:** confirm via `\d+ transactions` in psql what `transactions_status_check` and `transactions_transaction_type_check` currently allow — this CSV lists constraint names but not their expressions, so the exact existing values are unverified.
```sql
-- File: docs/sql/migrations/004_add_disbursement_support.sql

-- landlords: add the one missing field needed to call Nomba's transfer endpoints
ALTER TABLE landlords
  ADD COLUMN IF NOT EXISTS bank_code TEXT,
  ADD COLUMN IF NOT EXISTS bank_verified_at TIMESTAMPTZ;  -- set when lookup_bank_account() confirms account_name

-- transactions: add Nomba-specific disbursement fields
ALTER TABLE transactions
  ADD COLUMN IF NOT EXISTS nomba_transfer_ref TEXT UNIQUE,      -- merchantTxRef, idempotency key (Part 1.6)
  ADD COLUMN IF NOT EXISTS nomba_transfer_id TEXT,              -- data.id from transfer response
  ADD COLUMN IF NOT EXISTS source_transfer_id UUID
    REFERENCES virtual_account_transfers(id);                  -- the inbound payment that funded this payout

-- Extend transaction_type to cover the outbound side (nomba_collection already covers inbound)
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_transaction_type_check;
ALTER TABLE transactions ADD CONSTRAINT transactions_transaction_type_check
  CHECK (transaction_type IN (
    'rent_payment',
    'security_deposit',
    'guarantee_contribution',
    'nomba_collection',
    'nomba_disbursement'        -- NEW
  ));

CREATE INDEX IF NOT EXISTS idx_transactions_nomba_transfer_ref
  ON transactions(nomba_transfer_ref);
```
On write: `payment_gateway = 'nomba'`, `transaction_type = 'nomba_disbursement'`, `amount = calculate_landlord_payout(received, platform_fee)` (Part 5), `landlord_id`/`agreement_id` from the source agreement, `source_transfer_id` pointing at the `virtual_account_transfers` row that triggered it.

---

## PART 4 — NombaClient Service

**File: `server/app/services/nomba_client.py`**

```python
import hmac
import hashlib
import base64
import logging
import os
import asyncio
import time
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class NombaAPIError(Exception):
    pass


class NombaClient:
    """
    Nomba API client with token caching, virtual account creation,
    disbursement, and webhook signature verification.

    Uses NOMBA_ENV env var to switch between test and live credentials.
    Always sends NOMBA_PARENT_ACCOUNT_ID in the accountId header, even
    when the URL path targets the collection sub-account.
    """

    def __init__(self):
        env = os.environ.get("NOMBA_ENV", "test")
        if env == "live":
            self.client_id = os.environ["NOMBA_LIVE_CLIENT_ID"]
            self.client_secret = os.environ["NOMBA_LIVE_CLIENT_SECRET"]
            self.base_url = "https://api.nomba.com/v1"
        else:
            self.client_id = os.environ["NOMBA_TEST_CLIENT_ID"]
            self.client_secret = os.environ["NOMBA_TEST_CLIENT_SECRET"]
            self.base_url = "https://sandbox.nomba.com/v1"

        self.parent_account_id = os.environ["NOMBA_PARENT_ACCOUNT_ID"]
        self.sub_account_id = os.environ["NOMBA_SUB_ACCOUNT_ID"]
        self.webhook_secret = os.environ["NOMBA_WEBHOOK_SECRET"]

        self._token = None
        self._refresh_token_value = None
        self._expires_at = 0.0   # epoch seconds
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _issue_token(self):
        """Full re-issue via client_credentials. Always called under self._lock."""
        resp = requests.post(
            f"{self.base_url}/auth/token/issue",
            headers={"Content-Type": "application/json", "accountId": self.parent_account_id},
            json={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "00":
            raise NombaAPIError(f"Token issue failed: {body.get('description', 'Unknown error')}")
        self._store_token_data(body["data"])
        logger.info("Nomba token issued (client_credentials)")

    async def _refresh_token(self):
        """
        Refresh via the stored refresh_token. Falls back to _issue_token()
        if none is stored yet, or if the refresh itself fails (refresh_token
        may have expired). Always called under self._lock.
        """
        if not self._refresh_token_value:
            await self._issue_token()
            return

        resp = requests.post(
            f"{self.base_url}/auth/token/refresh",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "accountId": self.parent_account_id,
            },
            json={"grant_type": "refresh_token", "refresh_token": self._refresh_token_value},
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "00":
            logger.warning("Token refresh failed (%s) -- falling back to re-issue", body.get("description"))
            self._refresh_token_value = None
            await self._issue_token()
            return
        self._store_token_data(body["data"])
        logger.info("Nomba token refreshed via refresh_token")

    def _store_token_data(self, data: dict):
        """Token lifetime is 60 minutes. Refresh 5 minutes before expiry."""
        self._token = data["access_token"]
        self._refresh_token_value = data.get("refresh_token", self._refresh_token_value)
        expires_at_str = data.get("expiresAt")
        if expires_at_str:
            try:
                dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                self._expires_at = dt.timestamp() - 300   # 5-min safety buffer
            except Exception:
                self._expires_at = time.time() + 3300     # 55 min fallback
        else:
            self._expires_at = time.time() + 3300

    async def _get_token(self) -> str:
        """Return cached token or refresh if expired. Thread-safe."""
        if self._token and time.time() < self._expires_at:
            return self._token
        async with self._lock:
            if self._token and time.time() < self._expires_at:
                return self._token
            await self._refresh_token()
        return self._token

    async def _headers(self) -> dict:
        token = await self._get_token()
        return {
            "Authorization": f"Bearer {token}",
            "accountId": self.parent_account_id,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Virtual account creation (Phase 1 -- Collect)
    # ------------------------------------------------------------------

    async def create_virtual_account(
        self,
        account_ref: str,
        account_name: str,
        expected_amount: float | None = None,
    ) -> dict:
        """
        Create a virtual NUBAN for a signed agreement, routed through the
        single collection sub-account (NOMBA_SUB_ACCOUNT_ID) -- NOT the
        bare parent endpoint, and NOT one sub-account per landlord.

        account_ref:     Use agreement.id (your UUID) -- stable lookup key.
        account_name:    COALESCE(tenant full_name, email, 'NuloAfrica Tenant')
        expected_amount: Periodic rent in Naira. CONFIRMED: sent as a JSON
                         number (decimal Naira), not kobo, not a string.
        """
        payload = {
            "accountRef": account_ref,
            "accountName": account_name,
            "currency": "NGN",
        }
        if expected_amount is not None:
            payload["expectedAmount"] = round(float(expected_amount), 2)

        headers = await self._headers()
        resp = requests.post(
            f"{self.base_url}/accounts/virtual/{self.sub_account_id}",
            headers=headers,
            json=payload,
            timeout=15,
        )
        logger.info("Nomba create_virtual_account | ref=%s | status=%s", account_ref, resp.status_code)
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "00":
            raise NombaAPIError(f"Nomba error: {body.get('description', 'Unknown error')}")
        return body["data"]

    # ------------------------------------------------------------------
    # Webhook signature verification (Phase 2 -- Reconcile)
    # ------------------------------------------------------------------

    def verify_webhook_signature(
        self,
        payload: dict,
        signature: str,
        nomba_timestamp: str,
    ) -> bool:
        """
        Verify a Nomba webhook signature.

        NOT a raw-body hash. Colon-joined string of 9 fields, HMAC-SHA256,
        base64-encoded. Comparison is EXACT-CASE via hmac.compare_digest() --
        base64 is case-sensitive, do not lowercase either side.

        Verified against Nomba's published test vector -- confirmed match,
        no case-folding needed.
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

            digest = hmac.new(self.webhook_secret.encode(), hashing_payload.encode(), hashlib.sha256).digest()
            expected = base64.b64encode(digest).decode()
            return hmac.compare_digest(signature, expected)
        except Exception as e:
            logger.error("Signature verification error: %s", e)
            return False

    # ------------------------------------------------------------------
    # Disbursement (Phase 3 -- confirmed in scope, Part 0)
    # ------------------------------------------------------------------

    async def lookup_bank_account(self, account_number: str, bank_code: str) -> dict:
        """
        Verify a recipient bank account before initiating any transfer.
        ALWAYS call before transfer_to_bank() -- confirms the account exists
        and returns the verified account holder name.
        """
        headers = await self._headers()
        resp = requests.post(
            f"{self.base_url}/transfers/bank/lookup",
            headers=headers,
            json={"accountNumber": account_number, "bankCode": bank_code},
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "00":
            raise NombaAPIError(f"Bank lookup failed: {body.get('description', 'Unknown error')}")
        logger.info("Bank lookup OK | account=%s | bank=%s | name=%s",
                    account_number, bank_code, body["data"].get("accountName"))
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
        Disburse funds to a landlord's bank account from the collection
        sub-account.

        - Endpoint is /v2/transfers/bank/{subAccountId} -- v2, NOT v1.
        - Sub-account transfers must be enabled by Nomba first (external
          dependency -- confirm this early, see Part 1.6).
        - amount is DECIMAL NAIRA, sent as a JSON number -- same convention
          as expectedAmount, confirmed against the live OpenAPI spec.
        - merchant_tx_ref: your idempotency key. Reuse on retries. Only
          generate a new ref after a REFUND status, never for PENDING.
        - 201 response = accepted, processing async, NOT an error. Final
          outcome arrives via transfer.success / payout_failed webhook.
        """
        transfer_url = self.base_url.rsplit("/v1", 1)[0] + "/v2"
        amount = round(float(amount_naira), 2)

        headers = await self._headers()
        resp = requests.post(
            f"{transfer_url}/transfers/bank/{self.sub_account_id}",
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
        logger.info("transfer_to_bank | ref=%s | amount_ngn=%.2f | status=%s",
                    merchant_tx_ref, amount, resp.status_code)

        if resp.status_code == 201:
            body = resp.json()
            logger.info("Transfer processing async | ref=%s | nomba_status=%s",
                        merchant_tx_ref, body.get("data", {}).get("status"))
            return body.get("data", {})

        resp.raise_for_status()
        body = resp.json()
        if body.get("code") not in ("00", "201"):
            raise NombaAPIError(f"Transfer failed: {body.get('description', 'Unknown error')}")
        return body.get("data", {})


# Singleton — import and use this instance across your routers
nomba_client = NombaClient()
```

---

## PART 5 — Helper Functions

**File: `server/app/services/nomba_helpers.py`**

```python
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

GRACE_PERIODS = {
    "ANNUAL": 7,
    "SEMI_ANNUAL": 5,
    "QUARTERLY": 3,
    "MONTHLY": 1,
}

TOLERANCE_PCT = 0.02   # +/- 2% variance treated as full payment


def calculate_expected_amount(monthly_rent: float, frequency: str) -> float:
    """
    Calculate the lump-sum payment expected per payment cycle.
    monthly_rent is always stored as the base monthly unit.
    """
    multipliers = {
        "MONTHLY": 1,
        "QUARTERLY": 3,
        "SEMI_ANNUAL": 6,
        "ANNUAL": 12,
    }
    return monthly_rent * multipliers.get(frequency, 1)


def calculate_next_due_date(lease_start_date: date, frequency: str) -> date:
    """Return the first payment due date from lease start."""
    deltas = {
        "MONTHLY": relativedelta(months=1),
        "QUARTERLY": relativedelta(months=3),
        "SEMI_ANNUAL": relativedelta(months=6),
        "ANNUAL": relativedelta(years=1),
    }
    return lease_start_date + deltas.get(frequency, relativedelta(months=1))


def is_within_grace_period(due_date: date, frequency: str) -> bool:
    """Return True if today is still within the grace period for this frequency."""
    grace_days = GRACE_PERIODS.get(frequency, 1)
    return date.today() <= due_date + timedelta(days=grace_days)


def classify_payment(
    received: float,
    expected: float,
) -> str:
    """
    Return reconciliation status string.
    Tolerance of +/- 2% for rounding/fee variance.
    """
    if expected <= 0:
        return "PENDING"
    variance = (received - expected) / expected
    if abs(variance) <= TOLERANCE_PCT:
        return "FULL_PAYMENT"
    elif variance < 0:
        return "UNDERPAYMENT"
    else:
        return "OVERPAYMENT"


def calculate_landlord_payout(received: float, platform_fee: float) -> float:
    """
    NEW -- Phase 3 (disbursement). Split calculation: platform_fee stays
    in the collection sub-account, the remainder goes to the landlord.
    Round to 2dp since this feeds directly into transfer_to_bank()'s
    decimal-Naira amount field.
    """
    return round(max(received - platform_fee, 0), 2)
```

---

## PART 6 — API Routes

**File: `server/app/routes/nomba.py`**

```python
import logging
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from app.services.nomba_client import nomba_client, NombaAPIError
from app.services.nomba_helpers import (
    calculate_expected_amount,
    calculate_next_due_date,
    classify_payment,
)
from app.dependencies import get_current_user
from app.database import supabase_admin   # your existing service-role client

logger = logging.getLogger(__name__)
router = APIRouter()

# ======================================================================
# ROUTE 1: Provision Nomba virtual account for a signed agreement
# POST /api/v1/agreements/{agreement_id}/provision-nomba
# ======================================================================

@router.post("/agreements/{agreement_id}/provision-nomba")
async def provision_nomba(
    agreement_id: str,
    background_tasks: BackgroundTasks,       # Rule 5: BackgroundTasks BEFORE Depends
    current_user=Depends(get_current_user),
):
    # Fetch agreement
    result = await asyncio.get_event_loop().run_in_executor(    # Rule 6
        None,
        lambda: supabase_admin
            .table("agreements")
            .select("*")
            .eq("id", agreement_id)
            .single()
            .execute()
    )
    agreement = result.data
    if not agreement:
        raise HTTPException(404, "Agreement not found")

    # Auth check: only landlord or tenant on this agreement
    if current_user["id"] not in (agreement["landlord_id"], agreement["tenant_id"]):
        raise HTTPException(403, "Not authorized")

    # Only provision for signed agreements
    if agreement["status"] != "SIGNED":
        raise HTTPException(400, "Agreement must be in SIGNED status before provisioning")

    # Idempotent: already provisioned
    if agreement.get("virtual_account_number"):
        return {
            "status": "already_provisioned",
            "virtual_account_number": agreement["virtual_account_number"],
            "virtual_account_name": agreement["virtual_account_name"],
        }

    # Get tenant name for account label
    tenant_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("tenant_profiles")
            .select("full_name, email")
            .eq("id", agreement["tenant_id"])
            .single()
            .execute()
    )
    tenant = tenant_result.data or {}
    account_name = (
        tenant.get("full_name")
        or tenant.get("email")
        or "NuloAfrica Tenant"
    )

    frequency = agreement.get("payment_frequency") or "MONTHLY"
    expected_amount = calculate_expected_amount(
        float(agreement["rent_amount"]), frequency
    )

    try:
        data = await nomba_client.create_virtual_account(
            account_ref=agreement_id,   # agreement.id is the stable ref
            account_name=account_name,
            expected_amount=expected_amount,
        )
    except NombaAPIError as e:
        logger.error("Nomba provisioning failed for agreement %s: %s", agreement_id, e)
        raise HTTPException(502, f"Nomba provisioning failed: {str(e)}")

    next_due = calculate_next_due_date(
        agreement["lease_start_date"], frequency
    ) if agreement.get("lease_start_date") else None

    # Update agreement row
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .update({
                "virtual_account_number": data["bankAccountNumber"],
                "virtual_account_name": data["bankAccountName"],
                "nomba_account_ref": data["accountRef"],
                "expected_payment_amount": expected_amount,
                "payment_frequency": frequency,
                "next_payment_due_date": str(next_due) if next_due else None,
                "reconciliation_status": "PENDING",
                "total_received_amount": 0,
            })
            .eq("id", agreement_id)
            .execute()
    )

    logger.info(
        "Virtual account provisioned | agreement=%s | nuban=%s",
        agreement_id, data["bankAccountNumber"]
    )

    # Notify tenant in background (non-blocking)
    background_tasks.add_task(
        notify_tenant_account_provisioned, agreement_id, data
    )

    return {
        "status": "provisioned",
        "virtual_account_number": data["bankAccountNumber"],
        "virtual_account_name": data["bankAccountName"],
        "bank_name": data.get("bankName"),
        "expected_amount": expected_amount,
        "frequency": frequency,
        "next_due_date": str(next_due) if next_due else None,
    }


# ======================================================================
# ROUTE 2: Nomba webhook receiver
# POST /webhooks/nomba/transfer
# NOTE: registered WITHOUT /api/v1 prefix — see main.py registration
# ======================================================================

@router.post("/webhooks/nomba/transfer")
async def nomba_webhook(request: Request):
    """
    Receive and process Nomba payment webhooks.

    CRITICAL implementation notes:
    1. Parse JSON first (signature algorithm needs parsed fields)
    2. Read nomba-signature AND nomba-timestamp from headers
    3. Verify signature BEFORE any DB writes
    4. Check idempotency (requestId) BEFORE reconciliation
    5. Always return 200 after verification + storage — reconciliation
       errors are async problems, not retry-trigger problems
    """
    # Step 1: Get raw headers before any await
    signature = request.headers.get("nomba-signature", "")
    nomba_timestamp = request.headers.get("nomba-timestamp", "")

    # Step 2: Parse body
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    # Step 3: Verify signature
    if not signature or not nomba_client.verify_webhook_signature(
        payload, signature, nomba_timestamp
    ):
        logger.warning(
            "Invalid webhook signature | sig=%s | ts=%s",
            signature[:20] if signature else "MISSING", nomba_timestamp
        )
        # Log for audit but don't write to virtual_account_transfers
        raise HTTPException(401, "Invalid signature")

    # Step 4: Extract top-level fields
    request_id = payload.get("requestId")
    event_type = payload.get("event_type")

    if not request_id:
        raise HTTPException(400, "Missing requestId")

    # Step 5: Idempotency check
    existing = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .select("id")
            .eq("nomba_request_id", request_id)
            .execute()
    )
    if existing.data:
        logger.info("Duplicate webhook ignored | requestId=%s", request_id)
        return {"status": "already_processed"}

    # Step 6: Extract transaction fields
    data = payload.get("data", {})
    transaction = data.get("transaction", {})
    customer = data.get("customer", {})

    transaction_type = transaction.get("type", "")
    account_ref = transaction.get("aliasAccountReference", "")
    amount_received = transaction.get("transactionAmount", 0)

    # Step 7: Store the transfer record first (audit trail regardless of outcome)
    transfer_insert = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .insert({
                "nomba_request_id": request_id,
                "nomba_transaction_id": transaction.get("transactionId"),
                "account_ref": account_ref,
                "account_number": transaction.get("aliasAccountNumber"),
                "amount_received": amount_received,
                "sender_name": customer.get("senderName"),
                "sender_bank": customer.get("bankName"),
                "currency": "NGN",
                "event_type": event_type,
                "transaction_type": transaction_type,
                "raw_payload": payload,
                "signature_valid": True,
            })
            .execute()
    )
    transfer_row = transfer_insert.data[0] if transfer_insert.data else {}

    # Step 8: Only reconcile for virtual account funding events
    if event_type == "payment_success" and transaction_type == "vact_transfer":
        try:
            await reconcile_payment(transfer_row, account_ref, amount_received)
        except Exception as e:
            # Log but don't re-raise — return 200 so Nomba doesn't retry
            logger.error(
                "Reconciliation error | requestId=%s | error=%s", request_id, e
            )

    return {"status": "ok"}


# ======================================================================
# ROUTE 3: Payment status for an agreement
# GET /api/v1/agreements/{agreement_id}/payment-status
# ======================================================================

@router.get("/agreements/{agreement_id}/payment-status")
async def payment_status(
    agreement_id: str,
    current_user=Depends(get_current_user),
):
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .select(
                "id, payment_frequency, expected_payment_amount, "
                "total_received_amount, reconciliation_status, "
                "next_payment_due_date, virtual_account_number, "
                "virtual_account_name, tenant_id, landlord_id"
            )
            .eq("id", agreement_id)
            .single()
            .execute()
    )
    agreement = result.data
    if not agreement:
        raise HTTPException(404, "Agreement not found")

    if current_user["id"] not in (agreement["tenant_id"], agreement["landlord_id"]):
        raise HTTPException(403, "Not authorized")

    transfers = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .select("id, amount_received, sender_name, created_at, reconciliation_result")
            .eq("account_ref", agreement_id)
            .order("created_at", desc=True)
            .execute()
    )

    return {
        "agreement_id": agreement_id,
        "frequency": agreement["payment_frequency"],
        "expected_amount": float(agreement["expected_payment_amount"] or 0),
        "total_received": float(agreement["total_received_amount"] or 0),
        "reconciliation_status": agreement["reconciliation_status"],
        "next_due_date": agreement["next_payment_due_date"],
        "virtual_account_number": agreement["virtual_account_number"],
        "virtual_account_name": agreement["virtual_account_name"],
        "transfer_history": transfers.data or [],
    }


# ======================================================================
# ROUTE 4: Health check (for judges)
# GET /api/v1/health/nomba
# ======================================================================

@router.get("/health/nomba")
async def nomba_health():
    """Judges can hit this to verify the integration is live."""
    try:
        token = await nomba_client._get_token()
        token_ok = bool(token)
    except Exception as e:
        return {"status": "error", "nomba_auth": False, "error": str(e)}

    return {
        "status": "ok",
        "nomba_auth": token_ok,
        "webhook_url": "https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer",
        "environment": "test" if "sandbox" in nomba_client.base_url else "live",
    }


# ======================================================================
# Internal: Reconciliation engine
# ======================================================================

async def reconcile_payment(
    transfer_row: dict,
    account_ref: str,
    amount_received: float,
):
    """
    Match an inbound transfer against the expected agreement payment.
    Updates agreements.reconciliation_status and total_received_amount.
    Inserts a transaction record and a reconciliation log entry.
    """
    import asyncio

    if not account_ref:
        logger.warning("Webhook with no aliasAccountReference — cannot reconcile")
        return

    # Look up agreement by the accountRef (which is agreement.id)
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .select(
                "id, tenant_id, landlord_id, rent_amount, "
                "expected_payment_amount, payment_frequency, "
                "total_received_amount, reconciliation_status"
            )
            .eq("id", account_ref)   # accountRef == agreement.id
            .execute()
    )

    if not result.data:
        # Transfer arrived for unknown account ref
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin
                .table("virtual_account_transfers")
                .update({"reconciliation_result": "MISDIRECTED"})
                .eq("id", transfer_row.get("id"))
                .execute()
        )
        logger.warning("MISDIRECTED payment | accountRef=%s", account_ref)
        return

    agreement = result.data[0]
    expected = float(agreement["expected_payment_amount"] or 0)
    prev_total = float(agreement["total_received_amount"] or 0)
    new_total = prev_total + float(amount_received)
    prev_status = agreement["reconciliation_status"]

    new_status = classify_payment(float(amount_received), expected)
    variance_pct = (
        round(((float(amount_received) - expected) / expected) * 100, 2)
        if expected > 0 else 0
    )

    # Update agreement
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .update({
                "total_received_amount": new_total,
                "reconciliation_status": new_status,
            })
            .eq("id", agreement["id"])
            .execute()
    )

    # Update transfer record with result
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .update({
                "agreement_id": agreement["id"],
                "reconciliation_result": new_status,
            })
            .eq("id", transfer_row.get("id"))
            .execute()
    )

    # Reconciliation log
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("payment_reconciliation_log")
            .insert({
                "agreement_id": agreement["id"],
                "transfer_id": transfer_row.get("id"),
                "previous_status": prev_status,
                "new_status": new_status,
                "expected_amount": expected,
                "received_amount": float(amount_received),
                "variance_pct": variance_pct,
                "notes": f"frequency={agreement['payment_frequency']}",
            })
            .execute()
    )

    # transactions table entry (joins with existing payment history)
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .insert({
                "agreement_id": agreement["id"],
                "tenant_id": agreement["tenant_id"],
                "landlord_id": agreement["landlord_id"],
                "amount": float(amount_received),
                "transaction_type": "nomba_collection",
                "status": "completed",
                "payment_gateway": "nomba",
                "currency": "NGN",
                "notes": f"frequency={agreement['payment_frequency']} status={new_status}",
            })
            .execute()
    )

    logger.info(
        "Reconciled | agreement=%s | received=%.2f | expected=%.2f | status=%s",
        agreement["id"], float(amount_received), expected, new_status
    )


# Background task helper
async def notify_tenant_account_provisioned(agreement_id: str, data: dict):
    """Send in-app / email notification that virtual account is ready."""
    # Use your existing notification_service pattern here
    logger.info(
        "TODO: notify tenant | agreement=%s | nuban=%s",
        agreement_id, data.get("bankAccountNumber")
    )
```

---

## PART 7 — Router Registration

**File: `server/app/main.py` — add these lines in router registration section**

```python
from app.routes.nomba import router as nomba_router

# Nomba API routes (with /api/v1 prefix)
app.include_router(
    nomba_router,
    prefix="/api/v1",
    tags=["nomba"]
)

# NOTE: The webhook endpoint is also registered under /api/v1
# so the full path is /api/v1/webhooks/nomba/transfer
# Submit this full URL to the hackathon form:
# https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer
```

**Route order check (Rule 7):**
Your nomba router has these routes:
1. `POST /agreements/{agreement_id}/provision-nomba` — specific enough, no conflict
2. `POST /webhooks/nomba/transfer` — specific path, no wildcard
3. `GET /agreements/{agreement_id}/payment-status` — if your existing `agreements.py` router has `GET /{id}`, make sure nomba routes are registered first OR these routes don't conflict since they're in different routers

---

## PART 8 — Thunder Client Test Plan

**Complete this in order. Do not move to the next test until the current one passes.**

### Day 1 Tests

**TEST 1.0 — Amount format verification (do this BEFORE writing code)**
```
POST https://sandbox.nomba.com/v1/auth/token/issue
Headers: Content-Type: application/json, accountId: {NOMBA_PARENT_ACCOUNT_ID}
Body: { "grant_type": "client_credentials", "client_id": "..TEST..", "client_secret": "..TEST.." }
Expected: 200, data.access_token present
Save token for next requests.

POST https://sandbox.nomba.com/v1/accounts/virtual
Headers: Authorization: Bearer {token}, accountId: {parent_id}, Content-Type: application/json
Body A: { "accountRef": "amount_test_001", "accountName": "Test User", "currency": "NGN", "expectedAmount": 10000.00 }
Body B: { "accountRef": "amount_test_002", "accountName": "Test User", "currency": "NGN", "expectedAmount": 1000000 }

GET https://sandbox.nomba.com/v1/accounts/virtual/amount_test_001
-> Check what value comes back. Match with narration if any.

**Amount convention per endpoint (verified from community + Nomba docs):**
| Endpoint | `amount` field convention | Verified by |
|----------|---------------------------|-------------|
| `/v1/accounts/virtual` (expectedAmount) | decimal Naira (float) | PRD Part 0, line 48; production webhook `transactionAmount: 10` matching "Transfer 10.00" |
| `/v2/transfers/bank/{subAccountId}` (amount) | decimal Naira (float) | PRD v2 Part 1.6, OpenAPI spec type:number format:double |
| `/v1/orders` (checkout) | kobo (int) | Nomba community thread, Discord 2026-07-01 |
| `/v1/accounts/virtual/{id}/orders` | kobo (int) | Likely matches `/v1/orders` parent class |

**No env var needed.** Virtual accounts and bank transfers (our scope) use decimal Naira.
If a future endpoint uses kobo, add an `amount_format` parameter to that method
explicitly -- do not introduce a global `NOMBA_AMOUNT_FORMAT` env var.
```

**TEST 1.1 — Provisioning: happy path**
```
POST http://localhost:8000/api/v1/agreements/{valid_signed_agreement_id}/provision-nomba
Auth: your existing JWT
Expected 200:
{
  "status": "provisioned",
  "virtual_account_number": "93XXXXXXXX",
  "virtual_account_name": "Nomba/...",
  "expected_amount": <number>,
  "frequency": "MONTHLY"
}
Verify in Supabase: agreements row has virtual_account_number, nomba_account_ref, reconciliation_status=PENDING
```

**TEST 1.2 — Provisioning: idempotent re-call**
```
POST same URL again
Expected 200: { "status": "already_provisioned", ... }
Verify: no second Nomba API call made (check logs), DB unchanged
```

**TEST 1.3 — Provisioning: unsigned agreement**
```
POST with an agreement_id where status != 'SIGNED'
Expected: 400 "Agreement must be in SIGNED status"
```

**TEST 1.4 — Provisioning: wrong user**
```
POST with a JWT from a user not on this agreement
Expected: 403
```

### Day 2 Tests

**First: generate your test signature locally**
```python
import hmac, hashlib, base64, json

secret = "NombaHackathon2026"
timestamp = "2026-07-01T10:00:00Z"

payload = {
    "event_type": "payment_success",
    "requestId": "test-req-001",
    "data": {
        "merchant": {
            "walletId": "test-wallet-001",
            "walletBalance": 50000,
            "userId": "YOUR_SUB_ACCOUNT_ID"
        },
        "terminal": {},
        "transaction": {
            "aliasAccountNumber": "9391076543",
            "fee": 5,
            "sessionId": "test-session-001",
            "type": "vact_transfer",
            "transactionId": "test-txn-001",
            "aliasAccountName": "NuloAfrica/Test Tenant",
            "responseCode": "",
            "originatingFrom": "api",
            "transactionAmount": 500000,   # adjust per amount format result
            "narration": "Rent payment",
            "time": timestamp,
            "aliasAccountReference": "YOUR_REAL_AGREEMENT_UUID",
            "aliasAccountType": "VIRTUAL"
        },
        "customer": {
            "bankCode": "058",
            "senderName": "TEST TENANT",
            "bankName": "GTBank",
            "accountNumber": "0123456789"
        }
    }
}

t = payload["data"]["transaction"]
m = payload["data"]["merchant"]
hashing_payload = (
    f"{payload['event_type']}:{payload['requestId']}:{m['userId']}:{m['walletId']}:"
    f"{t['transactionId']}:{t['type']}:{t['time']}:{t['responseCode']}:{timestamp}"
)
digest = hmac.new(secret.encode(), hashing_payload.encode(), hashlib.sha256).digest()
print("nomba-signature:", base64.b64encode(digest).decode())
```

**TEST 2.1 — Webhook: valid full payment**
```
POST http://localhost:8000/api/v1/webhooks/nomba/transfer
Headers:
  nomba-signature: {computed above}
  nomba-timestamp: 2026-07-01T10:00:00Z
  Content-Type: application/json
Body: {payload from above}
Expected: 200 { "status": "ok" }
Verify DB:
  - virtual_account_transfers has 1 row with nomba_request_id="test-req-001"
  - agreements.reconciliation_status = "FULL_PAYMENT" (if amount matches)
  - payment_reconciliation_log has 1 row
  - transactions has 1 row with transaction_type="nomba_collection"
```

**TEST 2.2 — Webhook: idempotency (replay same payload)**
```
POST same request again with identical body + signature
Expected: 200 { "status": "already_processed" }
Verify: still only 1 row in virtual_account_transfers, agreement unchanged
```

**TEST 2.3 — Webhook: bad signature**
```
POST with nomba-signature: "invalidsignature=="
Expected: 401
Verify: no row inserted in virtual_account_transfers
```

**TEST 2.4 — Webhook: underpayment**
```
Change transactionAmount to something below expected (e.g. half)
Recompute signature with requestId="test-req-002"
Expected: 200, reconciliation_status="UNDERPAYMENT"
```

**TEST 2.5 — Webhook: overpayment**
```
Change transactionAmount to 2x expected
requestId="test-req-003"
Expected: 200, reconciliation_status="OVERPAYMENT"
```

**TEST 2.6 — Webhook: misdirected (unknown agreement)**
```
Change aliasAccountReference to a UUID not in your agreements table
requestId="test-req-004"
Expected: 200, virtual_account_transfers row has reconciliation_result="MISDIRECTED"
agreements table unchanged
```

**TEST 2.7 — Payment status endpoint**
```
GET http://localhost:8000/api/v1/agreements/{agreement_id}/payment-status
Auth: landlord JWT or tenant JWT for this agreement
Expected: 200 with frequency, expected_amount, total_received, reconciliation_status, transfer_history
```

**TEST 2.8 — Health check**
```
GET http://localhost:8000/api/v1/health/nomba
Expected: 200 { "status": "ok", "nomba_auth": true, "environment": "test" }
```

### Day 3 — Pre-submission checks

1. Push to GitHub, wait for Render deploy
2. Repeat TEST 2.1 and 2.3 against `https://api.nuloafrica.com` (not localhost)
3. Verify Render env vars all set (no missing secret causes 500)
4. Submit webhook form with `https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer`

---

## PART 9 — Pre-Submission Checklist

Run this literally before submitting. Every unchecked item costs points.

**Security**
- [ ] `NOMBA_WEBHOOK_SECRET=NombaHackathon2026` set in Render env vars (NOT in code)
- [ ] `NOMBA_LIVE_CLIENT_SECRET` and `NOMBA_TEST_CLIENT_SECRET` in Render env vars (NOT in code)
- [ ] Webhook handler uses `hmac.compare_digest()` not `==` for signature comparison
- [ ] Signature verification runs BEFORE any DB write
- [ ] Webhook returns 401 on invalid signature, 200 on valid (including duplicates)

**Correctness**
- [x] Amount format confirmed via live OpenAPI spec (decimal Naira, JSON number) — no Day 1 sandbox test required, though a ₦1 real sandbox transfer is still worth running before any live disbursement
- [ ] All 6 reconciliation scenarios pass Thunder Client tests locally
- [ ] Idempotency tested with actual replay — confirmed no double-write
- [ ] `aliasAccountReference` → `agreement.id` mapping confirmed working end-to-end
- [ ] `transactions.transaction_type` migration ran — `nomba_collection` accepted without error

**Phase 3 — disbursement (confirmed in scope, Part 0)**
- [ ] Confirmed with Nomba hackathon team that sub-account transfers are enabled on your account
- [ ] Migration 004 ran (`landlord_bank_accounts`, `disbursements`)
- [ ] `lookup_bank_account()` called and its `accountName` shown to landlord before every `transfer_to_bank()` call, never a user-typed name
- [ ] At least one real sandbox disbursement completed and reconciled against the `disbursements` table

**Operations**
- [ ] Health endpoint `GET /api/v1/health/nomba` returns 200 with `nomba_auth: true`
- [ ] All 3 DB migrations ran — verify with the SQL check query in Migration 003
- [ ] Render logs accessible for live webhook debugging
- [ ] Webhook URL (`https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer`) returns non-timeout response to a plain curl POST

**Submission form**
- [ ] Sub-account ID from Nomba dashboard (Accounts → your sub-account → Account ID)
- [ ] Webhook URL: `https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer`
- [ ] Signing key in your env var matches `NombaHackathon2026` exactly

---

## PART 10 — Architecture Rules to Obey (from NULOGUIDE)

These apply to every file you create or modify in this integration:

| Rule | What it means here |
|---|---|
| Rule 5 | `BackgroundTasks` param comes BEFORE `Depends()` in every route signature — already applied in provision_nomba above |
| Rule 6 | All Supabase calls inside async FastAPI must use `run_in_executor` — applied throughout |
| Rule 7 | Register nomba router before any wildcard `/{id}` routes in main.py |
| Rule 17 | No Unicode characters in any `.py` file — use ASCII only in strings, comments, logs |
| Rule 18 | Always use `supabase_admin` (service role client), never anon key |
| Rule 21 | Paystack webhooks use HMAC-SHA512 over raw body. Nomba webhooks use HMAC-SHA256 over a constructed string, base64 encoded. These are completely different — do not mix them up |

---

## PART 11 — File Manifest

### New files to create
```
server/app/services/nomba_client.py        ← NombaClient class + singleton
server/app/services/nomba_helpers.py       ← calculate_expected_amount, classify_payment etc
server/app/routes/nomba.py                 ← collection + reconciliation endpoints
server/tests/test_nomba_webhook.py         ← unit tests for signature verification + reconciliation
docs/sql/migrations/001_add_payment_frequency_to_properties.sql
docs/sql/migrations/002_add_nomba_columns_to_agreements.sql
docs/sql/migrations/003_create_nomba_tables.sql
docs/SECURITY.md                           ← document the security decisions

# Phase 3 only — see SCOPE FLAG, Part 0. Confirm before creating.
docs/sql/migrations/004_create_disbursement_tables.sql
server/app/routes/disbursements.py         ← lookup + transfer routes, not yet drafted
```

### Files to modify
```
server/app/main.py                         ← register nomba_router
server/.env.example                        ← add all NOMBA_ vars
README.md                                  ← add Nomba integration section
```

### Files to NOT touch
```
server/app/routes/payments.py              ← Paystack integration, leave alone
server/app/routes/agreements.py            ← existing agreement CRUD, leave alone
```