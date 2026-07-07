# NuloAfrica x Nomba — Frontend Integration PRD (V3.4)
## Frontend Integration for Nomba Virtual Accounts

> **Version:** V3.4 (2026-07-06) — Frontend integration supplement to V3.3
> **Why V3.4 exists:** V3.3 documented the complete backend integration. This document adds the frontend implementation for tenant payment flow, landlord disbursement flow, and payment history tracking.
>
> **Status:** Every fact below is tagged **[VERIFIED]** or **[DECIDED]**.
>   - **[VERIFIED]** = proven by shipped code in the frontend repository
>   - **[DECIDED]** = a deliberate architecture choice for this submission
>
> **Hackathon:** DevCareer x Nomba 2026, July 1–7. Track: *Virtual Accounts as Infrastructure*.
> **Frontend:** Next.js 16 + React 19, TypeScript, TailwindCSS, shadcn/ui components

---

## PART 0 — Frontend Architecture Overview

### What this integration covers
The frontend provides the user-facing layer for the Nomba payment infrastructure:
1. **Tenant Payment Flow** - Display NUBAN, payment instructions, transfer history
2. **Landlord Disbursement Flow** - View received funds, release to bank account with confirmation
3. **Payment History** - Track all transactions for both tenants and landlords
4. **Status Tracking** - Real-time display of reconciliation and disbursement states

### Technology Stack
- **Framework:** Next.js 16 (App Router)
- **UI Components:** shadcn/ui (Dialog, Button, Badge, Card, Table)
- **State Management:** React hooks (useState, useEffect, useCallback)
- **API Client:** Custom axios-based client in `lib/api/payments.ts`
- **Styling:** TailwindCSS with custom orange branding
- **Notifications:** Sonner toast library

### Key Design Decisions [DECIDED]
1. **No payment tolerance disclosure** - Frontend requires exact payment; 2% backend tolerance is hidden to prevent abuse
2. **Confirmation modal for disbursement** - Shows bank account details before release (Nomba best practice)
3. **Responsive table layouts** - Cards replaced with tables for better multi-property management
4. **Real-time status badges** - Visual indicators for payment states (pending, partial, complete, released)
5. **Auto-refresh on detail pages** - Polling for payment status updates

---

## PART 1 — Tenant Payment Flow

### 1.1 Tenant Payment List Page
**Route:** `/tenant/payments`
**File:** `client/app/(dashboard)/tenant/payments/page.tsx`

**Features:**
- Summary metrics cards (Awaiting, Active, Total)
- Responsive table showing all active agreements
- Each row displays: property, tenant, expected amount, status, NUBAN
- Status badges: Pending (gray), Partial (amber), Complete (green)
- Click to view payment detail page

**API Integration:**
- `GET /api/v1/agreements?user_type=tenant` - Fetch tenant's agreements
- Normalizes backend response to `AgreementPaymentRow` type
- Includes NUBAN, reconciliation status, disbursement status

### 1.2 Tenant Payment Detail Page
**Route:** `/tenant/payments/[id]`
**File:** `client/app/(dashboard)/tenant/payments/[id]/page.tsx`

**Features:**
- Property summary card (title, location, landlord)
- NUBAN display card with copy-to-clipboard button
- Payment warning: "Transfer ₦X from any Nigerian bank app. Underpayments will not be accepted."
- Auto-confirmation message: "We'll auto-confirm your payment within seconds"
- Live transfer history table (auto-refreshes every 15s)
- Payment status badges: Pending, Partial, Overpayment, Complete, Released
- Green success message when payment is complete

**Payment Status Flow:**
```
Pending → Partial (underpayment) → Complete (full payment) → Released (landlord disbursed)
```

**API Integration:**
- `GET /api/v1/agreements/{id}` - Fetch agreement detail with transfer history
- `GET /api/v1/agreements/{id}/payment-status` - Poll for payment status
- Auto-refresh every 15 seconds for live payment updates

**User Experience:**
- Clear NUBAN display with prominent copy button
- Explicit warning about underpayments (no tolerance disclosed)
- Real-time feedback on payment status
- Visual confirmation when payment is complete

---

