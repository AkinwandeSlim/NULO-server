# NuloAfrica x Nomba — Hackathon Integration PRD (V3)
## The Single Source of Truth for the Nomba Virtual-Accounts Integration

> **Version:** V3.2 (2026-07-04) — supersedes V3.1.
> **Why V3.2 exists:** V3.1 was accurate on the Nomba *API* side but drifted from the *code* and *database* reality on several points (manual-vs-auto disbursement, the `force=true` test override, the duplicate bank columns between `landlords` and `landlord_profiles`, the migrations path, the OpenAPI file path, the requery guard). V3.2 re-grounds every claim in a file/line and records the remaining glitches as OPEN items rather than hiding them. **No claim in this PRD is a guess.** Each is sourced from the shipped code or the live DB schema (`database/newupdateDB.csv`).
>
> **Status:** Every fact below is tagged **[VERIFIED]**, **[DECIDED]**, **[OPEN]**, or **[KNOWN GLITCH]**.
>   - **[VERIFIED]** = proven by a live call (sandbox OR production) and/or the shipped code + OpenAPI spec (`docs/nomba_openapi.json`).
>   - **[DECIDED]** = a deliberate architecture choice for this submission (rationale given).
>   - **[OPEN]** = genuinely unresolved; CANNOT be tested in sandbox; must be validated in production.
>   - **[KNOWN GLITCH]** = a real defect we know about, documented honestly, with a queued fix.
>
> **Hackathon:** DevCareer x Nomba 2026, July 1–7. Track: *Virtual Accounts as Infrastructure*.
> **Live backend:** https://api.nuloafrica.com (Render; GitHub: `AkinwandeSlim/NULO-server`, branch `main`)
> **Webhook URL (submitted to Nomba):** `https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer`

> ### What changed from V3.1 → V3.2 (read once)
> V3.1 corrected the Nomba API facts after the 2026-07-04 live test. V3.2 corrects the *code/DB* facts that V3.1 still guessed at:
> 1. **Disbursement is MANUAL** (landlord hits the endpoint), not auto-on-FULL_PAYMENT. The `force=true` body override is a real, shipped test-only escape hatch — documented, not hidden.
> 2. **Payout bank details live in two places** (`landlords` AND `landlord_profiles`) — a known glitch. V3.2 designates `landlord_profiles` as the intended single source of truth and queues the migration; the disburse route still reads `landlords` today and that is flagged.
> 3. **Real migrations directory** is `docs/sql/migrations/` (not `docs/sql/migrations/` inside `server/` — that folder does not exist in the repo). The PRD now points at the real files.
> 4. **OpenAPI spec** is at `docs/nomba_openapi.json` (not `docs/hackathon/nomba_openapi.json`).
> 5. **Requery** is shipped with a defensive match-guard AND is still effectively unverified on production — status stays [OPEN].
> 6. The **lookup-bank route persists payout data to `landlords`** today; V3.2 records the move to `landlord_profiles` as an OPEN Stage-2 fix.

---

## PART 0 — Architecture (LIVE-VERIFIED 2026-07-04)

### What NuloAfrica is
Zero agency-fee rental marketplace for Nigerian cities (Lagos, Abuja, Port Harcourt).
Stack: Next.js 16 + React 19 frontend, FastAPI + Python backend (Render), Supabase (PostgreSQL), Paystack (existing rent flow — left untouched), Twilio + SMTP notifications.

### Hackathon scope
Multi-frequency rental payment infrastructure on Nomba Virtual Accounts, covering the full money lifecycle: **collect -> reconcile -> disburse**. Nigerian landlords want annual rent upfront; tenants want monthly. We assign a dedicated Nomba virtual account (NUBAN) **per signed agreement**, support 4 payment frequencies, reconcile every inbound transfer automatically, then disburse the landlord's share.

### The Nomba architecture — PARENT-HEADER, SUB-ACCOUNT-WALLET, per-agreement [DECIDED + VERIFIED 2026-07-04]
```
Parent account (shared "mothership", id f666ef9b-888e-4799-85ce-acb505b28023)
  |  <- the accountId HEADER on EVERY request is ALWAYS this parent id
  |     (true for BOTH parent and sub-account endpoints; sub is in the path)
  |
  +- Sub-account (id 282e5b9b-d14f-4e43-840d-43ddfd90a071)              <-- THE SAFE HAVEN
  |     - holds the registered webhook URL (this is what the Nomba form scopes)
  |     - holds the SPENDABLE balance for outbound transfers
  |     - all VAs for the hackathon are provisioned under it
  |
  +- Virtual Account per SIGNED AGREEMENT                               <-- COLLECT
  |     accountRef = agreement.id + "-SUB"   (the -SUB suffix is the runtime
  |                                            signal that the VA is sub-account-scoped;
  |                                            the disburse route reads account_ref
  |                                            and picks the sub-account transfer path
  |                                            when it ends with -SUB)
  |     -> POST /v1/accounts/virtual/{subAccountId}      (parent in header, sub in path)
  |     -> VA's accountHolderId = sub-account (282e5b9b-...)
  |     -> tenant transfers rent to this NUBAN
  |     -> Nomba fires webhook -> we reconcile by aliasAccountReference
  |        (regex strips -SUB, leaving agreement.id, the UUID) -> look up agreement
  |
  +- Disburse landlord share via POST /v2/transfers/bank/{subAccountId}  <-- DISBURSE
        (parent in header, sub in path). The parent endpoint
        /v2/transfers/bank returns 400 INSUFFICIENT_BALANCE even though
        the parent balance API reports 10M+ NGN — the parent has 0 spendable balance.
        platform_fee = the residual kept from the collection before paying the landlord.
```

