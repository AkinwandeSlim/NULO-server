"""
Simple Test Agreement Generation API (No Auth Required)
========================================================

Quick testing version that bypasses authentication for development.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from app.services.ai.ai_service import ai_service
from app.services.agreement_service import AgreementService

logger = logging.getLogger(__name__)
router = APIRouter()

class SimpleTestRequest(BaseModel):
    tenant_name: str
    landlord_name: str
    property_address: str
    monthly_rent: int
    lease_duration: str = "12 months"
    property_type: str = "Apartment"

class SimpleTestResponse(BaseModel):
    success: bool
    agreement: Optional[str] = None
    agreement_source: Optional[str] = None
    generation_metadata: Optional[dict] = None
    error: Optional[str] = None
    usage_stats: Optional[dict] = None

@router.post("/generate-agreement-simple", response_model=SimpleTestResponse)
async def test_generate_agreement_simple(request: SimpleTestRequest):
    """
    Simple test AI agreement generation WITHOUT authentication.
    
    This is for development testing only. Bypasses auth and directly tests AI generation.
    """
    try:
        logger.info(f"🧪 Simple test agreement generation:")
        logger.info(f"   Tenant: {request.tenant_name}")
        logger.info(f"   Landlord: {request.landlord_name}")
        logger.info(f"   Property: {request.property_address}")
        logger.info(f"   Rent: ₦{request.monthly_rent:,}")
        logger.info(f"   Duration: {request.lease_duration}")
        
        # Basic validation
        if request.monthly_rent <= 0:
            raise HTTPException(status_code=400, detail="Monthly rent must be positive")
        
        if len(request.tenant_name.strip()) < 2:
            raise HTTPException(status_code=400, detail="Tenant name too short")
        
        if len(request.landlord_name.strip()) < 2:
            raise HTTPException(status_code=400, detail="Landlord name too short")
        
        if len(request.property_address.strip()) < 10:
            raise HTTPException(status_code=400, detail="Property address too short")
        
        # Call AI service directly (no agreement service wrapper)
        logger.info(f"🤖 Calling AI service directly...")
        
        try:
            # Direct AI service call
            ai_result = await ai_service.generate_agreement(
                tenant_name=request.tenant_name.strip(),
                landlord_name=request.landlord_name.strip(),
                property_address=request.property_address.strip(),
                monthly_rent=request.monthly_rent,
                lease_duration=request.lease_duration,
                property_type=request.property_type
            )
            
            if ai_result["success"]:
                logger.info(f"✅ AI generation successful!")
                return SimpleTestResponse(
                    success=True,
                    agreement=ai_result["agreement"],
                    agreement_source="groq_llama",
                    generation_metadata={
                        "compliance_score": ai_result.get("compliance_score", 0),
                        "model_used": ai_result.get("model_used", "unknown"),
                        "tokens_used": ai_result.get("tokens_used", 0),
                        "cost_usd": ai_result.get("cost_usd", 0),
                        "generated_at": ai_result.get("generated_at", "unknown")
                    },
                    usage_stats=ai_service.get_usage_stats()
                )
            else:
                logger.error(f"❌ AI generation failed: {ai_result.get('error')}")
                # Fallback to manual template
                logger.info(f"🔄 Falling back to manual template...")
                
                from datetime import datetime
                template_terms = f"""
TENANCY AGREEMENT

This Tenancy Agreement is made on this {datetime.now().strftime("%dth day of %B, %Y")}.

PARTIES:
1. LANDLORD: {request.landlord_name}
2. TENANT: {request.tenant_name}

PROPERTY:
{request.property_address}
({request.property_type})

FINANCIAL TERMS:
- Monthly Rent: ₦{request.monthly_rent:,}
- Lease Duration: {request.lease_duration}
- Security Deposit: ₦{request.monthly_rent * 2:,}

TERMS AND CONDITIONS:
1. The tenant shall pay rent monthly in advance.
2. The property shall be used for residential purposes only.
3. The tenant shall maintain the property in good condition.
4. The landlord shall handle structural repairs.
5. Either party may terminate with proper notice.

SIGNATURES:
Landlord: ____________________ {request.landlord_name}
Tenant: ____________________ {request.tenant_name}
Date: ____________________

Generated via NuloAfrica Platform - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                """.strip()
                
                return SimpleTestResponse(
                    success=True,
                    agreement=template_terms,
                    agreement_source="manual_template",
                    generation_metadata={
                        "template_version": "enhanced_v1",
                        "fallback_reason": ai_result.get("error", "AI service unavailable")
                    },
                    usage_stats=ai_service.get_usage_stats()
                )
                
        except Exception as ai_error:
            logger.error(f"❌ AI service error: {str(ai_error)}")
            # Always provide template fallback (same as production)
            from datetime import datetime
            template_terms = f"""
TENANCY AGREEMENT

