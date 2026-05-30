"""
Groq AI Agreement API Routes
============================

FastAPI routes for generating Nigerian tenancy agreements using Groq AI.
This provides REST endpoints for the NuloAfrica platform.

Endpoints:
- POST /api/v1/groq/generate-agreement - Generate simple agreement
- POST /api/v1/groq/generate-advanced-agreement - Generate advanced agreement
- GET /api/v1/groq/test-connection - Test Groq AI connection
- GET /api/v1/groq/usage-stats - Get usage statistics
- POST /api/v1/groq/reset-stats - Reset usage statistics
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

from app.services.ai.ai_service import ai_service

router = APIRouter(prefix="/api/v1/groq", tags=["Groq AI Agreement"])
logger = logging.getLogger(__name__)

# Request/Response Models
class SimpleAgreementRequest(BaseModel):
    """Request model for simple agreement generation"""
    tenant_name: str = Field(..., description="Tenant's full name")
    landlord_name: str = Field(..., description="Landlord's full name")
    property_address: str = Field(..., description="Property address")
    monthly_rent: int = Field(..., gt=0, description="Monthly rent in Naira")
    lease_duration: str = Field(default="1 year", description="Lease duration")
    property_type: str = Field(default="Apartment", description="Property type")

class AdvancedAgreementRequest(BaseModel):
    """Request model for advanced agreement generation"""
    tenant_data: Dict[str, Any] = Field(..., description="Complete tenant information")
    landlord_data: Dict[str, Any] = Field(..., description="Complete landlord information")
    property_data: Dict[str, Any] = Field(..., description="Complete property information")

class AgreementResponse(BaseModel):
    """Response model for agreement generation"""
    success: bool
    agreement: Optional[str] = None
    model_used: Optional[str] = None
    tokens_used: Optional[int] = None
    generation_time_seconds: Optional[float] = None
    cost_usd: Optional[float] = None
    compliance: Optional[Dict[str, bool]] = None
    compliance_score: Optional[float] = None
    summary: Optional[Dict[str, Any]] = None
    usage_stats: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    message: Optional[str] = None

class ConnectionTestResponse(BaseModel):
    """Response model for connection test"""
    connected: bool
    service: str = "Groq AI"
    model: str = "llama-3.3-70b-versatile"
    timestamp: str
    message: Optional[str] = None

class UsageStatsResponse(BaseModel):
    """Response model for usage statistics"""
    usage_stats: Dict[str, Any]
    cost_analysis: Dict[str, Any]
    timestamp: str

# Routes
@router.get("/test-connection", response_model=ConnectionTestResponse)
async def test_connection():
    """
    Test Groq AI connection
    
    Returns:
        ConnectionTestResponse: Connection status and details
    """
    try:
        logger.info("🔍 Testing Groq AI connection...")
        
        is_connected = await ai_service.test_connection()
        
        response = ConnectionTestResponse(
            connected=is_connected,
            timestamp=datetime.now().isoformat(),
            message="Groq AI connection successful" if is_connected else "Groq AI connection failed"
        )
        
        logger.info(f"✅ Connection test result: {is_connected}")
        return response
        
    except Exception as e:
        logger.error(f"❌ Connection test error: {str(e)}")
        raise HTTPException(500, f"Connection test failed: {str(e)}")

@router.post("/generate-agreement", response_model=AgreementResponse)
async def generate_simple_agreement(
    request: SimpleAgreementRequest,
    background_tasks: BackgroundTasks
):
    """
    Generate simple Nigerian tenancy agreement using Groq AI
    
    Args:
        request: Simple agreement request data
        background_tasks: FastAPI background tasks for logging
    
    Returns:
        AgreementResponse: Generated agreement or error details
    """
    try:
        logger.info(f"📝 Generating simple agreement for: {request.tenant_name} → {request.landlord_name}")
        
        # Validate input
        if request.monthly_rent <= 0:
            raise HTTPException(400, "Monthly rent must be greater than 0")
        
        if not request.tenant_name.strip():
            raise HTTPException(400, "Tenant name is required")
        
        if not request.landlord_name.strip():
            raise HTTPException(400, "Landlord name is required")
        
        if not request.property_address.strip():
            raise HTTPException(400, "Property address is required")
        
        # Generate agreement
        result = await ai_service.generate_agreement(
            tenant_name=request.tenant_name,
            landlord_name=request.landlord_name,
            property_address=request.property_address,
            monthly_rent=request.monthly_rent,
            lease_duration=request.lease_duration,
            property_type=request.property_type
        )
        
        if not result["success"]:
            logger.error(f"❌ Agreement generation failed: {result['error']}")
            return AgreementResponse(
                success=False,
                error=result["error"],
                message="Failed to generate agreement"
            )
        
        # Log successful generation in background
        background_tasks.add_task(
            log_agreement_generation,
            "simple",
            request.tenant_name,
            request.landlord_name,
            result["tokens_used"],
            result["cost_usd"]
        )
        
        logger.info(f"✅ Simple agreement generated successfully for {request.tenant_name}")
        
        return AgreementResponse(
            success=True,
            agreement=result["agreement"],
            model_used=result["model_used"],
            tokens_used=result["tokens_used"],
            generation_time_seconds=result["generation_time_seconds"],
            cost_usd=result["cost_usd"],
            compliance=result["compliance"],
            compliance_score=result["compliance_score"],
            summary=result["summary"],
            usage_stats=result["usage_stats"],
            message="Simple agreement generated successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Simple agreement generation error: {str(e)}")
        raise HTTPException(500, f"Failed to generate agreement: {str(e)}")

@router.post("/generate-advanced-agreement", response_model=AgreementResponse)
async def generate_advanced_agreement(
    request: AdvancedAgreementRequest,
    background_tasks: BackgroundTasks
):
    """
    Generate advanced Nigerian tenancy agreement with full data using Groq AI
    
    Args:
        request: Advanced agreement request with complete data
        background_tasks: FastAPI background tasks for logging
    
    Returns:
        AgreementResponse: Generated agreement or error details
    """
    try:
        tenant_name = request.tenant_data.get('full_name', 'Unknown')
        landlord_name = request.landlord_data.get('full_name', 'Unknown')
        
        logger.info(f"📋 Generating advanced agreement for: {tenant_name} → {landlord_name}")
        
        # Validate required fields
        required_tenant_fields = ['full_name', 'address', 'phone_number', 'email']
        required_landlord_fields = ['full_name', 'address', 'phone_number', 'email']
        required_property_fields = ['full_address', 'city', 'price']
        
        for field in required_tenant_fields:
            if not request.tenant_data.get(field, '').strip():
                raise HTTPException(400, f"Tenant {field} is required")
        
        for field in required_landlord_fields:
            if not request.landlord_data.get(field, '').strip():
                raise HTTPException(400, f"Landlord {field} is required")
        
        for field in required_property_fields:
            field_value = request.property_data.get(field)
            if field == 'price':
                if not field_value or not isinstance(field_value, (int, float)) or field_value <= 0:
                    raise HTTPException(400, "Property price must be greater than 0")
            else:
                if not field_value or not str(field_value).strip():
                    raise HTTPException(400, f"Property {field} is required")
        
        # Price validation is now handled in the loop above
        
        # Generate advanced agreement
        result = await ai_service.generate_advanced_agreement(
            tenant_data=request.tenant_data,
            landlord_data=request.landlord_data,
            property_data=request.property_data
        )
        
        if not result["success"]:
            logger.error(f"❌ Advanced agreement generation failed: {result['error']}")
            return AgreementResponse(
                success=False,
                error=result["error"],
                message="Failed to generate advanced agreement"
            )
        
        # Log successful generation in background
        background_tasks.add_task(
            log_agreement_generation,
            "advanced",
            tenant_name,
            landlord_name,
            result["tokens_used"],
            result["cost_usd"]
        )
        
        logger.info(f"✅ Advanced agreement generated successfully for {tenant_name}")
        
        return AgreementResponse(
            success=True,
            agreement=result["agreement"],
            model_used=result["model_used"],
            tokens_used=result["tokens_used"],
            generation_time_seconds=result["generation_time_seconds"],
            cost_usd=result["cost_usd"],
            compliance=result["compliance"],
            compliance_score=result["compliance_score"],
            summary=result["summary"],
            usage_stats=result["usage_stats"],
            metadata=result["metadata"],
            message="Advanced agreement generated successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Advanced agreement generation error: {str(e)}")
        raise HTTPException(500, f"Failed to generate advanced agreement: {str(e)}")

@router.get("/usage-stats", response_model=UsageStatsResponse)
async def get_usage_statistics():
    """
    Get Groq AI usage statistics and cost analysis
    
    Returns:
        UsageStatsResponse: Current usage statistics and cost analysis
    """
    try:
        logger.info("📊 Retrieving usage statistics...")
        
        stats = ai_service.get_usage_stats()
        
        # Calculate cost analysis
        cost_analysis = {
            "cost_per_1000_agreements": stats["cost_per_agreement"] * 1000,
            "estimated_monthly_cost_100_agreements": stats["cost_per_agreement"] * 100,
            "estimated_monthly_cost_500_agreements": stats["cost_per_agreement"] * 500,
            "estimated_monthly_cost_1000_agreements": stats["cost_per_agreement"] * 1000,
            "tokens_per_agreement": stats["average_tokens_per_request"],
            "groq_vs_openai_savings": {
                "groq_cost_per_1m_tokens": 0.05,
                "openai_cost_per_1m_tokens": 2.00,
                "savings_percentage": 97.5,
                "savings_per_1m_tokens": 1.95
            }
        }
        
        response = UsageStatsResponse(
            usage_stats=stats,
            cost_analysis=cost_analysis,
            timestamp=datetime.now().isoformat()
        )
        
        logger.info(f"✅ Usage statistics retrieved: {stats['total_requests']} requests, ${stats['total_cost_usd']:.6f} total")
        return response
        
    except Exception as e:
        logger.error(f"❌ Usage statistics error: {str(e)}")
        raise HTTPException(500, f"Failed to retrieve usage statistics: {str(e)}")

@router.post("/reset-stats")
async def reset_usage_statistics():
    """
    Reset usage statistics (for testing or new billing period)
    
    Returns:
        dict: Confirmation message
    """
    try:
        logger.info("🔄 Resetting usage statistics...")
        
        ai_service.reset_usage_stats()
        
        logger.info("✅ Usage statistics reset successfully")
        return {
            "success": True,
            "message": "Usage statistics reset successfully",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Reset statistics error: {str(e)}")
        raise HTTPException(500, f"Failed to reset usage statistics: {str(e)}")

@router.get("/health")
async def health_check():
    """
    Health check endpoint for Groq AI service
    
    Returns:
        dict: Health status
    """
    try:
        is_connected = await ai_service.test_connection()
        stats = ai_service.get_usage_stats()
        
        return {
            "status": "healthy" if is_connected else "unhealthy",
            "service": "Groq AI Agreement Generator",
            "model": ai_service.model,
            "connected": is_connected,
            "total_requests": stats["total_requests"],
            "success_rate": stats["success_rate"],
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Health check error: {str(e)}")
        return {
            "status": "error",
            "service": "Groq AI Agreement Generator",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# Background task for logging
async def log_agreement_generation(
    agreement_type: str,
    tenant_name: str,
    landlord_name: str,
    tokens_used: int,
    cost_usd: float
):
    """Background task to log agreement generation"""
    try:
        logger.info(f"📝 AGREEMENT GENERATED: {agreement_type.upper()} | "
                   f"Tenant: {tenant_name} | Landlord: {landlord_name} | "
                   f"Tokens: {tokens_used} | Cost: ${cost_usd:.6f}")
    except Exception as e:
        logger.error(f"❌ Background logging error: {str(e)}")

# Export router
__all__ = ["router"]
