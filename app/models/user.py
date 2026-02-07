"""
User-related Pydantic models for request/response validation
"""
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, Literal
from datetime import datetime


# Enums
UserType = Literal["tenant", "landlord", "admin"]
VerificationStatus = Literal["pending", "approved", "rejected", "partial"]


# Request Models
class UserRegister(BaseModel):
    """User registration request - minimal for Option A signup"""
    email: EmailStr
    password: str = Field(..., min_length=8)  # ✅ Fixed: Changed from 6 to 8 to match frontend
    full_name: Optional[str] = None  # Will be filled in onboarding
    user_type: Optional[UserType] = "tenant"  # Default to tenant, set in onboarding
    phone_number: Optional[str] = None  # Will be filled in onboarding
    
    # Landlord verification fields
    nin: Optional[str] = None
    bvn: Optional[str] = None
    id_document: Optional[str] = None  # File path or URL
    selfie_photo: Optional[str] = None  # File path or URL
    account_type: Optional[Literal["individual", "company"]] = "individual"
    company_name: Optional[str] = None
    cac_number: Optional[str] = None
    cac_certificate: Optional[str] = None  # File path or URL
    tax_id: Optional[str] = None


class UserLogin(BaseModel):
    """User login request"""
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    """User profile update request"""
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    avatar_url: Optional[str] = None
    location: Optional[str] = None  
    onboarding_completed: Optional[bool] = None  
    user_type: Optional[str] = None


# Response Models
class UserBase(BaseModel):
    """Base user response"""
    id: str
    email: str
    full_name: Optional[str]
    avatar_url: Optional[str]
    location: Optional[str]
    user_type: UserType  # Changed from user_type to match database column
    trust_score: int
    verification_status: VerificationStatus
    created_at: datetime
    
    class Config:
        from_attributes = True


class TenantProfile(BaseModel):
    """Tenant-specific profile"""
    budget: Optional[float]
    preferred_location: Optional[str]
    move_in_date: Optional[datetime]
    preferences: dict = {}
    documents: dict = {}
    profile_completion: int
    onboarding_completed: bool
    
    class Config:
        from_attributes = True


class LandlordProfile(BaseModel):
    """Landlord-specific profile"""
    ownership_docs: list[str] = []
    verification_submitted_at: Optional[datetime]
    verification_approved_at: Optional[datetime]
    guarantee_joined: bool
    guarantee_contribution: float
    bank_account_number: Optional[str]
    bank_name: Optional[str]
    
    class Config:
        from_attributes = True


class UserResponse(UserBase):
    """Complete user response with type-specific data"""
    tenant_profile: Optional[TenantProfile] = None
    landlord_profile: Optional[LandlordProfile] = None


class AuthResponse(BaseModel):
    """Authentication response"""
    success: bool
    user: UserResponse
    access_token: str
    token_type: str = "bearer"
    message: Optional[str] = None


class SocialLoginRequest(BaseModel):
    """Social login request payload from frontend"""
    provider: str
    provider_account_id: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    profile: dict
    user_type: Optional[UserType] = None
    # Onboarding fields for Google users
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    location: Optional[str] = None
    onboarding_completed: Optional[bool] = None


# Trust Score Models
class TrustScoreBreakdown(BaseModel):
    """Trust score detailed breakdown"""
    trust_score: int
    breakdown: dict = {
        "base_score": 50,
        "verification_bonus": 0,
        "rating_impact": 0,
        "completion_bonus": 0,
        "guarantee_bonus": 0,
    }
    ratings: dict = {
        "average": 0.0,
        "count": 0,
    }
