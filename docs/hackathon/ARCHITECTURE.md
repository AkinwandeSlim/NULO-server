# NuloAfrica Architecture & Security Note

> **Submission document for DevCareer Nomba Hackathon 2026 (July 1-7)**
> **Hackathon track:** Virtual Accounts as Infrastructure
> **Version:** 1.0 (frozen for submission; living document post-hackathon)
> **Last updated:** 2026-06-30

This document is the single source of truth for the NuloAfrica platform architecture, covering the four mandatory submission areas:

1. **System architecture** (component diagram, data flow, deployment)
2. **Auth** (Supabase Auth + JWT, role gating, route protection)
3. **Webhooks** (Nomba signature verification, Paystack, idempotency, retry policy)
4. **Data handling** (Supabase tables, RLS, PII, encryption, soft-deletion)

It also documents the **Nomba integration architecture** in detail, the dual-payment-gateway design, and the forward-going architecture (what we expect to evolve post-hackathon and what we expect to stay).

---

## 1. System Architecture

### 1.1 What NuloAfrica is

A zero-agency-fee rental marketplace for Nigerian cities (Lagos, Abuja, Port Harcourt). Two-sided platform: **landlords list properties** (verified through KYC), **tenants search and apply** (pay rent via dedicated virtual accounts).

### 1.2 High-level component diagram

```
                           +-------------------+
                           |   End users       |
                           | (landlords,       |
                           |  tenants, admins) |
                           +---------+---------+
                                     |
                          HTTPS     |     OAuth (Google)
                          JWT       |
                                     v
+-------------------------------------------------------+
|              Frontend (Next.js 16, React 19)         |
|   Vercel-hosted, Tailwind CSS, Vercel Web Analytics   |
|   - App Router with route groups                     |
|   - React Context for auth/dashboard state           |
|   - Middleware-based route protection                |
+--+----------+------------+------------+--------------+
   |          |            |            |
   | REST     | REST       | REST       | REST
   v          v            v            v
+-----------------------------------------------------------+
|              Backend (FastAPI, Python 3.14)              |
|   Render-hosted (https://api.nuloafrica.com)             |
|                                                           |
|  +-------------+  +-------------+  +-------------+       |
|  | /auth/*     |  | /properties |  | /agreements |  ...  |
|  +-------------+  +-------------+  +-------------+       |
|                                                           |
|  +-------------+  +-------------+  +-------------+       |
|  | /webhooks/  |  | /webhooks/  |  | /admin/*    |       |
|  | nomba/...   |  | paystack/.. |  | (gated)     |       |
|  +-------------+  +-------------+  +-------------+       |
|                                                           |
|  +----------------+  +----------------+                  |
|  | Rate limiter   |  | License        |                  |
|  | middleware     |  | middleware     |                  |
|  +----------------+  +----------------+                  |
+--+------------+-------------+--------------+-------------+
   |            |             |              |
   | service    | service     | HTTP         | HTTP
   | role       | role        | (Nomba API)  | (Paystack API)
   v            v             v              v
+---------+  +---------+   +-----------+  +-----------+
| Supabase|  | Supabase|   |   Nomba   |  | Paystack  |
| Auth    |  | Postgres|   | sandbox/  |  | (live)    |
|         |  | (data)  |   |  live     |  |           |
+---------+  +---------+   +-----------+  +-----------+
                |                ^
                |                |  webhooks
                +----------------+
                    (signed)
```

### 1.3 Tech stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | Next.js 16 (App Router) + React 19 | SSR, route protection, image optimization |
| Styling | Tailwind CSS + custom orange gradient theme | Industry-standard benchmarking, conversion-optimized |
| State | React Context (auth, dashboard) + TanStack-style fetches | No Redux, deliberately simple |
| Analytics | Vercel Web Analytics | Page metrics, conversion tracking |
| Backend | FastAPI + Python 3.14 | Async, type-safe, fast |
| Auth | Supabase Auth + custom JWT | Email/password, Google OAuth, magic links |
| Database | Supabase PostgreSQL | Shared primary-key pattern (see §4.2) |
| Storage | Supabase Storage (private buckets + signed URLs) | Profile images, verification docs, property photos |
| Payments — existing | Paystack (card, bank transfer) | Pre-hackathon flow |
| Payments — new | **Nomba Virtual Accounts** | Hackathon scope, multi-frequency rent collection |
| Notifications | Twilio (SMS) + SMTP (email) | Tenant/landlord alerts |
| AI | Groq API (Llama) | Agreement generation, document processing |
| Hosting — backend | Render (Docker-free Python service) | `https://api.nuloafrica.com` |
| Hosting — frontend | Vercel | Edge CDN, ISR |

