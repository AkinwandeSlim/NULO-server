# Payment Flow End-to-End Test Checklist

**Test Duration:** ~15 minutes  
**Priority:** CRITICAL for hackathon demo  
**Status:** Ready to test

---

## **Test Scenario: Tenant Payment Journey**

### **Prerequisites:**
- [ ] Backend server running (`python run.py`)
- [ ] Frontend server running (`npm run dev`)
- [ ] Test tenant account logged in
- [ ] Active agreement with NUBAN provisioned
- [ ] Nomba sandbox environment configured

---

## **Phase 1: Dashboard View (2 min)**

### **Tenant Dashboard:**
- [ ] Payment Overview Card shows correct data
  - [ ] Property title displayed
  - [ ] Payment frequency badge (Monthly/Quarterly/Annual)
  - [ ] Progress bar shows % paid
  - [ ] Per-payment, Paid, Outstanding amounts correct
  - [ ] "Pay Now" button visible if balance > 0
  - [ ] "View Receipt" button if fully paid
  - [ ] "Details →" button works

- [ ] Payment Timeline (Sidebar)
  - [ ] Shows correct number of periods
  - [ ] Current period highlighted with pulse
  - [ ] Paid periods show green checkmark
  - [ ] Countdown badges show days remaining
  - [ ] "View Full Payment Details" button works

- [ ] 4-Cell Stats Grid
  - [ ] Active Lease count correct
  - [ ] Activity count matches badge items
  - [ ] Messages count with unread badge
  - [ ] Maintenance count shows

- [ ] Engagement/Trust Indicators
  - [ ] Engagement level dot (green/orange/gray)
  - [ ] Trust score badge visible
  - [ ] Activity level text ("high"/"medium"/"low")

**✅ Dashboard tracking:**
- [ ] `payment_details_viewed` tracked when viewing dashboard

---

## **Phase 2: Payment Detail Page (5 min)**

### **Navigation:**
- [ ] Click "Pay Now" from Payment Overview → Opens `/tenant/payments/{id}`
- [ ] Page loads without errors
- [ ] URL contains agreement ID

### **Hero Metrics (4 cards):**
- [ ] Total Due - shows full rent amount
- [ ] Amount Paid - shows total received with %
- [ ] Outstanding - shows balance remaining
- [ ] Status - badge shows correct state (Fully Paid/Partially Paid/Awaiting)

### **Payment Progress Bar:**
- [ ] Visual progress matches %
- [ ] "₦X paid" and "₦Y remaining" labels correct

### **Payment Schedule Timeline:**
- [ ] All periods displayed (12 for monthly, 4 for quarterly, etc.)
- [ ] Period dates correct (e.g., "Period 1 · Jan 15 – Apr 14")
- [ ] Paid periods show green ✓
- [ ] Current period shows orange clock with pulse
- [ ] Future periods show gray dot
- [ ] Countdown badges accurate ("5d left", "Overdue")

### **Property Details Card:**
- [ ] Property name and location
- [ ] Lease start/end dates
- [ ] Landlord name with icon

### **Transaction History:**
- [ ] All payments listed (if any)
- [ ] Amount, date, status correct
- [ ] Source bank shown
- [ ] Receipt download button works
- [ ] Pagination works (if >5 transactions)

### **NUBAN Panel (Sidebar):**
- [ ] Account number displayed in large font
- [ ] Copy button works → Shows "Copied" toast
- [ ] Outstanding balance alert (if balance > 0)
  - [ ] Shows: Expected, Paid so far, Still to pay
- [ ] Success message if fully paid
- [ ] Payment instructions visible
- [ ] "Generate NUBAN" button (if no NUBAN)

**✅ Payment page tracking:**
- [ ] `payment_details_viewed` tracked on page load
- [ ] `nuban_copied` tracked when NUBAN copied
- [ ] `receipt_downloaded` tracked when receipt button clicked

---

## **Phase 3: Payment Reconciliation (5 min)**

### **Make Test Payment:**
1. [ ] Copy NUBAN from payment detail page
2. [ ] Open Nomba sandbox/webhook simulator
3. [ ] Send test transfer (amount = outstanding balance)
4. [ ] Wait 5-10 seconds