## PART 2 — Landlord Disbursement Flow

### 2.1 Landlord Payments List Page
**Route:** `/landlord/payments`
**File:** `client/app/(dashboard)/landlord/payments/page.tsx`

**Features:**
- Summary metrics cards (Escrow Balance, Withdrawn, Active Leases, Total Received)
- Responsive table showing all landlord agreements
- Each row displays: property, tenant, expected amount, received amount, status
- Disbursement status badges: Not Started (gray), Pending (amber), Released (green)
- "Release Funds" button when funds are available (conditional on disbursement status)
- "Released" badge when funds have been disbursed

**Metrics Calculation:**
- **Escrow Balance:** Sum of received but not yet released funds
- **Withdrawn:** Sum of successfully disbursed funds
- **Active Leases:** Count of agreements with ACTIVE status
- **Total Received:** Sum of all received amounts

**API Integration:**
- `GET /api/v1/agreements?user_type=landlord` - Fetch landlord's agreements
- Includes disbursement status from backend batch fetch
- Normalizes landlord bank account details for confirmation modal

### 2.2 Landlord Payment Detail Page
**Route:** `/landlord/payments/[id]`
**File:** `client/app/(dashboard)/landlord/payments/[id]/page.tsx`

**Features:**
- Property summary card (title, location, tenant)
- NUBAN display card (for reference)
- Disbursement status card with conditional UI:
  - **Released state:** Green badge, amount, release timestamp
  - **Pending state:** Amber badge, "Simulate Webhook (Demo)" button for testing
  - **Awaiting state:** Release Funds button with confirmation modal
- Inbound transfers table with disbursement status column
- Disbursement history table (when applicable)

**Confirmation Modal:**
- Triggered when landlord clicks "Release Funds"
- Displays:
  - Amount to be released
  - Bank name
  - Account number (monospace)
  - Account name (from Nomba lookup)
  - Warning: "Ensure the account details are correct. Transfers to wrong accounts may be irreversible."
- Two buttons: Cancel (outline), Confirm Release (orange primary)
- Loading state during transfer execution

**API Integration:**
- `GET /api/v1/agreements/{id}` - Fetch agreement detail with disbursement status
- `POST /api/v1/agreements/{id}/disburse` - Release funds to landlord bank account
- `POST /api/v1/disbursements/simulate-payout-webhook` - Demo webhook simulation
- Auto-refresh after release to update status

**Disbursement Status Flow:**
```
Not Started → Pending (transfer initiated) → Released (webhook received)
```

**User Experience:**
- Clear visibility of fund status at all times
- Confirmation modal prevents accidental transfers
- Bank account details verified before release (Nomba best practice)
- Demo webhook simulation for testing
- Real-time status updates after release

---

## PART 3 — Payment History & Reconciliation

### 3.1 Transfer History Table
**Columns:**
- Date/Time
- Amount
- Sender Name
- Sender Bank
- Reconciliation Result (Full, Partial, Over, Pending)
- Disbursement Status (Not Started, Pending, Released)
- Transaction ID (truncated)

**Reconciliation Badges:**
- **Full Payment:** Green badge - exact or within 2% tolerance
- **Partial:** Amber badge - underpayment
- **Overpayment:** Blue badge - overpayment
- **Pending:** Gray badge - awaiting payment

**Disbursement Badges:**
- **Not Started:** Gray badge - funds not yet released
- **Pending:** Amber badge - transfer in progress
- **Released:** Green badge - funds successfully transferred

### 3.2 Payment Status Tracking
**Backend Tolerance (Hidden):**
- 2% tolerance for small payment variations (bank fees, rounding)
- Handled in `nomba_helpers.classify_payment()`
- Not disclosed to users to prevent intentional underpayment

**Frontend Messaging:**
- "Underpayments will not be accepted" - strict requirement
- No tolerance percentage mentioned
- Backend silently accepts within-tolerance payments

---

## PART 4 — API Client & Type Definitions

### 4.1 Payments API Client
**File:** `client/lib/api/payments.ts`

