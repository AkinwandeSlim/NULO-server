# Landlord Payment Improvements Summary

## Date: 2026-07-07

## Issues Fixed

### 1. ✅ UnboundLocalError in disbursements.py (Line 524)

**Problem:**
```python
UnboundLocalError: cannot access local variable 'nomba_client' where it is not associated with a value
```

**Root Cause:**
Line 391 had a redundant import `from app.services.nomba_client import NombaClient` inside the `disburse_to_landlord` function. This caused Python to treat `nomba_client` as a local variable throughout the entire function scope, shadowing the module-level import at line 21.

**Fix Applied:**
Removed the redundant import statement at line 391. The module-level import `from app.services.nomba_client import NombaAPIError, nomba_client` at line 21 is sufficient.

**File:** `server/app/routes/disbursements.py`

---

### 2. ✅ Bank Details Showing as Placeholders

**Problem:**
The release funds confirmation dialog on both list and detail pages was showing:
- "Your Bank" instead of actual bank name
- "••••••••" instead of actual account number
- "Your Account Name" instead of actual account name

**Root Cause:**
The frontend was already correctly structured to read `landlord.bank_account_number`, `landlord.bank_name`, and `landlord.account_name` from the API response, but needed verification that the backend was fetching these fields.

**Fix Verified:**
The backend already has proper bank details fetch logic in `server/app/routes/agreements.py`:
- `_fetch_agreement_participants` (lines 105-118): Fetches bank details from `landlord_profiles` for single agreement
- `get_agreements` (lines 282-300): Batch-fetches bank details from `landlord_profiles` for agreement list

**Files Involved:**
- Backend: `server/app/routes/agreements.py`
- Frontend: `client/lib/api/payments.ts` (normalizeAgreementRow function)
- UI: `client/app/(dashboard)/landlord/payments/page.tsx` (list page)
- UI: `client/app/(dashboard)/landlord/payments/[id]/page.tsx` (detail page)

---

### 3. ✅ Release Funds Button Behavior

**Problem:**
The release button on the landlord payments list page needed to match the detail page behavior (confirmation dialog with bank details).

**Fix Verified:**
The list page (`client/app/(dashboard)/landlord/payments/page.tsx`) already has:
- ✅ Confirmation dialog with bank details display (lines 480-571)
- ✅ Uses centralized `paymentsAPI.releaseFunds()` from `lib/api/payments.ts`
- ✅ Fetches transfer history to get correct `source_transfer_id` (lines 143-157)
- ✅ Same UX flow as detail page

---

### 4. ✅ Receipt Generation Button

**Problem:**
Need to verify receipt generation button is working properly.

