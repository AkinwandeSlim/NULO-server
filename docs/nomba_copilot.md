# Copilot Prompt — NuloAfrica Nomba Hackathon Integration
## Paste this entire prompt to your AI Copilot/Cursor to begin implementation

---

## YOUR FIRST TASK BEFORE WRITING ANY CODE

You are working on the NuloAfrica codebase. Before touching any file, you must read two reference documents and the database schema in full:

1. **Architecture guide** (existing platform rules, completed features, known bugs):
   `C:\MyFiles\DOCUMENT-2026\Nuelo_Poc\NULO-DEV\docs\prd\NULOGUIDE_UPDATED.md`

2. **Nomba integration PRD** (everything you need to build, verified API facts, test plan):
   `C:\MyFiles\DOCUMENT-2026\Nuelo_Poc\NULO-DEV\docs\hackathon\nomba_PRD.md`

3. **Live database schema** (actual columns, constraints, indexes — use this to verify every table/column reference before writing SQL or Supabase queries):
   `C:\MyFiles\DOCUMENT-2026\Nuelo_Poc\NULO-DEV\database\newupdatDB.csv`

Read all three completely before generating a single line of code. If any file is not found at its path, stop and tell me — do not proceed on assumptions.

---

## WHAT YOU ARE BUILDING

**Project:** NuloAfrica — zero agency-fee Nigerian rental marketplace
**Task:** Integrate Nomba Virtual Accounts for multi-frequency rental payment collection
**Hackathon:** DevCareer Nomba Hackathon 2026, July 1–7
**Track:** Virtual Accounts as Infrastructure
**Live backend:** https://api.nuloafrica.com (FastAPI on Render, repo: AkinwandeSlim/NULO-server, branch: main)

The existing Paystack integration handles one-time payments and must NOT be touched.
You are adding Nomba alongside it — a parallel payment rail for frequency-aware rent collection.

---

## ARCHITECTURE RULES — NEVER VIOLATE THESE

These come from NULOGUIDE_UPDATED.md. Every file you create or modify must obey them:

| Rule | Requirement |
|---|---|
| Rule 1 | Shared PK pattern: `tenant_profiles.id = auth.users.id`. Always `.eq('id', user_id)`, never `.eq('user_id', ...)` |
| Rule 5 | `background_tasks: BackgroundTasks` MUST come BEFORE `Depends()` in every FastAPI route signature |
| Rule 6 | All Supabase calls inside `async` FastAPI functions MUST use `run_in_executor` |
| Rule 7 | FastAPI route order: specific named routes FIRST, wildcard `/{id}` LAST — always |
| Rule 15 | React: NEVER define a component function inside another component |
| Rule 17 | No Unicode in any `.py` file — ASCII only in strings, comments, log messages |
| Rule 18 | Always use `supabase_admin` (service role client). Never the anon key on the backend |
| Rule 21 | Paystack webhook uses HMAC-SHA512 over raw body, header `x-paystack-signature`. DO NOT confuse this with Nomba's completely different scheme |
| Rule 22 | New snake_case fields from backend must be normalized to camelCase in `dashboardAPI.ts`, not in React components |
| Rule 23 | Dashboard loading guards must use: `if (!mounted || loading || allDataLoading) return <Spinner />` |

---

## DATABASE SCHEMA VERIFICATION RULES

Before writing ANY Supabase query, SQL migration, or table reference:

1. Open `C:\MyFiles\DOCUMENT-2026\Nuelo_Poc\NULO-DEV\database\newupdatDB.csv`
2. Confirm the table exists under `schema_name = public`
3. Confirm the exact column name — do not guess or use aliases
4. Check `constraint_type` column — if `c` (CHECK) exists on the column, find the constraint name and honor it exactly
5. Check `constraint_type = p` for primary keys, `f` for foreign keys, `u` for unique constraints