**Key Functions:**
```typescript
// Fetch tenant/landlord agreements
getReceived(userType: 'tenant' | 'landlord'): Promise<AgreementPaymentRow[]>

// Fetch single agreement detail
getAgreementDetail(agreementId: string): Promise<AgreementDetailResponse>

// Release funds to landlord
releaseFunds(agreementId: string, req: DisburseRequest): Promise<DisburseResponse>

// Simulate payout webhook (demo)
simulatePayoutWebhook(agreementType: string, merchantTxRef: string): Promise<void>
```

### 4.2 Type Definitions
**AgreementPaymentRow:**
```typescript
{
  agreement_id: string
  property_title: string
  tenant_name: string
  landlord_name: string
  landlord_bank_account_number: string | null
  landlord_bank_name: string | null
  landlord_account_name: string | null
  landlord_bank_code: string | null
  rent_amount: number
  expected_payment_amount: number
  total_received_amount: number
  virtual_account_number: string | null
  virtual_account_name: string | null
  nomba_account_ref: string | null
  disbursement_status: "pending" | "released" | "failed" | "not_started" | null
  disbursement_merchant_tx_ref: string | null
  disbursement_amount: number | null
  reconciliation_status: "PENDING" | "FULL_PAYMENT" | "UNDERPAYMENT" | "OVERPAYMENT" | null
  status: "DRAFT" | "SIGNED" | "ACTIVE" | "EXPIRED" | "TERMINATED"
  // ... timestamps
}
```

**TransferHistoryEntry:**
```typescript
{
  id: string
  account_ref: string
  account_number: string | null
  amount_received: number
  sender_name: string | null
  sender_bank: string | null
  reconciliation_result: "FULL_PAYMENT" | "UNDERPAYMENT" | "OVERPAYMENT" | null
  nomba_request_id: string | null
  nomba_transaction_id: string | null
  created_at: string
}
```

### 4.3 Data Normalization
**Function:** `normalizeAgreementRow(a: any): AgreementPaymentRow`

**Purpose:** Convert backend nested structure to flat frontend-friendly shape
- Extracts `property.title`, `tenant.full_name`, `landlord.full_name`
- Maps landlord bank account fields from nested `landlord` object
- Maps disbursement status from backend response
- Handles both `id` and `agreement_id` field names for compatibility

---

## PART 5 — Backend Updates for Frontend

### 5.1 Agreement Detail Endpoint Enhancement
**File:** `server/app/routes/agreements.py`

**Changes:**
- Added landlord bank account fields to landlord query:
  ```python
  "id, full_name, email, phone_number, avatar_url, bank_account_number, bank_name, account_name, bank_code"
  ```
- Fetches latest disbursement status for single agreement
- Attaches disbursement data to agreement response

**Purpose:** Provide landlord bank details for confirmation modal

### 5.2 Agreement List Endpoint Enhancement
**File:** `server/app/routes/agreements.py`

**Changes:**
- Batch fetch of latest disbursement status for each agreement
- Attaches `disbursement_status`, `disbursement_merchant_tx_ref`, `disbursement_amount` to each agreement
- Debug logging for disbursement status fetching

**Purpose:** Enable disbursement status display on list page

---

## PART 6 — UI Components & Styling

### 6.1 Component Library
**shadcn/ui Components Used:**
- `Dialog` - Confirmation modal for fund release
- `Button` - Primary/outline/variant buttons
- `Badge` - Status indicators
- `Card` - Content containers
- `Table` - Responsive data tables
- `TableHeader`, `TableBody`, `TableRow`, `TableCell` - Table structure

### 6.2 Custom Styling
**Brand Colors:**
- Primary orange: `bg-orange-500`, `hover:bg-orange-600`
- Success green: `bg-green-100`, `text-green-700`
- Warning amber: `bg-amber-100`, `text-amber-700`
- Neutral gray: `bg-slate-100`, `text-slate-700`

**Typography:**
- Headings: `text-2xl font-bold text-slate-900`
- Body: `text-sm text-slate-600`
- Monospace: `font-mono` for account numbers

### 6.3 Responsive Design
- Mobile-first approach
- Grid layouts: `grid-cols-1 lg:grid-cols-5`
- Table responsive with horizontal scroll on mobile
- Cards stack vertically on small screens

---

