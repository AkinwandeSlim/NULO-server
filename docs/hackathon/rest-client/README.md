# Nomba flow — local self-testing

One-command, fully-automated test of the full Nomba **collect → reconcile → disburse** flow against a running local NuloAfrica backend. No manual JWT pasting, no simulator round-trip, no Thunder Client environment to maintain.

## Why this exists

The `.http` file (`nomba_flow.http`) requires pre-computed HMAC signatures and pasted JWTs — the REST Client format can't compute HMAC/base64 dynamically, so every webhook call needed a manual simulator round-trip first. This Python runner removes that friction: it **mints JWTs itself**, **signs every webhook fresh** with the correct `{uuid}-SUB` accountRef, and **asserts** each step passed.

It also exercises the **fixed `provision-nomba` route (Path B / sub-account-scoped)** — the webhook payloads mirror exactly what Nomba sends for a Path-B VA, so `payment_status` history is non-empty (validates the `-SUB`-aware UUID-extraction fix).

## Pre-reqs

1. **Local server running** with `.env` loaded:
   ```powershell
   cd "C:\MyFiles\DOCUMENT-2026\Nuelo_Poc\NULO-DEV\server"
   .\venv\Scripts\Activate.ps1
   uvicorn app.main:app --reload --port 8000
   ```
   The server talks to Nomba sandbox for provisioning/lookups; this script only talks to the local server over HTTP, so it never hits the Python-3.14 TLS issue on Nomba/Supabase.

2. **`.env` contains** `JWT_SECRET_KEY` (used to mint JWTs) and `NOMBA_WEBHOOK_SECRET=NombaHackathon2026` (used to sign webhooks). Both are already present.

3. Python deps: `requests`, `python-jose`, `certifi` (all already installed in the venv).

## Run

```powershell
cd "C:\MyFiles\DOCUMENT-2026\Nuelo_Poc\NULO-DEV"
python docs\hackathon\rest-client\e2e_nomba_flow.py
```

Override defaults via env vars:
```powershell
$env:NOMBA_E2E_BASE_URL="http://localhost:8000/api/v1"
$env:AGREEMENT_ID="8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
$env:LANDLORD_BANK_ACCOUNT="0000000000"   # for lookup-bank
$env:LANDLORD_BANK_CODE="035"              # for lookup-bank
python docs\hackathon\rest-client\e2e_nomba_flow.py
```

Exit code `0` = all steps passed; non-zero = at least one step failed (CI-friendly).

## What it verifies (10 steps)

| # | Step | Asserts |
|---|---|---|
| 1 | `GET /health/nomba` | 200 + `nomba_auth: true` |
| 2 | `POST /agreements/{id}/provision-nomba` | 200 (Path B sub-account VA, idempotent) |
| 3 | `GET /agreements/{id}/payment-status` BEFORE | 200 + learns real `expected_amount` |
| 4 | `POST /webhooks/nomba/transfer` × 4 | full/under/over/misdirected all 200 |
| 5 | replay full_payment (same `requestId`) | second call → `already_processed` (idempotency) |
| 6 | bad signature | 401 |
| 7 | `GET .../payment-status` AFTER | `transfer_history` non-empty (validates `-SUB`-aware query) |
| 8 | `POST /disbursements/lookup-bank` | 200 + verified account |
| 9 | `POST /agreements/{id}/disburse` | 200 + `merchant_tx_ref` (uses `force:true` test override) |
| 10 | `GET /disbursements/{merchant_tx_ref}` | 200 |

All four webhook payloads (step 4) carry `aliasAccountReference = f"{agreement_id}-SUB"` and `merchant.userId = NOMBA_SUB_ACCOUNT_ID` — the exact shape Nomba sends for a Path-B sub-account VA.

## Notes / honest caveats

- **Step 9 (disburse) passes `force: true`** — the documented hackathon test override that bypasses the `FULL_PAYMENT` gate (the latest transfer may be an `underpayment`/`misdirected` from step 4). **Remove `force` for any real flow** (PRD V3 OPEN #3 — auto-disburse is the Stage-2 fix).
- **Step 2 returns 200 even if the VA already exists** — the provision route is idempotent (recovery branch reuses an existing VA). Look for the NUBAN in the response body.
- **The four scenario amounts are ratio-based** off the real `expected_amount` fetched in step 3 (default fallback 990,000), so reconciliation labels stay correct even if the agreement's expected amount differs.
- **TLS**: the script uses `certifi`'s CA bundle for any HTTPS calls (header health checks etc. are plain HTTP to localhost). If you point `BASE_URL` at the live `https://api.nuloafrica.com`, certifi avoids the Python-3.14 "unable to get local issuer certificate" failure.
