# 3-5 Minute Demo Script for Hackathon Submission

## 🎬 Demo Flow (Voice Narration + Screen Actions)

### **0:00-0:30 | Introduction**
**Screen:** Show home page `noloafrica.com`
**Voice:** "Hi, I'm [Your Name] from NoloAfrica. We're solving Nigeria's rental payment problem by integrating Nomba's virtual accounts to enable flexible rent collection and automatic landlord disbursements."

### **0:30-1:00 | Tenant Login & Property Browsing**
**Screen:** Login as tenant → Browse properties
**Voice:** "Let me show you how it works. I'll log in as a tenant and browse available properties. Our platform has over 23 verified listings across Nigerian cities."

**Actions:**
- Login: `mediaslim0705@gmail.com` / `nombahackathon2026`
- Scroll through property listings
- Click on a property to view details

### **1:00-1:30 | Tenant Application**
**Screen:** Property details → Apply button → Application form
**Voice:** "Tenants can easily apply for properties with a single click. The application process is streamlined and requires basic information."

**Actions:**
- Click "Apply Now" on a property
- Fill in application details
- Submit application

### **1:30-2:00 | Landlord Dashboard & Application Review**
**Screen:** Logout → Login as landlord → Dashboard → Applications
**Voice:** "Now let's switch to the landlord side. Landlords receive applications in their dashboard and can review tenant details before approving."

**Actions:**
- Logout
- Login: `raphawellnessoptimization@gmail.com` / `nombahackathon2026`
- Navigate to dashboard
- Review the tenant application
- Click "Approve"

### **2:00-2:30 | Agreement Creation & Nomba VA Provisioning**
**Screen:** Create agreement → Agreement details → Virtual account appears
**Voice:** "Once approved, the landlord creates a rental agreement. Our system automatically provisions a dedicated Nomba virtual account for this agreement, enabling secure rent collection."

**Actions:**
- Create signed agreement
- Show the Nomba virtual account number automatically appearing
- Mention the sub-account setup for proper webhook routing

### **2:30-3:00 | Payment Simulation**
**Screen:** Show webhook script or payment simulation → Payment status updates
**Voice:** "When the tenant pays into this virtual account, Nomba sends us a webhook notification. Our system automatically reconciles the payment and updates the agreement status."

**Actions:**
- Show payment status changing from PENDING to FULL_PAYMENT
- Display the reconciliation logic (±2% tolerance)
- Show payment received in landlord dashboard

### **3:00-3:30 | Auto-Disbursement**
**Screen:** Disbursement status → Bank verification → Disbursement complete
**Voice:** "After full payment is received, our system automatically triggers disbursement to the landlord's verified bank account. We verify bank details before payout to ensure security."

**Actions:**
- Show disbursement status changing to RELEASED
- Mention bank account verification integration
- Show landlord dashboard with updated balance

### **3:30-4:00 | Key Features Summary**
**Screen:** Scroll through dashboard showing analytics, notifications, property management
**Voice:** "Our platform supports multiple payment frequencies - monthly, quarterly, semi-annual, and annual. Landlords get real-time analytics and tenants get flexible payment options."

**Actions:**
- Show landlord dashboard analytics
- Show notification system
- Show property management features

### **4:00-4:30 | Technical Highlights**
**Screen:** Show API documentation or architecture diagram (optional)
**Voice:** "Technically, we've implemented secure webhook signature verification, idempotency handling, and comprehensive audit logging. Our architecture is production-ready with proper error handling and fallback mechanisms."

**Actions:**
- Briefly show API health check endpoint
- Mention parent-subaccount setup
- Reference the comprehensive documentation

### **4:30-5:00 | Conclusion**
**Screen:** Back to home page with contact info
**Voice:** "NoloAfrica is transforming Nigerian rentals by making rent collection seamless and secure. Thank you for watching our demo. You can test the platform yourself using the credentials provided in our submission."

**Actions:**
- Show home page
- Display test credentials on screen
- End with thank you message

---

## 📝 Key Points to Emphasize

**Must Mention:**
- Multi-frequency rent support (Monthly/Quarterly/Semi-Annual/Annual)
- Nomba virtual account integration with sub-account setup
- Automatic payment reconciliation with ±2% tolerance
- Secure webhook signature verification
- Auto-disbursement to verified landlord accounts
- Production-ready architecture with proper error handling

**Technical Highlights:**
- HMAC-SHA256 signature verification
- Idempotency handling
- Parent-subaccount setup for proper webhook routing
- Bank account verification before disbursement
- Comprehensive audit logging

**Demo Tips:**
- Speak clearly and at a moderate pace
- Keep mouse movements smooth and deliberate
- Highlight key UI elements as you mention them
- Show loading states to demonstrate real API calls
- Have test credentials ready for quick login
- Practice the flow once before recording

---

## ⏱️ Timing Breakdown

| Section | Duration | Focus |
|---------|----------|-------|
| Introduction | 30s | Problem statement + solution overview |
| Tenant flow | 1m | User experience + property browsing |
| Landlord flow | 1m | Dashboard + application approval |
| Nomba integration | 1m | VA provisioning + payment reconciliation |
| Disbursement | 30s | Auto-payout + bank verification |
| Technical summary | 1m | Architecture + security features |
| Conclusion | 30s | Call to action + credentials |

**Total: 4.5-5 minutes**
