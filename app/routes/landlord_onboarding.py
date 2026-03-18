"""
Landlord Onboarding API Routes
Handles 4Ps verification process and admin tracking
"""

from fastapi import APIRouter, Depends, HTTPException, Path, BackgroundTasks, Query, Request
from typing import Optional, List
from uuid import UUID
import logging

from ..database import supabase, supabase_admin
from ..models.landlord_onboarding import (
    LandlordOnboardingCreate, LandlordOnboardingUpdate, LandlordOnboardingResponse,
    Step1Data, Step2Data, Step3Data, Step4Data,
    OnboardingStepResponse, OnboardingSubmissionResponse,
    AdminReviewUpdate, AdminReviewResponse, AdminQueueResponse,
    DocumentProcessingJobCreate, DocumentProcessingJobResponse
)
from ..middleware.auth import get_current_user, get_current_admin
from ..services.email_service import email_service
from ..services.notification_service import notification_service
from datetime import datetime
import os

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/onboarding", tags=["landlord-onboarding"])


@router.post("/start", response_model=LandlordOnboardingResponse)
async def start_onboarding(
    onboarding_data: LandlordOnboardingCreate,
    current_user = Depends(get_current_user)
):
    """Start new onboarding process for landlord"""
    print(f"\n✅ [ONBOARDING] Starting onboarding for user: {current_user['id']}")
    
    try:
        # Check if user already has onboarding
        existing_check = supabase.table("landlord_onboarding").select("*").eq("landlord_id", current_user['id']).execute()
        
        if existing_check.data:
            print(f"❌ [ONBOARDING] User {current_user['id']} already has onboarding")
            raise HTTPException(
                status_code=400,
                detail="Onboarding already started for this user"
            )
        
        # Create landlord profile if not exists
        profile_check = supabase.table("landlord_profiles").select("*").eq("user_id", current_user['id']).execute()
        
        if not profile_check.data:
            profile_data = {
                "user_id": current_user['id'],
                "onboarding_started": True,
                "first_time_visit": False,
                "created_at": "now()"
            }
            supabase.table("landlord_profiles").insert(profile_data).execute()
            print(f"✅ [ONBOARDING] Created landlord profile for user: {current_user['id']}")
        
        # Create onboarding record
        onboarding_record = {
            "landlord_id": current_user['id'],
            "current_step": 1,
            "ip_address": onboarding_data.ip_address,
            "user_agent": onboarding_data.user_agent,
            "created_at": "now()"
        }
        
        result = supabase.table("landlord_onboarding").insert(onboarding_record).execute()
        
        print(f"✅ [ONBOARDING] Onboarding started successfully: {result.data[0]['id']}")
        return result.data[0]
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error starting onboarding: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/step-{step}", response_model=OnboardingStepResponse)
async def submit_onboarding_step(
    step: int = Path(ge=1, le=4),
    step_data: dict = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user = Depends(get_current_user)
):
    """Submit onboarding step data"""
    print(f"\n✅ [ONBOARDING] Submitting step {step} for user: {current_user['id']}")
    
    try:
        # Get user's onboarding
        onboarding_check = supabase.table("landlord_onboarding").select("*").eq("landlord_id", current_user['id']).execute()
        
        if not onboarding_check.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found. Please start onboarding first."
            )
        
        onboarding = onboarding_check.data[0]
        
        # Validate step sequence
        if step != onboarding['current_step']:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot submit step {step}. Current step is {onboarding['current_step']}"
            )
        
        # Process step-specific data
        if step == 1:
            return await _process_step_1(onboarding, step_data or {}, background_tasks)
        elif step == 2:
            return await _process_step_2(onboarding, step_data or {})
        elif step == 3:
            return await _process_step_3(onboarding, step_data or {}, background_tasks)
        elif step == 4:
            return await _process_step_4(onboarding, step_data or {}, background_tasks)
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ONBOARDING] Error processing step {step}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process step {step}: {str(e)}"
        )