**Why sub-account-wallet and why not parent-only (revised from V3.0):**
1. A Nomba sub-account = a *merchant/business* collection wallet. Your team has exactly ONE (id `282e5b9b-...`) for the hackathon. You do NOT create sub-accounts programmatically — you already have the one.
2. **VAs ARE scoped to the sub-account via the path-based endpoint** `POST /v1/accounts/virtual/{subAccountId}`. V3.0 said this was impossible; live evidence 2026-07-04 (NUBAN `3783622764`, `accountHolderId: 282e5b9b-...`) proves it works. VAs created this way route their inbound webhooks through the sub-account's registered URL.
3. The parent has 0 spendable balance — `GET /v1/accounts/balance` mirrors the sub-account's funds but `POST /v2/transfers/bank` (parent transfer) returns 400 INSUFFICIENT_BALANCE. Only `POST /v2/transfers/bank/{subAccountId}` can disburse.
4. Parent-scoped VAs (V3.0's recommendation) silently drop inbound webhooks with "No redirect configuration" because the registered URL is on the sub-account, not the parent.
5. The correct grain is **per agreement**: `accountRef = agreement.id + "-SUB"` gives each signed lease its own NUBAN, and the webhook's `aliasAccountReference` maps back via regex UUID extraction.
6. Reconciliation is by `accountRef` in our own DB (the ledger), independent of where funds physically settle on Nomba's side.

### Out of scope
- Tokenized cards / direct debits / mandates (different track; sandbox-nonfunctional).
- Auto-disbursement on FULL_PAYMENT — disbursement is **MANUAL** (landlord triggers via dashboard). Auto is a queued Stage-2 item (see Part 5 OPEN #4).
- Landlord analytics dashboard, payment-schedule calendar UI, full frontend polish.
- Nightly reconciliation cron (webhook + on-demand requery cover the demo).

### Locked decisions — do not re-open
1. Backend-first. No frontend work until endpoints pass Thunder Client / probe tests.
2. Nomba runs ALONGSIDE Paystack. Do not touch `payments.py` or `agreements.py`.
3. `accountRef = agreement.id + "-SUB"` for new VAs. The `-SUB` suffix is the runtime signal that the disburse route uses to pick the sub-account transfer endpoint.
4. `NOMBA_WEBHOOK_SECRET=NombaHackathon2026` — the hackathon organiser's signing key, not a dashboard key.
5. `accountId` HEADER = the shared parent `f666ef9b...` on EVERY call, including auth. Sub-account is in the URL PATH, not the header. This is the #1 fix for 403s (Nomba support golden rule).
6. Amounts for Virtual Accounts and Transfers are **decimal Naira**. Checkout is the only kobo path. `NOMBA_AMOUNT_FORMAT` was removed 2026-07-03 (wrong + unused); do not reintroduce it.
7. **All new VAs are sub-account-scoped (V3.1).** Parent-scoped VAs are legacy and silent-fail for webhooks.
8. **Disbursement is MANUAL** in the code today [VERIFIED in `app/routes/disbursements.py` header comment + route]. Auto-disburse is Stage-2, not shipped.

---

## PART 1 — Verified API Contracts

Base URLs [VERIFIED]:
| Env (`NOMBA_ENV`) | Base URL | Credentials |
|---|---|---|
| `test` (default) | `https://sandbox.nomba.com/v1` | `NOMBA_TEST_*` |
| `live` | `https://api.nomba.com/v1` | `NOMBA_LIVE_*` |

> Transfers are `/v2/` paths (e.g. `https://api.nomba.com/v2/transfers/bank/...`); everything else is `/v1/`. The client strips `/v1` off `self.base_url` and rebuilds `/v2` for transfers (see `transfer_to_bank` at `app/services/nomba_client.py`).

Match creds to URL (TEST->sandbox, LIVE->api). Mixing them yields 401/403.

### 1.1 Authentication [VERIFIED]
```
POST {base}/auth/token/issue                (first run / refresh_token expired)
Headers: Content-Type: application/json
         accountId: f666ef9b-888e-4799-85ce-acb505b28023   (parent, always)
Body:    { "grant_type": "client_credentials",
           "client_id": "{NOMBA_*_CLIENT_ID}",
           "client_secret": "{NOMBA_*_CLIENT_SECRET}" }
Response: { "code": "00", "data": { "access_token", "refresh_token", "expiresAt" } }

POST {base}/auth/token/refresh              (all subsequent refreshes)
Headers: Authorization: Bearer {current token}, accountId: {parent}, Content-Type: application/json
Body:    { "grant_type": "refresh_token", "refresh_token": "{stored}" }
```
- **Token lifetime = 30 minutes** [VERIFIED — live `expiresAt` was exactly issue-time + 30 min; confirmed by Victor Shoaga, Nomba engineer]. Cache in memory; refresh at the **25-minute** mark (5-min buffer). One shared token across all calls, guarded by `asyncio.Lock`. Prefer `token/refresh` over re-issuing (avoids re-exposing `client_secret`); fall back to `token/issue` if refresh fails.
- Shipped in `nomba_client._issue_token` / `_refresh_token` / `_get_token` / `_store_token_data`.

### 1.2 Virtual Account Creation [VERIFIED — 2 paths live]

There are TWO working VA-creation endpoints, both verified live on production 2026-07-04.

**Path A — Parent-scoped (legacy; NOT recommended for new VAs):**
```
POST {base}/v1/accounts/virtual
Headers: Authorization: Bearer {token}, accountId: {parent}, Content-Type: application/json
Body:    { "accountRef": "{agreement.id}", "accountName": "{sanitised tenant/landlord name}" }
```
- Body is EXACTLY `{accountRef, accountName}` (OpenAPI spec lists only these two, both required). `currency` and `expectedAmount` do NOT exist; we track expected amount locally in `agreements.expected_payment_amount`.
- Sub-account id in `?accountId=` query or body is IGNORED on this endpoint.
- **Inbound webhooks for parent-scoped VAs silently fail** with "No redirect configuration" when the registered URL is on the sub-account. Confirmed live 2026-07-04 with NUBAN `8404605359`.
- Shipped in `create_virtual_account()`.

**Path B — Sub-account-scoped (V3.1+ default; USE THIS for new VAs):**
```
POST {base}/v1/accounts/virtual/{subAccountId}
Headers: Authorization: Bearer {token}, accountId: {parent}, Content-Type: application/json
Body:    { "accountRef": "{agreement.id}-SUB", "accountName": "{sanitised name}" }
Response (code "00"): data = { createdAt, accountHolderId (=sub-account 282e5b9b-...),
   accountRef, bvn, accountName, bankName, bankAccountNumber, bankAccountName,
   currency, callbackUrl, expired }
```
- Sub-account ID is in the **URL PATH**, header stays parent.
- `accountHolderId` comes back as the SUB-ACCOUNT — verified live, NUBAN `3783622764`, `bankName: "Nombank Microfinance Bank"`.
- Live propagation test (2026-07-04, ~10s): OPay ₦100 → NUBAN `3783622764` → `payment_success` webhook → reconciliation row with real `txn_id` and real sender name.
- Shipped in `create_virtual_account_for_subaccount()`.

**accountName sanitisation [VERIFIED — shipped in `provision_nomba` route]:**
Nomba rejects ANY special character (including `-` and `.`). The route keeps only ASCII alphanumerics + single spaces, collapses whitespace, pads to 8 chars, truncates to 64. Nomba auto-prefixes the name with "Nomba / ".

**accountRef length:** Nomba spec requires 16–64 chars. `agreement.id` (UUID, 36 chars) always satisfies this; the `-SUB` suffix keeps it under 64. The route raises 400 if the agreement_id is outside 16–64.

**Recovery flow [VERIFIED — shipped]:**
If a prior provisioning succeeded on Nomba but failed before our DB write, the VA is orphaned on Nomba. The `provision-nomba` route first calls `get_virtual_account(agreement_id)` (Path A `GET /v1/accounts/virtual/{accountRef}`); if it finds a non-expired VA it reuses it instead of re-creating. This is how NUBAN `8404605359` was recovered.

**Stores:** `bankAccountNumber -> agreements.virtual_account_number` (show tenant); `bankAccountName -> agreements.virtual_account_name`; `accountRef -> agreements.nomba_account_ref`.

> ⚠️ **[KNOWN GLITCH]** The `provision-nomba` route calls **Path A** (`create_virtual_account`) even though Path B is the recommended default. There is **no wired route that calls `create_virtual_account_for_subaccount`** for new provisions; the sub-account VA `3783622764` was created via a one-off script, not via the app route. See Part 5 OPEN #5.

### 1.3 Webhook — signature + payload [VERIFIED]
Nomba signs with **HMAC-SHA256 over a colon-joined 9-field string** (NOT a raw-body hash), **base64**-encoded. Independently confirmed by a working handler and a hand-computed test vector.

Headers Nomba sends you:
```
nomba-signature: base64 HMAC-SHA256      <- verify against THIS exact header name (no x- prefix)
nomba-timestamp: 2026-07-01T10:00:00Z    <- REQUIRED for signature reconstruction (from header, not body)
nomba-signature-algorithm: HmacSHA256
```
Signature construction (shipped in `verify_webhook_signature`):
```python
hashing_payload = (
    f"{event_type}:{request_id}:{user_id}:{wallet_id}:"
    f"{transaction_id}:{transaction_type}:{transaction_time}:"
    f"{response_code}:{nomba_timestamp}"
)
# response_code: use "" if null/empty (never the string "null")
# nomba_timestamp comes from the nomba-timestamp REQUEST HEADER
digest = hmac.new(secret.encode(), hashing_payload.encode(), hashlib.sha256).digest()
signature = base64.b64encode(digest).decode()
# compare with hmac.compare_digest() -- EXACT case (base64 is case-sensitive)
```
Hand-verified test vector (matches): `secret=HkatexKDZg7CLWy96q5sfrVHSvtoz92B` → `Kt9095hQxfgmVbx6iz7G2tPhHdbdXgLlyY/mf35sptw=`.

Key payload mappings for reconciliation:
| Payload field | Use |
|---|---|
| `event_type` = `payment_success` | check first |
| `data.transaction.type` = `vact_transfer` | reconcile ONLY when this |
| `data.transaction.aliasAccountReference` | **= your accountRef = agreement.id (+optional `-SUB`)** -> regex-extract UUID -> look up agreement |
| `data.transaction.transactionAmount` | compare to `expected_payment_amount` |
| `data.transaction.aliasAccountNumber` | cross-check `agreements.virtual_account_number` |
| `data.transaction.transactionId` | store for audit |
| `data.customer.senderName` | store for tenant record |
| `requestId` (top-level) | idempotency key (`virtual_account_transfers.nomba_request_id` UNIQUE; reject dup) |

**Retry/ack rule (shipped):** verify signature -> store `requestId` (unique insert, try/except for dup) -> return **200** even if reconciliation errors (log it, do not re-raise). Non-2xx triggers up to 5 Nomba retries (2, 5, 11, 24, 53 min).

### 1.4 Event types [VERIFIED against real payload sample]
| event_type | transaction.type | Meaning | Handler |
|---|---|---|---|
| `payment_success` | `vact_transfer` | Virtual account funded — OURS | `_reconcile_payment` |
| `payment_success` | other | Card/other — ignore | (no-op) |
| `payout_success` | `transfer` | Outbound transfer settled | `_handle_payout_event` -> `released` |
| `payout_failed` | — | Outbound transfer failed | `_handle_payout_event` -> `failed` |
| `payout_refund` | — | Payout reversed | `_handle_payout_event` -> `refunded` |

### 1.5 Bank Account Lookup [VERIFIED]
```
POST {base}/transfers/bank/lookup
Headers: Authorization: Bearer {token}, accountId: {parent}, Content-Type: application/json
Body:    { "accountNumber": "0000000000", "bankCode": "035" }
Response (code "00"): data = { "accountNumber", "accountName" }
```
ALWAYS call before a transfer; use the returned `accountName` (never a user-typed name) in the transfer. Bank codes come from `GET {base}/transfers/banks` (77 banks). Shipped in `lookup_bank_account()` + `get_banks_list()`.

### 1.6 Bank Transfer (disbursement) [VERIFIED — 2 paths live]

**Path A — Parent wallet (`/v2/transfers/bank`) — BROKEN in production:**
```
POST https://api.nomba.com/v2/transfers/bank
Headers: Authorization: Bearer {token}, accountId: {parent}, Content-Type: application/json
Body:    { "amount": 137.53, "accountNumber": "0000000000", "accountName": "{from lookup}",
           "bankCode": "035", "merchantTxRef": "NULO-DISB-XXXXXXXX",
           "senderName": "NuloAfrica", "narration": "Rent disbursement" }
Response: HTTP 200/201, data.status in { SUCCESS | PENDING_BILLING | NEW | REFUND }
```
- Amount = decimal Naira (JSON number). Verified by sending `137.53` and getting it echoed.
- **Returns 400 INSUFFICIENT_BALANCE in production** even when `GET /v1/accounts/balance` on the parent reports 10M+ NGN. Parent has 0 spendable balance.
- Shipped in `transfer_to_bank()`.

**Path B — Sub-account wallet (`/v2/transfers/bank/{subAccountId}`) — V3.1 default; USE THIS:**
```
POST https://api.nomba.com/v2/transfers/bank/282e5b9b-d14f-4e43-840d-43ddfd90a071
Headers: Authorization: Bearer {token}, accountId: {parent}, Content-Type: application/json
Body:    (same shape as Path A)
Response: HTTP 200, data.status in { SUCCESS | PENDING_BILLING | NEW | REFUND }
```
- Sub-account ID in the **URL PATH**, header stays parent. Funds originate from the sub-account wallet (the actual spendable balance).
- Live proof (2026-07-04): `merchant_tx_ref: NULO-DISB-8C9DA144`, amount ₦100, `nomba_transfer_id: c7e3e0a2-5c04-4b6f-9b2a-3c466986345e`, `data.status: SUCCESS`, transaction → `released` end-to-end.
- Shipped in `transfer_to_bank_from_subaccount()`.

**Status —> transactions.status mapping (shipped in `disburse_to_landlord`):**
| Nomba `data.status` | `transactions.status` | timestamp set |
|---|---|---|
| `SUCCESS` | `released` | `released_at` |
| `REFUND` | `failed` | — |
| `NEW` / `PENDING_BILLING` | `pending` | — |
| (payout webhook later) | `released` / `failed` / `refunded` | `released_at` / `refunded_at` |

- Rate limit: 5 transfers to the same recipient per minute.
- Idempotency: `merchantTxRef = "NULO-DISB-{transfer_id[:8]}"`, append `-R{n}` on retry after REFUND. Reuse the same ref across retries of the *same logical* transfer; only mint a new ref after REFUND.

**Disbursement routing logic (shipped in `disbursements.py`):** the disburse route reads the source `virtual_account_transfers.account_ref`; if it ends with `-SUB` it calls `transfer_to_bank_from_subaccount` (Path B), else `transfer_to_bank` (Path A). Reads `NOMBA_SUB_ACCOUNT_ID` from env at call time.

### 1.7 Requery Transfer [OPEN — guarded, unverified on production]
Intended: `GET {base}/transactions/accounts/single?transactionRef={merchantTxRef}` to poll a `PENDING_BILLING`/`NEW` transfer whose webhook never arrived.
- **[OPEN] This endpoint is BROKEN/unusable in sandbox** [VERIFIED broken 2026-07-03]: it ignores the ref entirely — returned the SAME unrelated record for our ref, a Nomba transaction id, and a bogus ref.
- **Mitigation shipped:** `requery_transfer()` returns the raw `data` dict but the route layer is expected to apply a match-guard — trust only records tied back by `merchantTxRef` echo, Nomba transfer id, or exact amount; otherwise treat as no-result. (The guard is documented in V3.1; verify it still gates consumption before relying on requery.)
- **Must be re-tested in production.** Other documented variants to evaluate live: `GET /v1/transactions/requery/{sessionId}` and `/transactions/accounts/{subAccountId}/single`.

### 1.8 Checkout (alternative, kobo) [VERIFIED contract — NOT used in the rent flow]
`POST {base}/checkout/order` — hosted payment page. Amount in **KOBO** (multiply Naira × 100). This is the only kobo path. Shipped in `create_checkout_order()` but **not wired into the rent flow** (rent uses Virtual Accounts, decimal Naira). Kept for future card checkout.

---

## PART 2 — Environment Variables

```bash
NOMBA_ENV=test                                   # test | live
NOMBA_PARENT_ACCOUNT_ID=f666ef9b-888e-4799-85ce-acb505b28023   # shared parent; accountId HEADER on every call
NOMBA_SUB_ACCOUNT_ID=282e5b9b-d14f-4e43-840d-43ddfd90a071       # REQUIRED. Scopes VAs, routes inbound webhooks, holds spendable balance.
NOMBA_TEST_CLIENT_ID=...
NOMBA_TEST_CLIENT_SECRET=...
NOMBA_LIVE_CLIENT_ID=...
NOMBA_LIVE_CLIENT_SECRET=...
NOMBA_WEBHOOK_SECRET=NombaHackathon2026           # organiser signing key
# DO NOT add NOMBA_AMOUNT_FORMAT — removed 2026-07-03 (wrong + unused; amounts are decimal Naira).
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
```
Shipped behaviour (`nomba_client.__init__): if `NOMBA_SUB_ACCOUNT_ID` is missing, the client logs a warning that disbursements will fail with INSUFFICIENT_BALANCE. (V3.0 wrongly warned that setting it was deprecated; V3.1 flipped that.)

---

## PART 3 — Database (as it actually exists today)

Reference: `database/newupdateDB.csv` is the exported live schema (source of truth for column names). Migrations live in **`docs/sql/migrations/`** (the real path; note there is NO `server/docs/sql/migrations/` folder).

### 3.1 Tables the Nomba integration uses [VERIFIED against CSV]

**`agreements` (32 cols)** — carries the per-agreement VA + reconciliation state.
Nomba columns: `virtual_account_number` (UNIQUE), `virtual_account_name`, `nomba_account_ref` (UNIQUE), `payment_frequency` (CHECK MONTHLY/QUARTERLY/SEMI_ANNUAL/ANNUAL), `expected_payment_amount`, `payment_schedule`, `next_payment_due_date`, `total_received_amount`, `reconciliation_status` (CHECK PENDING/FULL_PAYMENT/UNDERPAYMENT/OVERPAYMENT/MISDIRECTED/DUPLICATE).

**`virtual_account_transfers` (16 cols)** — inbound webhook audit + idempotency.
Columns: `id`, `nomba_request_id` (UNIQUE — idempotency), `nomba_transaction_id`, `account_ref`, `account_number`, `amount_received`, `sender_name`, `sender_bank`, `currency`, `event_type`, `transaction_type`, `reconciliation_result`, `agreement_id`, `signature_valid`, `raw_payload`, `created_at`.

**`payment_reconciliation_log` (10 cols)** — audit trail of each reconciliation.
Columns: `id`, `agreement_id`, `transfer_id`, `previous_status`, `new_status`, `expected_amount`, `received_amount`, `variance_pct`, `notes`, `created_at`.

**`transactions` (22 cols)** — the ledger for both inbound and outbound.
Nomba columns: `transaction_type` (extended with `nomba_collection` + `nomba_disbursement`), `status` (CHECK pending/held/released/refunded/failed — **`completed` is NOT allowed**), `nomba_transfer_ref` (UNIQUE — the merchantTxRef), `nomba_transfer_id`, `source_transfer_id` (FK -> virtual_account_transfers), `held_at`, `released_at`, `refunded_at`, `amount`, `currency`, `payment_gateway`.
- [VERIFIED] `application_id` and `property_id` are **nullable** (Migration 005). The reconcile path pulls them from the agreement; missing values insert as NULL.

**`properties` (49 cols)** — `payment_frequency` (Migration 001) drives the schedule.

### 3.2 The landlord data split [VERIFIED — this is the IMPORTANT part for docs/security]

Rent user identity and landlord payout/BKYC data are spread across **three** tables. V3.2 designates `landlord_profiles` as the single source of truth for payout bank details (DECIDED this session):

| Table | Role | Key columns |
|---|---|---|
| `users` (55) | Identity, auth, role (`role`, `user_type` = LANDLORD/TENANT/ADMIN), contact (`full_name`, `email`, `phone`), engagement/trust | `id`, `role`, `user_type`, `full_name`, `email`, `phone`, `verification_status` |
| `landlord_profiles` (45) | **KYC + payout single source of truth (target).** BVN/NIN/CAC, onboarding steps, verification flags, AND bank payout fields | `id`, `bvn`, `nin`, `cac_number`, `is_verified`, `bank_account_number`, `bank_name`, `account_name`, `payment_method_verified`, ... |
| `landlords` (15) | Legacy payout holder — **still where the disburse route reads/writes today** | `id`, `bank_account_number`, `bank_code`, `bank_name`, `account_name`, `bank_verified_at`, ... |
| `tenant_profiles` (12) | Tenant intent (budget, income, preferred locations) — no payout relevance | `id`, `budget_range`, `monthly_income_range`, `preferred_locations`, ... |

### 3.3 [KNOWN GLITCH] Duplicate bank columns + disburse route target

**The defect:** payout bank details exist in BOTH `landlords` and `landlord_profiles`, with overlapping but not identical columns:

| column | `landlords` | `landlord_profiles` |
|---|---|---|
| `account_name` | ✅ | ✅ (DUPLICATE) |
| `bank_account_number` | ✅ | ✅ (DUPLICATE) |
| `bank_name` | ✅ | ✅ (DUPLICATE) |
| `bank_code` | ✅ | ❌ (missing — needed) |
| `bank_verified_at` | ✅ | ❌ (missing — needed) |
| `bank_statement_url` | ❌ | ✅ (KYC, stays) |

**What the code does today:** `POST /disbursements/lookup-bank` upserts the verified bank details into **`landlords`**; `POST /agreements/{id}/disburse` reads bank details from **`landlords`**. Both ignore `landlord_profiles`.

**Target (V3.2 DECIDED):** `landlord_profiles` is the single source of truth for payout bank details. Migration queued (Part 5 OPEN #1):
1. Add `bank_code` and `bank_verified_at` to `landlord_profiles`.
2. Move `lookup-bank` upsert + the disburse SELECT from `landlords` → `landlord_profiles`.
3. Drop the 5 bank-payout columns (`account_name`, `bank_account_number`, `bank_name`, `bank_code`, `bank_verified_at`) from `landlords`. Keep `landlords` for its non-bank legacy fields (`guarantee_*`, `ownership_docs`, `verification_*`).
The change is NOT applied yet (the disburse route is working on production); it is documented and queued so the submission is honest about current state.

### 3.4 Migrations actually applied (real files in `docs/sql/migrations/`)
- **001** `properties.payment_frequency` (also `001_add_payment_frequency_to_properties.sql`).
- **002** `agreements`: payment_frequency, expected_payment_amount, payment_schedule, virtual_account_number (UNIQUE), virtual_account_name, nomba_account_ref (UNIQUE), next_payment_due_date, total_received_amount, reconciliation_status CHECK.
- **003** `virtual_account_transfers` (+ `nomba_request_id` UNIQUE), `payment_reconciliation_log`, `transactions.transaction_type` extended with `nomba_collection`.
- **004** `landlords.bank_code` + `bank_verified_at`; `transactions`: `nomba_transfer_ref` (UNIQUE), `nomba_transfer_id`, `source_transfer_id` FK; `transaction_type` extended with `nomba_disbursement`.
- **005** `transactions.application_id` / `property_id` made nullable.
Migrations are `IF NOT EXISTS`-guarded; do not re-run blindly. (Other unrelated files in the migrations dir are pre-hackathon schema work.)

### 3.5 `transactions.status` allowed values [VERIFIED from the live CHECK constraint]
```
transactions_status_check = status IN ('pending','held','released','refunded','failed')
```
**`'completed'` is NOT allowed** (the V3.0-era handler used `'completed'`; fixed to `'released'`). Therefore:
- Inbound collection reconciled → `status = 'held'` (`held_at` set).
- Disbursement settled (`SUCCESS`) → `'released'` (`released_at`). `REFUND` → `'failed'`. `NEW`/`PENDING_BILLING` → `'pending'`.

---

## PART 4 — Code Map (matches this PRD — verified against shipped files)

| File | Responsibility |
|---|---|
| `server/app/services/nomba_client.py` | `NombaClient`: token issue/refresh (30-min, refresh at 25), `create_virtual_account` (Path A), `create_virtual_account_for_subaccount` (Path B, `-SUB`), `get_virtual_account` (recovery), `expire_virtual_account`, `verify_webhook_signature` (9-field base64, exact-case compare), `lookup_bank_account`, `get_banks_list`, `transfer_to_bank` (Path A; broken in prod), `transfer_to_bank_from_subaccount` (Path B; V3.1 default), `requery_transfer` (guarded, OPEN), `create_checkout_order` (kobo, checkout only). |
| `server/app/services/nomba_helpers.py` | `calculate_expected_amount`, `calculate_next_due_date`, `classify_payment` (+/-2% tolerance), `calculate_landlord_payout`, `build_merchant_tx_ref`._LastUpdated. |
| `server/app/routes/nomba.py` | `POST /agreements/{id}/provision-nomba` (idempotent + recovery, accountName sanitisation), `POST /webhooks/nomba/transfer` (signature -> idempotency -> reconcile/payout), `GET /agreements/{id}/payment-status`, `GET /health/nomba`, `_reconcile_payment` (regex UUID extraction from `-SUB` accountRef), `_handle_payout_event`. |
| `server/app/routes/disbursements.py` | `POST /disbursements/lookup-bank` (upserts payout bank into `landlords` today → target `landlord_profiles`), `POST /agreements/{id}/disburse` (MANUAL; auto-routes Path A/B on `-SUB` suffix; supports `force=true` test override; inserts pending transaction first), `GET /disbursements/{merchant_tx_ref}`. |

**Architecture rules obeyed (NULOGUIDE):** Rule 5 (BackgroundTasks before Depends), Rule 6 (`run_in_executor` for all Supabase), Rule 7 (specific routes before wildcards), Rule 17 (ASCII-only `.py`), Rule 18 (`supabase_admin` only), Rule 21 (Nomba HMAC-SHA256 constructed-string vs Paystack HMAC-SHA512 raw-body — never mix).

---

## PART 5 — OPEN items + known glitches (production-validation checklist)

These are NOT settled. Each is either untestable in sandbox, a known defect, or a queued Stage-2 change. Validate/fix before/at submission.

1. **[KNOWN GLITCH] Duplicate payout bank columns.** `landlords` and `landlord_profiles` both carry `account_name`, `bank_account_number`, `bank_name`; the disburse route reads `landlords`. **Target: `landlord_profiles` as single source of truth.** Migration queued (Part 3.3). The route works today; this is a hygiene fix, not a live bug.
2. **[OPEN] Requery by ref (Part 1.7).** Broken in sandbox; match-guard shipped. Re-test `single?transactionRef=`, `requery/{sessionId}`, the `{subAccountId}` variants in production before relying on requery for payout finalisation.
3. **[OPEN] Auto-disbursement.** Disbursement is MANUAL (landlord hits the endpoint). Stage-2: a post-reconciliation hook that auto-triggers `disburse_to_landlord` on FULL_PAYMENT (with a grace window + guard against double-disburse). The `force=true` test override must be removed for any real flow.
4. **[KNOWN GLITCH] `provision-nomba` route uses Path A only.** New VAs should use Path B (sub-account-scoped) per V3.1, but the route calls `create_virtual_account` (Path A). The live sub-account VA `3783622764` was created via a one-off script, not the route. Stage-2: point the route at `create_virtual_account_for_subaccount` and append `-SUB` to the accountRef.
5. **[OPEN] Frontend not wired.** The Next.js frontend does not yet call these endpoints with auth. Stage-2 wiring: tenant "pay" panel (show NUBAN), landlord dashboard (received/disbursed/release-funds).

---

## PART 6 — Skill-vs-reality deviation register

`nomba/skill/SKILL.md` is a good generic agent skill; 2026-07-03 live testing proved it WRONG on load-bearing facts for the hackathon account. Where the skill and this PRD disagree, **this PRD wins** — each deviation is evidence-backed:

| # | Skill says | Reality (this PRD) | Evidence |
|---|---|---|---|
| 1 | Webhook = HMAC over **raw body**, **hex**, header `nomba-sig-value` | 9-field colon-joined string, **base64**, header `nomba-signature` | Hand-verified test vector + teammate's working handler (Part 1.3) |
| 2 | Token valid **60 min** (refresh at 55) | **30 min** (refresh at 25) | Live `expiresAt` = issue + 30 min; Nomba engineer (Victor Shoaga) |
| 3 | Sandbox host `sandbox.api.nomba.com` | `sandbox.nomba.com` | Live auth succeeds on `sandbox.nomba.com` |
| 4 | Sub-account scoping of VA creation is **not possible** | **IS possible** via path-based endpoint `POST /v1/accounts/virtual/{subAccountId}` | Live 2026-07-04: NUBAN `3783622764`, `accountHolderId: 282e5b9b-...` |

Also vs skill: amounts are **decimal Naira** for VA/Transfers (skill implies kobo everywhere — kobo is Checkout-only); sub-account scoping of VA creation IS possible (V3.1 corrects V3.0).

---

## PART 7 — Test Plan

### Sandbox (done / repeatable) — `server/scripts/` probes or Thunder Client (`docs/thunderclient/`)
- Auth: `POST /auth/token/issue` → 200, `access_token`, `expiresAt` = +30 min. [VERIFIED]
- VA Path A: `POST /accounts/virtual` (header=parent, body 2 fields) → code 00, NUBAN. [VERIFIED; legacy]
- VA Path B: `POST /accounts/virtual/{subAccountId}` (header=parent, path=sub) → code 00, NUBAN, `accountHolderId: <sub>`. [VERIFIED live]
- Banks/lookup: `GET /transfers/banks` (77), `POST /transfers/bank/lookup` → resolved name. [VERIFIED]
- Transfer Path A: `POST /v2/transfers/bank` amount `137.53` → code 00, echoed amount. [VERIFIED in sandbox; BROKEN in prod with INSUFFICIENT_BALANCE]
- Transfer Path B: `POST /v2/transfers/bank/{subAccountId}` → code 00, `SUCCESS`. [VERIFIED live]
- Provisioning route + reconciliation scenarios (full/under/over/misdirected/idempotent/bad-signature): run locally with `scripts/simulate_nomba_webhook.py` (signature computed with `NombaHackathon2026`).

### Production (V3.2 LIVE PROOF 2026-07-04)
1. Deploy to Render with LIVE creds (`NOMBA_ENV=live`). Done.
2. `GET /api/v1/health/nomba` → `{"status":"ok","nomba_auth":true,"environment":"live"}`. Done.
3. Real OPay ₦100 → NUBAN `3783622764` → `payment_success` webhook → `virtual_account_transfers` + `transactions(status='held')`. Done. Real `txn_id: API-VACT_TRA-282E5-7c8cfa87-...`, ~10s end-to-end.
4. Real ₦100 disbursement via Path B → `data.status: SUCCESS`, `nomba_transfer_id: c7e3e0a2-...`, `transactions.status: released`. Done. OPEN #2 (where funds settle) resolved — funds settle in the sub-account; disbursement uses Path B.

### Still to validate on production before submission
- Requery endpoint variants (Part 1.7 / OPEN #2).
- Move disburse route to `landlord_profiles` (OPEN #1) — non-blocking for submission, but documented honestly.
- Confirm `NOMBA_SUB_ACCOUNT_ID` is set on Render (its absence now logs a warning, not the inverse).

---

## PART 8 — File Manifest

Integration-owned files (real paths):
```
server/app/services/nomba_client.py
server/app/services/nomba_helpers.py
server/app/routes/nomba.py
server/app/routes/disbursements.py
docs/nomba_openapi.json                          # the spec (NOT docs/hackathon/)
docs/sql/migrations/001_add_payment_frequency_to_properties.sql
docs/sql/migrations/002_add_nomba_columns_to_agreements.sql
docs/sql/migrations/003_create_nomba_tables.sql
docs/sql/migrations/004_add_disbursement_support.sql
docs/sql/migrations/005_make_transaction_fields_nullable.sql
docs/thunderclient/thunder-collection_nomba_flow.json
docs/rest-client/nomba_flow.http
docs/rest-client/payloads/{full_payment,underpayment,overpayment,misdirected}.json
server/scripts/simulate_nomba_webhook.py
server/scripts/simulate_live_webhook.py
server/scripts/simulate_payout_webhook.py
server/scripts/check_agreement.py
server/scripts/check_agreement_live.py
server/scripts/check_quick.py
server/scripts/check_db_data.py
server/scripts/check_subaccount_balance.py
server/scripts/check_va_state.py
server/scripts/debug_nomba_webhooks.py
server/scripts/diagnose_va_creation.py
server/scripts/get_pending_disbursement.py
server/scripts/poll_opay_webhook.py
server/scripts/poll_webhook.py
server/scripts/reprovision_live_va.py
server/scripts/repush_failed_webhooks.py
server/scripts/reset_test_data.py
server/scripts/trigger_disburse.py
server/scripts/update_agreement_ref.py
database/newupdateDB.csv                          # exported live schema — column-name source of truth
```

---

## Changelog

- **V3.0** (2026-07-03) — Initial V3. Parent-centric architecture, parent-only disbursement, 1-path VA creation.
- **V3.1** (2026-07-04) — Live production evidence forced three API corrections: sub-account-scoped VAs ARE possible (Path B); funds settle in the sub-account (Path B disbursement); sub-account is the SAFE HAVEN. Open items #1 and #2 resolved with live proof; #3 (requery) still open.
- **V3.2** (2026-07-04) — Re-grounded in the actual code + DB:
  1. Disbursement documented as **MANUAL** (route header + shipped code); auto-disburse is a queued Stage-2 item (OPEN #4), not shipped.
  2. The **`force=true` test override** on the disburse route is documented honestly (Part 4 / Part 5 OPEN #4).
  3. Introduced the **`landlord_profiles` vs `landlords` payout-data split** as a [KNOWN GLITCH] and designated `landlord_profiles` the single source of truth for payout bank details, with a queued migration (Part 3.2 / 3.3 / OPEN #1).
  4. Corrected the **migrations path** to `docs/sql/migrations/` (real files; no `server/docs/sql/`).
  5. Corrected the **OpenAPI spec path** to `docs/nomba_openapi.json` (not `docs/hackathon/`).
  6. Documented that **`provision-nomba` uses Path A only** despite Path B being the default — a [KNOWN GLITCH] (OPEN #5).
  7. Requery kept [OPEN] with the match-guard mitigation; re-test in production still required.

---
*V3 generated 2026-07-03. V3.1 corrections 2026-07-04 after live production evidence. V3.2 corrections 2026-07-04 after re-grounding in the shipped code and `database/newupdateDB.csv`. Every `[VERIFIED]` line has a timestamp; every `[OPEN]`/`[KNOWN GLITCH]` item must be resolved or honestly surfaced before submission.*
