"""
Pydantic Schemas for Landlord Onboarding API
Based on Supabase database schema
"""

from pydantic import BaseModel, Field, validator, HttpUrl
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime, date
from uuid import UUID


# Base schemas
class LandlordOnboardingBase(BaseModel):
    """Base schema for landlord onboarding"""
    current_step: int = Field(ge=1, le=4, default=1)
    full_name: Optional[str] = Field(max_length=255)
    phone: Optional[str] = Field(max_length=20)
    date_of_birth: Optional[date]
    landlord_type: Optional[Literal['individual', 'company']]
    
    # Company info (if company type)
    company_name: Optional[str] = Field(max_length=255)
    company_address: Optional[str]
    company_rc_number: Optional[str] = Field(max_length=50)
    
    # Identity verification
    nin: Optional[str] = Field(max_length=11, min_length=11)
    bvn: Optional[str] = Field(max_length=11, min_length=11)
    id_document_type: Optional[str] = Field(max_length=50)
    id_document_number: Optional[str] = Field(max_length=100)
    
    # Bank information
    bank_name: Optional[str] = Field(max_length=100)
    account_number: Optional[str] = Field(max_length=20)
    account_name: Optional[str] = Field(max_length=255)
    account_type: Optional[str] = Field(max_length=50)
    
    # Protection information
    has_insurance: bool = False
    insurance_provider: Optional[str] = Field(max_length=255)
    insurance_policy_number: Optional[str] = Field(max_length=100)
    insurance_expiry_date: Optional[date]
    
    has_guarantor: bool = False
    guarantor_name: Optional[str] = Field(max_length=255)
    guarantor_phone: Optional[str] = Field(max_length=20)
    guarantor_email: Optional[str] = Field(max_length=255)
    guarantor_relationship: Optional[str] = Field(max_length=100)
    guarantor_address: Optional[str]
    
    # Documents storage
    documents: Optional[Dict[str, Any]] = {}
    
    @validator('nin')
def validate_nin(cls, v):
        if v and len(v) != 11:
            raise ValueError('NIN must be exactly 11 digits')
        return v
    
    @validator('bvn')
    def validate_bvn(cls, v):
        if v and len(v) != 11:
            raise ValueError('BVN must be exactly 11 digits')
        return v


class LandlordOnboardingCreate(LandlordOnboardingBase):
    """Schema for creating landlord onboarding"""
    landlord_id: UUID
    ip_address: Optional[str]
    user_agent: Optional[str]


class LandlordOnboardingUpdate(BaseModel):
    """Schema for updating landlord onboarding"""
    current_step: Optional[int] = Field(ge=1, le=4)
    full_name: Optional[str] = Field(max_length=255)
    phone: Optional[str] = Field(max_length=20)
    date_of_birth: Optional[date]
    landlord_type: Optional[Literal['individual', 'company']]
    
    # Step-specific updates
    profile_step_completed: Optional[bool]
    property_step_completed: Optional[bool]
    payment_step_completed: Optional[bool]
    protection_step_completed: Optional[bool]
    
    # Document URLs
    nin_document_url: Optional[HttpUrl]
    id_document_url: Optional[HttpUrl]
    selfie_url: Optional[HttpUrl]
    bank_statement_url: Optional[HttpUrl]
    insurance_document_url: Optional[HttpUrl]
    guarantor_id_url: Optional[HttpUrl]
    
    # Company info
    company_name: Optional[str] = Field(max_length=255)
    company_address: Optional[str]
    company_rc_number: Optional[str] = Field(max_length=50)
    
    # Bank info
    bank_name: Optional[str] = Field(max_length=100)
    account_number: Optional[str] = Field(max_length=20)
    account_name: Optional[str] = Field(max_length=255)
    account_type: Optional[str] = Field(max_length=50)
    
    # Protection info
    has_insurance: Optional[bool]
    insurance_provider: Optional[str] = Field(max_length=255)
    insurance_policy_number: Optional[str] = Field(max_length=100)
    insurance_expiry_date: Optional[date]
    
    has_guarantor: Optional[bool]
    guarantor_name: Optional[str] = Field(max_length=255)
    guarantor_phone: Optional[str] = Field(max_length=20)
    guarantor_email: Optional[str] = Field(max_length=255)
    guarantor_relationship: Optional[str] = Field(max_length=100)
    guarantor_address: Optional[str]
    
    # Documents
    documents: Optional[Dict[str, Any]]