async def _process_step_1(
    onboarding: dict, 
    step_data: dict, 
    background_tasks: BackgroundTasks
) -> OnboardingStepResponse:
    """Process Step 1: Basic Information (MVP - Manual Admin Review)"""
    try:
        # Update onboarding with step 1 data (basic info + verification numbers)
        update_data = {
            "profile_step_completed": True,
            "current_step": 2,
            "full_name": step_data.get("full_name"),
            "phone": step_data.get("phone"),
            "landlord_type": step_data.get("landlord_type"),
            "date_of_birth": step_data.get("date_of_birth"),
            "company_name": step_data.get("company_name"),
            "company_address": step_data.get("company_address"),
            "nin": step_data.get("nin"),  # National Identification Number
            "bvn": step_data.get("bvn"),  # Bank Verification Number
            "updated_at": "now()"
        }
        
        supabase.table("landlord_onboarding").update(update_data).eq("id", onboarding['id']).execute()
        
        # MVP: Manual admin verification - no automated processing
        # TODO: Future - Implement NIN validation API
        # TODO: Future - Implement BVN validation API
        # TODO: Future - Implement automated identity verification
        print(f"✅ [ONBOARDING] Step 1 completed - Data saved for manual admin review")
        
        return OnboardingStepResponse(
            success=True,
            message="Step 1 completed successfully. Ready for document upload!",
            current_step=2,
            next_step=2,
            step_completed=True,
            onboarding_id=onboarding['id']
        )
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error processing step 1: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process step 1: {str(e)}"
        )


async def _process_step_2(
    onboarding: dict, 
    step_data: dict,
    background_tasks: BackgroundTasks
) -> OnboardingStepResponse:
    """Process Step 2: Document Upload Phase (MVP - Manual Admin Review)"""
    try:
        # Update onboarding with step 2 data (documents + selfie)
        update_data = {
            "document_step_completed": True,
            "current_step": 3,
            "id_document_url": step_data.get("id_document_url"),
            "proof_of_address_url": step_data.get("proof_of_address_url"),
            "company_registration_url": step_data.get("company_registration_url"),
            "selfie_url": step_data.get("selfie_url"),  # Liveness check
            "updated_at": "now()"
        }
        
        supabase.table("landlord_onboarding").update(update_data).eq("id", onboarding['id']).execute()
        
        # MVP: Manual admin verification - no automated processing
        # TODO: Future - Implement ID document OCR and validation
        # TODO: Future - Implement facial recognition for selfie matching
        # TODO: Future - Implement proof of address verification
        # TODO: Future - Implement company registration validation
        print(f"✅ [ONBOARDING] Step 2 completed - Documents saved for manual admin review")
        
        return OnboardingStepResponse(
            success=True,
            message="Step 2 completed successfully. Ready for property information!",
            current_step=3,
            next_step=3,
            step_completed=True,
            onboarding_id=onboarding['id']
        )
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error processing step 2: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def _process_step_3(
    onboarding: dict, 
    step_data: dict,
    background_tasks: BackgroundTasks
) -> OnboardingStepResponse:
    """Process Step 3: Property Information (MVP - Manual Admin Review)"""
    try:
        # Update onboarding with step 3 data (property info)
        update_data = {
            "property_step_completed": True,
            "current_step": 4,
            "property_address": step_data.get("property_address"),
            "property_type": step_data.get("property_type"),
            "property_images": step_data.get("property_images"),
            "property_ownership_proof": step_data.get("property_ownership_proof"),
            "updated_at": "now()"
        }
        
        supabase.table("landlord_onboarding").update(update_data).eq("id", onboarding['id']).execute()
        
        # MVP: Manual admin verification - no automated processing
        # TODO: Future - Implement property address geolocation verification
        # TODO: Future - Implement property ownership document validation
        # TODO: Future - Implement property image analysis
        print(f"✅ [ONBOARDING] Step 3 completed - Property data saved for manual admin review")
        
        return OnboardingStepResponse(
            success=True,
            message="Step 3 completed successfully. Ready for bank information!",
            current_step=4,
            next_step=4,
            step_completed=True,
            onboarding_id=onboarding['id']
        )
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error processing step 3: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def _process_step_4(
    onboarding: dict, 
    step_data: dict,
    background_tasks: BackgroundTasks
) -> OnboardingStepResponse:
    """Process Step 4: Bank Account Information (MVP - Manual Admin Review)"""
    try:
        # Update onboarding with step 4 data (bank info)
        update_data = {
            "payment_step_completed": True,
            "current_step": 4,  # Database constraint: current_step must be <= 4  # Completed
            "bank_name": step_data.get("bank_name"),
            "bank_account_number": step_data.get("bank_account_number"),
            "bank_account_name": step_data.get("bank_account_name"),
            "bank_verification_number": step_data.get("bank_verification_number"),
            "bank_statement_url": step_data.get("bank_statement_url"),
            "updated_at": "now()"
        }
        
        supabase.table("landlord_onboarding").update(update_data).eq("id", onboarding['id']).execute()
        
        # MVP: Manual admin verification - no automated processing
        # TODO: Future - Implement BVN validation with bank API
        # TODO: Future - Implement bank account verification
        # TODO: Future - Implement bank statement analysis
        print(f"✅ [ONBOARDING] Step 4 completed - Bank data saved for manual admin review")
        
        return OnboardingStepResponse(
            success=True,
            message="Step 4 completed successfully. Ready for submission!",
            current_step=5,
            next_step=None,
            step_completed=True,
            onboarding_id=onboarding['id']
        )
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error processing step 4: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))