This Tenancy Agreement is made on this {datetime.now().strftime("%dth day of %B, %Y")} ("Agreement Date")

BETWEEN:
LANDLORD
- Full Name: {request.landlord_name}
- Address: [Landlord Address to be provided]
- Phone: [Landlord Phone to be provided]
- Email: [Landlord Email to be provided]

AND:
TENANT
- Full Name: {request.tenant_name}
- Address: [Tenant Address to be provided]
- Phone: [Tenant Phone to be provided]
- Email: [Tenant Email to be provided]

PROPERTY DETAILS:
- Property Address: {request.property_address}
- Property Type: {request.property_type}
- Use: Residential purposes only

LEASE TERMS:
- Lease Duration: {request.lease_duration}
- Start Date: {datetime.now().strftime('%B %d, %Y')}
- End Date: {(datetime.now().replace(year=datetime.now().year + 1)).strftime('%B %d, %Y')}

FINANCIAL TERMS:
- Monthly Rent: ₦{request.monthly_rent:,}
- Annual Rent: ₦{request.monthly_rent * 12:,}
- Security Deposit: ₦{request.monthly_rent * 2:,} (equivalent to 2 months' rent)
- Payment Method: Via NuloAfrica platform
- Payment Schedule: Monthly in advance
- Payment Due: On or before the 1st day of each month

TERMS AND CONDITIONS:

1. RENT PAYMENT
   - Rent shall be paid monthly in advance through the NuloAfrica platform
   - Late payment shall attract a penalty of 5% of the monthly rent
   - All payments are subject to NuloAfrica's escrow protection

2. SECURITY DEPOSIT
   - Security deposit is refundable subject to property inspection at move-out
   - Deposit will be returned within 30 days of lease termination
   - Deductions may be made for damages beyond normal wear and tear

3. PROPERTY MAINTENANCE
   - Tenant shall maintain the property in good condition and repair
   - Tenant is responsible for minor repairs and maintenance
   - Landlord shall be responsible for major structural repairs

4. UTILITIES AND SERVICES
   - Tenant shall be responsible for payment of electricity, water, and waste disposal
   - Landlord shall be responsible for property taxes and building insurance
   - Service charges (if applicable) shall be paid by tenant

5. PROPERTY USE
   - The property shall be used solely for residential purposes
   - No commercial activities shall be conducted on the premises
   - No subletting shall be allowed without landlord's written consent

6. ACCESS AND INSPECTION
   - Landlord shall have right to inspect property with 24 hours notice
   - Reasonable access shall be allowed for repairs and maintenance
   - Emergency access shall be permitted without prior notice

7. DEFAULT AND REMEDIES
   - Rent arrears exceeding 30 days constitute default
   - Landlord may terminate agreement for persistent default
   - Tenant may withhold rent for major breaches by landlord

8. TERMINATION NOTICE
   - Tenant shall provide 6 months written notice before termination
   - Landlord shall provide 1 month written notice before termination
   - Notice shall be in writing and signed by the terminating party

9. DISPUTE RESOLUTION
   - All disputes shall first be resolved through mutual discussion
   - If unresolved, disputes shall be referred to arbitration
   - Arbitration shall be conducted in accordance with Nigerian Arbitration Act 2011

10. LEGAL COMPLIANCE
    - This agreement is governed by the laws of the Federal Republic of Nigeria
    - Lagos Tenancy Law 2011 compliance is acknowledged by both parties
    - Both parties acknowledge receipt and understanding of all terms

11. FORCE MAJEURE
    - Neither party shall be liable for breaches due to force majeure events
    - Government actions affecting property use shall be considered force majeure
    - Affected party shall notify the other party within 14 days of such events

12. ENTIRE AGREEMENT
    - This agreement constitutes the entire understanding between parties
    - No verbal agreements or modifications shall be recognized
    - Changes must be in writing and signed by both parties

SIGNATURES:

This agreement is automatically generated upon application approval.
Both parties must digitally sign to activate the lease.

LANDLORD:
_________________________
{request.landlord_name}
Date: _________________

TENANT:
_________________________
{request.tenant_name}
Date: _________________

WITNESSED BY:
_________________________
Witness Name
Date: _________________

NOTICE: This is a legally binding agreement. Read carefully before signing.
Generated via NuloAfrica Platform - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                """.strip()
            
            return SimpleTestResponse(
                success=True,
                agreement=template_terms,
                agreement_source="manual_template",
                generation_metadata={
                    "template_version": "enhanced_v1",
                    "fallback_reason": f"AI service error: {str(ai_error)}"
                },
                usage_stats=ai_service.get_usage_stats()
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Simple test error: {str(e)}")
        return SimpleTestResponse(
            success=False,
            error=f"Internal server error: {str(e)}",
            usage_stats=ai_service.get_usage_stats()
        )
