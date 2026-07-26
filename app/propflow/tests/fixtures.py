"""
PropFlow Test Fixtures
Complete test data for end-to-end PropFlow testing.

Usage:
    from app.propflow.tests.fixtures import *
    
    # Use sample tenant data
    tenant_data = SAMPLE_TENANTS[0]
    
    # Use sample property data  
    property_data = SAMPLE_PROPERTIES[0]
    
    # Use sample inquiry
    inquiry_text = SAMPLE_INQUIRIES["pidgin_basic"]
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any

# ═══════════════════════════════════════════════════════════════════════════════
# SAMPLE TENANTS
# ═══════════════════════════════════════════════════════════════════════════════

### **2. Mem0 API (RECOMMENDED)**

**Step 1**: Go to [Mem0.ai](https://mem0.ai/)
**Step 2**: Create account and verify email
**Step 3**: Go to **Dashboard** → **API Keys**
**Step 4**: Generate new API key
**Step 5**: Copy the key

**Configuration**:
```bash
MEM0_API_KEY=your-mem0-api-key-here
MEM0_USER_ID=propflow-tenant
MEM0_ENABLED=true
MEM0_EMBEDDING_MODEL=text-embedding-3-small
MEM0_LLM_MODEL=gpt-4o-mini
```

**Alternative (Disable Mem0)**:
```bash
MEM0_ENABLED=false  # Uses mock memory instead
```

### **3. Alibaba Cloud OSS (HACKATHON PROOF FILE)**

**Step 1**: Go to [Alibaba Cloud OSS Console](https://oss.console.aliyun.com/)  
**Step 2**: Create OSS bucket (e.g., `nuloafrica-agreements`)
**Step 3**: Go to **RAM Access Control** → **AccessKey Management**
**Step 4**: Create AccessKey pair
**Step 5**: Note down AccessKeyId and AccessKeySecret

**Configuration**:
```bash
OSS_ACCESS_KEY_ID=your-oss-access-key-id
OSS_ACCESS_KEY_SECRET=your-oss-access-key-secret
OSS_BUCKET_NAME=nuloafrica-agreements
OSS_ENDPOINT=https://oss-us-west-1.aliyuncs.com
OSS_ENABLED=true
```

### **4. Supabase Database**

**Option A: Use Existing NuloAfrica DB**
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-supabase-service-key
SUPABASE_ANON_KEY=your-supabase-anon-key
```

**Option B: Create New Supabase Project**  
**Step 1**: Go to [Supabase](https://supabase.com/)
**Step 2**: Create new project
**Step 3**: Go to **Settings** → **API**
**Step 4**: Copy URL and service role key
**Step 5**: Run database migrations (see Database Setup section)

---

## 🛠️ **Installation Steps**

### **1. Clone Repository**
```bash
git clone https://github.com/AkinwandeSlim/NULO-DEV.git
cd NULO-DEV
```

### **2. Backend Setup**
```bash
cd server

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys (see API Keys Setup section)
```

### **3. Frontend Setup**
```bash
cd client

# Install dependencies
pnpm install  # or npm install / yarn install

# Configure environment
cp .env.example .env.local
# Add any frontend-specific environment variables
```

### **4. Database Setup (If Using New Supabase)**

**Run Migrations**:
```bash
cd server
python scripts/setup_propflow_tables.py
```

**Or manually create required tables**:
```sql
-- Essential PropFlow tables (if not already exists)
CREATE TABLE IF NOT EXISTS applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    property_id UUID REFERENCES properties(id),
    status VARCHAR(20) DEFAULT 'pending',
    propflow_thread_id VARCHAR(255),
    landlord_briefing TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agreements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(), 
    application_id UUID REFERENCES applications(id),
    status VARCHAR(20) DEFAULT 'PENDING_TENANT',
    virtual_account_number VARCHAR(20),
    expected_payment_amount DECIMAL(15,2),
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 🧪 **Testing Framework**

### **Test Modes**

**1. Mock Mode (No API Keys Required)**
- Uses pre-defined mock responses
- Perfect for demo without API credits
- Tests workflow logic and state transitions

**2. Real API Mode (Requires API Keys)**  
- Makes actual calls to Qwen, Mem0, OSS
- Tests real AI performance and integration
- Consumes API credits

**3. Hybrid Mode**
- Real Qwen + Mock Mem0/OSS
- Useful when some services unavailable

### **Running Tests**

#### **Evaluation Tests**
```bash
cd server

# Mock mode - no API keys needed
python -m app.propflow.tests.eval_agent --mock

# Real API mode - requires QWEN_API_KEY
python -m app.propflow.tests.eval_agent

# Save report for submission
python -m app.propflow.tests.eval_agent --output eval_report.json

# Verbose mode with detailed breakdown
python -m app.propflow.tests.eval_agent --verbose
```

#### **Unit Tests**
```bash
# Test individual components
python -m pytest app/propflow/tests/test_graph.py -v

# Test services  
python -m pytest app/propflow/tests/test_services.py -v

# Test all PropFlow components
python -m pytest app/propflow/tests/ -v
```

#### **Integration Tests**
```bash
# End-to-end workflow test
python scripts/test_propflow_e2e.py

# Test with specific scenario
python scripts/test_propflow_e2e.py --scenario "Happy Path - Pidgin to Lease"

# Test all scenarios
python scripts/test_propflow_e2e.py --all-scenarios
```

---

## 🚀 **Running the Application**

### **Development Mode**

**Terminal 1 - Backend**:
```bash
cd server
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 - Frontend**:
```bash  
cd client
pnpm dev
```

**Terminal 3 - PropFlow Chat Test**:
```bash
cd server
python scripts/test_propflow_chat.py
```

### **Production Mode**
```bash
cd server
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

---

## 📊 **Demo Scenarios**

### **Scenario 1: Nigerian Pidgin Input**
```bash
# Start application
# Open http://localhost:3000
# Navigate to tenant dashboard  
# Click PropFlow chat widget
# Input: "I wan 2-bed flat for Lekki, budget 500k monthly"
# Expected: Intent extracted → Properties found → Application created
```

### **Scenario 2: Memory Integration (Returning Tenant)**
```bash
# Use same tenant from Scenario 1
# Input: "I want apartment again, similar area"
# Expected: Mem0 memory retrieved → Personalized search → Faster processing
```

### **Scenario 3: Landlord Approval Flow**
```bash
# Continue from Scenario 1
# Application reaches "awaiting_landlord_approval"
# Simulate landlord approval via API:
curl -X POST http://localhost:8000/api/v1/propflow/resume/{thread_id} \
  -H "Authorization: Bearer {landlord_jwt}" \
  -d '{"decision": "approved"}'
```

### **Scenario 4: Complete Payment Flow**
```bash
# Continue from Scenario 3
# Agreement signed by both parties
# PropFlow provisions Nomba DVA
# Shows payment account: "Pay ₦500,000 to account 9391076543"
```

---

## 🔍 **Troubleshooting**

### **Common Issues**

**1. Qwen API Authentication Error**
```bash
# Error: 401 Unauthorized
# Solution: Check QWEN_API_KEY in .env file
# Verify key is valid at dashscope-intl.aliyuncs.com
```

**2. Mem0 Connection Failed**
```bash
# Error: Mem0 connection failed
# Solution 1: Check MEM0_API_KEY
# Solution 2: Set MEM0_ENABLED=false to use mock mode
```

**3. OSS Upload Failed**  
```bash
# Error: OSS access denied
# Solution: Verify OSS_ACCESS_KEY_ID and OSS_ACCESS_KEY_SECRET
# Check bucket permissions in Alibaba Cloud console
```

**4. Database Connection Error**
```bash
# Error: Supabase connection failed
# Solution: Check SUPABASE_URL and SUPABASE_SERVICE_KEY
# Verify database is accessible and migrations ran
```

**5. Frontend API Connection Error**
```bash
# Error: API calls failing
# Solution: Ensure backend is running on port 8000
# Check CORS settings in FastAPI
```

### **Debug Mode**
```bash
# Enable detailed logging
export PROPFLOW_LOG_LEVEL=DEBUG
export QWEN_LOG_LEVEL=DEBUG

# Run with debug
python -m app.propflow.tests.eval_agent --debug
```

### **Health Checks**
```bash
# Backend health
curl http://localhost:8000/api/v1/health

# PropFlow health
curl http://localhost:8000/api/v1/health/propflow

# Database health  
curl http://localhost:8000/api/v1/health/db
```

---

## 📈 **Performance Expectations**

### **Mock Mode Results**
```
Intent Field Accuracy: ~54%
Confidence Calibration: 0.25  
Pidgin Processing: ~68%
Briefing Quality: 100% (3-sentence compliance)
Briefing Grounding: ~40%
Overall Score: ~68%
```

### **Real Qwen Mode Results**  
```
Intent Field Accuracy: ~88% (+34% improvement)
Confidence Calibration: <0.10 (4x better)
Pidgin Processing: ~85% (+17% improvement)  
Briefing Quality: 100% (maintained)
Briefing Grounding: ~85% (+45% improvement)
Overall Score: ~88% (+20% improvement)
```

### **Expected Response Times**
- **Intent Extraction**: 2-4 seconds (Qwen API call)
- **Property Matching**: <1 second (local database)
- **Application Creation**: <2 seconds (database write)
- **Briefing Generation**: 3-5 seconds (Qwen API call)
- **End-to-end Flow**: 15-30 seconds (depending on API latency)

---

## 🎬 **Demo Scripts**

### **Quick Demo (5 minutes)**
```bash
# 1. Health check
curl http://localhost:8000/api/v1/health

# 2. Evaluation test
python -m app.propflow.tests.eval_agent --mock --quick

# 3. Chat simulation
python scripts/simulate_propflow_chat.py --scenario pidgin_basic

# 4. Show results
cat eval_report.json | jq '.overall_score'
```

### **Full Demo (15 minutes)**
```bash
# 1. Complete evaluation
python -m app.propflow.tests.eval_agent --output full_eval.json

# 2. End-to-end test
python scripts/test_propflow_e2e.py --all-scenarios

# 3. Frontend demo
# Open browser to http://localhost:3000
# Navigate through complete tenant journey

# 4. Generate demo report
python scripts/generate_demo_report.py --output demo_results.md
```

---

## 📋 **Submission Checklist**

### **Before Hackathon Demo**
- [ ] All API keys configured and tested
- [ ] Both mock and real mode working
- [ ] Evaluation shows >85% Qwen performance  
- [ ] Frontend chat widget functional
- [ ] End-to-end flow completes successfully
- [ ] Documentation updated with latest results
- [ ] Demo video recorded (3 minutes)
- [ ] Repository is public and up-to-date

### **For Judges**
- [ ] `SUBMISSION_README.md` completed
- [ ] Alibaba Cloud OSS integration documented
- [ ] Evaluation report generated (`eval_report.json`)
- [ ] Setup instructions verified (this guide)
- [ ] Demo scenarios tested and working
- [ ] Performance metrics documented

---

## 📞 **Support**

### **Technical Issues**
- Check logs in `server/logs/propflow.log`
- Run health checks for all services
- Verify environment variables are set correctly

### **API Issues**
- **Qwen**: Check dashscope-intl.aliyuncs.com status
- **Mem0**: Check mem0.ai service status  
- **OSS**: Verify Alibaba Cloud console accessC:\MyFiles\DOCUMENT-2026\Nuelo_Poc\NULO-DEV\docs\hackathon\Qwen

### **Performance Issues**
- Monitor API response times
- Check database query performance
- Verify network connectivity

---

**Guide Status**: ✅ **Complete**  
**Last Updated**: July 15, 2026  
**PropFlow Version**: 3.1.0
SAMPLE_TENANTS: List[Dict[str, Any]] = [
    {
        "id": "550e8400-e29b-41d4-a716-446655440001",
        "email": "chidi.obi@flutterwave.com",
        "full_name": "Chidi Obi",
        "phone": "+2348123456789",
        "role": "tenant",
        "profile": {
            "identity_verification_status": "verified",
            "employment_status": "employed",
            "monthly_income_range": "500000-1000000",
            "company_name": "Flutterwave Technology Solutions",
            "job_title": "Senior Software Engineer",
            "work_location": "Lagos Island",
            "guarantor_name": "Dr. Ngozi Obi",
            "guarantor_phone": "+2348987654321",
            "emergency_contact_name": "Mrs. Adunni Obi",
            "emergency_contact_phone": "+2348111222333",
            "references": {
                "previous_landlord": "Mr. Tunde Bakare",
                "previous_landlord_phone": "+2348555666777"
            }
        }
    },
    {
        "id": "550e8400-e29b-41d4-a716-446655440002", 
        "email": "fatima.hassan@andela.com",
        "full_name": "Fatima Hassan",
        "phone": "+2349876543210",
        "role": "tenant",
        "profile": {
            "identity_verification_status": "verified",
            "employment_status": "employed", 
            "monthly_income_range": "300000-500000",
            "company_name": "Andela Nigeria",
            "job_title": "Product Manager",
            "work_location": "Victoria Island",
            "guarantor_name": "Mallam Yusuf Hassan",
            "guarantor_phone": "+2349111222333",
            "emergency_contact_name": "Hajiya Amina Hassan",
            "emergency_contact_phone": "+2349444555666"
        }
    }
]
# ═══════════════════════════════════════════════════════════════════════════════
# SAMPLE PROPERTIES  
# ═══════════════════════════════════════════════════════════════════════════════

SAMPLE_PROPERTIES: List[Dict[str, Any]] = [
    {
        "id": "770e8400-e29b-41d4-a716-446655440001",
        "title": "Modern 2-Bedroom Apartment in Lekki Phase 1",
        "location": "Lekki Phase 1, Lagos",
        "address": "15 Admiralty Way, Lekki Phase 1",
        "price": 480000.0,
        "beds": 2,
        "baths": 2,
        "size_sqm": 85,
        "property_type": "apartment",
        "status": "approved", 
        "verification_status": "verified",
        "landlord_id": "660e8400-e29b-41d4-a716-446655440001",
        "amenities": ["parking", "security", "generator", "swimming_pool"],
        "images": [
            "https://example.com/property1_1.jpg",
            "https://example.com/property1_2.jpg"
        ],
        "created_at": "2026-07-10T10:00:00Z"
    },
    {
        "id": "770e8400-e29b-41d4-a716-446655440002",
        "title": "Luxury 3-Bedroom Flat in Victoria Island", 
        "location": "Victoria Island, Lagos",
        "address": "25 Kofo Abayomi Street, Victoria Island",
        "price": 850000.0,
        "beds": 3,
        "baths": 3,
        "size_sqm": 120,
        "property_type": "apartment",
        "status": "approved",
        "verification_status": "verified", 
        "landlord_id": "660e8400-e29b-41d4-a716-446655440002",
        "amenities": ["parking", "security", "elevator", "gym", "swimming_pool"],
        "created_at": "2026-07-12T14:30:00Z"
    }
]
# ═══════════════════════════════════════════════════════════════════════════════
# SAMPLE INQUIRIES (VARIOUS FORMATS)
# ═══════════════════════════════════════════════════════════════════════════════

SAMPLE_INQUIRIES: Dict[str, str] = {
    # Nigerian Pidgin examples
    "pidgin_basic": "I wan 2-bed flat for Lekki, my budget na 500k monthly",
    "pidgin_detailed": "Abeg I dey find house for Victoria Island area. I wan 3-bedroom with parking. My budget na 800k to 1M per month. I wan move in by August",
    "pidgin_urgent": "I need house sharp sharp! 2-bed apartment for Lekki or Ajah. Budget 400k-600k monthly. I get job for VI, need am before month end",
    
    # Formal English
    "formal_basic": "I'm looking for a 2-bedroom apartment in Lekki Phase 1, budget ₦500,000 monthly",
    "formal_detailed": "Good day, I need a 3-bedroom apartment in Victoria Island or Ikoyi. My budget is between ₦800,000 to ₦1,200,000 monthly. I work on Lagos Island and prefer modern amenities like parking, security, and generator backup. Move-in date is flexible but preferably by end of August 2026.",
    
    # Mixed format (common in Nigeria)
    "mixed_casual": "Hi, I want to rent apartment for Lekki area. 2-bedroom, budget around 400-500k monthly. I work for tech company, need good internet. When can I view?",
    "mixed_specific": "Good morning, I'm looking for house to rent. I want 3-bed apartment, preferably Victoria Island or Lekki Phase 1. Budget na ₦700k-900k monthly. I need am urgently because my current lease dey expire next month.",
    
    # Edge cases for testing
    "vague_budget": "I want nice apartment in good area of Lagos. Not too expensive but not too cheap. 2 or 3 bedrooms", 
    "no_location": "I need 2-bedroom apartment, budget ₦600k monthly. Good security and parking important",
    "no_bedrooms": "Looking for apartment in Lekki area, budget around ₦500k monthly. Need parking and security"
}
# ═══════════════════════════════════════════════════════════════════════════════
# EXPECTED INTENT EXTRACTIONS (GROUND TRUTH)
# ═══════════════════════════════════════════════════════════════════════════════

EXPECTED_INTENTS: Dict[str, Dict[str, Any]] = {
    "pidgin_basic": {
        "property_type": "apartment",
        "location": "Lekki", 
        "bedrooms": 2,
        "budget_monthly": 500000.0,
        "budget_annual": None,
        "move_in_date": None,
        "payment_frequency": "MONTHLY",
        "special_requests": []
    },
    "formal_detailed": {
        "property_type": "apartment",
        "location": "Victoria Island", 
        "bedrooms": 3,
        "budget_monthly": 1000000.0,  # Mid-range of 800k-1.2M
        "budget_annual": None,
        "move_in_date": "2026-08-31",
        "payment_frequency": "MONTHLY", 
        "special_requests": ["parking", "security", "generator"]
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# MOCK RESPONSES FOR TESTING
# ═══════════════════════════════════════════════════════════════════════════════

MOCK_QWEN_RESPONSES: Dict[str, str] = {
    "intent_extraction": '''
    {
        "property_type": "apartment",
        "location": "Lekki",
        "bedrooms": 2,
        "budget_monthly": 500000.0,
        "budget_annual": null,
        "move_in_date": null,
        "payment_frequency": "MONTHLY",
        "special_requests": [],
        "confidence": 0.91
    }
    ''',
    
    "landlord_briefing": '''Chidi Obi is a Senior Software Engineer at Flutterwave with verified income in the ₦500k-1M range, seeking a 2-bedroom apartment in Lekki for ₦480k monthly. He has a strong employment history in tech, verified identity documents, and a guarantor (Dr. Ngozi Obi) with solid references from previous landlords.'''
}
# ═══════════════════════════════════════════════════════════════════════════════
# TEST SCENARIOS
# ═══════════════════════════════════════════════════════════════════════════════

TEST_SCENARIOS: List[Dict[str, Any]] = [
    {
        "name": "Happy Path - Pidgin to Lease",
        "description": "Complete flow from Pidgin inquiry to signed lease",
        "tenant": SAMPLE_TENANTS[0],
        "inquiry": SAMPLE_INQUIRIES["pidgin_basic"],
        "expected_property_matches": 1,  # Should match Lekki property
        "expected_intent": EXPECTED_INTENTS["pidgin_basic"],
        "landlord_decision": "approved",
        "expected_final_stage": "nomba_provisioned"
    },
    {
        "name": "Application Rejection",
        "description": "Landlord rejects application, tenant notified with reason",
        "tenant": SAMPLE_TENANTS[1],
        "inquiry": SAMPLE_INQUIRIES["formal_detailed"],
        "expected_property_matches": 1,
        "landlord_decision": "rejected",
        "rejection_reason": "Income verification required", 
        "expected_final_stage": "rejected"
    },
    {
        "name": "No Properties Found",
        "description": "Tenant inquiry matches no available properties",
        "tenant": SAMPLE_TENANTS[1],
        "inquiry": "I want 5-bedroom mansion in Banana Island for ₦200k monthly",
        "expected_property_matches": 0,
        "expected_final_stage": "no_properties_found"
    }
]

# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_tenant_by_id(tenant_id: str) -> Dict[str, Any] | None:
    """Get tenant data by ID"""
    for tenant in SAMPLE_TENANTS:
        if tenant["id"] == tenant_id:
            return tenant
    return None

def get_property_by_id(property_id: str) -> Dict[str, Any] | None:
    """Get property data by ID"""  
    for prop in SAMPLE_PROPERTIES:
        if prop["id"] == property_id:
            return prop
    return None
def get_matching_properties(location: str, bedrooms: int | None, max_price: float | None) -> List[Dict[str, Any]]:
    """Filter properties based on criteria (mimics match_properties logic)"""
    matches = []
    
    for prop in SAMPLE_PROPERTIES:
        # Location check (case-insensitive, partial match)
        if location and location.lower() not in prop["location"].lower():
            continue
            
        # Bedrooms check  
        if bedrooms and prop["beds"] != bedrooms:
            continue
            
        # Price check
        if max_price and prop["price"] > max_price:
            continue
            
        matches.append(prop)
    
    return matches[:3]  # Top 3 matches

def create_mock_thread_id() -> str:
    """Generate mock thread ID for testing"""
    return f"test-thread-{uuid.uuid4().hex[:8]}"

def create_mock_application_id() -> str:
    """Generate mock application ID for testing"""
    return f"app-{uuid.uuid4().hex[:8]}"

# Export all fixtures
__all__ = [
    "SAMPLE_TENANTS",
    "SAMPLE_PROPERTIES", 
    "SAMPLE_INQUIRIES",
    "EXPECTED_INTENTS",
    "MOCK_QWEN_RESPONSES",
    "TEST_SCENARIOS",
    "get_tenant_by_id",
    "get_property_by_id",
    "get_matching_properties",
    "create_mock_thread_id",
    "create_mock_application_id"
]