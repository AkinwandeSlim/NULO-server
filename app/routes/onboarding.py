"""
Landlord Onboarding routes
Follows same Supabase pattern as auth.py and properties.py
"""
from fastapi import APIRouter, HTTPException, Depends, status, Query, BackgroundTasks
from app.models.landlord_onboarding import (
    LandlordOnboardingCreate, Step1Data, Step2Data, Step3Data, Step4Data,
    LandlordOnboardingUpdate, LandlordOnboardingResponse,
    OnboardingStepResponse, OnboardingSubmissionResponse,
    AdminReviewUpdate, AdminReviewResponse, AdminQueueResponse,
    DocumentProcessingJobCreate, DocumentProcessingJobResponse,
    OnboardingProgressResponse, LandlordProfileResponse
)
from app.database import supabase, supabase_admin
from app.middleware.auth import get_current_user, get_admin_user
from datetime import datetime
from typing import Optional, List
import uuid

router = APIRouter(prefix="/onboarding", tags=["landlord-onboarding"])

@router.post("/start", response_model=LandlordOnboardingResponse)
async def start_onboarding(
    onboarding_data: LandlordOnboardingCreate,
    current_user: dict = Depends(get_current_user)
):
    """Start new onboarding process for landlord"""
    try:
        print(f"🚀 [ONBOARDING] Starting onboarding for user: {current_user['id']}")
        
        # Check if user already has onboarding
        existing_data = supabase.table("landlord_onboarding").select("*").eq("landlord_id", current_user['id']).execute()
        
        if existing_data.data:
            print(f"⚠️ [ONBOARDING] User already has onboarding: {existing_data.data[0]['id']}")
            raise HTTPException(
                status_code=400,
                detail="Onboarding already started for this user"
            )
        
        # Create landlord profile if not exists
        profile_data = supabase.table("landlord_profiles").select("*").eq("user_id", current_user['id']).execute()
        
        if not profile_data.data:
            print(f"📝 [ONBOARDING] Creating landlord profile for user: {current_user['id']}")
            profile = {
                "user_id": current_user['id'],
                "onboarding_started": True,
                "first_time_visit": False,
                "created_at": datetime.utcnow().isoformat()
            }
            supabase.table("landlord_profiles").insert(profile).execute()
        else:
            profile = profile_data.data[0]
        
        # Create onboarding record
        onboarding_record = {
            "landlord_id": profile['id'],
            "current_step": onboarding_data.current_step,
            "onboarding_started_at": datetime.utcnow().isoformat(),
            "ip_address": onboarding_data.ip_address,
            "user_agent": onboarding_data.user_agent,
            "created_at": datetime.utcnow().isoformat()
        }
        
        result = supabase.table("landlord_onboarding").insert(onboarding_record).execute()
        
        print(f"✅ [ONBOARDING] Onboarding started successfully: {result.data[0]['id']}")
        return result.data[0]
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error starting onboarding: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/step-{step}", response_model=OnboardingStepResponse)
async def submit_onboarding_step(
    step: int,
    step_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Submit onboarding step data"""
    try:
        print(f"📝 [ONBOARDING] Submitting step {step} for user: {current_user['id']}")
        
        # Get user's onboarding
        onboarding_data = supabase.table("landlord_onboarding").select("*").eq("landlord_id", current_user['id']).execute()
        
        if not onboarding_data.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found. Please start onboarding first."
            )
        
        onboarding = onboarding_data.data[0]
        
        # Validate step sequence
        if step != onboarding['current_step']:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot submit step {step}. Current step is {onboarding['current_step']}"
            )
        
        # Process step-specific data
        update_data = {"last_updated_at": datetime.utcnow().isoformat()}
        
        if step == 1:
            update_data.update({
                "full_name": step_data.get("full_name"),
                "phone": step_data.get("phone"),
                "date_of_birth": step_data.get("date_of_birth"),
                "landlord_type": step_data.get("landlord_type"),
                "company_name": step_data.get("company_name"),
                "company_address": step_data.get("company_address"),
                "company_rc_number": step_data.get("company_rc_number"),
                "nin": step_data.get("nin"),
                "bvn": step_data.get("bvn"),
                "id_document_type": step_data.get("id_document_type"),
                "id_document_number": step_data.get("id_document_number"),
                "nin_document_url": str(step_data.get("nin_document_url")) if step_data.get("nin_document_url") else None,
                "id_document_url": str(step_data.get("id_document_url")) if step_data.get("id_document_url") else None,
                "selfie_url": str(step_data.get("selfie_url")) if step_data.get("selfie_url") else None,
                "profile_step_completed": True,
                "current_step": 2
            })
            
        elif step == 2:
            update_data.update({
                "first_property_id": step_data.get("first_property_id"),
                "property_step_completed": True,
                "current_step": 3
            })
            
        elif step == 3:
            update_data.update({
                "bank_name": step_data.get("bank_name"),
                "account_number": step_data.get("account_number"),
                "account_name": step_data.get("account_name"),
                "account_type": step_data.get("account_type"),
                "bank_statement_url": str(step_data.get("bank_statement_url")) if step_data.get("bank_statement_url") else None,
                "payment_step_completed": True,
                "current_step": 4
            })
            
        elif step == 4:
            update_data.update({
                "has_insurance": step_data.get("has_insurance", False),
                "insurance_provider": step_data.get("insurance_provider"),
                "insurance_policy_number": step_data.get("insurance_policy_number"),
                "insurance_expiry_date": step_data.get("insurance_expiry_date"),
                "insurance_document_url": str(step_data.get("insurance_document_url")) if step_data.get("insurance_document_url") else None,
                "has_guarantor": step_data.get("has_guarantor", False),
                "guarantor_name": step_data.get("guarantor_name"),
                "guarantor_phone": step_data.get("guarantor_phone"),
                "guarantor_email": step_data.get("guarantor_email"),
                "guarantor_relationship": step_data.get("guarantor_relationship"),
                "guarantor_address": step_data.get("guarantor_address"),
                "guarantor_id_url": str(step_data.get("guarantor_id_url")) if step_data.get("guarantor_id_url") else None,
                "protection_step_completed": True,
                "current_step": 5
            })
        
        # Update onboarding
        result = supabase.table("landlord_onboarding").update(update_data).eq("id", onboarding['id']).execute()
        
        # Update landlord profile
        profile_update = {}
        if step == 1:
            profile_update["profile_step_completed"] = True
        elif step == 2:
            profile_update["property_step_completed"] = True
        elif step == 3:
            profile_update["payment_step_completed"] = True
        elif step == 4:
            profile_update["protection_step_completed"] = True
        
        if profile_update:
            profile_update["updated_at"] = datetime.utcnow().isoformat()
            supabase.table("landlord_profiles").update(profile_update).eq("landlord_id", current_user['id']).execute()
        
        print(f"✅ [ONBOARDING] Step {step} completed successfully")
        
        return OnboardingStepResponse(
            success=True,
            message=f"Step {step} completed successfully",
            current_step=update_data["current_step"],
            next_step=update_data["current_step"] if update_data["current_step"] <= 4 else None,
            step_completed=True,
            onboarding_id=onboarding['id']
        )
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error submitting step {step}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process step {step}: {str(e)}")

@router.post("/submit", response_model=OnboardingSubmissionResponse)
async def submit_complete_onboarding(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """Submit complete onboarding for admin review"""
    try:
        print(f"📤 [ONBOARDING] Submitting complete onboarding for user: {current_user['id']}")
        
        # Get user's onboarding
        onboarding_data = supabase.table("landlord_onboarding").select("*").eq("landlord_id", current_user['id']).execute()
        
        if not onboarding_data.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        onboarding = onboarding_data.data[0]
        
        # Check if all steps are completed
        if not (onboarding.get('profile_step_completed') and 
                onboarding.get('payment_step_completed') and 
                onboarding.get('protection_step_completed')):
            raise HTTPException(
                status_code=400,
                detail="All required steps must be completed before submission"
            )
        
        # Mark as submitted for review
        update_data = {
            "submitted_for_review": True,
            "submitted_for_review_at": datetime.utcnow().isoformat(),
            "admin_review_status": "pending",
            "all_steps_completed": True,
            "onboarding_completed_at": datetime.utcnow().isoformat(),
            "last_updated_at": datetime.utcnow().isoformat()
        }
        
        result = supabase.table("landlord_onboarding").update(update_data).eq("id", onboarding['id']).execute()
        
        # Update landlord profile
        profile_update = {
            "onboarding_completed_at": datetime.utcnow().isoformat(),
            "first_time_visit": False,
            "profile_step_completed": onboarding.get('profile_step_completed'),
            "property_step_completed": onboarding.get('property_step_completed'),
            "payment_step_completed": onboarding.get('payment_step_completed'),
            "protection_step_completed": onboarding.get('protection_step_completed'),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        supabase.table("landlord_profiles").update(profile_update).eq("landlord_id", current_user['id']).execute()
        
        # Update main users table verification status
        user_update = {
            "verification_status": "pending",
            "onboarding_completed": True,
            "onboarding_step": 5,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        supabase.table("users").update(user_update).eq("id", current_user['id']).execute()
        
        print(f"✅ [ONBOARDING] Onboarding submitted successfully: {onboarding['id']}")
        
        return OnboardingSubmissionResponse(
            success=True,
            message="Onboarding submitted successfully for admin review",
            onboarding_id=onboarding['id'],
            submitted_for_review=True,
            submitted_at=datetime.utcnow(),
            admin_review_status="pending"
        )
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error submitting onboarding: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to submit onboarding: {str(e)}")

@router.get("/progress", response_model=LandlordOnboardingResponse)
async def get_onboarding_progress(
    current_user: dict = Depends(get_current_user)
):
    """Get current onboarding progress"""
    try:
        print(f"📊 [ONBOARDING] Getting progress for user: {current_user['id']}")
        
        # Get user's onboarding
        onboarding_data = supabase.table("landlord_onboarding").select("*").eq("landlord_id", current_user['id']).execute()
        
        if not onboarding_data.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        print(f"✅ [ONBOARDING] Progress retrieved successfully")
        return onboarding_data.data[0]
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error getting progress: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get progress: {str(e)}")

@router.get("/status/{onboarding_id}", response_model=LandlordOnboardingResponse)
async def get_onboarding_status(
    onboarding_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get specific onboarding status"""
    try:
        print(f"🔍 [ONBOARDING] Getting status for onboarding: {onboarding_id}")
        
        # Get onboarding with user verification
        onboarding_data = supabase.table("landlord_onboarding").select(
            "*",
            landlord_profiles="inner(user_id, onboarding_started, onboarding_completed_at)"
        ).eq("id", onboarding_id).execute()
        
        if not onboarding_data.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        # Verify ownership
        if onboarding_data.data[0]['landlord_profiles']['user_id'] != current_user['id']:
            raise HTTPException(
                status_code=403,
                detail="Access denied"
            )
        
        print(f"✅ [ONBOARDING] Status retrieved successfully")
        return onboarding_data.data[0]
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error getting status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")

# Admin endpoints
@router.get("/admin/queue", response_model=AdminQueueResponse)
async def get_admin_onboarding_queue(
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    current_user: dict = Depends(get_admin_user)
):
    """Get admin onboarding queue"""
    try:
        print(f"👨‍💼 [ADMIN] Getting onboarding queue for admin: {current_user['id']}")
        
        # Build query
        query = supabase_admin.table("landlord_onboarding").select(
            "*",
            landlord_profiles="inner(user_id, onboarding_started, onboarding_completed_at)"
        )
        
        if status_filter:
            query = query.eq("admin_review_status", status_filter)
        
        # Get all onboarding items
        result = query.order("submitted_for_review_at", desc=True).execute()
        
        # Count by status
        pending_count = supabase_admin.table("landlord_onboarding").select("id", count="exact").eq("admin_review_status", "pending").execute()
        in_review_count = supabase_admin.table("landlord_onboarding").select("id", count="exact").eq("admin_review_status", "in_review").execute()
        approved_count = supabase_admin.table("landlord_onboarding").select("id", count="exact").eq("admin_review_status", "approved").execute()
        rejected_count = supabase_admin.table("landlord_onboarding").select("id", count="exact").eq("admin_review_status", "rejected").execute()
        needs_correction_count = supabase_admin.table("landlord_onboarding").select("id", count="exact").eq("admin_review_status", "needs_correction").execute()
        
        print(f"✅ [ADMIN] Queue retrieved successfully: {len(result.data)} items")
        
        return AdminQueueResponse(
            total_pending=pending_count.count or 0,
            total_in_review=in_review_count.count or 0,
            total_approved=approved_count.count or 0,
            total_rejected=rejected_count.count or 0,
            total_needs_correction=needs_correction_count.count or 0,
            onboarding_items=result.data
        )
        
    except Exception as e:
        print(f"❌ [ADMIN] Error getting queue: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get queue: {str(e)}")

@router.put("/admin/review/{onboarding_id}", response_model=AdminReviewResponse)
async def review_onboarding(
    onboarding_id: str,
    review_data: AdminReviewUpdate,
    current_user: dict = Depends(get_admin_user)
):
    """Admin review and update onboarding status"""
    try:
        print(f"👨‍💼 [ADMIN] Reviewing onboarding: {onboarding_id}")
        
        # Get onboarding
        onboarding_data = supabase_admin.table("landlord_onboarding").select("*").eq("id", onboarding_id).execute()
        
        if not onboarding_data.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        onboarding = onboarding_data.data[0]
        
        # Update review status
        update_data = {
            "admin_review_status": review_data.admin_review_status,
            "admin_reviewer_id": current_user['id'],
            "admin_feedback": review_data.admin_feedback,
            "admin_reviewed_at": datetime.utcnow().isoformat(),
            "last_updated_at": datetime.utcnow().isoformat()
        }
        
        # Update verification statuses if provided
        if review_data.nin_verified is not None:
            update_data["nin_verified"] = review_data.nin_verified
        if review_data.bvn_verified is not None:
            update_data["bvn_verified"] = review_data.bvn_verified
        if review_data.id_document_verified is not None:
            update_data["id_document_verified"] = review_data.id_document_verified
        if review_data.selfie_verified is not None:
            update_data["selfie_verified"] = review_data.selfie_verified
        if review_data.bank_verification_status is not None:
            update_data["bank_verification_status"] = review_data.bank_verification_status
        
        result = supabase_admin.table("landlord_onboarding").update(update_data).eq("id", onboarding_id).execute()
        
        # Update user verification status in main users table
        if review_data.admin_review_status == "approved":
            user_update = {
                "verification_status": "verified",
                "updated_at": datetime.utcnow().isoformat()
            }
        elif review_data.admin_review_status == "rejected":
            user_update = {
                "verification_status": "rejected",
                "updated_at": datetime.utcnow().isoformat()
            }
        else:
            user_update = {
                "verification_status": "under_review",
                "updated_at": datetime.utcnow().isoformat()
            }
        
        # Get landlord profile to update user table
        profile_data = supabase_admin.table("landlord_profiles").select("user_id").eq("id", onboarding['landlord_id']).execute()
        if profile_data.data:
            supabase_admin.table("users").update(user_update).eq("id", profile_data.data[0]['user_id']).execute()
        
        print(f"✅ [ADMIN] Onboarding reviewed successfully: {onboarding_id}")
        return result.data[0]
        
    except Exception as e:
        print(f"❌ [ADMIN] Error reviewing onboarding: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to review onboarding: {str(e)}")

@router.get("/admin/details/{onboarding_id}", response_model=AdminReviewResponse)
async def get_onboarding_details(
    onboarding_id: str,
    current_user: dict = Depends(get_admin_user)
):
    """Get detailed onboarding information for admin review"""
    try:
        print(f"🔍 [ADMIN] Getting details for onboarding: {onboarding_id}")
        
        # Get detailed onboarding with profile info
        result = supabase_admin.table("landlord_onboarding").select(
            "*",
            landlord_profiles="inner(user_id, onboarding_started, onboarding_completed_at)"
        ).eq("id", onboarding_id).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        print(f"✅ [ADMIN] Details retrieved successfully")
        return result.data[0]
        
    except Exception as e:
        print(f"❌ [ADMIN] Error getting details: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get details: {str(e)}")

# Document processing endpoints
@router.post("/documents/process", response_model=DocumentProcessingJobResponse)
async def create_document_processing_job(
    job_data: DocumentProcessingJobCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """Create document processing job"""
    try:
        print(f"📄 [DOCUMENTS] Creating processing job for: {job_data.document_type}")
        
        # Verify onboarding ownership
        onboarding_check = supabase.table("landlord_onboarding").select("landlord_id").eq("id", job_data.onboarding_id).execute()
        
        if not onboarding_check.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        if onboarding_check.data[0]['landlord_id'] != current_user['id']:
            raise HTTPException(
                status_code=403,
                detail="Access denied"
            )
        
        # Create processing job
        job_record = {
            "onboarding_id": job_data.onboarding_id,
            "document_type": job_data.document_type,
            "document_url": str(job_data.document_url),
            "original_filename": job_data.original_filename,
            "content_hash": job_data.content_hash,
            "job_status": "queued",
            "created_at": datetime.utcnow().isoformat()
        }
        
        result = supabase.table("document_processing_jobs").insert(job_record).execute()
        
        print(f"✅ [DOCUMENTS] Processing job created: {result.data[0]['id']}")
        return result.data[0]
        
    except Exception as e:
        print(f"❌ [DOCUMENTS] Error creating processing job: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create processing job: {str(e)}")

@router.get("/documents/{onboarding_id}", response_model=List[DocumentProcessingJobResponse])
async def get_document_processing_jobs(
    onboarding_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get document processing jobs for onboarding"""
    try:
        print(f"📄 [DOCUMENTS] Getting processing jobs for: {onboarding_id}")
        
        # Verify ownership
        onboarding_check = supabase.table("landlord_onboarding").select("landlord_id").eq("id", onboarding_id).execute()
        
        if not onboarding_check.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        if onboarding_check.data[0]['landlord_id'] != current_user['id']:
            raise HTTPException(
                status_code=403,
                detail="Access denied"
            )
        
        # Get processing jobs
        result = supabase.table("document_processing_jobs").select("*").eq("onboarding_id", onboarding_id).order("created_at", desc=True).execute()
        
        print(f"✅ [DOCUMENTS] Processing jobs retrieved: {len(result.data)} items")
        return result.data
        
    except Exception as e:
        print(f"❌ [DOCUMENTS] Error getting processing jobs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get processing jobs: {str(e)}")