### 1.4 Deployment topology

| Environment | Frontend | Backend | Database |
|-------------|----------|---------|----------|
| **Local dev** | `localhost:3000` | `localhost:8000` | Supabase cloud (test project) |
| **Staging** | Vercel preview | Render preview | Supabase cloud (test project) |
| **Production** | `nuloafrica.com` (Vercel) | `api.nuloafrica.com` (Render) | Supabase cloud (live project) |

A single Render service runs the FastAPI app. All env vars are set in the Render dashboard — nothing in the repo. The frontend reads `NEXT_PUBLIC_API_URL` at build time.

### 1.5 Repository layout

```
NULO-DEV/                          (frontend, Next.js)
server/                            (backend, FastAPI)
  app/
    routes/                        (one file per resource: properties, agreements, nomba, ...)
    services/                      (business logic: nomba_client, payment_scheduler, ...)
    middleware/                    (auth, rate_limit, license)
    models/                        (Pydantic schemas)
  scripts/                         (simulate_nomba_webhook.py, etc.)
  tests/                           (pytest: test_nomba_webhook.py, etc.)
  migrations -> docs/sql/migrations/
docs/
  prd/                             (product requirements, integration plan)
  architecture/                    (this document, comparison docs)
  security/                        (SECURITY.md, threat model)
  hackathon/                       (PRD, training, copilot spec)
  sql/migrations/                  (versioned SQL, run in order)
```

---

## 2. Authentication (Auth)

### 2.1 Identity model

NuloAfrica has three identity roles, all stored in Supabase Auth's `auth.users` table with shared primary keys into role-specific profile tables:

| Role | Profile table | Capabilities |
|------|---------------|--------------|
| `landlord` | `landlord_profiles` | List properties, receive rent, message tenants |
| `tenant` | `tenant_profiles` | Search properties, apply, sign agreements, pay rent |
| `admin` | `admin_profiles` (gated) | Verify landlords, moderate listings, view audit log |

The shared-PK pattern means `landlord_profiles.id` equals the user's `auth.users.id`. This is a deliberate simplification — no separate `user_id` column on profile tables. The cost is the loss of "soft user → many profiles" modeling, which we don't need.

### 2.2 Sign-in flow

```
User submits email + password (or clicks Google)
        |
        v
POST /api/v1/auth/signin (or /api/v1/auth/google)
        |
        v
Supabase Auth validates credentials
        |
        v
Backend issues short-lived JWT (HS256, 30-min expiry)
containing { sub: user_id, role: landlord|tenant|admin, iat, exp }
        |
        v
Frontend stores JWT in httpOnly cookie + in-memory for API calls
        |
        v
GET /api/v1/users/me (or context-provided) returns full profile
```

### 2.3 Google OAuth

```
User clicks "Sign in with Google"
        |
        v
Redirect to Supabase OAuth endpoint with redirect_uri
        |
        v
User authorizes in Google
        |
        v
Google redirects to /api/v1/auth/google/callback?code=...
        |
        v
Backend exchanges code for tokens via Supabase
        |
        v
Backend creates auth.users row if new, then issues our JWT
        |
        v
Redirect to frontend /auth/callback?token=...
        |
        v
Frontend stores JWT, calls /users/me to get role + profile
```

### 2.4 Route protection — middleware stack

Every request passes through this stack in [main.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/main.py):

| Middleware | Purpose | Bypass |
|------------|---------|--------|
| CORS | Allow `nuloafrica.com`, `localhost:3000` | n/a |
| License check | Verify platform license is active (anti-piracy) | `/api/v1/health/*` |
| Rate limiter | 100 req/min per IP, 10 req/sec per user | Webhook endpoints (high-volume) |
| Auth (FastAPI Depends) | Validate JWT, attach `current_user` | `/api/v1/auth/*`, `/api/v1/webhooks/*` |

`get_current_user` lives in [auth.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/middleware/auth.py) and is the only place JWT validation happens. All protected routes depend on it.

### 2.5 Role gating

Two layers of authorization:

1. **Coarse role check** — `current_user["role"] in {"landlord", "admin"}` to allow property CRUD
2. **Fine-grained resource check** — `current_user["id"] in (agreement["tenant_id"], agreement["landlord_id"])` to allow payment status / viewing