**Critical schema facts already verified from the CSV:**
- `agreements` table: has `id`, `tenant_id`, `landlord_id`, `property_id`, `application_id`, `status`, `rent_amount`, `deposit_amount`, `platform_fee`, `service_charge`, `lease_start_date`, `lease_end_date`, `lease_duration`, `terms`, `document_url`, `generation_metadata`, `agreement_source`, `landlord_signed_at`, `tenant_signed_at`, `landlord_signature_ip`, `tenant_signature_ip`, `created_at`, `updated_at`. **It has NO Nomba columns yet — the migrations add them.**
- `properties` table: has no `payment_frequency` column yet — Migration 001 adds it. It DOES have `deleted_at` (contradicts old docs — verified from CSV, `idx_properties_deleted_at` exists). Properties also use `verification_status` for lifecycle.
- `transactions` table: `transaction_type` has a CHECK constraint. Current allowed values are `rent_payment`, `security_deposit`, `guarantee_contribution`. Migration 003 extends this to add `nomba_collection`.
- `tenant_profiles.id = auth.users.id` (shared PK — no separate `user_id` FK column)
- `applications.user_id` is the tenant FK (not `tenant_id`) — Rule 8

---

## ENVIRONMENT VARIABLES

These must exist in Render dashboard AND in your local `.env` file.
Never hardcode any value. Never commit secrets.

```
NOMBA_PARENT_ACCOUNT_ID=<from Nomba team credentials>
NOMBA_SUB_ACCOUNT_ID=<from Nomba team credentials>
NOMBA_TEST_CLIENT_ID=<from test credentials>
NOMBA_TEST_CLIENT_SECRET=<from test credentials>
NOMBA_LIVE_CLIENT_ID=<from live credentials>
NOMBA_LIVE_CLIENT_SECRET=<from live credentials>
NOMBA_ENV=test
NOMBA_AMOUNT_FORMAT=decimal
NOMBA_WEBHOOK_SECRET=NombaHackathon2026
```

`NOMBA_ENV=test` uses sandbox + test credentials.
`NOMBA_ENV=live` uses production API + live credentials.
`NOMBA_AMOUNT_FORMAT` must be set after Day 1 Thunder Client verification test — do not hardcode.

---

## IMPLEMENTATION ORDER — DO NOT SKIP STEPS

### STEP 1 — Run DB Migrations (Supabase SQL Editor)

Run these three files in order. After each one, run the verification query at the bottom of Migration 003 to confirm columns exist before proceeding.

**File to create:** `server/docs/sql/migrations/001_add_payment_frequency_to_properties.sql`
```sql
ALTER TABLE properties
  ADD COLUMN IF NOT EXISTS payment_frequency VARCHAR(50) NOT NULL DEFAULT 'MONTHLY'
  CHECK (payment_frequency IN ('MONTHLY', 'ANNUAL', 'SEMI_ANNUAL', 'QUARTERLY'));
```

**File to create:** `server/docs/sql/migrations/002_add_nomba_columns_to_agreements.sql`
```sql
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
    CHECK (reconciliation_status IN (
      'PENDING','FULL_PAYMENT','UNDERPAYMENT','OVERPAYMENT','MISDIRECTED','DUPLICATE'
    ));

-- Extend existing check_positive_amounts constraint
ALTER TABLE agreements DROP CONSTRAINT IF EXISTS check_positive_amounts;
ALTER TABLE agreements ADD CONSTRAINT check_positive_amounts
  CHECK (
    rent_amount > 0
    AND deposit_amount >= 0
    AND platform_fee >= 0
    AND (expected_payment_amount IS NULL OR expected_payment_amount > 0)
  );
```

**File to create:** `server/docs/sql/migrations/003_create_nomba_tables.sql`
```sql
CREATE TABLE IF NOT EXISTS virtual_account_transfers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agreement_id UUID REFERENCES agreements(id),
  nomba_request_id TEXT UNIQUE NOT NULL,
  nomba_transaction_id TEXT,
  account_ref TEXT NOT NULL,
  account_number TEXT,
  amount_received NUMERIC(12,2) NOT NULL,
  sender_name TEXT,
  sender_bank TEXT,
  currency TEXT DEFAULT 'NGN',
  event_type TEXT NOT NULL,
  transaction_type TEXT,
  raw_payload JSONB NOT NULL,
  signature_valid BOOLEAN NOT NULL,
  reconciliation_result TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_vat_agreement ON virtual_account_transfers(agreement_id);
CREATE INDEX IF NOT EXISTS idx_vat_request_id ON virtual_account_transfers(nomba_request_id);
CREATE INDEX IF NOT EXISTS idx_vat_account_ref ON virtual_account_transfers(account_ref);

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

-- Extend transactions CHECK constraint
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_transaction_type_check;
ALTER TABLE transactions ADD CONSTRAINT transactions_transaction_type_check
  CHECK (transaction_type IN (
    'rent_payment',
    'security_deposit',
    'guarantee_contribution',
    'nomba_collection'
  ));

-- Verification query — run this after migrations, confirm 6 rows returned
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'agreements'
AND column_name IN (
  'payment_frequency','expected_payment_amount','virtual_account_number',
  'nomba_account_ref','reconciliation_status','total_received_amount'
);
```