@router.post("/submit", response_model=OnboardingSubmissionResponse)
async def submit_complete_onboarding(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user)
):
    """Submit complete onboarding for admin review."""
    print(f"\n🚀 [ONBOARDING/submit] User: {current_user['id']}")

    try:
        # Accept optional body — frontend sends payload but truth is in DB + current_user
        try:
            request_data = await request.json()
        except Exception:
            request_data = {}

        # ── 1. Ensure landlord_profiles row exists ────────────────────────────
        profile_check = supabase_admin.table("landlord_profiles").select("id").eq(
            "id", current_user["id"]
        ).execute()

        if not profile_check.data:
            print(f"🆕 [ONBOARDING/submit] Creating landlord_profiles for {current_user['id']}")
            supabase_admin.table("landlord_profiles").insert({
                "id": current_user["id"],
                "onboarding_started": True,
                "first_time_visit": False,
                "profile_step_completed": True,
                "property_step_completed": True,
                "payment_step_completed": True,
                "protection_step_completed": True,
                "onboarding_completed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }).execute()
            print(f"✅ [ONBOARDING/submit] landlord_profiles created")
        else:
            supabase_admin.table("landlord_profiles").update({
                "first_time_visit": False,
                "profile_step_completed": True,
                "property_step_completed": True,
                "payment_step_completed": True,
                "protection_step_completed": True,
                "onboarding_completed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", current_user["id"]).execute()
            print(f"✅ [ONBOARDING/submit] landlord_profiles updated")

        # ── 2. Upsert landlord_onboarding record ──────────────────────────────
        onboarding_check = supabase_admin.table("landlord_onboarding").select("*").eq(
            "landlord_id", current_user["id"]
        ).execute()

        upsert_data = {
            "landlord_id":   current_user["id"],
            "full_name":     request_data.get("full_name"),
            "phone":         request_data.get("phone"),
            "date_of_birth": request_data.get("date_of_birth"),
            "landlord_type": request_data.get("landlord_type"),
            "company_name":  request_data.get("company_name"),
            "company_address": request_data.get("company_address"),
            "bank_name":     request_data.get("bank_name"),
            "account_number": request_data.get("account_number"),
            "account_name":  request_data.get("account_name"),
            "profile_step_completed":    True,
            "property_step_completed":   True,
            "payment_step_completed":    True,
            "protection_step_completed": True,
            "all_steps_completed":       True,
            "current_step":              4,
            "submitted_for_review":      True,
            "submitted_for_review_at":   datetime.utcnow().isoformat(),
            "submitted_at":              datetime.utcnow().isoformat(),
            "admin_review_status":       "pending",
            "onboarding_completed_at":   datetime.utcnow().isoformat(),
            "last_updated_at":           datetime.utcnow().isoformat(),
        }

        if onboarding_check.data:
            onboarding_id = onboarding_check.data[0]["id"]
            print(f"📝 [ONBOARDING/submit] Updating existing record: {onboarding_id}")
            result = supabase_admin.table("landlord_onboarding").update(
                upsert_data
            ).eq("id", onboarding_id).execute()
        else:
            print(f"🆕 [ONBOARDING/submit] Creating new record")
            upsert_data["onboarding_started_at"] = datetime.utcnow().isoformat()
            result = supabase_admin.table("landlord_onboarding").insert(upsert_data).execute()

        onboarding = result.data[0] if result.data else {}
        print(f"✅ [ONBOARDING/submit] DB updated for {onboarding.get('id')}")

        # ── 3. Update users table ─────────────────────────────────────────────
        print(f"🔄 [ONBOARDING/submit] Updating user_type to 'landlord' for user {current_user['id']}")
        supabase.table("users").update({
            "user_type": "landlord",  # CRITICAL FIX: Ensure user_type is set to landlord
            "verification_status": "pending",
            "onboarding_completed": True,
            "onboarding_step": 5,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", current_user["id"]).execute()
        print(f"✅ [ONBOARDING/submit] User table updated - user_type='landlord', verification_status='pending'")

        # ── 4. CRITICAL: Update Supabase auth metadata immediately ───────────────
        print(f"🔄 [ONBOARDING/submit] Updating Supabase auth metadata for user {current_user['id']}")
        try:
            auth_update_result = supabase_admin.auth.admin.update_user_by_id(
                current_user["id"],
                {
                    "user_metadata": {
                        "user_type": "landlord",
                        "verification_status": "pending",
                        "onboarding_completed": True,
                        "onboarding_step": 5,
                    },
                    "app_metadata": {
                        "user_type": "landlord",
                        "verification_status": "pending",
                        "onboarding_completed": True,
                        "onboarding_step": 5,
                    }
                }
            )
            print(f"✅ [ONBOARDING/submit] Supabase auth metadata updated successfully")
        except Exception as auth_error:
            print(f"⚠️ [ONBOARDING/submit] Failed to update auth metadata: {auth_error}")
            # Don't fail the request, but log the error

        # ── 5. Fire notifications via notification_service (non-fatal) ────────
        try:
            user_r = supabase.table("users").select("email, full_name").eq(
                "id", current_user["id"]
            ).execute()
            user_row = user_r.data[0] if user_r.data else {}

            # Email + in-app → landlord
            await notification_service.notify_onboarding_submitted(
                user_id=current_user["id"],
                user_email=user_row.get("email", ""),
                user_name=user_row.get("full_name") or "Landlord",
                onboarding_id=onboarding.get("id", ""),
            )
            print(f"✅ [ONBOARDING/submit] Landlord notified at {user_row.get('email')}")

            # Email + in-app → admin
            await notification_service.notify_admin_new_submission(
                admin_email=os.getenv("ADMIN_EMAIL", "nuloafrica26@outlook.com"),
                landlord_name=user_row.get("full_name") or "Landlord",
                landlord_email=user_row.get("email", ""),
                onboarding_id=onboarding.get("id", ""),
            )
            print(f"✅ [ONBOARDING/submit] Admin notified")

        except Exception as _ne:
            logger.warning(f"⚠️ [ONBOARDING/submit] Notifications failed (non-fatal): {_ne}")

        # ── 5. Return ─────────────────────────────────────────────────────────
        return {
            "success": True,
            "message": "Onboarding submitted successfully for admin review",
            "onboarding_id": onboarding.get("id"),
            "submitted_for_review": True,
            "submitted_at": onboarding.get("submitted_for_review_at"),
            "admin_review_status": onboarding.get("admin_review_status", "pending"),
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ONBOARDING/submit] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))






@router.post("/submit-complete", response_model=OnboardingSubmissionResponse)
async def submit_complete_onboarding_v2(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user)
):
    """Alias for /submit — frontend calls this path to avoid legacy router conflicts."""
    return await submit_complete_onboarding(request, background_tasks, current_user)


@router.get("/progress", response_model=LandlordOnboardingResponse)
async def get_onboarding_progress(
    current_user = Depends(get_current_user)
):
    """Get current onboarding progress"""
    try:
        onboarding_check = supabase.table("landlord_onboarding").select("*").eq("landlord_id", current_user['id']).execute()
        
        if not onboarding_check.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        return onboarding_check.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ONBOARDING] Error getting progress: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{onboarding_id}", response_model=LandlordOnboardingResponse)
async def get_onboarding_status(
    onboarding_id: str,
    current_user = Depends(get_current_user)
):
    """Get specific onboarding status (for verification pending page)"""
    try:
        # Verify ownership first
        onboarding_check = supabase.table("landlord_onboarding").select("*").eq("id", onboarding_id).eq("landlord_id", current_user['id']).execute()
        
        if not onboarding_check.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        return onboarding_check.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ONBOARDING] Error getting status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Admin endpoints