Admin-only endpoints live under `/api/v1/admin/*` and check `current_user["role"] == "admin"` explicitly. There is no "implicit admin" — every admin endpoint declares its requirement.

### 2.6 Token expiry handling

- JWT access tokens expire in 30 minutes
- Frontend `apiClient` interceptor ([client.ts](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/client/lib/api/client.ts)) catches 401 responses and triggers a silent refresh via Supabase's refresh-token cookie
- If refresh fails, the user is redirected to `/signin` with a flash message
- Dashboard stats and sensitive fetches happen in `DashboardContext` with role-gated queries (server re-verifies role on every request)

---

## 3. Webhooks

The platform has two webhook receivers, each with a fundamentally different signature scheme. This is the most security-critical part of the system.

### 3.1 Nomba virtual account webhooks

**Endpoint:** `POST /api/v1/webhooks/nomba/transfer`
**URL for submission:** `https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer`

**Signature scheme:**
- Algorithm: **HMAC-SHA256** (NOT SHA512)
- Input: colon-joined string of **9 specific payload fields** (NOT raw body)
- Output: **base64** (NOT hex)
- Headers: `nomba-signature`, `nomba-timestamp` (both required)
- Comparison: `hmac.compare_digest()` after `.lower()` on both sides (case-insensitive, per Nomba's own sample code)

**The 9-field hash construction:**
```
f"{event_type}:{request_id}:{user_id}:{wallet_id}:"
f"{transaction_id}:{transaction_type}:{transaction_time}:"
f"{response_code}:{nomba_timestamp}"
```

**Verified test vector (confirmed match against Nomba's published sample):**
```
secret:  HkatexKDZg7CLWy96q5sfrVHSvtoz92B
input:   payment_success:45f2dc2d-...:b7b10e81-...:6756ff80...:API-VACT_TRA-...:vact_transfer:2025-09-29T10:51:44Z::2025-09-29T10:51:44Z
output:  Kt9095hQxfgmVbx6iz7G2tPhHdbdXgLlyY/mf35sptw=
```

Implementation: [nomba_client.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/services/nomba_client.py#L246-L289)

**Implementation order in webhook handler (never change):**
1. Read `nomba-signature` and `nomba-timestamp` headers
2. Parse JSON body
3. Verify signature → **401 if invalid, nothing written to DB**
4. Check idempotency on `requestId` → **200 if duplicate**
5. Insert into `virtual_account_transfers` (audit trail)
6. Dispatch reconciliation if `event_type=payment_success` AND `type=vact_transfer`
7. **Always return 200** after step 5 — reconciliation errors are async problems, not retry triggers

Implementation: [nomba.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/routes/nomba.py#L155-L237)

**Retry policy:** Nomba retries non-2xx responses up to 5 times (2m → 5m → 11m → 24m → 53m, ~95 min total). A 500 from a reconciliation bug would cause 5 duplicate attempts. **This is why we return 200 after step 5.**

**Idempotency:** `virtual_account_transfers.nomba_request_id` has a UNIQUE constraint. Duplicate webhooks hit the existing-row check in step 4 and return 200 without re-processing.

### 3.2 Paystack webhooks (existing)

**Endpoint:** `POST /api/v1/webhooks/paystack`
**Signature scheme (DIFFERENT from Nomba):**
- Algorithm: **HMAC-SHA512** (NOT SHA256)
- Input: **raw request body** (NOT a constructed string)
- Output: **hex** (NOT base64)
- Header: `x-paystack-signature`
- Comparison: `hmac.compare_digest()`

This is intentionally different from Nomba. Paystack signs the literal bytes; Nomba signs a constructed string. **Do not mix these up — copy-pasting one verifier into the other will silently fail.** This is documented as Rule 21 in the architecture rules.

### 3.3 Why two different schemes

We use both gateways simultaneously because they serve different payment flows:

| Gateway | Use case | Signature |
|---------|----------|-----------|
| Paystack | Tenant pays first month's rent + deposit (one-time card/bank) | SHA512 over raw body |
| Nomba | Multi-frequency recurring rent (monthly/quarterly/annual) into dedicated virtual accounts | SHA256 over 9-field string |

A new agreement has a SIGNED status. Once signed, either the tenant can pay through Paystack (one-shot) or the landlord can provision a Nomba virtual account for ongoing rent. The two flows write to different transactions rows tagged with `payment_gateway`.

### 3.4 Webhook security summary

| Concern | Mitigation |
|---------|-----------|
| Forged webhook | Signature verification BEFORE any DB write |
| Replay attack | Idempotency check on `requestId` / `reference` |
| Retry storm | Always 200 after signature + audit insert |
| Timing attack on signature | `hmac.compare_digest()` (constant-time) |
| Case-mismatch in signature | `.lower()` on both sides (Nomba-specific) |
| Timestamp replay | Out of scope for hackathon (replay window is ~95 min via Nomba's retry policy; signature alone is the gate) |
| Secrets in code | All env-vars via Render dashboard |
| Open ports | Only `https://api.nuloafrica.com` exposed; no SSH, no direct DB |

---

## 4. Data Handling

### 4.1 Storage topology

| Data | Where | Encrypted at rest | Access pattern |
|------|-------|-------------------|----------------|
| User credentials (email, hashed pwd, OAuth tokens) | Supabase Auth (`auth.users`) | Yes (Supabase-managed) | Service role only |
| User profiles (landlord, tenant) | `public.landlord_profiles`, `public.tenant_profiles` | Yes (Supabase-managed) | RLS + service role |
| Property listings | `public.properties` | Yes | RLS + service role |
| Agreements (signed PDFs, AI terms) | `public.agreements` | Yes | RLS + service role |
| Transactions (rent payments) | `public.transactions` | Yes | RLS + service role |
| Verification docs (NIN, selfie, proof of address) | Supabase Storage `landlord-verification` bucket (private) | Yes | **1-hour signed URLs only** |
| Property photos | Supabase Storage `property-photos` bucket (public) | Yes | Public CDN |
| Profile avatars | Supabase Storage `avatars` bucket (public) | Yes | Public CDN |
| Nomba virtual account transfers | `public.virtual_account_transfers` (new) | Yes | Service role only |
| Reconciliation audit log | `public.payment_reconciliation_log` (new) | Yes | Service role only |

### 4.2 The shared-PK pattern

To keep queries simple and avoid join cost, every "profile" or "resource owned by a user" table uses the user's `auth.users.id` as its primary key:

```
auth.users.id  ==  landlord_profiles.id  ==  properties.landlord_id  ==  agreements.landlord_id
auth.users.id  ==  tenant_profiles.id    ==  applications.user_id    ==  agreements.tenant_id
```

Pros: zero indirection, "this user's properties" is `WHERE landlord_id = me`, no FK to a separate `users` table.
Cons: a user can only be one role at a time. We don't need multi-role users.

The trade-off is explicit and documented. **For future multi-role support, we'd add a `user_roles` join table and migrate FKs — see §7.3.**

### 4.3 Row-Level Security (RLS)

Supabase RLS is enabled on every public table. Policies follow three patterns:

1. **Owner can read/write own rows** — e.g., `auth.uid() = landlord_profiles.id`
2. **Public can read active rows** — e.g., `properties.verification_status = 'approved' AND deleted_at IS NULL`
3. **Service role bypasses** — backend uses `supabase_admin` (service role key) for all writes

The `supabase_admin` client bypasses RLS by design. This is Rule 18 of our architecture rules. **An anon key is never used in the backend.**

### 4.4 Soft deletion

Properties, agreements, and landlord profiles use `deleted_at TIMESTAMPTZ` for soft deletion. Filters always include `deleted_at IS NULL` in:

- Backend query helpers (e.g., `get_landlord_properties`)
- Frontend `useMemo` filters in dashboards (defense in depth against cache snapshots)
- RLS policies (where applicable)

Hard deletion only happens for:
- Admin-purged records (after a 90-day grace period)
- Test/seed data cleared during migrations

### 4.5 PII handling

| PII field | Where | Protection |
|-----------|-------|-----------|
| BVN (Bank Verification Number) | Nomba response only (not stored) | Nomba-proxied; we discard immediately |
| NIN (National ID) | `landlord_verifications.nin_document_url` (storage path) | Private bucket + 1-hour signed URL on read |
| Selfie photos | `landlord_verifications.selfie_url` | Private bucket + 1-hour signed URL |
| Proof of address | `landlord_verifications.proof_of_address_url` | Private bucket + 1-hour signed URL |
| Property ownership proof | `landlord_verifications.property_ownership_proof` | Private bucket + 1-hour signed URL |
| BVN-decoded names | Never stored | Nomba returns the BVN holder's name on the account creation; we use it for `accountName` only |
| Bank account numbers | `agreements.virtual_account_number` | Encrypted at rest; only shown to the agreement's tenant + landlord |

**The 1-hour signed URL pattern** is enforced in the admin verification detail endpoint. Direct file paths are never returned to the client.

### 4.6 The Nomba-specific tables (new for hackathon)

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `virtual_account_transfers` | Audit trail of every inbound transfer | `nomba_request_id` (UNIQUE), `account_ref`, `amount_received`, `sender_name`, `sender_bank`, `raw_payload`, `signature_valid` |
| `payment_reconciliation_log` | Audit trail of every reconciliation decision | `previous_status`, `new_status`, `expected_amount`, `received_amount`, `variance_pct` |

The `transactions` table was extended with a new CHECK value: `nomba_collection`. This is cleaner than JSONB `notes.metadata.payment_gateway` because it keeps SQL analytics simple (`WHERE transaction_type = 'nomba_collection'` works without casting).

Migrations: [docs/sql/migrations/002_add_nomba_columns_to_agreements.sql](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/docs/sql/migrations/002_add_nomba_columns_to_agreements.sql), [003_create_nomba_tables.sql](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/docs/sql/migrations/003_create_nomba_tables.sql)

---

## 5. The Nomba Integration Architecture

### 5.1 The problem we solve

Nigerian landlords want annual rent upfront (70% of the rental market). Tenants want monthly. The market is split.

### 5.2 The solution

Each **signed agreement** gets a **dedicated Nomba virtual account** under NuloAfrica's sub-account. The tenant transfers rent into this NUBAN at whatever frequency the agreement specifies. We reconcile every inbound transfer automatically.

### 5.3 Data flow

```
+----------+                          +-------------+
| Tenant   |  signs agreement         | Agreement   |
|          |  (status: SIGNED)        | row         |
+----+-----+                          +------+------+
     |                                        |
     | clicks "Pay rent"                     |
     v                                        |
+----------+                                  |
| Backend   |  POST /agreements/{id}/provision-nomba
| route     |-------------------------------->+
+----------+                                  |
                                              v
                                    +---------------------+
                                    | nomba_helpers.      |
                                    | calculate_expected  |
                                    | _amount(rent, freq) |
                                    +----------+----------+
                                               |
                                               v
                                    +---------------------+
                                    | nomba_client.       |
                                    | create_virtual_     |
                                    | account()           |
                                    +----------+----------+
                                               |
                                  POST /accounts/virtual/{SUB_ACCOUNT_ID}
                                  Headers: Bearer + accountId (parent)
                                               |
                                               v
                                    +---------------------+
                                    |   Nomba API         |
                                    +----------+----------+
                                               |
                                  Returns NUBAN + accountName
                                               |
                                               v
                                    +---------------------+
                                    | UPDATE agreements   |
                                    | SET virtual_account |
                                    | _number, _name, ... |
                                    +----------+----------+
                                               |
                                               v
                                    +---------------------+
                                    | BackgroundTasks:    |
                                    | notify tenant       |
                                    +---------------------+

[Later, when tenant transfers money]

     Tenant transfers to NUBAN
              |
              v
+----------------------------------+
| Nomba server sends webhook       |
| POST /webhooks/nomba/transfer    |
| Headers: nomba-signature, ts     |
+----------------------------------+
              |
              v
+----------------------------------+
| 1. Read headers                 |
| 2. Parse JSON                   |
| 3. Verify HMAC-SHA256 signature |
|    (9-field string hash)        |
|    -> 401 if invalid            |
+----------------------------------+
              |
              v
+----------------------------------+
| 4. Idempotency check on         |
|    requestId (UNIQUE)           |
|    -> 200 if duplicate          |
+----------------------------------+
              |
              v
+----------------------------------+
| 5. INSERT into                  |
|    virtual_account_transfers    |
+----------------------------------+
              |
              v
+----------------------------------+
| 6. _reconcile_payment()         |
|    - match by aliasAccountRef   |
|    - classify as FULL_PAYMENT,   |
|      UNDERPAYMENT, OVERPAYMENT, |
|      or MISDIRECTED             |
|    - update agreements total    |
|    - log to reconciliation_log  |
|    - insert transactions row    |
+----------------------------------+
              |
              v
+----------------------------------+
| 7. Return 200                   |
|    (even if reconciliation err) |
+----------------------------------+
```

### 5.4 The 4 payment frequencies

| Frequency | Multiplier | Grace period | Use case |
|-----------|------------|--------------|----------|
| `MONTHLY` | 1× rent | 1 day | Tenant pays month-to-month |
| `QUARTERLY` | 3× rent | 3 days | Tenant pays every 3 months |
| `SEMI_ANNUAL` | 6× rent | 5 days | Tenant pays every 6 months |
| `ANNUAL` | 12× rent | 7 days | Tenant pays full year upfront (landlord-preferred) |

Helper: [nomba_helpers.py](file:///c:/MyFiles/DOCUMENT-2026/Nuola_Poc/NULO-DEV/server/app/services/nomba_helpers.py) — `calculate_expected_amount`, `classify_payment`, `is_within_grace_period`.

### 5.5 The 6 reconciliation states

| State | Meaning | Triggered by |
|-------|---------|--------------|
| `PENDING` | Account created, no transfer yet | Initial state, or `expected_amount = 0` |
| `FULL_PAYMENT` | Received ≈ expected (±2% tolerance) | `abs((received - expected) / expected) <= 0.02` |
| `UNDERPAYMENT` | Received < expected (outside tolerance) | `received < expected * 0.98` |
| `OVERPAYMENT` | Received > expected (outside tolerance) | `received > expected * 1.02` |
| `MISDIRECTED` | Transfer to unknown account ref | `accountRef` not found in `agreements` |
| `DUPLICATE` | Same `requestId` already processed | Caught at idempotency layer (never reaches classifier) |

The 2% tolerance absorbs bank fees and rounding. This is a deliberate trade-off documented in the helper file.

### 5.6 The 4 endpoints

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `/api/v1/agreements/{id}/provision-nomba` | POST | Create a NUBAN for a SIGNED agreement | JWT (tenant or landlord on agreement) |
| `/api/v1/webhooks/nomba/transfer` | POST | Receive Nomba transfer notifications | HMAC signature |
| `/api/v1/agreements/{id}/payment-status` | GET | Show current paid / expected / status | JWT (tenant or landlord on agreement) |
| `/api/v1/health/nomba` | GET | Health check for judges + monitoring | None (returns auth state) |

Full source: [nomba.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/routes/nomba.py)

### 5.7 The Nomba API source-of-truth hierarchy

When the live Nomba docs contradict the training/certification doc, the training doc wins. The training doc is written by Nomba engineers; some live-docs pages are written by non-technical staff and are out of date. Specific facts pinned by the training doc:

| Fact | Value | Source |
|------|-------|--------|
| Token lifetime | 60 minutes | Training doc |
| Token refresh | `POST /v1/auth/token/refresh` | Live API + training |
| Virtual account URL | `/accounts/virtual/{sub_account_id}` | Live API |
| `expectedAmount` format | decimal Naira, JSON number (float) | Live OpenAPI spec |
| Signature comparison | case-insensitive | Nomba sample code |
| Webhook timestamp header | `nomba-timestamp` | Live API |

This hierarchy is documented in [SECURITY.md](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/docs/SECURITY.md) under "API Source-of-Truth Hierarchy."

### 5.7.1 Per-endpoint amount convention

**This is a real Nomba API inconsistency that catches teams off-guard.** Different Nomba endpoints use different amount conventions:

| Endpoint | `amount` field | Convention | Our usage |
|----------|----------------|------------|-----------|
| `/v1/accounts/virtual` (`expectedAmount`) | decimal Naira (float) | We use this | Hackathon: yes |
| `/v2/transfers/bank/{subAccountId}` (`amount`) | decimal Naira (float) | We use this | Hackathon: yes (Phase 3) |
| `/v1/orders` (checkout) | kobo (int) | We do NOT use | N/A |
| `/v1/accounts/virtual/{id}/orders` | kobo (int) | We do NOT use | N/A |

**Verified by:**
- Virtual accounts: PRD Part 0 + production webhook example (`transactionAmount: 10` matching "Transfer 10.00")
- Transfers: OpenAPI spec, type: number, format: double
- Orders: Nomba community Discord thread, 2026-07-01

**No env var controls this.** If a future endpoint uses kobo, the fix is per-method, not global — add an `amount_format` parameter to that method explicitly. Do NOT introduce a `NOMBA_AMOUNT_FORMAT` env var (it was the v1 PRD idea, it was removed because the per-endpoint inconsistency can't be expressed as a single toggle).

---

## 6. Architecture Rules (Hammer These)

These rules came from real bugs. They are non-negotiable for this codebase. Each rule has caused a production issue at least once.

| # | Rule | Why |
|---|------|-----|
| 5 | `BackgroundTasks` parameter must come BEFORE `Depends()` in route signatures | FastAPI dependency ordering — wrong order breaks the dependency tree silently |
| 6 | All Supabase calls in async FastAPI routes must use `asyncio.get_event_loop().run_in_executor()` | Supabase's Python client is sync — calling it directly from async blocks the event loop |
| 7 | Specific routes (`/agreements/{id}/provision-nomba`) must be registered BEFORE wildcard routes (`/agreements/{id}`) | FastAPI matches in registration order — wildcards would shadow specifics |
| 17 | No Unicode characters in any `.py` file | Render build issues with non-ASCII log messages and JSON serialization edge cases |
| 18 | Backend always uses `supabase_admin` (service role), never the anon key | RLS bypass is required for cross-tenant operations; the anon key would 401 |
| 21 | Paystack webhooks use SHA512 over raw body; Nomba webhooks use SHA256 over 9-field string. **Do not mix.** | Different signature schemes, both verified — copy-pasting one verifier into the other silently fails verification |

---

## 7. What Will Change Post-Hackathon vs What Will Stay

This is the part that matters for the architecture's longevity. The hackathon is one deadline; the platform will run for years.

### 7.1 What will stay (the bones)

| Component | Why it stays |
|-----------|--------------|
| The shared-PK pattern | It's the right model for our role structure |
| Supabase Auth + custom JWT | The 30-min expiry + refresh flow is industry standard |
| Webhook signature verification (Nomba, Paystack) | The security guarantees are non-negotiable |
| Soft deletion pattern | We need to preserve audit trail; hard-deletes would lose compliance value |
| RLS on all public tables | Defense in depth, even though backend uses service role |
| The 4 endpoint structure for Nomba | Provision, webhook, status, health — minimum viable surface |

### 7.2 What may evolve (with explicit triggers)

| Component | Evolution trigger | Target |
|-----------|-------------------|--------|
| `expectedAmount` field | Day 1 sandbox test confirms whether kobo vs decimal is real | Likely stays decimal; verified by training doc |
| Token caching in-process | Multi-instance Render deployment | Move to Redis-backed token cache (5-line change in `_get_token`) |
| Reconciliation engine | Volume >1000 transfers/day | Move to background queue (Celery or RQ) instead of inline in webhook |
| `nomba_collection` transaction type | Adding more gateways (e.g., Flutterwave) | Add `flutterwave_collection`, leave the others as-is |
| 1-hour signed URLs on verification docs | Adding admin "download all" feature | Switch to a single batched signed URL with longer expiry |
| Number input `handleNumberChange` | Tenant enters "0123" expecting Naira | Already handled, stays as-is |
| `ENABLE_PROPERTY_STEP` onboarding flag | Product decision on whether Step 3 is required | Either remove the flag or remove Step 3 |
| `deleted_at IS NULL` filters | If we add admin "show deleted" view | Add a query param `?include_deleted=true` (gated to admin role) |

### 7.3 What is explicitly deferred (post-hackathon roadmap)

- Multi-role users (would require a `user_roles` join table)
- Admin analytics dashboard
- Payment schedule calendar UI
- Nightly reconciliation cron
- Tokenized cards / direct debits / mandates
- Outbound Nomba transfers (payouts to landlord bank accounts)

These are documented in the post-hackathon roadmap section of [NOMBA_INTEGRATION_REVIEW_AND_IMPLEMENTATION_PLAN.md](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/docs/prd/NOMBA_INTEGRATION_REVIEW_AND_IMPLEMENTATION_PLAN.md).

---

## 8. Submission-Specific Notes

### 8.1 Why this architecture wins the hackathon

The hackathon judges care about three things:
1. **Depth over breadth** — one integration done well beats five half-done
2. **Real problem solved** — multi-frequency rent is a real Nigerian rental market pain
3. **Production-ready code** — webhook security, idempotency, audit trail, test coverage

We win on all three:
1. We implemented one integration (Nomba virtual accounts) deeply — token lifecycle, signature verification, 6 reconciliation states, full audit trail
2. The 70%/30% landlord/tenant market split is a real friction point
3. Our webhook handler is hardened (HMAC + idempotency + always-200), our test suite has 25 tests including the verified Nomba test vector, and we have end-to-end Thunder Client test plans

### 8.2 What the judges will verify

| Check | Where |
|-------|-------|
| Webhook signature works | `GET /api/v1/health/nomba` returns `nomba_auth: true` |
| Idempotency works | Replay same webhook → `already_processed` |
| Reconciliation logic works | Webhook with `transactionAmount` different from `expected_payment_amount` → status changes |
| Test coverage exists | `pytest server/tests/test_nomba_webhook.py` runs clean |
| Security is documented | This document, [SECURITY.md](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/docs/SECURITY.md) |
| Code is clean | No Unicode in `.py` files (Rule 17), no `==` for signature comparison, no `supabase_anon` |

### 8.3 Test credentials (for judges)

#### Platform Test Accounts
| Role | Email | Password | Purpose |
|------|-------|----------|---------|
| Landlord | raphawellnessoptimization@gmail.com | nombahackathon2026 | Property listing, agreement management, disbursement testing |
| Tenant | mediaslim0705@gmail.com | nombahackathon2026 | Property search, applications, payment simulation |

#### Nomba Environment Credentials
| Environment | URL | Auth |
|-------------|-----|------|
| Sandbox | `https://sandbox.nomba.com/v1` | `NOMBA_TEST_CLIENT_ID` / `NOMBA_TEST_CLIENT_SECRET` in Render env |
| Live | `https://api.nomba.com/v1` | `NOMBA_LIVE_CLIENT_ID` / `NOMBA_LIVE_CLIENT_SECRET` in Render env |
| Webhook signing key | n/a | `NOMBA_WEBHOOK_SECRET=NombaHackathon2026` |

#### Parent-Subaccount Setup
- **Parent Account ID:** `f666ef9b-888e-4799-85ce-acb505b28023`
- **Subaccount ID:** `282e5b9b-d14f-4e43-840d-43ddfd90a071`
- **Webhook URL:** `https://api.noloafrica.com/api/v1/webhooks/nomba/transfer`
- All virtual accounts and disbursements use the sub-account for proper webhook routing and spendable balance access.

For local testing, `server/.env.example` has placeholder values. The webhook simulator at `server/scripts/simulate_nomba_webhook.py` generates valid signed payloads without needing real Nomba credentials.

---

## 9. File Manifest (Architecture-Critical Files)

### New files (hackathon scope)
```
server/app/services/nomba_client.py        # HMAC + token lifecycle
server/app/services/nomba_helpers.py       # Amount/frequency logic
server/app/routes/nomba.py                 # 4 endpoints
server/tests/test_nomba_webhook.py         # 25 unit tests
server/scripts/simulate_nomba_webhook.py   # Test payload generator
docs/sql/migrations/001_add_payment_frequency_to_properties.sql
docs/sql/migrations/002_add_nomba_columns_to_agreements.sql
docs/sql/migrations/003_create_nomba_tables.sql
docs/architecture/ARCHITECTURE.md          # This document
```

### Modified files
```
server/app/main.py                         # Registered nomba router
server/.env.example                        # Added NOMBA_* vars
```

### Files NOT touched (architectural stability)
```
server/app/routes/payments.py              # Paystack flow unchanged
server/app/routes/agreements.py            # Existing agreement CRUD unchanged
server/app/middleware/auth.py              # JWT logic unchanged
```

---

## 10. Glossary

| Term | Meaning |
|------|---------|
| **NUBAN** | Nigerian Uniform Bank Account Number — 10-digit bank account number |
| **Virtual account** | A Nomba-provided NUBAN that routes incoming transfers to a parent wallet, identified by a stable `accountRef` (we use `agreement.id`) |
| **Sub-account** | A Nomba account identifier under the parent account; funds route to the parent by default if omitted from URL |
| **accountRef** | A string you provide to Nomba to tag a virtual account; we use our `agreement.id` (UUID) |
| **HMAC-SHA256** | A keyed hash; you hash the message with a shared secret and compare hashes to verify the sender |
| **Idempotency** | The property that the same request processed twice produces the same result and no duplicate side effects |
| **Reconciliation** | Matching an inbound payment to an expected invoice and updating the agreement's paid/owing status |
| **Tolerance** | The ±2% band around `expected_amount` that we treat as a "full" payment; absorbs bank fees and rounding |
| **Misdirected** | A payment received for an `accountRef` we don't recognize (orphan / wrong tenant) |

---

*This document is intentionally verbose — it is both the hackathon submission artifact AND the post-hackathon engineering onboarding document. New engineers should be able to read this and understand every architectural decision in the system.*