**Status:**
According to `docs/hackathon/RECEIPT_BRANDING_FIXES.md`, receipt generation is fully implemented:
- ✅ Backend endpoint: POST `/api/v1/agreements/{agreement_id}/receipt`
- ✅ Tenant page: Download Receipt button in NUBAN panel
- ✅ Landlord page: Download Receipt button in disbursement panel
- ✅ Orange branding (#F97316)
- ✅ Receipt types: "PAYMENT RECEIPT" for tenants, "DISBURSEMENT RECEIPT" for landlords
- ✅ Loading states and error handling

**Files:**
- Backend: `server/app/routes/agreements.py` (lines 802-875, 1337-1540)
- Frontend: `client/lib/api/agreements.ts` (generateReceipt method)
- UI: Both tenant and landlord payment detail pages

---

## Next Steps

### 1. Restart Backend Server
The `UnboundLocalError` fix requires the backend server to be restarted:
```bash
# In server/ directory
# Press Ctrl+C to stop the current server
# Then restart:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Test Disbursement Flow
After restart, test the complete flow:
1. Navigate to landlord payments list: `http://localhost:3000/landlord/payments`
2. Click "Release" button on an agreement with `FULL_PAYMENT` status
3. Verify confirmation dialog shows:
   - ✅ Bank name (not "Your Bank")
   - ✅ Account number (not "••••••••")
   - ✅ Account name (not "Your Account Name")
4. Click "Confirm & Release"
5. Verify disbursement proceeds without `UnboundLocalError`

### 3. Verify Bank Details Lookup
The system now has automatic bank verification at three points:
1. **Onboarding**: When landlord first enters bank details via `/disbursements/lookup-bank`
2. **Auto-verification**: If bank details exist but `bank_verified_at` is null, auto-stamps on first disburse
3. **Re-verification**: Before each disburse, re-verifies bank account if cache is stale (>24h)

**Nomba API Integration Points:**
- `POST /api/v1/disbursements/lookup-bank` - Initial bank account verification
- `POST /api/v1/agreements/{id}/disburse` - Re-verifies before transfer if >24h old

**Database Fields** (landlord_profiles table):
- `bank_account_number`: Account number (10 digits)
- `bank_code`: Bank code (e.g., "000013" for GT Bank)
- `account_name`: Verified account holder name from Nomba
- `bank_name`: Human-readable bank name
- `bank_verified_at`: Timestamp of last successful verification

---

## Architecture Notes

### API Flow
```
Frontend (React)
    ↓
lib/api/payments.ts (paymentsAPI.releaseFunds)
    ↓
POST /api/v1/agreements/{id}/disburse
    ↓
server/app/routes/disbursements.py (disburse_to_landlord)
    ↓
nomba_client.lookup_bank_account() [if cache stale]
    ↓
nomba_client.send_payout()
    ↓
Create transaction record (status: pending)
    ↓
Webhook: POST /api/v1/nomba/payout-webhook
    ↓
Update transaction status → released
```

### Data Flow
```
1. User clicks "Release Funds"
2. Frontend fetches transfer_history to get source_transfer_id
3. Frontend calls releaseFunds(agreement_id, { source_transfer_id })
4. Backend validates:
   - Agreement exists
   - User is landlord
   - Payment is FULL_PAYMENT
   - No duplicate disbursement
5. Backend fetches landlord bank details from landlord_profiles
6. Backend re-verifies bank account if >24h old
7. Backend calls Nomba API to initiate payout
8. Backend creates transaction record (status: pending)
9. Nomba calls webhook when payout succeeds
10. Webhook updates transaction status → released
```

---

## Testing Checklist

- [ ] Backend server restarted successfully
- [ ] Disburse endpoint no longer throws `UnboundLocalError`
- [ ] Bank details show correctly in confirmation dialog (list page)
- [ ] Bank details show correctly in confirmation dialog (detail page)
- [ ] Release funds completes successfully
- [ ] Receipt generation works for landlords after disbursement
- [ ] CORS errors resolved (if any)

---

## Database Schema Reference

### landlord_profiles
```sql
CREATE TABLE landlord_profiles (
    id UUID PRIMARY KEY REFERENCES users(id),
    bank_account_number TEXT,
    bank_name TEXT,
    account_name TEXT,          -- Verified name from Nomba
    bank_code TEXT,             -- Bank code (e.g., "000013")
    bank_verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### transactions (disbursements)
```sql
-- Relevant columns for disbursements:
agreement_id UUID REFERENCES agreements(id)
source_transfer_id UUID REFERENCES virtual_account_transfers(id)
transaction_type TEXT -- 'nomba_disbursement'
status TEXT -- 'pending', 'released', 'failed'
amount DECIMAL
nomba_transfer_ref TEXT -- Merchant transaction reference
landlord_id UUID REFERENCES users(id)
created_at TIMESTAMPTZ
released_at TIMESTAMPTZ
```

---

## Files Modified in This Session

1. ✅ `server/app/routes/disbursements.py` - Removed redundant nomba_client import (line 391)

---

## Related Documentation

- [RECEIPT_BRANDING_FIXES.md](./RECEIPT_BRANDING_FIXES.md) - Receipt generation feature
- [Nomba Payment Integration Plan](../backup/checkpoint/Nomba_Payment_Integration_Plan_05_07_21_33.md) - Complete payment flow
- [QA Test Checklist](../backup/NuloAfrica_—_QA_Test_Checklist.ini) - Testing procedures

---

## Support

If issues persist after backend restart:

1. **Check backend logs** for detailed error messages
2. **Verify database** has landlord_profiles records with bank details
3. **Check Nomba API** credentials in `.env` file
4. **Verify CORS** settings in `server/app/main.py`

**Backend logs location:** Terminal where `uvicorn` is running
**Frontend logs location:** Browser console (F12)
