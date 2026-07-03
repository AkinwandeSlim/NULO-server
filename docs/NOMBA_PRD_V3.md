# NuloAfrica x Nomba — Hackathon Integration PRD (V3)
## The Single Source of Truth for the Nomba Virtual-Accounts Integration

> **Version:** V3 (2026-07-03) — supersedes `NOMBA_PRD_V2.md` and `nomba_PRD.md`.
> **Status:** Every fact below is tagged **[VERIFIED]**, **[DECIDED]**, or **[OPEN]**.
>   - **[VERIFIED]** = proven by a live sandbox call and/or the shipped OpenAPI spec (`docs/hackathon/nomba_openapi.json`) on 2026-07-03.
>   - **[DECIDED]** = a deliberate architecture choice for this submission (rationale given).
>   - **[OPEN]** = genuinely unresolved; CANNOT be tested in sandbox; must be validated in production. Never treat an [OPEN] item as settled.
> **Hackathon:** DevCareer x Nomba 2026, July 1–7. Track: *Virtual Accounts as Infrastructure*.
> **Live backend:** https://api.nuloafrica.com (Render, GitHub: AkinwandeSlim/NULO-server, branch: main)
> **Webhook URL (submitted):** https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer

> ### Why V3 exists (read once)
> V2 accumulated contradictory changelog entries (v2 "sub-account confirmed" vs v4 "sub-account removed"), a kobo/decimal-Naira confusion, and several claims that later proved wrong when tested against the live sandbox. V3 is a clean rewrite built only on evidence gathered on 2026-07-03: live sandbox calls with the real hackathon credentials, plus the OpenAPI spec shipped in the repo. Where V2 asserted something we could not prove, V3 marks it **[OPEN]** instead of stating it as fact. **Do not merge V2 content back in.**

---

## PART 0 — Architecture (DECIDED)

### What NuloAfrica is
Zero agency-fee rental marketplace for Nigerian cities (Lagos, Abuja, Port Harcourt).
Stack: Next.js 16 + React 19 frontend, FastAPI + Python backend, Supabase (PostgreSQL), Paystack (existing rent flow — leave untouched), Twilio + SMTP notifications.

### Hackathon scope
Multi-frequency rental payment infrastructure on Nomba Virtual Accounts, covering the full money lifecycle: **collect -> reconcile -> disburse**. Nigerian landlords want annual rent upfront; tenants want monthly. We assign a dedicated Nomba virtual account (NUBAN) **per signed agreement**, support 4 payment frequencies, reconcile every inbound transfer automatically, then disburse the landlord's share.

### The architecture — PARENT-CENTRIC, per-agreement [DECIDED]
```
Parent account (shared "mothership", id f666ef9b-888e-4799-85ce-acb505b28023)
  |  <- the accountId HEADER on EVERY request is ALWAYS this parent id
  |
  +- Virtual Account per SIGNED AGREEMENT   (accountRef = agreement.id)   <-- COLLECT
  |     tenant transfers rent to this NUBAN
  |     -> Nomba fires webhook -> we reconcile by accountRef (= agreement.id)
  |
  +- Disburse landlord share via POST /v2/transfers/bank (parent)         <-- DISBURSE
        platform_fee = the residual left in the parent account (our logic, not Nomba's)
```

**Why parent-centric, and why NOT per-landlord sub-accounts:**
1. A Nomba sub-account = a *merchant/business*. Your team has exactly ONE (id `282e5b9b-d14f-4e43-840d-43ddfd90a071`). You do not mint one per landlord — that is not what they are for.
2. **The VA-creation endpoint cannot scope a virtual account to a sub-account anyway** [VERIFIED]. `POST /accounts/virtual` is header-scoped to the parent; a sub-account id passed in query OR body is ignored (see Part 1.2). So "collect under the parent" is not a compromise — it is how the API behaves.
3. The correct grain is **per agreement**: `accountRef = agreement.id` gives each signed lease its own NUBAN, and the webhook's `aliasAccountReference` maps straight back for reconciliation.
4. Reconciliation is by `accountRef` in our own DB (the ledger), independent of where funds physically settle on Nomba's side.

### Out of scope for the 3 days
- Tokenized cards / direct debits / mandates (different track; also sandbox-nonfunctional).
- Landlord analytics dashboard, payment-schedule calendar UI, full frontend polish.
- Nightly reconciliation cron (webhook + on-demand requery cover the demo).

