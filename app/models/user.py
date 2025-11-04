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
    """User registration request"""
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=2)
    user_type: UserType  # Changed from user_type to match database column
    phone_number: Optional[str] = None


class UserLogin(BaseModel):
    """User login request"""
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    """User profile update request"""
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    avatar_url: Optional[str] = None


# Response Models
class UserBase(BaseModel):
    """Base user response"""
    id: str
    email: str
    full_name: Optional[str]
    avatar_url: Optional[str]
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