@router.get("/admin/queue", response_model=AdminQueueResponse)
async def get_admin_onboarding_queue(
    status: Optional[str] = Query(None, description="Filter by status"),
    admin_user = Depends(get_current_admin)
):
    """Get admin onboarding queue"""
    print(f"\n✅ [ONBOARDING] Admin {admin_user['id']} requesting onboarding queue")
    
    try:
        # Build query
        query = supabase.table("landlord_onboarding").select("*")
        
        if status:
            query = query.eq("admin_review_status", status)
        
        # Order by submission date
        result = query.order("submitted_for_review_at", desc=True).execute()
        
        # Get counts by status
        pending_count = supabase.table("landlord_onboarding").select("id", count="exact").eq("admin_review_status", "pending").execute()
        in_review_count = supabase.table("landlord_onboarding").select("id", count="exact").eq("admin_review_status", "in_review").execute()
        approved_count = supabase.table("landlord_onboarding").select("id", count="exact").eq("admin_review_status", "approved").execute()
        rejected_count = supabase.table("landlord_onboarding").select("id", count="exact").eq("admin_review_status", "rejected").execute()
        needs_correction_count = supabase.table("landlord_onboarding").select("id", count="exact").eq("admin_review_status", "needs_correction").execute()
        
        return AdminQueueResponse(
            total_pending=pending_count.count or 0,
            total_in_review=in_review_count or 0,
            total_approved=approved_count or 0,
            total_rejected=rejected_count or 0,
            total_needs_correction=needs_correction_count or 0,
            onboarding_items=result.data or []
        )
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error getting admin queue: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/review/{onboarding_id}", response_model=AdminReviewResponse)
async def review_onboarding(
    onboarding_id: str,
    review_data: AdminReviewUpdate,
    background_tasks: BackgroundTasks,
    admin_user = Depends(get_current_admin)
):
    """Admin review and update onboarding status"""
    print(f"\n✅ [ONBOARDING] Admin {admin_user['id']} reviewing onboarding: {onboarding_id}")
    
    try:
        # Get onboarding
        onboarding_check = supabase.table("landlord_onboarding").select("*").eq("id", onboarding_id).execute()
        
        if not onboarding_check.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        # Update review status
        update_data = {
            "admin_review_status": review_data.admin_review_status,
            "admin_reviewer_id": admin_user['id'],
            "admin_feedback": review_data.admin_feedback,
            "admin_reviewed_at": "now()",
            "updated_at": "now()"
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
        
        result = supabase.table("landlord_onboarding").update(update_data).eq("id", onboarding_id).execute()
        
        # Update user verification status + fire landlord notification
        landlord_id = onboarding_check.data[0]['landlord_id']

        # Fetch landlord details once — used by all 3 branches
        landlord_row = supabase.table("users").select(
            "email, full_name"
        ).eq("id", landlord_id).execute()
        landlord = landlord_row.data[0] if landlord_row.data else {}
        landlord_email = landlord.get("email", "")
        landlord_name  = landlord.get("full_name") or "Landlord"

        if review_data.admin_review_status == 'approved':
            await _update_user_verification_status(landlord_id, 'verified')
            background_tasks.add_task(
                notification_service.notify_verification_approved,
                user_id=landlord_id,
                user_email=landlord_email,
                user_name=landlord_name,
                trust_score=100,
            )
            print(f"✅ [ONBOARDING] Approval notification queued for {landlord_email}")

        elif review_data.admin_review_status == 'rejected':
            await _update_user_verification_status(landlord_id, 'rejected')
            background_tasks.add_task(
                notification_service.notify_verification_rejected,
                user_id=landlord_id,
                user_email=landlord_email,
                user_name=landlord_name,
                rejection_reason=review_data.admin_feedback or "Your documents could not be verified.",
                onboarding_id=onboarding_id,
            )
            print(f"✅ [ONBOARDING] Rejection notification queued for {landlord_email}")

        elif review_data.admin_review_status == 'needs_correction':
            # Reset to pending so landlord can resubmit
            await _update_user_verification_status(landlord_id, 'pending')
            background_tasks.add_task(
                notification_service.notify_verification_needs_correction,
                user_id=landlord_id,
                user_email=landlord_email,
                user_name=landlord_name,
                admin_feedback=review_data.admin_feedback or "Please review and resubmit your documents.",
                onboarding_id=onboarding_id,
            )
            print(f"✅ [ONBOARDING] Needs-correction notification queued for {landlord_email}")

        return result.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ONBOARDING] Error reviewing onboarding: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/details/{onboarding_id}", response_model=AdminReviewResponse)