class LandlordOnboardingResponse(LandlordOnboardingBase):
    """Schema for landlord onboarding response"""
    id: UUID
    landlord_id: UUID
    profile_step_completed: bool
    property_step_completed: bool
    payment_step_completed: bool
    protection_step_completed: bool
    all_steps_completed: bool
    onboarding_started_at: datetime
    onboarding_completed_at: Optional[datetime]
    
    # Verification status
    nin_verified: bool
    bvn_verified: bool
    id_document_verified: bool
    selfie_verified: bool
    bank_verification_status: Literal['pending', 'verified', 'failed']
    document_processing_status: Literal['pending', 'processing', 'completed', 'failed']
    
    # Document URLs
    nin_document_url: Optional[str]
    id_document_url: Optional[str]
    selfie_url: Optional[str]
    bank_statement_url: Optional[str]
    insurance_document_url: Optional[str]
    guarantor_id_url: Optional[str]
    
    # Admin review
    submitted_for_review: bool
    submitted_for_review_at: Optional[datetime]
    admin_review_status: Literal['pending', 'in_review', 'approved', 'rejected', 'needs_correction']
    admin_reviewer_id: Optional[UUID]
    admin_feedback: Optional[str]
    admin_reviewed_at: Optional[datetime]
    
    # Metadata
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime
    last_updated_at: datetime
    
    class Config:
        from_attributes = True


# Step-specific schemas
class Step1Data(BaseModel):
    """Step 1: Profile Information"""
    full_name: str = Field(..., max_length=255)
    phone: str = Field(..., max_length=20)
    date_of_birth: date
    landlord_type: Literal['individual', 'company']
    
    # Company info (required if company type)
    company_name: Optional[str] = Field(max_length=255)
    company_address: Optional[str]
    company_rc_number: Optional[str] = Field(max_length=50)
    
    # Identity verification
    nin: str = Field(..., max_length=11, min_length=11)
    bvn: Optional[str] = Field(max_length=11, min_length=11)
    id_document_type: str = Field(..., max_length=50)
    id_document_number: str = Field(..., max_length=100)
    
    # Document uploads
    nin_document_url: Optional[HttpUrl]
    id_document_url: Optional[HttpUrl]
    selfie_url: Optional[HttpUrl]
    
    @validator('company_name', 'company_address', 'company_rc_number')
def validate_company_fields(cls, v, values):
        if values.get('landlord_type') == 'company':
            if not v:
                raise ValueError('Company information is required for company type')
        return v


class Step2Data(BaseModel):
    """Step 2: Property Information (Optional)"""
    first_property_id: Optional[UUID]
    property_details: Optional[Dict[str, Any]]


class Step3Data(BaseModel):
    """Step 3: Payment/Bank Information"""
    bank_name: str = Field(..., max_length=100)
    account_number: str = Field(..., max_length=20)
    account_name: str = Field(..., max_length=255)
    account_type: str = Field(..., max_length=50)
    bank_statement_url: Optional[HttpUrl]


class Step4Data(BaseModel):
    """Step 4: Protection Information"""
    has_insurance: bool = False
    insurance_provider: Optional[str] = Field(max_length=255)
    insurance_policy_number: Optional[str] = Field(max_length=100)
    insurance_expiry_date: Optional[date]
    insurance_document_url: Optional[HttpUrl]
    
    has_guarantor: bool = False
    guarantor_name: Optional[str] = Field(max_length=255)
    guarantor_phone: Optional[str] = Field(max_length=20)
    guarantor_email: Optional[str] = Field(max_length=255)
    guarantor_relationship: Optional[str] = Field(max_length=100)
    guarantor_address: Optional[str]
    guarantor_id_url: Optional[HttpUrl]
    
    @validator('insurance_provider', 'insurance_policy_number', 'insurance_expiry_date')
def validate_insurance_fields(cls, v, values):
        if values.get('has_insurance'):
            if not v:
                raise ValueError('Insurance details are required when has_insurance is True')
        return v
    
    @validator('guarantor_name', 'guarantor_phone', 'guarantor_email', 'guarantor_relationship', 'guarantor_address')