---

### STEP 2 — Create Helper Service

**File to create:** `server/app/services/nomba_helpers.py`

```python
# NuloAfrica Nomba helper functions
# Rule 17: ASCII only -- no Unicode in .py files

from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

GRACE_PERIODS = {
    "ANNUAL": 7,
    "SEMI_ANNUAL": 5,
    "QUARTERLY": 3,
    "MONTHLY": 1,
}

FREQUENCY_MULTIPLIERS = {
    "MONTHLY": 1,
    "QUARTERLY": 3,
    "SEMI_ANNUAL": 6,
    "ANNUAL": 12,
}

TOLERANCE_PCT = 0.02  # +/- 2% variance treated as full payment


def calculate_expected_amount(monthly_rent: float, frequency: str) -> float:
    """Return the lump-sum amount expected per payment cycle."""
    multiplier = FREQUENCY_MULTIPLIERS.get(frequency, 1)
    return round(monthly_rent * multiplier, 2)


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
    """True if today is still within grace period for this frequency."""
    grace_days = GRACE_PERIODS.get(frequency, 1)
    return date.today() <= due_date + timedelta(days=grace_days)


def classify_payment(received: float, expected: float) -> str:
    """
    Return reconciliation status.
    FULL_PAYMENT: within +/-2% tolerance
    UNDERPAYMENT: below tolerance
    OVERPAYMENT: above tolerance
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
```

---

### STEP 3 — Create NombaClient Service

**File to create:** `server/app/services/nomba_client.py`

```python
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
    - Auth endpoint: POST /auth/token/issue
    - Required headers: Authorization: Bearer {token}, accountId: {PARENT_ACCOUNT_ID}
    - Token lifetime: 60 min. Cache and refresh at 55-min mark.
    - Webhook signature: HMAC-SHA256 over colon-joined string of 9 fields (NOT raw body)
    - Webhook signature output: base64 encoded (NOT hex)
    - Webhook header: nomba-signature (lowercase)
    - nomba-timestamp header is required for signature reconstruction
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
        self.webhook_secret = os.environ["NOMBA_WEBHOOK_SECRET"]

        self._token = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh_token(self):
        """Fetch fresh token. Always called under self._lock."""
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
        data = body.get("data", body)
        self._token = data["access_token"]

        expires_at_str = data.get("expiresAt", "")
        try:
            dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            self._expires_at = dt.timestamp() - 300  # 5-min safety buffer
        except Exception:
            self._expires_at = time.time() + 3300  # 55-min fallback

        logger.info("Nomba token refreshed")

    async def _get_token(self) -> str:
        """Return cached token or refresh. Thread-safe via asyncio.Lock."""
        if self._token and time.time() < self._expires_at:
            return self._token
        async with self._lock:
            # Double-check after acquiring lock
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

    async def create_virtual_account(
        self,
        account_ref: str,
        account_name: str,
        expected_amount: float | None = None,
    ) -> dict:
        """
        Create a Nomba virtual NUBAN for a rental agreement.

        account_ref: Use agreement.id (UUID) as stable lookup key.
        account_name: Tenant display name (COALESCE full_name, email, fallback).
        expected_amount: Periodic rent in Naira.

        AMOUNT FORMAT: Controlled by NOMBA_AMOUNT_FORMAT env var.
        Set to 'kobo' or 'decimal' after Day 1 Thunder Client verification.
        Default: 'decimal' (supported by real webhook examples showing transactionAmount=120 for 120 Naira)
        """
        payload = {
            "accountRef": account_ref,
            "accountName": account_name,
            "currency": "NGN",
        }

        if expected_amount is not None:
            amount_format = os.environ.get("NOMBA_AMOUNT_FORMAT", "decimal")
            if amount_format == "kobo":
                payload["expectedAmount"] = int(round(expected_amount * 100))
            else:
                payload["expectedAmount"] = round(float(expected_amount), 2)

        headers = await self._headers()
        resp = requests.post(
            f"{self.base_url}/accounts/virtual",
            headers=headers,
            json=payload,
            timeout=15,
        )

        logger.info(
            "create_virtual_account | ref=%s | status=%s | env=%s",
            account_ref,
            resp.status_code,
            os.environ.get("NOMBA_ENV", "test"),
        )
        resp.raise_for_status()

        body = resp.json()
        if body.get("code") != "00":
            raise NombaAPIError(body.get("description", "Nomba error"))
        return body["data"]
        # Returns: accountRef, accountName, bankName, bankAccountNumber,
        # bankAccountName, currency, callbackUrl

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

        Verified test vector (hand-computed, confirmed match):
        secret=HkatexKDZg7CLWy96q5sfrVHSvtoz92B
        expected=Kt9095hQxfgmVbx6iz7G2tPhHdbdXgLlyY/mf35sptw=
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


# Module-level singleton -- import this in your routes
nomba_client = NombaClient()
```