### Locked decisions — do not re-open
1. Backend-first. No frontend work until endpoints pass Thunder Client / probe tests.
2. Nomba runs ALONGSIDE Paystack. Do not touch `payments.py` or `agreements.py`.
3. `accountRef = agreement.id` (your UUID). No Nomba-side ID storage needed for lookup.
4. `NOMBA_WEBHOOK_SECRET=NombaHackathon2026` — the hackathon organiser's signing key, not a dashboard key.
5. `accountId` HEADER = the shared parent `f666ef9b...` on EVERY call, including auth. This is the #1 fix for 403s (Nomba support golden rule). Never put the sub-account id in the header.
6. Amounts for Virtual Accounts and Transfers are **decimal Naira** (see Part 1). Do NOT reintroduce a `NOMBA_AMOUNT_FORMAT` env var — it was removed on 2026-07-03 because it was wrong and unused.

---

## PART 1 — Verified API Contracts

Base URLs [VERIFIED]:
| Env (`NOMBA_ENV`) | Base URL | Credentials |
|---|---|---|
| `test` (default) | `https://sandbox.nomba.com/v1` | `NOMBA_TEST_*` |
| `live` | `https://api.nomba.com/v1` | `NOMBA_LIVE_*` |

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
- **Token lifetime = 30 minutes** [VERIFIED — live `expiresAt` was exactly issue-time + 30 min; also confirmed by Victor Shoaga, Nomba engineer]. Cache in memory; refresh at the **25-minute** mark (5-min buffer). One shared token across all calls, guarded by `asyncio.Lock`. Prefer `token/refresh` over re-issuing (avoids re-exposing `client_secret`); fall back to `token/issue` if refresh fails.

### 1.2 Virtual Account Creation [VERIFIED]
```
POST {base}/accounts/virtual
Headers: Authorization: Bearer {token}
         accountId: {parent}          (header only — this scopes the call)
         Content-Type: application/json
Body:    { "accountRef": "{agreement.id}", "accountName": "{tenant display name}" }
Response (code "00"): data = {
   createdAt, accountHolderId, accountRef, bvn, accountName,
   bankName, bankAccountNumber, bankAccountName, currency, callbackUrl, expired
}
```
**Confirmed facts (live + spec):**
- Body is EXACTLY `{accountRef, accountName}`. The OpenAPI spec lists only these two, both required. `currency` and `expectedAmount` do NOT exist in the spec — we track the expected amount locally in `agreements.expected_payment_amount`.
- **No sub-account scoping is possible here.** Passing a sub-account id as `?accountId=` (query) OR in the body is IGNORED: the response `accountHolderId` came back as the PARENT (`f666ef9b...`) in every variant tested. `/virtual-accounts/sub-account` (a path some training docs cite) returns **404 — does not exist**.
- **Store:** `bankAccountNumber` -> `agreements.virtual_account_number` (show tenant); `bankAccountName` -> `agreements.virtual_account_name`; `accountRef` -> `agreements.nomba_account_ref` (confirm it echoes your UUID).

### 1.3 Webhook — signature + payload [VERIFIED]
Nomba signs with **HMAC-SHA256 over a colon-joined 9-field string** (NOT a raw-body hash), **base64**-encoded. This was independently confirmed by a working handler from a teammate and by a hand-computed test vector.

