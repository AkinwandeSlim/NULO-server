"""
Landlord Onboarding Pydantic Models for FastAPI
Based on Supabase database schema from LANDLORD_ONBORAD.info
Consistent with user.py model structure
"""

from pydantic import BaseModel, Field, validator, HttpUrl
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime, date
from uuid import UUID


# Enums
LandlordType = Literal["individual", "company"]
DocumentType = Literal["nin", "bvn", "id_document", "selfie", "bank_statement", "cac_certificate", "insurance", "guarantor_id"]
JobStatus = Literal["queued", "processing", "completed", "failed", "retrying"]
AdminReviewStatus = Literal["pending", "in_review", "approved", "rejected", "needs_correction"]
VerificationStatus = Literal["pending", "verified", "failed"]
DocumentProcessingStatus = Literal["pending", "processing", "completed", "failed"]
AccountType = Literal["savings", "current"]


# Request Models
class LandlordOnboardingCreate(BaseModel):
    """Create landlord onboarding request"""
    landlord_id: UUID
    current_step: int = Field(ge=1, le=4, default=1)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class Step1Data(BaseModel):
    """Step 1: Profile Information"""
    full_name: str = Field(..., max_length=255)
    phone: str = Field(..., max_length=20)
    date_of_birth: date
    landlord_type: LandlordType
    
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
    account_type: AccountType
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


class LandlordOnboardingUpdate(BaseModel):
    """Update landlord onboarding request"""
    current_step: Optional[int] = Field(ge=1, le=4)
    full_name: Optional[str] = Field(max_length=255)
    phone: Optional[str] = Field(max_length=20)
    date_of_birth: Optional[date]
    landlord_type: Optional[LandlordType]
    
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
    account_type: Optional[AccountType]
    
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


# Document Processing Models
class DocumentProcessingJobCreate(BaseModel):
    """Create document processing job"""
    onboarding_id: UUID
    document_type: DocumentType
    document_url: str
    original_filename: Optional[str] = Field(max_length=255)
    content_hash: Optional[str] = Field(max_length=64)


class DocumentProcessingJobUpdate(BaseModel):
    """Update document processing job"""
    job_status: Optional[JobStatus]
    processing_metadata: Optional[Dict[str, Any]]
    error_message: Optional[str]
    extraction_results: Optional[Dict[str, Any]]
    verification_results: Optional[Dict[str, Any]]
    confidence_score: Optional[int] = Field(ge=0, le=100)


# Admin Review Models
class AdminReviewUpdate(BaseModel):
    """Admin review update"""
    admin_review_status: AdminReviewStatus
    admin_feedback: Optional[str]
    
    # Verification updates
    nin_verified: Optional[bool]
    bvn_verified: Optional[bool]
    id_document_verified: Optional[bool]
    selfie_verified: Optional[bool]
    bank_verification_status: Optional[VerificationStatus]


# Response Models
class LandlordOnboardingBase(BaseModel):
    """Base landlord onboarding response"""
    id: UUID
    landlord_id: UUID
    current_step: int
    full_name: Optional[str]
    phone: Optional[str]
    date_of_birth: Optional[date]
    landlord_type: Optional[LandlordType]
    
    # Company info
    company_name: Optional[str]
    company_address: Optional[str]
    company_rc_number: Optional[str]
    
    # Identity verification
    nin: Optional[str]
    nin_verified: bool
    nin_document_url: Optional[str]
    
    bvn: Optional[str]
    bvn_verified: bool
    
    id_document_type: Optional[str]
    id_document_number: Optional[str]
    id_document_url: Optional[str]
    id_document_verified: bool
    
    selfie_url: Optional[str]
    selfie_verified: bool
    
    # Documents storage
    documents: Optional[Dict[str, Any]]
    document_processing_status: DocumentProcessingStatus
    document_extraction_cache: Optional[Dict[str, Any]]
    
    # Step 2: Property Information
    first_property_id: Optional[UUID]
    
    # Step 3: Payment/Bank Information
    bank_name: Optional[str]
    account_number: Optional[str]
    account_name: Optional[str]
    account_type: Optional[AccountType]
    bank_verification_status: VerificationStatus
    bank_statement_url: Optional[str]
    
    # Step 4: Protection Information
    has_insurance: bool
    insurance_provider: Optional[str]
    insurance_policy_number: Optional[str]
    insurance_expiry_date: Optional[date]
    insurance_document_url: Optional[str]
    
    has_guarantor: bool
    guarantor_name: Optional[str]
    guarantor_phone: Optional[str]
    guarantor_email: Optional[str]
    guarantor_relationship: Optional[str]
    guarantor_address: Optional[str]
    guarantor_id_url: Optional[str]
    
    # 4Ps Step Tracking
    profile_step_completed: bool
    property_step_completed: bool
    payment_step_completed: bool
    protection_step_completed: bool
    all_steps_completed: bool
    
    # Timestamps
    onboarding_started_at: datetime
    onboarding_completed_at: Optional[datetime]
    
    # Admin review
    submitted_for_review: bool
    submitted_for_review_at: Optional[datetime]
    admin_review_status: AdminReviewStatus
    admin_reviewer_id: Optional[UUID]
    admin_feedback: Optional[str]
    admin_reviewed_at: Optional[datetime]
    
    # Processing Queue
    processing_queue_id: Optional[str]
    
    # Security/Audit Fields
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime
    last_updated_at: datetime
    
    class Config:
        from_attributes = True