---

### STEP 4 — Create Nomba Routes

**File to create:** `server/app/routes/nomba.py`

```python
# NuloAfrica Nomba payment routes
# Rule 17: ASCII only -- no Unicode characters
# Rule 7: specific routes before wildcard /{id}
# Rule 5: BackgroundTasks before Depends()
# Rule 6: run_in_executor for all Supabase calls
# Rule 18: supabase_admin only

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.database import supabase_admin
from app.dependencies import get_current_user
from app.services.nomba_client import NombaAPIError, nomba_client
from app.services.nomba_helpers import (
    calculate_expected_amount,
    calculate_next_due_date,
    classify_payment,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# ROUTE 1: Provision virtual account for a signed agreement
# POST /api/v1/agreements/{agreement_id}/provision-nomba
# ============================================================

@router.post("/agreements/{agreement_id}/provision-nomba")
async def provision_nomba(
    agreement_id: str,
    background_tasks: BackgroundTasks,     # Rule 5: before Depends
    current_user=Depends(get_current_user),
):
    # Fetch agreement -- Rule 6: run_in_executor
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .select("*")
            .eq("id", agreement_id)
            .single()
            .execute(),
    )
    agreement = result.data
    if not agreement:
        raise HTTPException(404, "Agreement not found")

    # Auth: only tenant or landlord on this agreement
    if current_user["id"] not in (
        agreement["tenant_id"], agreement["landlord_id"]
    ):
        raise HTTPException(403, "Not authorized")

    if agreement["status"] != "SIGNED":
        raise HTTPException(
            400, "Agreement must be in SIGNED status before provisioning"
        )

    # Idempotent: already provisioned
    if agreement.get("virtual_account_number"):
        return {
            "status": "already_provisioned",
            "virtual_account_number": agreement["virtual_account_number"],
            "virtual_account_name": agreement["virtual_account_name"],
            "expected_amount": float(agreement.get("expected_payment_amount") or 0),
            "frequency": agreement.get("payment_frequency"),
        }

    # Get tenant name -- Rule 1: .eq('id', ...) for shared PK tables
    tenant_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("tenant_profiles")
            .select("full_name, email")
            .eq("id", agreement["tenant_id"])
            .single()
            .execute(),
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
            account_ref=agreement_id,
            account_name=account_name,
            expected_amount=expected_amount,
        )
    except NombaAPIError as exc:
        logger.error(
            "Nomba provisioning failed | agreement=%s | error=%s",
            agreement_id, exc,
        )
        raise HTTPException(502, f"Nomba provisioning failed: {exc}")

    next_due = None
    if agreement.get("lease_start_date"):
        from datetime import date
        start = date.fromisoformat(str(agreement["lease_start_date"]))
        next_due = calculate_next_due_date(start, frequency)

    # Write to agreements table
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
            .execute(),
    )

    logger.info(
        "Virtual account provisioned | agreement=%s | nuban=%s | freq=%s | expected=%.2f",
        agreement_id, data["bankAccountNumber"], frequency, expected_amount,
    )

    background_tasks.add_task(
        _notify_tenant_account_ready, agreement_id, data
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


# ============================================================
# ROUTE 2: Nomba webhook receiver
# POST /api/v1/webhooks/nomba/transfer
# ============================================================

@router.post("/webhooks/nomba/transfer")
async def nomba_webhook(request: Request):
    """
    Receive Nomba payment webhooks.

    Implementation order (never change):
    1. Read headers first (nomba-signature + nomba-timestamp)
    2. Parse JSON body
    3. Verify signature -- return 401 if invalid, nothing written to DB
    4. Check idempotency (requestId) -- return 200 if duplicate
    5. Write transfer record to virtual_account_transfers
    6. Dispatch reconciliation if event_type=payment_success AND type=vact_transfer
    7. Always return 200 after step 5+ (reconciliation errors must not cause retries)

    Retry policy: Nomba retries non-2xx up to 5 times (2min, 5min, 11min, 24min, 53min).
    A 500 from a reconciliation bug will cause 5 duplicate attempts over ~95 minutes.
    """
    signature = request.headers.get("nomba-signature", "")
    nomba_timestamp = request.headers.get("nomba-timestamp", "")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    # Step 3: Verify signature
    if not signature or not nomba_client.verify_webhook_signature(
        payload, signature, nomba_timestamp
    ):
        logger.warning(
            "Invalid webhook signature | sig_prefix=%s | ts=%s",
            signature[:20] if signature else "MISSING",
            nomba_timestamp,
        )
        raise HTTPException(401, "Invalid signature")

    request_id = payload.get("requestId")
    event_type = payload.get("event_type")

    if not request_id:
        raise HTTPException(400, "Missing requestId")

    # Step 4: Idempotency
    existing = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .select("id")
            .eq("nomba_request_id", request_id)
            .execute(),
    )
    if existing.data:
        logger.info("Duplicate webhook ignored | requestId=%s", request_id)
        return {"status": "already_processed"}

    # Step 5: Extract payload fields
    data = payload.get("data", {})
    transaction = data.get("transaction", {})
    customer = data.get("customer", {})

    transaction_type = transaction.get("type", "")
    account_ref = transaction.get("aliasAccountReference", "")
    amount_received = transaction.get("transactionAmount", 0)

    # Step 6: Write transfer record
    transfer_insert = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .insert({
                "nomba_request_id": request_id,
                "nomba_transaction_id": transaction.get("transactionId"),
                "account_ref": account_ref,
                "account_number": transaction.get("aliasAccountNumber"),
                "amount_received": float(amount_received),
                "sender_name": customer.get("senderName"),
                "sender_bank": customer.get("bankName"),
                "currency": "NGN",
                "event_type": event_type,
                "transaction_type": transaction_type,
                "raw_payload": payload,
                "signature_valid": True,
            })
            .execute(),
    )
    transfer_row = (
        transfer_insert.data[0] if transfer_insert.data else {}
    )

    # Step 7: Reconcile only for virtual account funding
    if event_type == "payment_success" and transaction_type == "vact_transfer":
        try:
            await _reconcile_payment(
                transfer_row, account_ref, float(amount_received)
            )
        except Exception as exc:
            logger.error(
                "Reconciliation error | requestId=%s | error=%s",
                request_id, exc,
            )
            # Do NOT re-raise -- must return 200 to prevent retry storm

    return {"status": "ok"}


# ============================================================
# ROUTE 3: Payment status for an agreement
# GET /api/v1/agreements/{agreement_id}/payment-status
# NOTE: Rule 7 -- this must be registered BEFORE any wildcard /{id} route
# ============================================================

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
            .execute(),
    )
    agreement = result.data
    if not agreement:
        raise HTTPException(404, "Agreement not found")

    if current_user["id"] not in (
        agreement["tenant_id"], agreement["landlord_id"]
    ):
        raise HTTPException(403, "Not authorized")

    transfers = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .select(
                "id, amount_received, sender_name, sender_bank, "
                "reconciliation_result, created_at"
            )
            .eq("account_ref", agreement_id)
            .order("created_at", desc=True)
            .execute(),
    )

    return {
        "agreementId": agreement_id,
        "frequency": agreement["payment_frequency"],
        "expectedAmount": float(agreement.get("expected_payment_amount") or 0),
        "totalReceived": float(agreement.get("total_received_amount") or 0),
        "reconciliationStatus": agreement["reconciliation_status"],
        "nextDueDate": agreement["next_payment_due_date"],
        "virtualAccountNumber": agreement["virtual_account_number"],
        "virtualAccountName": agreement["virtual_account_name"],
        "transferHistory": transfers.data or [],
    }
    # Rule 22: keys already camelCase for frontend consumption


# ============================================================
# ROUTE 4: Health check -- judges hit this to verify integration
# GET /api/v1/health/nomba
# ============================================================

@router.get("/health/nomba")
async def nomba_health():
    try:
        token = await nomba_client._get_token()
        auth_ok = bool(token)
    except Exception as exc:
        return {
            "status": "error",
            "nombaAuth": False,
            "error": str(exc),
        }
    return {
        "status": "ok",
        "nombaAuth": auth_ok,
        "webhookUrl": "https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer",
        "environment": "live" if "api.nomba.com" in nomba_client.base_url else "test",
    }


# ============================================================
# Internal: Reconciliation engine
# ============================================================

async def _reconcile_payment(
    transfer_row: dict,
    account_ref: str,
    amount_received: float,
):
    """
    Match inbound transfer to agreement. Update status and totals.
    account_ref = aliasAccountReference from webhook = agreement.id
    """
    if not account_ref:
        logger.warning("No aliasAccountReference in webhook -- cannot reconcile")
        return

    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .select(
                "id, tenant_id, landlord_id, rent_amount, "
                "expected_payment_amount, payment_frequency, "
                "total_received_amount, reconciliation_status"
            )
            .eq("id", account_ref)
            .execute(),
    )

    if not result.data:
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin
                .table("virtual_account_transfers")
                .update({"reconciliation_result": "MISDIRECTED"})
                .eq("id", transfer_row.get("id"))
                .execute(),
        )
        logger.warning("MISDIRECTED payment | accountRef=%s", account_ref)
        return

    agreement = result.data[0]
    expected = float(agreement.get("expected_payment_amount") or 0)
    prev_total = float(agreement.get("total_received_amount") or 0)
    new_total = round(prev_total + amount_received, 2)
    prev_status = agreement["reconciliation_status"]
    new_status = classify_payment(amount_received, expected)

    variance_pct = (
        round(((amount_received - expected) / expected) * 100, 2)
        if expected > 0 else 0.0
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
            .execute(),
    )

    # Update transfer record
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("virtual_account_transfers")
            .update({
                "agreement_id": agreement["id"],
                "reconciliation_result": new_status,
            })
            .eq("id", transfer_row.get("id"))
            .execute(),
    )

    # Reconciliation audit log
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
                "received_amount": amount_received,
                "variance_pct": variance_pct,
                "notes": f"frequency={agreement['payment_frequency']}",
            })
            .execute(),
    )

    # transactions table entry
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("transactions")
            .insert({
                "agreement_id": agreement["id"],
                "tenant_id": agreement["tenant_id"],
                "landlord_id": agreement["landlord_id"],
                "amount": amount_received,
                "transaction_type": "nomba_collection",
                "status": "completed",
                "payment_gateway": "nomba",
                "currency": "NGN",
                "notes": (
                    f"frequency={agreement['payment_frequency']} "
                    f"status={new_status}"
                ),
            })
            .execute(),
    )

    logger.info(
        "Reconciled | agreement=%s | received=%.2f | expected=%.2f | status=%s",
        agreement["id"], amount_received, expected, new_status,
    )


async def _notify_tenant_account_ready(agreement_id: str, data: dict):
    """Background task: notify tenant their virtual account is ready."""
    logger.info(
        "Notify tenant | agreement=%s | nuban=%s",
        agreement_id, data.get("bankAccountNumber"),
    )
    # Plug into existing notification_service here following existing patterns
```

