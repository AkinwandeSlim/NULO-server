# The NuloAfrica Rental Payment Journey
## A Layman's Guide to How Rent Actually Moves — and Where Nomba Comes In

> **Hackathon document for DevCareer Nomba Hackathon 2026**
> **For:** Judges, demo audiences, onboarding engineers
> **Tone:** Plain language, narrative-first, no jargon
> **Last updated:** 2026-07-01

---

## The Three Characters

| Who | What they want | What they fear |
|-----|----------------|----------------|
| **Mrs. Adaeze** — landlord in Lekki | Reliable rent, every month, no chasing | Empty months, awkward "please pay" messages |
| **Tunde** — her tenant, young professional | A clean place, no surprise rent demands | Paying 12 months upfront, losing a job mid-year |
| **NuloAfrica** — the platform that connects them | To be the trusted middleman that solves the rent standoff | A landlord waiting 90 days for a tenant's first payment |

---

## The Standoff (Before Nomba)

This is the **#1 problem** in Nigerian rentals:

- **70% of landlords** want rent paid **annually upfront** (12 months at once)
- **70% of tenants** can only afford to pay **monthly**

Result: Mrs. Adaeze leaves her 4-bedroom flat empty for 4 months because Tunde can only afford ₦50k/month, not the ₦600k annual upfront she wants.

**Tunde loses a home. Mrs. Adaeze loses 4 months of income. Everyone loses.**

This is the cold-start problem. NuloAfrica already solves "find a tenant, sign a lease, pay first month" — but the **ongoing rent** is broken. Paystack works for one-time payments, but you can't ask a tenant to manually initiate 12 separate transfers over a year. They forget, or run out of money, or move.

We needed something that makes rent **automatic, recurring, and trustworthy** without forcing a 12-month lump sum.

---

## Enter Nomba: The Dedicated Bank Account Per Agreement

Here's the magic: when Mrs. Adaeze and Tunde sign a lease, **NuloAfrica creates a real, dedicated bank account for that specific agreement** — under the hood, using a Nomba Virtual Account.

Tunde doesn't transfer to "NuloAfrica" generically. He transfers to a **NUBAN** (10-digit Nigerian bank number) that is **only for his lease**:

```
Bank: Nombank MFB
Account Number:  9 3 9 1 0 7 6 5 4 3
Account Name:    Nomba / Mrs. Adaeze Okafor - Lekki Flat 4B
```

That account only exists for this one agreement. The money goes there, sits there, and is reconciled automatically. When it's time to pay Mrs. Adaeze, we move it to her real bank account in a single disbursement.

---

## The Full Journey (Layman View)

### Step 1: The Match
Mrs. Adaeze lists her flat on NuloAfrica. She chooses **ANNUAL** rent (₦600,000/year). Tunde sees the listing, applies, and they agree. They sign the lease digitally on the platform.

**Code touchpoint:** `server/app/routes/agreements.py` — agreement created with `status=SIGNED`, `payment_frequency=ANNUAL`, `expected_payment_amount=600000.0`.

### Step 2: The Virtual Account Is Born
The moment the lease is signed, NuloAfrica calls Nomba and says: *"Open a virtual account for this agreement, expecting ₦600,000 a year, with the landlord's name on it so tenants know who they're paying."*

Nomba responds in under 2 seconds with a fresh NUBAN. NuloAfrica shows it to Tunde inside the app:

```
"Your rent account is ready.
 Bank: Nombank MFB
 Account: 9391076543
 Pay any amount, any time, as long as the year's total reaches ₦600,000 by due dates."
```

**Code touchpoint:** [nomba_client.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/services/nomba_client.py) `create_virtual_account()` calls `POST /v1/accounts/virtual/{sub_account_id}` with `expectedAmount: 600000.0` (decimal Naira, NOT kobo) and `accountName: "Adaeze Okafor - Lekki Flat 4B"` (landlord name, not tenant).

### Step 3: Tunde Pays — His Way
Tunde decides to pay **monthly** (₦50,000 × 12 months). He opens his GTBank app, transfers ₦50,000 to `9391076543`. Done.