class LandlordOnboardingResponse(LandlordOnboardingBase):
    """Complete landlord onboarding response"""
    pass


class DocumentProcessingJobBase(BaseModel):
    """Base document processing job response"""
    id: UUID
    onboarding_id: UUID
    document_type: DocumentType
    document_url: str
    original_filename: Optional[str]
    
    # Processing status
    job_status: JobStatus
    processing_metadata: Optional[Dict[str, Any]]
    error_message: Optional[str]
    retry_count: int
    max_retries: int
    content_hash: Optional[str]
    
    # Processing results
    extraction_results: Optional[Dict[str, Any]]
    verification_results: Optional[Dict[str, Any]]
    confidence_score: Optional[int]
    
    # Timestamps
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class DocumentProcessingJobResponse(DocumentProcessingJobBase):
    """Complete document processing job response"""
    pass


class AdminReviewResponse(BaseModel):
    """Admin review response"""
    id: UUID
    landlord_id: UUID
    full_name: Optional[str]
    email: Optional[str]
    current_step: int
    admin_review_status: AdminReviewStatus
    submitted_for_review_at: Optional[datetime]
    admin_reviewed_at: Optional[datetime]
    admin_feedback: Optional[str]
    
    # Verification summary
    nin_verified: bool
    bvn_verified: bool
    id_document_verified: bool
    selfie_verified: bool
    bank_verification_status: VerificationStatus
    
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
    admin_review_status: AdminReviewStatus


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


class OnboardingProgressResponse(BaseModel):
    """Onboarding progress response"""
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


class LandlordProfileBase(BaseModel):
    """Base landlord profile response"""
    id: UUID
    user_id: UUID
    
    # Onboarding tracking
    onboarding_started: bool
    onboarding_completed_at: Optional[datetime]
    first_time_visit: bool
    
    # 4Ps Step completion tracking
    profile_step_completed: bool
    property_step_completed: bool
    payment_step_completed: bool
    protection_step_completed: bool
    
    # Current onboarding reference
    current_onboarding_id: Optional[UUID]
    
    # Verification tracking
    verification_fee_paid: bool
    verification_submitted_at: Optional[datetime]
    
    # Account type
    account_type: Optional[str]
    
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class LandlordProfileResponse(LandlordProfileBase):
    """Complete landlord profile response"""
    pass


class VerificationDocumentBase(BaseModel):
    """Base verification document response"""
    id: UUID
    user_id: UUID
    
    # Document information
    document_type: str
    document_name: str
    document_url: str
    file_size: Optional[int]
    mime_type: Optional[str]
    
    # Verification status
    is_verified: bool
    verification_notes: Optional[str]
    verified_at: Optional[datetime]
    verified_by: Optional[UUID]
    
    # Metadata
    upload_metadata: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class VerificationDocumentResponse(VerificationDocumentBase):
    """Complete verification document response"""
    pass
