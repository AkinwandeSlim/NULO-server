# Thunder Client — Testing the Nomba Flow (payment -> disbursement)

Full **collect -> reconcile -> disburse** walkthrough against the running backend on
`http://localhost:8000`, using the existing implementation. No real money (sandbox),
except the webhook, which is *simulated locally* (Nomba's real webhook only fires on
live creds — see PRD V3 Part 5).

## Files
- `thunder-collection_nomba_flow.json` — import as a Thunder Client **Collection**
- `thunder-environment_nomba_local.json` — import as a Thunder Client **Environment** (select it)

## Why the webhook is special
Every other endpoint is a normal REST call. The webhook
(`POST /webhooks/nomba/transfer`) **rejects anything without a valid `nomba-signature`**
(HMAC-SHA256 over a 9-field string, base64). Thunder Client can't compute that inline,
so you generate it with the existing script and paste it in. That's the only manual step.

## One-time setup
1. **Backend running:** `http://localhost:8000` (you already have it up). Confirm with request **0. Health** -> `nomba_auth: true`.
2. **Get a JWT.** Sign in via your app / `POST /api/v1/auth/...` and copy the access token.
   - `jwt` = a tenant OR landlord on the test agreement (for provision + status).
   - `landlordJwt` = the **landlord** on that agreement (for lookup-bank + disburse; the disburse route is landlord-only).
3. **Pick a SIGNED agreement.** In Supabase, find an `agreements` row with `status = 'SIGNED'`. Put its `id` in the `agreementId` env var. (Provisioning 400s on non-SIGNED — that's request-level validation, expected.)
4. **Align the simulator's userId.** Open `server/scripts/simulate_nomba_webhook.py` and set
   `SUB_ACCOUNT_USER_ID` to the SAME value you'll treat as `merchant.userId`. It only needs to
   be internally consistent (the signature hashes it and the handler re-hashes the same body),
   so any fixed string works — just don't change it between generating the sig and posting.

## Run order (collection is numbered)

### Folder 1 — Collect
| # | Request | Auth | Expect |
|---|---------|------|--------|
| 1 | Provision VA | `jwt` | 200 `provisioned` (or `already_provisioned` on re-run) + NUBAN |
| 2 | Payment status BEFORE | `jwt` | 200, `reconciliation_status: PENDING` |
| 3 | Webhook FULL | sig | 200 `ok` |
| 4 | Webhook REPLAY | sig | 200 `already_processed` (idempotency) |
| 5 | Webhook BAD sig | bad | **401** (nothing written) |
| 6 | Webhook UNDERPAYMENT | sig | 200, status -> `UNDERPAYMENT` |
| 7 | Webhook OVERPAYMENT | sig | 200, status -> `OVERPAYMENT` |
| 8 | Webhook MISDIRECTED | sig | 200, transfer row `reconciliation_result: MISDIRECTED`, agreement untouched |
| 9 | Payment status AFTER | `jwt` | 200, `FULL_PAYMENT`; auto-captures `sourceTransferId` from `transfer_history[0].id` |

**Generating each webhook body + signature** (run once per scenario, paste output):
```bash
cd server
./venv/Scripts/python.exe scripts/simulate_nomba_webhook.py <agreementId> full_payment
./venv/Scripts/python.exe scripts/simulate_nomba_webhook.py <agreementId> underpayment
./venv/Scripts/python.exe scripts/simulate_nomba_webhook.py <agreementId> overpayment
./venv/Scripts/python.exe scripts/simulate_nomba_webhook.py <agreementId> misdirected
```
For each: copy the printed `nomba-signature` into the matching env var
(`sigFull` / `sigUnder` / `sigOver` / `sigMisdir`) and paste the printed JSON into that
request's Body. Keep `nomba-timestamp` = `2026-07-01T10:00:00Z` (the script uses that exact value; changing one without the other breaks the signature).

> Note: run scenarios 6/7 with their own bodies (each has a distinct `requestId`, so they
> won't collide with the idempotency check). To re-run the same scenario, bump its
> `requestId` in the pasted body or you'll just get `already_processed`.

### Folder 2 — Disburse
| # | Request | Auth | Expect |
|---|---------|------|--------|
| 10 | Lookup + verify bank | `landlordJwt` | 200 + resolved `account_name`; persists `bank_code`/`bank_verified_at` on `landlords` |
| 11 | Disburse to landlord | `landlordJwt` | 200; uses captured `sourceTransferId`; auto-captures `merchantTxRef` |
| 12 | Disbursement status | `landlordJwt` | 200 with `status` (`pending`/`released`) |

**Preconditions the disburse route enforces** (all return clear 4xx if unmet):
- Source transfer must be reconciled `FULL_PAYMENT` (that's why you run collection first, scenario 3, and capture `sourceTransferId` in request 9).
- Landlord bank must be verified (`bank_verified_at` set) — that's request 10.
- `nomba_status` maps to `transactions.status`: `SUCCESS -> released`, `NEW`/`PENDING_BILLING -> pending`, `REFUND -> failed`. In sandbox a live transfer typically returns `PENDING_BILLING`, so expect `status: pending` here — that's correct, not a failure.

## Verify in Supabase after a full pass
- `agreements`: `virtual_account_number` set, `reconciliation_status`, `total_received_amount`.
- `virtual_account_transfers`: one row per webhook (`nomba_request_id` unique), MISDIRECTED flagged.
- `payment_reconciliation_log`: one row per reconciliation.
- `transactions`: a `nomba_collection` row `status='held'`, and a `nomba_disbursement` row `status='pending'|'released'`.

## Gotchas (so a red response doesn't mislead you)
- **401 on webhook 3/6/7/8** = signature/body/timestamp mismatch, not a code bug. Regenerate with the script; don't hand-edit the body after signing.
- **401 on JWT routes** = expired token (Supabase tokens are short-lived). Re-fetch and update `jwt`/`landlordJwt`.
- **400 on provision** = agreement isn't `SIGNED`. Pick a signed one.
- **Real Nomba `/accounts/virtual` / `/v2/transfers/bank`** are called by provision (1) and disburse (11) against **sandbox** — safe, no real money. The webhook is *local simulation only* until you deploy with live creds.