Headers Nomba sends you:
```
nomba-signature: base64 HMAC-SHA256      <- verify against THIS exact header name (no x- prefix)
nomba-timestamp: 2026-07-01T10:00:00Z    <- REQUIRED for signature reconstruction (from header, not body)
nomba-signature-algorithm: HmacSHA256
```
Signature construction:
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
# compare with hmac.compare_digest() — EXACT case (base64 is case-sensitive)
```
Hand-verified test vector (matches):
```
event_type=payment_success  request_id=45f2dc2d-d559-4773-bba3-2d5ec17b2e20
user_id=b7b10e81-...  wallet_id=6756ff80aafe04a795f18b38
transaction_id=API-VACT_TRA-B7B10-0435b274-...  type=vact_transfer
time=2025-09-29T10:51:44Z  response_code=(empty)  timestamp=2025-09-29T10:51:44Z
secret=HkatexKDZg7CLWy96q5sfrVHSvtoz92B
-> Kt9095hQxfgmVbx6iz7G2tPhHdbdXgLlyY/mf35sptw=
```
Key payload mappings for reconciliation:
| Payload field | Use |
|---|---|
| `event_type` = `payment_success` | check first |
| `data.transaction.type` = `vact_transfer` | reconcile ONLY when this |
| `data.transaction.aliasAccountReference` | **= your accountRef = agreement.id** -> look up agreement |
| `data.transaction.transactionAmount` | compare to `expected_payment_amount` |
| `data.transaction.aliasAccountNumber` | cross-check `agreements.virtual_account_number` |
| `data.transaction.transactionId` | store for audit |
| `data.customer.senderName` | store for tenant record |
| `requestId` (top-level) | idempotency key (unique index; reject dup) |

**Retry/ack rule:** verify signature -> store `requestId` -> return **200** even if reconciliation errors (log it, handle async). Non-2xx triggers up to 5 Nomba retries.

### 1.4 Event types [VERIFIED against real payload sample]
| event_type | transaction.type | Meaning |
|---|---|---|
| `payment_success` | `vact_transfer` | Virtual account funded  <- OURS |
| `payment_success` | other | Card/other, ignore |
| `payout_success` | `transfer` | Outbound transfer settled |
| `payout_failed` | — | Outbound transfer failed |
| `payout_refund` | — | Payout reversed |

### 1.5 Bank Account Lookup [VERIFIED]
```
POST {base}/transfers/bank/lookup
Headers: Authorization: Bearer {token}, accountId: {parent}, Content-Type: application/json
Body:    { "accountNumber": "0000000000", "bankCode": "035" }
Response (code "00"): data = { "accountNumber", "accountName" }
```
ALWAYS call before a transfer; show the returned `accountName` to the landlord and use IT (never a user-typed name) in the transfer. Bank codes come from `GET {base}/transfers/banks` (77 banks live; e.g. Wema = `035`, Access = `044`). Cache the list.

### 1.6 Transfer to Bank (disbursement, from PARENT) [VERIFIED]
```
POST https://sandbox.nomba.com/v2/transfers/bank       (v2; PARENT; NO subAccountId in path)
Headers: Authorization: Bearer {token}, accountId: {parent}, Content-Type: application/json
Body:    { "amount": 137.53,                 <- DECIMAL NAIRA, JSON number. Do NOT x100.
           "accountNumber": "0000000000",
           "accountName": "{from lookup}",
           "bankCode": "035",
           "merchantTxRef": "NULO-DISB-XXXXXXXX",   <- idempotency key, unique per transfer
           "senderName": "NuloAfrica",
           "narration": "Rent disbursement" }
Response: HTTP 200/201, data.status in { SUCCESS | PENDING_BILLING | NEW | REFUND }
```
- **Amount = decimal Naira, PROVEN** [VERIFIED]: we sent a non-integer `137.53` and Nomba accepted + echoed `137.53` (kobo is integer-only, so a surviving fraction proves decimal Naira). OpenAPI: `amount` is `type: number, format: double`. The kobo rule applies to **Checkout only**.
- **Status handling:** `SUCCESS` -> done (rare/immediate). `PENDING_BILLING` / `NEW` -> processing async, do NOT retry, wait for webhook. `REFUND` -> failed + auto-reversed, safe to retry with a NEW `merchantTxRef`.
- Rate limit: 5 transfers to the same recipient per minute.

### 1.7 Requery Transfer [OPEN — broken in sandbox]
Intended: `GET {base}/transactions/accounts/single?transactionRef={merchantTxRef}` to poll a `PENDING_BILLING`/`NEW` transfer whose webhook never arrived.
- **[OPEN] This endpoint is BROKEN/unusable in sandbox** [VERIFIED broken 2026-07-03]: it **ignores the ref** entirely — it returned the SAME unrelated record for our ref, for a Nomba transaction id, and for a deliberately bogus ref. `/transfers/{ref}` and `/transactions/{ref}` return 404 in sandbox.
- **Mitigation shipped:** `requery_transfer()` has a **defensive match-guard** — it only trusts the returned record if it can be tied back to THIS transfer by `merchantTxRef` echo, Nomba transfer id, or exact amount; otherwise it returns `status=None, _match_verified=False` so no payout is ever finalised off a stranger's record.
- **Must be re-tested in production.** The spec also documents `GET /v1/transactions/requery/{sessionId}` and `/transactions/accounts/{subAccountId}/single` — evaluate these live before relying on requery.

---

## PART 2 — Environment Variables

```bash
NOMBA_ENV=test                       # test | live
NOMBA_PARENT_ACCOUNT_ID=f666ef9b-888e-4799-85ce-acb505b28023   # shared parent; header on every call
NOMBA_SUB_ACCOUNT_ID=<team sub-account id>   # retained but NOT used for VA scoping (see Part 1.2);
                                             # only relevant if a future prod test moves disbursement
                                             # to /v1/transfers/bank/{subAccountId}