---

### STEP 5 — Register Router in main.py

Open `server/app/main.py`. Find where other routers are registered (look for existing `app.include_router` calls). Add the Nomba router AFTER all existing routers but BEFORE any catch-all handlers:

```python
from app.routes.nomba import router as nomba_router

# Add this block with the other router registrations:
app.include_router(
    nomba_router,
    prefix="/api/v1",
    tags=["nomba"],
)
```

**Route conflict check (Rule 7):**
After adding this, verify these nomba routes do not conflict with existing wildcard routes:
- `POST /api/v1/agreements/{agreement_id}/provision-nomba` — check `agreements.py` has no `/{id}/provision-nomba`
- `GET /api/v1/agreements/{agreement_id}/payment-status` — check `agreements.py` has no `/{id}/payment-status`
- If `agreements.py` has a catch-all `GET /{id}` route, the nomba router must be registered first

---

### STEP 6 — Local Webhook Simulation Script

**File to create:** `server/scripts/simulate_nomba_webhook.py`

Run this locally to generate valid test payloads for Thunder Client testing.

```python
"""
Local webhook simulation script.
Run: python simulate_nomba_webhook.py
Copy the output signature and payload into Thunder Client.
"""
import base64
import hashlib
import hmac
import json
import sys

SECRET = "NombaHackathon2026"
TIMESTAMP = "2026-07-01T10:00:00Z"

# Replace with a real agreement.id from your Supabase agreements table
AGREEMENT_ID = sys.argv[1] if len(sys.argv) > 1 else "YOUR-AGREEMENT-UUID-HERE"
SUB_ACCOUNT_USER_ID = "YOUR-SUB-ACCOUNT-ID-HERE"

SCENARIOS = {
    "full_payment": 500000.0,
    "underpayment": 100000.0,
    "overpayment": 800000.0,
    "misdirected": 500000.0,
}

scenario = sys.argv[2] if len(sys.argv) > 2 else "full_payment"
amount = SCENARIOS.get(scenario, 500000.0)
request_id = f"test-req-{scenario}-001"

account_ref = AGREEMENT_ID
if scenario == "misdirected":
    account_ref = "00000000-0000-0000-0000-000000000000"

payload = {
    "event_type": "payment_success",
    "requestId": request_id,
    "data": {
        "merchant": {
            "walletId": "test-wallet-001",
            "walletBalance": 50000,
            "userId": SUB_ACCOUNT_USER_ID,
        },
        "terminal": {},
        "transaction": {
            "aliasAccountNumber": "9391076543",
            "fee": 5,
            "sessionId": f"test-session-{scenario}",
            "type": "vact_transfer",
            "transactionId": f"test-txn-{scenario}-001",
            "aliasAccountName": "NuloAfrica/Test Tenant",
            "responseCode": "",
            "originatingFrom": "api",
            "transactionAmount": amount,
            "narration": f"Rent payment scenario={scenario}",
            "time": TIMESTAMP,
            "aliasAccountReference": account_ref,
            "aliasAccountType": "VIRTUAL",
        },
        "customer": {
            "bankCode": "058",
            "senderName": "TEST TENANT",
            "bankName": "GTBank",
            "accountNumber": "0123456789",
        },
    },
}

t = payload["data"]["transaction"]
m = payload["data"]["merchant"]
hashing_payload = (
    f"{payload['event_type']}:{payload['requestId']}:{m['userId']}:{m['walletId']}:"
    f"{t['transactionId']}:{t['type']}:{t['time']}:{t['responseCode']}:{TIMESTAMP}"
)

digest = hmac.new(SECRET.encode(), hashing_payload.encode(), hashlib.sha256).digest()
signature = base64.b64encode(digest).decode()

print("=" * 60)
print(f"Scenario: {scenario}")
print(f"Agreement ID: {AGREEMENT_ID}")
print(f"Amount: {amount}")
print("=" * 60)
print(f"nomba-signature: {signature}")
print(f"nomba-timestamp: {TIMESTAMP}")
print(f"Content-Type: application/json")
print("=" * 60)
print("Body:")
print(json.dumps(payload, indent=2))
```

