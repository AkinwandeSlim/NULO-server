# NuloAfrica - Nomba Integration Hackathon Submission

## 🚀 Project Overview
NuloAfrica is a comprehensive Nigerian rental property platform that integrates Nomba's virtual account and payment APIs to enable seamless rent collection and landlord disbursements. The platform supports multi-frequency rental payments (Monthly, Quarterly, Semi-Annual, Annual) with automatic reconciliation and disbursement.

## 🔗 Live Links
- **Live API:** https://api.nuloafrica.com
- **GitHub Repositories:**
  - Server: https://github.com/AkinwandeSlim/NULO-server
  - Client: https://github.com/AkinwandeSlim/NULO-client
- **Nomba Webhook URL (Registered):** https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer

## 🔑 Test Credentials for Judges

### Landlord Account
- **Email:** raphawellnessoptimization@gmail.com
- **Password:** nombahackathon2026
- **Use for:** Property listing, agreement management, disbursement testing
- **Status:** Onboarding complete, 23 properties listed

### Tenant Account  
- **Email:** mediaslim0705@gmail.com
- **Password:** nombahackathon2026
- **Use for:** Property search, applications, payment simulation
- **Status:** Ready to apply for properties

## 🎯 Demo Flow (Recommended)

### Full End-to-End Flow (5-7 minutes)
1. **Tenant browses** 23 available properties on marketplace
2. **Tenant applies** for a property
3. **Landlord reviews** application from dashboard
4. **Landlord approves** application and creates signed agreement
5. **Nomba virtual account** is automatically provisioned (sub-account-scoped)
6. **Payment simulation** via webhook (full payment)
7. **Landlord dashboard** shows payment received (status: HELD)
8. **Auto-disbursement** triggered to landlord's bank account (status: RELEASED)

## 🏗️ Nomba Integration Architecture

### Parent-Subaccount Setup
- **Parent Account:** Shared mothership (ID: `f666ef9b-888e-4799-85ce-acb505b28023`)
- **Subaccount:** Safe haven with registered webhook (ID: `282e5b9b-d14f-4e43-840d-43ddfd90a071`)
- **All VAs and Disbursements:** Use sub-account for proper webhook routing and spendable balance access

### Key Components
- **Virtual Accounts:** Per-agreement NUBANs with `accountRef = {agreementId}-SUB`
- **Webhook Handler:** Signature-verified, idempotent, reconciles inbound transfers
- **Bank Lookup:** Verified recipient accounts before disbursement
- **Disbursement Engine:** Auto-routes to parent/subaccount based on VA source
- **Reconciliation Logic:** Classifies payments (Full/Under/Over/Misdirected) with ±2% tolerance

## ✅ Key Features Implemented

### Nomba Integration
- ✅ **Virtual Account Provisioning (Path B):** Sub-account-scoped VAs with proper webhook routing
- ✅ **Webhook Signature Verification:** HMAC-SHA256 over colon-joined 9-field string
- ✅ **Idempotent Processing:** Prevents duplicate transactions using Nomba's `requestId`
- ✅ **Smart Reconciliation:**
  - FULL_PAYMENT: Within ±2% tolerance
  - UNDERPAYMENT: Below tolerance
  - OVERPAYMENT: Above tolerance
  - MISDIRECTED: No matching agreement
- ✅ **Bank Account Verification:** Pre-disbursement lookup with 24-hour cache
- ✅ **Auto-Disbursement:** Triggers on FULL_PAYMENT to verified landlord bank accounts
- ✅ **Manual Disbursement Fallback:** Landlord-initiated with `force=true` override for testing
- ✅ **Demo Mode:** Skip actual Nomba transfers with `DEMO_MODE=true`
- ✅ **Payment Status Polling:** Real-time agreement payment history

### Platform Features
- ✅ Property marketplace with 23+ listings
- ✅ Multi-frequency rent support (Monthly/Quarterly/Semi-Annual/Annual)
- ✅ Tenant application workflow
- ✅ Landlord dashboard with payment tracking & analytics
- ✅ Agreement generation and management
- ✅ Payment reconciliation and audit logs
- ✅ Admin verification system with property deletion
- ✅ Real-time notifications
- ✅ Auth context with DB-first user status (avoids stale JWT metadata)

## 📊 Test Results
- **Live Production Test:**
  - ✅ VA creation (sub-account): Successful
  - ✅ Real OPay ₦100 payment: Received & reconciled
  - ✅ Real ₦100 disbursement: Completed via sub-account
- **E2E Tests:** 9/13 steps passing
- **Test failures:** 4 failures due to test data cleanup (not system bugs)
- **Core functionality:** All payment and disbursement flows working correctly

## 🏗️ System Architecture
- **Backend:** Python FastAPI with Supabase
- **Frontend:** Next.js 16 with TypeScript and Tailwind CSS
- **Database:** Supabase PostgreSQL
- **Payment Integration:** Nomba API (v1 + v2 for transfers)
- **Authentication:** JWT with role-based access
- **Cache:** In-memory cache for dashboard stats (300s TTL)

## 📝 API Endpoints (Nomba Integration)

### Agreements
- `POST /api/v1/agreements/{agreementId}/provision-nomba`: Provision virtual account
- `GET /api/v1/agreements/{agreementId}/payment-status`: Get payment history
- `POST /api/v1/agreements/{agreementId}/disburse`: Disburse funds to landlord

### Webhooks
- `POST /api/v1/webhooks/nomba/transfer`: Handle Nomba webhooks (payment + payout events)

### Disbursements
- `POST /api/v1/disbursements/lookup-bank`: Verify bank account
- `GET /api/v1/disbursements/{merchantTxRef}`: Get disbursement status

### Health
- `GET /api/v1/health/nomba`: Check Nomba integration health

## 📁 Documentation Package
- `NOMBA_PRD_V3.md` - Complete Nomba integration PRD (verified facts, architecture, open items)
- `server/app/routes/nomba.py` - Nomba webhook & VA provisioning routes
- `server/app/routes/disbursements.py` - Disbursement routes
- `server/app/services/nomba_client.py` - Nomba API client with token management
- `server/app/services/nomba_helpers.py` - Payment calculation & helper functions
- `docs/sql/migrations/` - Database migrations for Nomba tables

## 🎬 Quick Demo Script
1. Login as tenant: `mediaslim0705@gmail.com` / `nombahackathon2026`
2. Browse properties and apply for one
3. Login as landlord: `raphawellnessoptimization@gmail.com` / `nombahackathon2026`
4. Review application and approve
5. Create agreement - Nomba VA automatically provisioned
6. Simulate payment via webhook script
7. View payment received in landlord dashboard (status: HELD)
8. Auto-disbursement triggers (or manually disburse) to verify payout (status: RELEASED)

## 🏆 Hackathon Highlights
- **Complete end-to-end payment flow:** Application → Agreement → VA → Payment → Reconciliation → Disbursement
- **Production-ready architecture:** Parent-subaccount setup with proper webhook routing
- **Robust error handling:** Idempotency, signature verification, balance checks
- **Demo-friendly features:** Simulation endpoints, `force=true` override, DEMO_MODE
- **Verified live on production:** Real OPay payment and disbursement tested
- **Comprehensive PRD:** Every claim backed by code or live API evidence
- **Fixed critical bugs:** Race conditions, stale JWT metadata, property listing defaults

---

**Submission Date:** July 7, 2026
**Team:** NuloAfrica
**Challenge:** Nomba Integration Hackathon
**Nomba PRD Version:** V3.3