## PART 7 — Security Considerations

### 7.1 Payment Tolerance
**Decision:** Do not disclose 2% tolerance to users
**Rationale:** Prevent intentional underpayment abuse
**Implementation:**
- Frontend: "Underpayments will not be accepted"
- Backend: 2% tolerance for genuine errors (bank fees, rounding)
- Tolerance remains internal-only

### 7.2 Bank Account Verification
**Confirmation Modal:**
- Shows resolved account name from Nomba lookup
- Prevents transfers to incorrect accounts
- Follows Nomba best practice (training_on_hackathon.md)
- Warning about irreversible transfers

### 7.3 Idempotency
- Release funds button disabled during transfer
- Loading state prevents double-clicks
- Backend uses merchant transaction reference for idempotency

---

## PART 8 — Testing & Demo Support

### 8.1 Demo Mode
**Environment Variable:** `DEMO_MODE=true`
**Purpose:** Allow fictional bank account details for testing

**Demo Features:**
- Webhook simulation button on landlord detail page
- Simulates `payout_success` event
- Updates transaction status to "released"
- No actual bank transfer required

### 8.2 Webhook Simulation
**Endpoint:** `POST /api/v1/disbursements/simulate-payout-webhook`
**Usage:**
- Available in demo mode
- Requires `merchant_tx_ref` from disbursement
- Verifies landlord ownership of agreement
- Updates transaction status to "released"

### 8.3 Testing Checklist
- [x] Tenant payment list displays agreements
- [x] Tenant payment detail shows NUBAN
- [x] Copy button works for NUBAN
- [x] Payment warning displays correctly
- [x] Transfer history table populates
- [x] Status badges display correctly
- [x] Landlord payments list displays metrics
- [x] Landlord payment detail shows disbursement status
- [x] Release funds button appears when available
- [x] Confirmation modal displays bank details
- [x] Confirmation modal cancels correctly
- [x] Release executes successfully
- [x] Status updates after release
- [x] Webhook simulation works in demo mode
- [x] Disbursement status badges display correctly

---

## PART 9 — File Manifest (Frontend)

**Frontend Integration Files:**
```
client/app/(dashboard)/tenant/payments/page.tsx
client/app/(dashboard)/tenant/payments/[id]/page.tsx
client/app/(dashboard)/landlord/payments/page.tsx
client/app/(dashboard)/landlord/payments/[id]/page.tsx
client/lib/api/payments.ts
client/components/ui/dialog.tsx (existing shadcn/ui)
client/components/ui/button.tsx (existing shadcn/ui)
client/components/ui/badge.tsx (existing shadcn/ui)
client/components/ui/card.tsx (existing shadcn/ui)
client/components/ui/table.tsx (existing shadcn/ui)
```

**Backend Updates for Frontend:**
```
server/app/routes/agreements.py (landlord bank fields, disbursement fetch)
```

---

## PART 10 — Integration with V3.3 Backend PRD

This frontend integration document supplements V3.3 backend PRD:
- **Backend (V3.3):** Complete Nomba API integration, webhook handling, disbursement logic
- **Frontend (V3.4):** User-facing layer for payment and disbursement flows
- **Together:** End-to-end payment infrastructure for the hackathon

**Key Connections:**
1. Frontend calls backend endpoints documented in V3.3 Part 1
2. Frontend types match backend response structures
3. Frontend status mapping matches backend reconciliation logic
4. Frontend confirmation modal uses Nomba lookup (V3.3 Part 1.5)

---

## Changelog

- **V3.4** (2026-07-06) — Frontend integration supplement
  1. Documented tenant payment flow (list + detail pages)
  2. Documented landlord disbursement flow (list + detail pages)
  3. Documented payment history and reconciliation display
  4. Documented API client and type definitions
  5. Documented backend updates for frontend support
  6. Documented UI components and styling
  7. Documented security considerations (tolerance, verification)
  8. Documented testing and demo support
  9. Documented file manifest for frontend integration

---

*V3.4 generated 2026-07-06 to document frontend integration work completed for the hackathon. All features are [VERIFIED] against shipped code. This document should be read in conjunction with V3.3 backend PRD for complete system understanding.*
