"""
Test Agreement Generation API
=================================

Quick test endpoint for AI agreement generation without full application flow.
This allows rapid testing of the AI service with custom data.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import logging

from app.services.ai.ai_service import ai_service
from app.services.agreement_service import AgreementService

logger = logging.getLogger(__name__)
router = APIRouter()

class TestAgreementRequest(BaseModel):
    tenant_name: str
    landlord_name: str
    property_address: str
    monthly_rent: int
    lease_duration: str = "12 months"
    property_type: str = "Apartment"

class TestAgreementResponse(BaseModel):
    success: bool
    agreement: Optional[str] = None
    agreement_source: Optional[str] = None
    generation_metadata: Optional[dict] = None
    error: Optional[str] = None
    usage_stats: Optional[dict] = None

@router.post("/generate-agreement", response_model=TestAgreementResponse)
async def test_generate_agreement(request: TestAgreementRequest):
    """
    Test AI agreement generation with custom data.
    
    This endpoint bypasses the full application flow and directly tests
    the AI agreement generation service with provided parameters.
    
    Args:
        request: Test agreement data
        
    Returns:
        Generated agreement with metadata or error
    """
    try:
        logger.info(f"🧪 Test agreement generation request:")
        logger.info(f"   Tenant: {request.tenant_name}")
        logger.info(f"   Landlord: {request.landlord_name}")
        logger.info(f"   Property: {request.property_address}")
        logger.info(f"   Rent: ₦{request.monthly_rent:,}")
        logger.info(f"   Duration: {request.lease_duration}")
        
        # Validate input
        if request.monthly_rent <= 0:
            raise HTTPException(status_code=400, detail="Monthly rent must be positive")
        
        if len(request.tenant_name.strip()) < 2:
            raise HTTPException(status_code=400, detail="Tenant name too short")
        
        if len(request.landlord_name.strip()) < 2:
            raise HTTPException(status_code=400, detail="Landlord name too short")
        
        if len(request.property_address.strip()) < 10:
            raise HTTPException(status_code=400, detail="Property address too short")
        
        # Prepare data in the format expected by generate_enhanced_agreement_terms
        property_data = {
            "full_address": request.property_address.strip(),
            "address": request.property_address.strip(),
            "location": request.property_address.strip(),
            "property_type": request.property_type,
            "type": request.property_type,
            "price": request.monthly_rent
        }
        
        tenant_data = {
            "full_name": request.tenant_name.strip(),
            "email": "test@example.com",
            "phone_number": "+2348000000000",
            "address": "Test Tenant Address"
        }
        
        lease_dates = {
            "lease_start_date": "2026-05-04",
            "lease_end_date": "2027-05-04",
            "lease_duration": int(request.lease_duration.split()[0]) if request.lease_duration.split()[0].isdigit() else 12,
            "duration_months": int(request.lease_duration.split()[0]) if request.lease_duration.split()[0].isdigit() else 12
        }

        # Generate agreement using the production service (exact same as tenant/landlord pages)
        result = await AgreementService.generate_enhanced_agreement_terms(
            property_data=property_data,
            tenant_data=tenant_data,
            landlord_name=request.landlord_name.strip(),
            lease_dates=lease_dates
        )
        
        # The service always returns terms, source, and metadata (no success key needed)
        agreement_source = result.get("source", "manual_template")
        generation_metadata = result.get("metadata", {})
        
        logger.info(f"✅ Test agreement generated successfully!")
        logger.info(f"   Source: {agreement_source}")
        logger.info(f"   Length: {len(result['terms'])} characters")
        
        if generation_metadata:
            logger.info(f"   Compliance: {generation_metadata.get('compliance_score', 'N/A')}%")
            logger.info(f"   Cost: ${generation_metadata.get('cost_usd', 0):.6f}")
        
        return TestAgreementResponse(
            success=True,
            agreement=result["terms"],
            agreement_source=agreement_source,
            generation_metadata=generation_metadata,
            usage_stats=ai_service.get_usage_stats()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Test agreement generation error: {str(e)}")
        return TestAgreementResponse(
            success=False,
            error=f"Internal server error: {str(e)}",
            usage_stats=ai_service.get_usage_stats()
        )

@router.get("/usage-stats")
async def get_usage_stats():
    """Get AI service usage statistics"""
    try:
        stats = ai_service.get_usage_stats()
        return {
            success: True,
            stats: stats
        }
    except Exception as e:
        logger.error(f"❌ Usage stats error: {str(e)}")
        return {
            success: False,
            error: str(e)
        }