Usage:
```bash
python server/scripts/simulate_nomba_webhook.py <agreement_uuid> full_payment
python server/scripts/simulate_nomba_webhook.py <agreement_uuid> underpayment
python server/scripts/simulate_nomba_webhook.py <agreement_uuid> overpayment
python server/scripts/simulate_nomba_webhook.py <agreement_uuid> misdirected
```

---

## THUNDER CLIENT TEST SEQUENCE

Run these in order. Do not proceed past a failing test.

### Day 1

| # | Test | URL | Expected |
|---|---|---|---|
| T1.0 | Auth: get token | `POST https://sandbox.nomba.com/v1/auth/token/issue` | 200, `data.access_token` present |
| T1.1 | Amount format | `POST https://sandbox.nomba.com/v1/accounts/virtual` with `expectedAmount: 10000.00` | 200, `code: "00"` |
| T1.2 | Amount format | Same with `expectedAmount: 1000000` | Compare which reads back correctly in GET |
| T1.3 | Provision: happy path | `POST /api/v1/agreements/{signed_id}/provision-nomba` | 200, `status: provisioned`, NUBAN present |
| T1.4 | Provision: idempotent | Same URL again | 200, `status: already_provisioned` |
| T1.5 | Provision: wrong status | Agreement where `status != SIGNED` | 400 |
| T1.6 | Provision: wrong user | Different user's JWT | 403 |