def validate_guarantor_fields(cls, v, values):
        if values.get('has_guarantor'):
            if not v:
                raise ValueError('Guarantor details are required when has_guarantor is True')
        return v


# Document Processing schemas
class DocumentProcessingJobBase(BaseModel):
    """Base schema for document processing jobs"""
    document_type: Literal['nin', 'bvn', 'id_document', 'selfie', 'bank_statement', 'cac_certificate', 'insurance', 'guarantor_id']
    document_url: str
    original_filename: Optional[str] = Field(max_length=255)


class DocumentProcessingJobCreate(DocumentProcessingJobBase):
    """Schema for creating document processing job"""
    onboarding_id: UUID
    content_hash: Optional[str] = Field(max_length=64)


class DocumentProcessingJobResponse(DocumentProcessingJobBase):
    """Schema for document processing job response"""
    id: UUID
    onboarding_id: UUID
    job_status: Literal['queued', 'processing', 'completed', 'failed', 'retrying']
    processing_metadata: Optional[Dict[str, Any]]
    error_message: Optional[str]
    retry_count: int
    max_retries: int
    content_hash: Optional[str]
    extraction_results: Optional[Dict[str, Any]]
    verification_results: Optional[Dict[str, Any]]
    confidence_score: Optional[int] = Field(ge=0, le=100)
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# Admin Review schemas
class AdminReviewUpdate(BaseModel):
    """Schema for admin review updates"""
    admin_review_status: Literal['pending', 'in_review', 'approved', 'rejected', 'needs_correction']
    admin_feedback: Optional[str]
    
    # Verification updates
    nin_verified: Optional[bool]
    bvn_verified: Optional[bool]
    id_document_verified: Optional[bool]
    selfie_verified: Optional[bool]
    bank_verification_status: Optional[Literal['pending', 'verified', 'failed']]


class AdminReviewResponse(BaseModel):
    """Schema for admin review response"""
    id: UUID
    landlord_id: UUID
    full_name: Optional[str]
    email: Optional[str]
    current_step: int
    admin_review_status: Literal['pending', 'in_review', 'approved', 'rejected', 'needs_correction']
    submitted_for_review_at: Optional[datetime]
    admin_reviewed_at: Optional[datetime]
    admin_feedback: Optional[str]
    
    # Verification summary
    nin_verified: bool
    bvn_verified: bool
    id_document_verified: bool
    selfie_verified: bool
    bank_verification_status: Literal['pending', 'verified', 'failed']
    
    # Document summary
    total_documents: int
    verified_documents: int
    pending_documents: int
    failed_documents: int
    
    # Progress summary
    profile_step_completed: bool
    property_step_completed: bool
    payment_step_completed: bool
    protection_step_completed: bool
    all_steps_completed: bool
    
    onboarding_completed_at: Optional[datetime]
    created_at: datetime
    last_updated_at: datetime
    
    class Config:
        from_attributes = True


# Progress tracking schemas
class OnboardingProgressResponse(BaseModel):
    """Schema for onboarding progress response"""
    user_id: UUID
    onboarding_started: bool
    onboarding_completed_at: Optional[datetime]
    first_time_visit: bool
    profile_step_completed: bool
    property_step_completed: bool
    payment_step_completed: bool
    protection_step_completed: bool
    current_onboarding_id: Optional[UUID]
    
    class Config:
        from_attributes = True


# API Response wrappers
class OnboardingStepResponse(BaseModel):
    """Response for step submission"""
    success: bool
    message: str
    current_step: int
    next_step: Optional[int]
    step_completed: bool
    onboarding_id: UUID


class OnboardingSubmissionResponse(BaseModel):
    """Response for complete onboarding submission"""
    success: bool
    message: str
    onboarding_id: UUID
    submitted_for_review: bool
    submitted_at: datetime
    admin_review_status: Literal['pending', 'in_review', 'approved', 'rejected', 'needs_correction']


class AdminQueueResponse(BaseModel):
    """Response for admin onboarding queue"""
    total_pending: int
    total_in_review: int
    total_approved: int
    total_rejected: int
    total_needs_correction: int
    onboarding_items: List[AdminReviewResponse]
    
    class Config:
        from_attributes = True