### **Auto-Refresh Behavior:**
- [ ] Page auto-refreshes every 15s
- [ ] New payment appears in transaction history
- [ ] Payment progress bar updates
- [ ] Outstanding balance updates
- [ ] Timeline periods update (green checkmarks)

### **Reconciliation Status:**
- [ ] Transaction shows correct reconciliation badge:
  - [ ] "Full Payment" (green) if exact amount
  - [ ] "Partial" (amber) if underpayment
  - [ ] "Overpaid" (purple) if overpayment

### **Dashboard Updates:**
- [ ] Navigate back to `/tenant`
- [ ] Payment Overview Card updates
- [ ] Payment Timeline updates
- [ ] Trust score increases (check engagement indicator)

**✅ Payment tracking:**
- [ ] `payment_made` tracked when new payment detected
- [ ] Engagement score increases in dashboard header
- [ ] Trust score badge updates

---

## **Phase 4: Receipt Generation (2 min)**

### **Generate Receipt:**
- [ ] Click "Download Receipt" button
- [ ] Loading spinner shows
- [ ] PDF opens in new tab
- [ ] Receipt contains:
  - [ ] Property details
  - [ ] Tenant details
  - [ ] Payment breakdown
  - [ ] Transaction history
  - [ ] Total paid amount
  - [ ] Date generated

**✅ Receipt tracking:**
- [ ] `receipt_downloaded` tracked when button clicked

---

## **Phase 5: Edge Cases (1 min)**

### **Test These Scenarios:**
- [ ] **Underpayment:** Transfer less than outstanding → Shows "Partial" badge
- [ ] **Overpayment:** Transfer more than outstanding → Shows "Overpaid" badge
- [ ] **No NUBAN:** Delete NUBAN → Shows "Generate NUBAN" button
- [ ] **Fully Paid:** All periods paid → Shows success message + receipt button
- [ ] **Overdue Period:** Period past due → Shows red "Overdue" badge

---

## **Known Issues to Verify:**

### **Fixed Issues:**
- [x] Payment Timeline integrated into sidebar (not in main content)
- [x] Activity card count matches badge items
- [x] Badge shows all action items (e.g., "1 to sign · 2 apps · 1 viewing")
- [x] Badge positioned below card count (not at top)
- [x] Only badge is clickable (not entire Activity card)
- [x] Engagement tracking added for payment activities

### **Potential Issues:**
- [ ] Auto-refresh might lag on slow connections
- [ ] Receipt generation might timeout on first request
- [ ] Nomba webhook might not fire in sandbox
- [ ] Pagination might break with >10 transactions

---

## **Demo Talking Points:**

### **For Judges:**
1. **"Reconciliation Engine is the core innovation"**
   - Handles MONTHLY, QUARTERLY, SEMI_ANNUAL, ANNUAL frequencies
   - Per-period calculation with exact date tracking
   - Auto-detects FULL_PAYMENT, UNDERPAYMENT, OVERPAYMENT

2. **"Real-time payment tracking"**
   - Tenant sees updates within 15 seconds
   - No manual landlord intervention needed
   - Engagement tracking builds trust score

3. **"Tenant-friendly UX"**
   - Payment schedule shows full year breakdown
   - Countdown timers for upcoming payments
   - Copy-paste NUBAN for easy bank transfer

4. **"Payment transparency"**
   - Every transaction tracked
   - Receipt generation on-demand
   - Clear breakdown: Total Due | Paid | Outstanding

---

## **Backup Plans (If Issues):**

### **If webhook doesn't fire:**
- Use Nomba sandbox webhook simulator manually
- Or use backend API call to trigger reconciliation

### **If receipt fails:**
- Show transaction history as proof of payment
- Mention PDF generation is async feature

### **If auto-refresh breaks:**
- Show manual refresh button
- Mention real-time updates are bonus feature

---

## **Final Checklist Before Submission:**

- [ ] All TypeScript errors resolved
- [ ] No console errors in browser
- [ ] Payment flow works end-to-end
- [ ] Engagement tracking confirmed working
- [ ] Screenshots/video captured for demo
- [ ] README updated with setup instructions
- [ ] Environment variables documented
- [ ] Test accounts credentials provided

---

**Estimated Test Time:** 15 minutes  
**Critical Path:** Dashboard → Payment Detail → Make Payment → Verify Update → Download Receipt

Good luck with the hackathon! 🚀