### Day 2

| # | Test | How | Expected |
|---|---|---|---|
| T2.1 | Webhook: valid full payment | Run simulation script, paste to Thunder Client | 200 `ok`, DB updated |
| T2.2 | Webhook: duplicate replay | Exact same request again | 200 `already_processed`, no DB change |
| T2.3 | Webhook: bad signature | Change one char in signature | 401, no DB write |
| T2.4 | Webhook: underpayment | Run script with `underpayment` | 200, `reconciliation_status=UNDERPAYMENT` |
| T2.5 | Webhook: overpayment | Run script with `overpayment` | 200, `reconciliation_status=OVERPAYMENT` |
| T2.6 | Webhook: misdirected | Run script with `misdirected` | 200, `reconciliation_result=MISDIRECTED` in transfers |
| T2.7 | Payment status | `GET /api/v1/agreements/{id}/payment-status` | 200, full status object |
| T2.8 | Health check | `GET /api/v1/health/nomba` | 200, `nombaAuth: true` |

### Day 3 (against live Render)

| # | Test | Expected |
|---|---|---|
| T3.1 | Health check on Render | `GET https://api.nuloafrica.com/api/v1/health/nomba` returns 200 |
| T3.2 | Repeat T2.1 against Render | Valid webhook accepted, DB updated |
| T3.3 | Repeat T2.3 against Render | Bad signature returns 401 |