async def get_onboarding_details(
    onboarding_id: str,
    admin_user = Depends(get_current_admin)
):
    """Get detailed onboarding information for admin review"""
    try:
        onboarding_check = supabase.table("landlord_onboarding").select("*").eq("id", onboarding_id).execute()
        
        if not onboarding_check.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        return onboarding_check.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ONBOARDING] Error getting onboarding details: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Document processing endpoints
@router.post("/documents/process", response_model=DocumentProcessingJobResponse)
async def create_document_processing_job(
    job_data: DocumentProcessingJobCreate,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user)
):
    """Create document processing job"""
    print(f"\n✅ [ONBOARDING] Creating document processing job for: {job_data.document_type}")
    
    try:
        # Verify onboarding belongs to user
        onboarding_check = supabase.table("landlord_onboarding").select("*").eq("id", job_data.onboarding_id).eq("landlord_id", current_user['id']).execute()
        
        if not onboarding_check.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        # Create processing job
        job_record = {
            "onboarding_id": job_data.onboarding_id,
            "document_type": job_data.document_type,
            "document_url": str(job_data.document_url),
            "original_filename": job_data.original_filename,
            "content_hash": job_data.content_hash,
            "status": "pending",
            "created_at": "now()"
        }
        
        result = supabase.table("document_processing_jobs").insert(job_record).execute()
        
        # Start background processing
        # TODO: Add background task for document processing
        print(f"✅ [ONBOARDING] Document processing started for job: {result.data[0]['id']}")
        
        return result.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ONBOARDING] Error creating document processing job: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{onboarding_id}", response_model=List[DocumentProcessingJobResponse])
async def get_document_processing_jobs(
    onboarding_id: str,
    current_user = Depends(get_current_user)
):
    """Get document processing jobs for onboarding"""
    try:
        # Verify ownership
        onboarding_check = supabase.table("landlord_onboarding").select("*").eq("id", onboarding_id).eq("landlord_id", current_user['id']).execute()
        
        if not onboarding_check.data:
            raise HTTPException(
                status_code=404,
                detail="Onboarding not found"
            )
        
        # Get jobs for this onboarding
        jobs_result = supabase.table("document_processing_jobs").select("*").eq("onboarding_id", onboarding_id).order("created_at", desc=True).execute()
        
        return jobs_result.data or []
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ONBOARDING] Error getting document processing jobs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Helper functions
async def _update_user_verification_status(user_id: str, status: str):
    """Update user verification status in main users table"""
    try:
        update_data = {
            "verification_status": status,
            "updated_at": "now()"
        }
        
        supabase.table("users").update(update_data).eq("id", user_id).execute()
        print(f"✅ [ONBOARDING] Updated user {user_id} verification status to {status}")
        
    except Exception as e:
        print(f"❌ [ONBOARDING] Error updating user verification status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))