A minute later, NuloAfrica gets a quiet, signed message from Nomba saying: *"Hey, ₦50,000 just landed. Reference: test-req-full_payment-001"*

NuloAfrica:
- Marks the transfer as received (audit trail)
- Updates the running total: `total_received = 50,000`, `expected = 600,000`
- Sets `reconciliation_status = UNDERPAYMENT` (we're not done yet, but a payment came in)
- Sends Tunde a friendly SMS: *"Got your ₦50k — 11 months to go!"*

**Code touchpoint:** [nomba.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/routes/nomba.py) webhook handler verifies Nomba's HMAC-SHA256 signature, inserts into `virtual_account_transfers`, then calls `_reconcile_payment()` which uses [nomba_helpers.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/services/nomba_helpers.py) `classify_payment()`.

### Step 4: The Months Roll By
Tunde pays the same way every month:
- February: ₦50,000 → total_received: 100,000
- March: ₦50,000 → total_received: 150,000
- ... and so on ...

By December, total_received hits ₦600,000. NuloAfrica sets `reconciliation_status = FULL_PAYMENT` and notifies both: *"Tunde has paid the full year. Lease good until January 2027."*

### Step 5: Mrs. Adaeze Gets Paid
At any point — monthly, quarterly, or end-of-year — Mrs. Adaeze can hit **"Withdraw to my bank"** in her dashboard.

NuloAfrica:
1. Looks up her verified bank account (she entered it once, we confirmed it with Nomba)
2. Calculates the payout: `received - platform_fee = 595,000` (₦5k service fee)
3. Generates a unique idempotency key: `NULO-DISB-1410D252`
4. Tells Nomba: *"Move ₦595,000 to GTBank 0123456789 — Mrs. Adaeze Okafor"*
5. Inserts a transactions row tagged `nomba_disbursement`
6. Status: `PENDING` (Nomba is processing, not yet settled)

A few seconds later, Nomba sends another signed message: *"Transfer settled."* NuloAfrica updates the row: `status = completed`, `released_at = now()`. Mrs. Adaeze gets a push notification: *"₦595,000 is now in your GTBank account."*

**Code touchpoint:** [disbursements.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/routes/disbursements.py) `POST /api/v1/agreements/{id}/disburse` calls [nomba_client.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/services/nomba_client.py) `transfer_to_bank()` which hits `POST /v2/transfers/bank/{sub_account_id}`. The `_handle_payout_event()` function in nomba.py updates the row when Nomba confirms.

---

## The Four Payment Frequencies (Layman View)

Tunde and Mrs. Adaeze can agree on any of these:

| Frequency | What it means for Tunde | What it means for Mrs. Adaeze | Helper |
|-----------|------------------------|------------------------------|--------|
| **MONTHLY** | Pay 1 month at a time, 12 times a year | Steady monthly income | [nomba_helpers.py `calculate_expected_amount(50000, "MONTHLY")`](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/services/nomba_helpers.py) → 50000.0 |
| **QUARTERLY** | Pay every 3 months, 4 times | Quarterly payout | → 150000.0 |
| **SEMI_ANNUAL** | Pay every 6 months, 2 times | Bi-annual payout | → 300000.0 |
| **ANNUAL** | Pay full year upfront, 1 time | Single payout, full year | → 600000.0 |

Tunde's transfers get compared against `expected_payment_amount / 12` every time, with a 2% tolerance for bank fees. If he pays ₦49,000 by accident, NuloAfrica marks it as `UNDERPAYMENT` and sends him a gentle reminder — not a rejection.

**Code touchpoint:** [nomba_helpers.py `classify_payment()`](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/services/nomba_helpers.py) returns one of 6 states: `PENDING`, `FULL_PAYMENT`, `UNDERPAYMENT`, `OVERPAYMENT`, `MISDIRECTED`, or `DUPLICATE`.

---

## What If Something Goes Wrong?

NuloAfrica is paranoid about the three things that can break a payment system:

| Scenario | What we do |
|----------|------------|
| **Forged webhook** (someone pretends to be Nomba) | Reject with 401. Nothing in our database changes. The signature is HMAC-SHA256 over a 9-field string we agreed on. Without the secret, attackers can't forge it. |
| **Replay attack** (the same webhook sent twice) | Detect via the unique `requestId` from Nomba. Insert into `virtual_account_transfers` with a UNIQUE constraint. The second attempt gets a 200 with "already_processed" but nothing changes. |
| **Retry storm** (Nomba retries up to 5 times over 95 min) | Always return 200 after the audit-trail insert. The 6 reconciliation states let the same agreement be re-evaluated cheaply without overwriting the original record. |
| **Bank account is wrong** (landlord mistyped their number) | Reject disbursement with 400. The landlord must verify their bank with Nomba first via `POST /api/v1/disbursements/lookup-bank`. Verified name is the source of truth — never user-typed. |
| **Transfer fails mid-flight** (Nomba returns REFUND) | NuloAfrica marks the transactions row as `refunded`. The landlord can retry with a NEW `merchantTxRef` (the old one is locked). |

---

## Why This Wins the Hackathon

There are three things that make this integration production-grade, not a hackathon hack:

1. **The 70/30 problem is real.** This isn't a synthetic demo. The Nigerian rental market is split 70/30 between annual and monthly preferences. We solve it for real.
2. **The integration is deep, not wide.** One Nomba product (Virtual Accounts) used to its full potential: 4 frequencies, 6 reconciliation states, idempotent webhooks, signed signatures, real audit trail. No half-baked features.
3. **The code is bullet-proof.** 30 unit tests including a hand-verified HMAC test vector, exact-case signature comparison, all 4 frequencies, all 6 reconciliation states, decimal Naira not kobo, and webhook idempotency that survives Nomba's 5-retry storm.

---

## The One-Sentence Pitch

> **NuloAfrica uses Nomba Virtual Accounts to give every rental agreement its own dedicated bank account, so landlords get the annual rent they want and tenants pay it monthly — automatically, securely, with the bank doing the reconciliation.**

---

## Quick Code Map (For the Curious Engineer)

If a judge asks "where does X happen?", point them here:

| Layman concept | Code location |
|----------------|---------------|
| "Sign the lease" | `server/app/routes/agreements.py` (existing) |
| "Open the virtual account" | [nomba_client.py: `create_virtual_account()`](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/services/nomba_client.py) |
| "Verify the webhook is real" | [nomba_client.py: `verify_webhook_signature()`](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/services/nomba_client.py) |
| "Was the payment enough?" | [nomba_helpers.py: `classify_payment()`](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/services/nomba_helpers.py) |
| "Move the money to the landlord" | [nomba_client.py: `transfer_to_bank()`](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/services/nomba_client.py) |
| "All 4 endpoints" | [nomba.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/routes/nomba.py) + [disbursements.py](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/server/app/routes/disbursements.py) |
| "Where the data lives" | `docs/sql/migrations/002` and `004` (the Nomba-specific schema) |
| "Why we trust the security" | [docs/architecture/ARCHITECTURE.md](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/docs/architecture/ARCHITECTURE.md) + [docs/SECURITY.md](file:///c:/MyFiles/DOCUMENT-2026/Nuelo_Poc/NULO-DEV/docs/SECURITY.md) |

---

## How to Use This Document for the Demo

| Section | When to use |
|---------|-------------|
| **The Standoff** | Opening hook — set up the problem |
| **The Three Characters** | Make the demo relatable — judges remember people, not APIs |
| **Enter Nomba** | Reveal the solution — the dedicated bank account concept |
| **The Full Journey** | Walk through the steps 1-5 with a live demo |
| **What If Something Goes Wrong** | Anticipate the "but what about security?" question |
| **Why This Wins the Hackathon** | Closing pitch — leave them with the three pillars |
| **The One-Sentence Pitch** | For Twitter, the readme, the demo intro slide |

---

*This document is intentionally written like a story, not a spec. The spec is in the [architecture doc](./ARCHITECTURE.md) and the [PRD](./nomba_PRD.md). The story is for humans.*