---

## FILES TO CREATE (complete list)

```
server/app/services/nomba_helpers.py           NEW
server/app/services/nomba_client.py            NEW
server/app/routes/nomba.py                     NEW
server/scripts/simulate_nomba_webhook.py       NEW
server/docs/sql/migrations/001_add_payment_frequency_to_properties.sql    NEW
server/docs/sql/migrations/002_add_nomba_columns_to_agreements.sql        NEW
server/docs/sql/migrations/003_create_nomba_tables.sql                    NEW
docs/SECURITY.md                               NEW
```

## FILES TO MODIFY (only these two)

```
server/app/main.py       Add nomba_router registration
server/.env.example      Add all NOMBA_ env var keys (no values)
```

## FILES TO NEVER TOUCH

```
server/app/routes/payments.py     Paystack -- leave alone
server/app/routes/agreements.py   Existing agreement CRUD -- leave alone
Any existing migration files       Do not modify
```

---

## SECURITY.md CONTENT

Create `docs/SECURITY.md` with this content:

```markdown
# NuloAfrica Nomba Integration Security

## Webhook Signature Verification
- Algorithm: HMAC-SHA256 over a colon-joined string of 9 payload fields
- Output: base64 encoded (NOT hex)
- Header: nomba-signature (lowercase)
- nomba-timestamp header required for signature reconstruction
- Comparison: hmac.compare_digest() always -- never == operator (timing attack prevention)
- Invalid signature: returns 401, nothing written to database

## Status Code Policy
- 401: invalid signature (not Nomba traffic, retry protection not needed)
- 200: valid signature + new event (processed successfully)
- 200: valid signature + duplicate requestId (already processed, idempotent)
- Reconciliation errors return 200 to prevent retry storms (error logged async)
- This is intentionally different from Paystack where all responses are 200

## Idempotency
- Inbound webhooks: requestId stored with UNIQUE constraint in virtual_account_transfers
- Outbound requests to Nomba: X-Idempotent-key header used on transfer calls
- These are two separate mechanisms -- do not conflate

## Secrets Management
- All credentials in environment variables via Render dashboard
- NOMBA_ENV flag controls test vs live credential selection
- NombaHackathon2026 is the hackathon organiser's signing key (not the dashboard key)
- Credentials never committed to repository

## Token Caching
- Access tokens cached in memory for up to 55 minutes
- asyncio.Lock prevents concurrent refresh race condition
- Token refreshed automatically when expired
```

---

## DONE SIGNAL

You are done when:
1. All 3 migrations ran and the verification query returns 6 rows
2. All 4 routes respond correctly in Thunder Client (T1.3 through T2.8)
3. Health check passes on Render: `https://api.nuloafrica.com/api/v1/health/nomba`
4. Webhook URL submitted to hackathon form: `https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer`
5. `docs/SECURITY.md` exists and is committed
ENDDOC

echo "Done. Lines: $(wc -l < /home/claude/COPILOT_PROMPT_NOMBA_INTEGRATION.md)"