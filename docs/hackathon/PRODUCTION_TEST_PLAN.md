# Nomba Production Test Plan
**Date:** 2026-07-03
**Live URL:** https://api.nuloafrica.com
**Status:** API Live, webhook URL submitted, awaiting activation by Nomba team

---

## Pre-Test Checklist
- [ ] Render deployment is live (confirmed: `/` returns welcome message)
- [ ] Health check endpoint responds OK
- [ ] Supabase database is accessible from production server
- [ ] Webhook URL `https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer` is submitted to Nomba
- [ ] You have a real Nigerian bank account to receive test disbursements (or use the existing UBA account from your local tests)

---

## Phase 1: Health & Auth Verification

### Test 1.1: Health Check
```bash
GET https://api.nuloafrica.com/api/v1/health/nomba
```
**Expected:**
```json
{
  "status": "ok",
  "nomba_auth": true,
  "webhook_url": "https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer",
  "environment": "test"
}
```
**Pass criteria:** `nomba_auth: true` (proves parent account credentials work in production env)

### Test 1.2: API Docs Accessible
```bash
GET https://api.nuloafrica.com/api/docs
```
**Pass criteria:** Swagger UI loads

---

## Phase 2: Virtual Account Provisioning

### Test 2.1: Sign in as a Tenant
1. Go to your frontend (https://nuloafrica.com or wherever it's hosted)
2. Sign in as a tenant
3. Navigate to a signed agreement

### Test 2.2: Trigger Provisioning
```bash
POST https://api.nuloafrica.com/api/v1/agreements/{agreement_id}/provision-nomba
Authorization: Bearer <tenant_or_landlord_jwt>
```
**Expected Response:**
```json
{
  "status": "success",
  "virtual_account_number": "2081650495",
  "virtual_account_name": "Evelyn Ismail - Property Name",
  "expected_amount": 500000.0,
  "frequency": "ANNUAL"
}
```
**Pass criteria:**
- Returns a real NUBAN (10 digits)
- Account name contains landlord's name
- `expected_amount` matches what you set in the agreement

### Test 2.3: Verify in Supabase
In Supabase SQL editor:
```sql
SELECT id, virtual_account_number, virtual_account_name, nomba_account_ref
FROM agreements
WHERE id = '<agreement_id>';
```
**Pass criteria:** All three fields are populated

---

## Phase 3: Inbound Payment (Webhook End-to-End)

### Test 3.1: Make a Real Transfer
Using any Nigerian bank app or web banking:
1. Transfer **exactly NGN 500,000.00** (or your expected amount) to the virtual account number from Test 2.2
2. **Note the transaction time** (Nomba's webhook should arrive within 30 seconds to 5 minutes)

### Test 3.2: Watch Render Logs
In Render dashboard → your service → Logs:
- Look for: `POST /api/v1/webhooks/nomba/transfer`
- Look for: `Nomba webhook received | event=payment_success`
- Look for: `Reconciliation: FULL_PAYMENT`

### Test 3.3: Verify in Supabase

**Check 1: `virtual_account_transfers` table**
```sql
SELECT * FROM virtual_account_transfers
WHERE agreement_id = '<agreement_id>'
ORDER BY created_at DESC LIMIT 1;
```
**Pass criteria:** New row with `reconciliation_result = 'FULL_PAYMENT'`

**Check 2: `payment_reconciliation_log` table**
```sql
SELECT * FROM payment_reconciliation_log
WHERE agreement_id = '<agreement_id>'
ORDER BY created_at DESC LIMIT 1;
```
**Pass criteria:** New audit row with `new_status = 'FULL_PAYMENT'`

**Check 3: `transactions` table**
```sql
SELECT * FROM transactions
WHERE agreement_id = '<agreement_id>'
  AND transaction_type = 'nomba_collection';
```
**Pass criteria:**
- `status = 'held'`
- `amount = 500000.0`
- `nomba_transfer_id` is populated
- `held_at` is set

**Check 4: `agreements` table updated**
```sql
SELECT id, total_received_amount, reconciliation_status
FROM agreements
WHERE id = '<agreement_id>';
```
**Pass criteria:**
- `total_received_amount = 500000.0`
- `reconciliation_status = 'FULL_PAYMENT'`

---

## Phase 4: Webhook Edge Cases (Optional but Recommended)

### Test 4.1: Underpayment
Send NGN 250,000 (50% of expected) to the same virtual account.
**Expected:** `reconciliation_result = 'UNDERPAYMENT'`

### Test 4.2: Overpayment
Send NGN 600,000 (120% of expected).
**Expected:** `reconciliation_result = 'OVERPAYMENT'`

### Test 4.3: Misdirected Payment
Send NGN 100 to a virtual account that doesn't exist (or to a wrong reference).
**Expected:** `reconciliation_result = 'MISDIRECTED'`

### Test 4.4: Idempotency
Send the same payment twice (Nomba should retry).
**Expected:** Second webhook is rejected (no duplicate `virtual_account_transfers` row)

---

## Phase 5: Disbursement Flow

### Test 5.1: Bank Account Verification
```bash
POST https://api.nuloafrica.com/api/v1/disbursements/lookup-bank
Authorization: Bearer <landlord_jwt>
Content-Type: application/json

{
  "account_number": "2081650495",
  "bank_code": "033"
}
```
**Expected Response:**
```json
{
  "account_number": "2081650495",
  "bank_name": "United Bank for Africa",
  "account_name": "Ismail Evelyn",
  "verified_at": "2026-07-03T20:00:00.000Z"
}
```
**Pass criteria:** Returns verified account name (not user-supplied)

**Verify in Supabase:**
```sql
SELECT bank_account_number, bank_name, account_name, bank_verified_at
FROM landlords
WHERE id = '<landlord_id>';
```
**Pass criteria:** All fields populated

### Test 5.2: Trigger Disbursement
```bash
POST https://api.nuloafrica.com/api/v1/agreements/{agreement_id}/disburse
Authorization: Bearer <landlord_jwt>
Content-Type: application/json

{
  "source_transfer_id": "<transfer_id_from_test_3.3>"
}
```
**Expected Response:**
```json
{
  "status": "pending",
  "merchant_tx_ref": "NULO-DISB-XXXXXXXX",
  "amount_ngn": 500000.0,
  "nomba_status": "PENDING_BILLING",
  "transaction_id": "..."
}
```
**Pass criteria:**
- `status = 'pending'`
- `merchant_tx_ref` matches `NULO-DISB-XXXXXXXX` format
- `amount_ngn` matches expected payout

### Test 5.3: Verify in Supabase
```sql
SELECT * FROM transactions
WHERE source_transfer_id = '<transfer_id>'
  AND transaction_type = 'nomba_disbursement';
```
**Pass criteria:**
- Row exists with `status = 'pending'`
- `nomba_transfer_ref = 'NULO-DISB-XXXXXXXX'`
- `nomba_transfer_id` is populated

### Test 5.4: Watch for Payout Webhook
Wait 30 seconds - 5 minutes for Nomba to send `payout_success` webhook.

**Check Render logs:**
- Look for: `event=payout_success`
- Look for: `Transaction status updated to 'released'`

**Verify in Supabase:**
```sql
SELECT status, released_at FROM transactions
WHERE nomba_transfer_ref = 'NULO-DISB-XXXXXXXX';
```
**Pass criteria:**
- `status = 'released'`
- `released_at` is set to current time

### Test 5.5: Check Bank Statement
Log into your bank (UBA) and verify you received NGN 500,000 (or expected payout amount).

---

## Phase 6: Error Handling Tests

### Test 6.1: Unverified Bank
Try to disburse without first calling `/lookup-bank`.
**Expected:** 400 error with message "Landlord bank account has not been verified"

### Test 6.2: Wrong Transfer
Try to disburse using a transfer ID that doesn't belong to the agreement.
**Expected:** 400 error with message "Source transfer does not belong to this agreement"

### Test 6.3: Non-Landlord Access
Try to disburse as the tenant (not the landlord).
**Expected:** 403 error

### Test 6.4: Already Disbursed
Try to disburse the same transfer twice.
**Expected:** Returns the existing transaction with `status: 'already_processed'`

---

## Phase 7: Monitoring & Logs

### Test 7.1: Render Logs
- Confirm logs are streaming in real-time
- Confirm Nomba-related logs are searchable
- Confirm no unexpected errors in production

### Test 7.2: Supabase Logs
- Check `supabase_admin` is using service role key (no RLS violations)
- Confirm `transactions` table inserts are working
- Confirm `payment_reconciliation_log` entries are being created

---

## Success Criteria Summary

Your integration is **PRODUCTION-READY** when ALL of these pass:
- [x] Health check returns `nomba_auth: true` in production
- [x] Virtual account can be created and persisted
- [x] Webhook receives `payment_success` events and reconciles correctly
- [x] Transactions table is updated with `status='held'` on collection
- [x] Bank account lookup saves verified details
- [x] Disbursement creates pending transaction BEFORE calling Nomba API
- [x] Payout webhook updates transaction to `status='released'`
- [x] All edge cases (under/over/misdirected) are handled
- [x] Idempotency works (no duplicate transactions)
- [x] Render logs show no errors during the flow

---

## Rollback Plan (If Something Goes Wrong)

If a critical issue is found in production:
1. **Revert Render deployment**: Go to Render dashboard → Manual Deploy → select previous working commit
2. **Disable webhook in Nomba dashboard**: Prevents Nomba from sending events to broken endpoint
3. **Database cleanup**: Manually delete any orphaned `transactions` or `virtual_account_transfers` rows
4. **Notify Nomba**: If the issue is on their side

---

## Reporting Template

When reporting test results, use this format:

```
## Test Run: [DATE]
- Tester: [Your Name]
- Environment: production
- Nomba env: test (or live if you've cut over)

### Tests Passed:
- [x] Test 1.1: Health check
- [x] Test 2.2: Virtual account provisioning
- ...

### Tests Failed:
- [ ] Test X.Y: [Description]
  - Expected: [...]
  - Actual: [...]
  - Logs: [screenshot or log snippet]

### Notes:
[Any additional observations]
```

---

*Generated 2026-07-03. Test before submitting to Nomba hackathon.*