NOMBA_TEST_CLIENT_ID=...
NOMBA_TEST_CLIENT_SECRET=...
NOMBA_LIVE_CLIENT_ID=...
NOMBA_LIVE_CLIENT_SECRET=...
NOMBA_WEBHOOK_SECRET=NombaHackathon2026        # organiser signing key
# DO NOT add NOMBA_AMOUNT_FORMAT — removed 2026-07-03 (wrong + unused; amounts are decimal Naira).
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
```

---

## PART 3 — Database (migrations already applied)

Migrations `001`–`004` in `docs/sql/migrations/` are **already applied** to the live schema (confirmed against `database/newupdateDB.csv`). Do not re-run blindly; they are `IF NOT EXISTS`-guarded.

- **001** `properties.payment_frequency` VARCHAR(50) CHECK in (MONTHLY, ANNUAL, SEMI_ANNUAL, QUARTERLY).
- **002** `agreements`: `payment_frequency`, `expected_payment_amount`, `payment_schedule`, `virtual_account_number` (UNIQUE), `virtual_account_name`, `nomba_account_ref` (UNIQUE), `next_payment_due_date`, `total_received_amount`, `reconciliation_status` CHECK in (PENDING, FULL_PAYMENT, UNDERPAYMENT, OVERPAYMENT, MISDIRECTED, DUPLICATE).
- **003** `virtual_account_transfers` (inbound audit + idempotency via `nomba_request_id` UNIQUE), `payment_reconciliation_log`, and `transactions.transaction_type` extended with `nomba_collection`.
- **004** `landlords.bank_code` + `bank_verified_at`; `transactions`: `nomba_transfer_ref` (UNIQUE), `nomba_transfer_id`, `source_transfer_id` FK; `transaction_type` extended with `nomba_disbursement`.

### CRITICAL — `transactions.status` allowed values [VERIFIED from live constraint]
```
transactions_status_check = status IN ('pending','held','released','refunded','failed')
```
**`'completed'` is NOT allowed.** Inserting it throws a constraint violation (silently swallowed by the webhook's try/except -> looks like success but writes nothing). Therefore:
- Inbound collection reconciled -> `transactions.status = 'held'` (money held in parent; `held_at` set).
- Disbursement settled (`SUCCESS`) -> `'released'` (`released_at` set). `REFUND` -> `'failed'`. `NEW`/`PENDING_BILLING` -> `'pending'`.

---

## PART 4 — Code Map (shipped, matches this PRD)

| File | Responsibility |
|---|---|
| `server/app/services/nomba_client.py` | `NombaClient`: token cache/refresh (30-min, 25-min refresh), `create_virtual_account` (bare, parent header), `verify_webhook_signature` (9-field base64), `lookup_bank_account`, `transfer_to_bank` (v2, decimal Naira), `requery_transfer` (with match-guard), `create_checkout_order` (kobo — checkout only) |
| `server/app/routes/nomba.py` | `POST /agreements/{id}/provision-nomba`, `POST /webhooks/nomba/transfer`, `GET /agreements/{id}/payment-status`, `GET /health/nomba`, `reconcile_payment()` |
| `server/app/routes/disbursements.py` | `POST /disbursements/lookup-bank`, `POST /agreements/{id}/disburse`, `GET /disbursements/{merchant_tx_ref}` |
| `server/app/services/nomba_helpers.py` | `calculate_expected_amount`, `calculate_next_due_date`, `classify_payment` (+/-2% tolerance), `calculate_landlord_payout`, `build_merchant_tx_ref` |

Architecture rules obeyed (from NULOGUIDE): Rule 5 (`BackgroundTasks` before `Depends`), Rule 6 (`run_in_executor` for all Supabase), Rule 7 (specific routes before wildcards), Rule 17 (ASCII-only `.py`), Rule 18 (`supabase_admin` only), Rule 21 (Nomba HMAC-SHA256 constructed-string vs Paystack HMAC-SHA512 raw-body — never mix).

---

## PART 5 — OPEN items (production-validation checklist)

These are NOT bugs and NOT settled. They cannot be verified in sandbox. Validate each on the live server before/at submission.

1. **[OPEN] Webhook delivery is live-creds only.** Reported in the hackathon Discord and consistent with the skill docs (sandbox webhook forwarding is unreliable; checkout webhooks are production-only). Test the real webhook only AFTER cutover to live creds on Render, using the submitted URL `https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer`. Until then, exercise the handler locally with `server/scripts/simulate_nomba_webhook.py`.
2. **[OPEN] Where funds settle — parent vs sub-account.** Nomba support says VA inflows credit YOUR sub-account (with a hackathon instant-settlement exception); the API shows the parent as `accountHolderId`. Sandbox cannot disambiguate (shared parent, no reliable balances, T+1 default per GOTCHA #11). Does not affect the demo (reconciliation is by `accountRef`; disbursement works from parent). **If production shows funds land in the sub-account, switch disbursement from `POST /v2/transfers/bank` to `POST /v1/transfers/bank/{subAccountId}` — a one-endpoint change.**
3. **[OPEN] Requery by ref (Part 1.7).** Broken in sandbox; guarded to fail-safe. Re-test `single?transactionRef=`, `requery/{sessionId}`, and the `{subAccountId}` variants in production.

---

## PART 6 — Skill-vs-reality deviation register

`nomba/skill/SKILL.md` is a good generic agent skill, but on 2026-07-03 live testing proved it WRONG on three load-bearing facts for the hackathon account. Where the skill and this PRD disagree, **this PRD wins** — each deviation is evidence-backed:

| # | Skill says | Reality (this PRD) | Evidence |
|---|---|---|---|
| 1 | Webhook = HMAC over **raw body**, **hex**, header `nomba-sig-value` | 9-field colon-joined string, **base64**, header `nomba-signature` | Hand-verified test vector + teammate's working handler (Part 1.3) |
| 2 | Token valid **60 min** (refresh at 55) | **30 min** (refresh at 25) | Live `expiresAt` = issue + 30 min; Nomba engineer (Victor Shoaga) |
| 3 | Sandbox host `sandbox.api.nomba.com` | `sandbox.nomba.com` | Live auth succeeds on `sandbox.nomba.com`; matches Nomba support env table |

Also note vs skill: amounts are **decimal Naira** for VA/Transfers (skill implies kobo everywhere — kobo is Checkout-only); sub-account scoping of VA creation is **not possible** (skill/training docs imply it is).

---

## PART 7 — Test Plan

### Sandbox (done / repeatable) — use `server/scripts/` probes or Thunder Client
- Auth: `POST /auth/token/issue` -> 200, `access_token`, `expiresAt` = +30 min. [VERIFIED]
- VA: `POST /accounts/virtual` (header=parent, body 2 fields) -> `code 00`, NUBAN. [VERIFIED]
- Banks/lookup: `GET /transfers/banks` (77), `POST /transfers/bank/lookup` -> resolved name. [VERIFIED]
- Transfer: `POST /v2/transfers/bank` amount `137.53` -> `code 00`, `PENDING_BILLING`, amount echoed. [VERIFIED]
- Provisioning route + reconciliation scenarios (full/under/over/misdirected/idempotent/bad-signature): run locally against `POST /api/v1/webhooks/nomba/transfer` with `simulate_nomba_webhook.py` (signature computed with `NombaHackathon2026`).

### Production (pre-submission) — the [OPEN] items
1. Deploy to Render with LIVE creds (`NOMBA_ENV=live`).
2. Verify `GET /api/v1/health/nomba` -> `nomba_auth: true`.
3. Submit/confirm webhook URL; fund a real VA with a tiny amount; confirm the webhook fires and reconciliation writes `virtual_account_transfers` + `transactions(status='held')`.
4. Run a ₦1 real disbursement; confirm `data.status`, then verify settlement account (resolves OPEN #2) and requery (resolves OPEN #3).

---

## PART 8 — File Manifest

New/owned by this integration:
```
server/app/services/nomba_client.py
server/app/services/nomba_helpers.py
server/app/routes/nomba.py
server/app/routes/disbursements.py
server/scripts/simulate_nomba_webhook.py
docs/sql/migrations/001_add_payment_frequency_to_properties.sql
docs/sql/migrations/002_add_nomba_columns_to_agreements.sql
docs/sql/migrations/003_create_nomba_tables.sql
docs/sql/migrations/004_add_disbursement_support.sql
```
Modify: `server/app/main.py` (register `nomba_router` under `/api/v1`), `server/.env.example`.
Do NOT touch: `server/app/routes/payments.py`, `server/app/routes/agreements.py` (Paystack + existing agreement CRUD).

---
*V3 generated 2026-07-03. Built only on live-verified evidence. Supersedes V2 — do not reintroduce V2 claims.*
