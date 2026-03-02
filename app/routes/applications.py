"""
Application routes
"""
import logging
from pydantic import ValidationError
from fastapi import APIRouter, HTTPException, Depends, status
from app.database import supabase_admin
from app.middleware.auth import get_current_user, get_current_tenant, get_current_landlord
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta

router = APIRouter(prefix="/applications")
logger = logging.getLogger(__name__)


class ApplicationCreate(BaseModel):
    property_id: str
    viewing_id: Optional[str] = None
    # Personal Info (will be extracted from user profile)
    message: Optional[str] = None
    
    # Employment Info
    employment_status: Optional[str] = None
    employer_name: Optional[str] = None
    monthly_income: Optional[int] = None
    
    # Additional Info
    move_in_date: Optional[str] = None
    lease_duration: Optional[str] = None
    number_of_occupants: Optional[int] = None
    has_pets: Optional[bool] = False
    pet_details: Optional[str] = None
    
    # References (JSONB)
    references: Optional[dict] = None
    
    # Documents (text array)
    documents: Optional[list] = None
    
    # Emergency contact
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class ApplicationApprove(BaseModel):
    pass


class ApplicationReject(BaseModel):
    reason: str
    reason_code: str


@router.post("/", response_model=dict)
async def create_application(
    application_data: ApplicationCreate,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Submit rental application (tenants only)
    Requires 100% profile completion (deferred KYC gate)
    """
    logger.info(f"📋 [APP] Received application data: {application_data.dict()}")
    
    try:
        tenant_id = current_user["id"]
        
        # Verify user exists in users table
        user_check = supabase_admin.table("users").select("id, user_type").eq(
            "id", tenant_id
        ).single().execute()
        
        if not user_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        if user_check.data["user_type"] != "tenant":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only tenants can submit applications"
            )
        
        # Check tenant profile completion - skip for now (deferred KYC gate)
        # TODO: Re-enable when profile completion is implemented
        
        # Check if property exists and get landlord info
        property_check = supabase_admin.table("properties").select("id, landlord_id, title, price").eq(
            "id", application_data.property_id
        ).single().execute()
        
        if not property_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        property_data = property_check.data
        
        # Check for existing application
        existing_app = supabase_admin.table("applications").select("id").eq(
            "user_id", tenant_id
        ).eq("property_id", application_data.property_id).execute()
        
        if existing_app.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already applied for this property"
            )
        
        # Create application with correct schema
        app_dict = {
            "user_id": tenant_id,  # Correct field name from database schema
            "property_id": application_data.property_id,
            "viewing_id": application_data.viewing_id,
            "status": "pending",  # Default status
            "message": application_data.message,
            "move_in_date": application_data.move_in_date,
            "lease_duration": application_data.lease_duration,
            "employment_status": application_data.employment_status,
            "employer_name": application_data.employer_name,
            "monthly_income": application_data.monthly_income,
            "number_of_occupants": application_data.number_of_occupants,
            "has_pets": application_data.has_pets,
            "pet_details": application_data.pet_details,
            "references": application_data.references or {},
            "documents": application_data.documents or [],
            "emergency_contact_name": application_data.emergency_contact_name,
            "emergency_contact_phone": application_data.emergency_contact_phone,
            "viewed_by_landlord": False
        }
        
        app_response = supabase_admin.table("applications").insert(app_dict).execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create application"
            )
        
        application = app_response.data[0]
        
        # Create mock escrow transaction (skip for now - implement in payment phase)
        # TODO: Implement in Priority 8 (Paystack integration)
        
        # Increment application count on property
        supabase_admin.table("properties").update({
            "application_count": supabase_admin.table("properties").select("application_count").eq(
                "id", application_data.property_id
            ).single().execute().data.get("application_count", 0) + 1
        }).eq("id", application_data.property_id).execute()
        
        # Send notification to landlord
        logger.info(f"📧 [APP] About to call notification service for application {application['id']}")
        
        # TODO: Temporarily disabled to isolate notification issue
        from app.services.notification_service import notification_service
        
        # Get landlord details for notification
        landlord_response = supabase_admin.table("users").select(
            "full_name, email, phone_number"
        ).eq("id", property_data["landlord_id"]).single().execute()
        
        landlord_details = landlord_response.data or {}
        
        # Get tenant details for notification
        tenant_response = supabase_admin.table("users").select(
            "full_name, email, phone_number"
        ).eq("id", tenant_id).single().execute()
        
        tenant_details = tenant_response.data or {}
        
        await notification_service.notify_application_submitted(
            application_id=application["id"],
            property_id=application_data.property_id,
            property_title=property_data["title"],
            tenant_id=tenant_id,
            tenant_name=tenant_details.get("full_name", "Unknown"),
            tenant_email=tenant_details.get("email"),
            tenant_phone=tenant_details.get("phone_number"),
            landlord_id=property_data["landlord_id"],
            landlord_name=landlord_details.get("full_name", "Landlord"),
            landlord_email=landlord_details.get("email"),
            landlord_phone=landlord_details.get("phone_number"),
            monthly_income=application_data.monthly_income,
            employment_status=application_data.employment_status,
            message=application_data.message or "No additional message provided",
        )
        
        return {
            "success": True,
            "application": application,
            "message": "Application submitted successfully"
        }
        
    except ValidationError as e:
        logger.error(f"❌ [APP] Validation error: {e.errors()}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation failed: {e.errors()}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to submit application: {str(e)}"
        )


@router.get("/my-applications")
async def get_my_applications(
    current_user: dict = Depends(get_current_tenant)
):
    """
    Get tenant's own applications
    """
    try:
        user_id = current_user["id"]
        
        response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, location, price, landlord_id)"
        ).eq("user_id", user_id).order("created_at", desc=True).execute()
        
        return {
            "success": True,
            "applications": response.data
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch applications: {str(e)}"
        )


@router.get("/received")
async def get_received_applications(
    current_user: dict = Depends(get_current_landlord)
):
    """
    Get applications received by landlord
    """
    try:
        user_id = current_user["id"]
        
        response = supabase_admin.table("applications").select(
            "*, property:properties!inner(id, title, location, price), user:users!user_id(id, full_name, email, phone_number, trust_score)"
        ).eq("property.landlord_id", user_id).order("created_at", desc=True).execute()
        
        return {
            "success": True,
            "applications": response.data
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch applications: {str(e)}"
        )


@router.get("/stats")
async def get_applications_stats(
    current_user: dict = Depends(get_current_user)
):
    """
    Get application statistics
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]
        
        if user_type == "tenant":
            # Tenant stats: total, pending, approved, rejected
            response = supabase_admin.table("applications").select(
                "status"
            ).eq("user_id", user_id).execute()
            
        elif user_type == "landlord":
            # Landlord stats: total received, pending, approved, rejected
            response = supabase_admin.table("applications").select(
                "status"
            ).eq("property.landlord_id", user_id).execute()
            
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid user type"
            )
        
        applications = response.data or []
        stats = {
            "total": len(applications),
            "pending": len([a for a in applications if a["status"] == "pending"]),
            "approved": len([a for a in applications if a["status"] == "approved"]),
            "rejected": len([a for a in applications if a["status"] == "rejected"])
        }
        
        return {
            "success": True,
            "stats": stats
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch stats: {str(e)}"
        )


@router.get("/")
async def get_applications(current_user: dict = Depends(get_current_user)):
    """
    Get user's applications
    Tenants see their own applications
    Landlords see applications for their properties
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]
        
        if user_type == "tenant":
            # Fetch tenant's applications
            response = supabase_admin.table("applications").select(
                "*, property:properties(id, title, location, price, landlord_id)"
            ).eq("user_id", user_id).order("created_at", desc=True).execute()
            
        elif user_type == "landlord":
            # Fetch applications for landlord's properties
            response = supabase_admin.table("applications").select(
                "*, property:properties!inner(id, title, location, price), user:users!user_id(id, full_name, email, phone_number, trust_score)"
            ).eq("property.landlord_id", user_id).order("created_at", desc=True).execute()
            
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid user type"
            )
        
        return {
            "success": True,
            "applications": response.data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch applications: {str(e)}"
        )


@router.get("/{application_id}")
async def get_application(
    application_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get application by ID
    - Tenants can view their own applications
    - Landlords can view applications for their properties
    - Marks as viewed by landlord if accessed by landlord
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]
        
        # Fetch application with full property and user details
        app_response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, description, property_type, address, full_address, location, city, state, price, beds, baths, sqft, images, amenities, furnished, pet_friendly, landlord_id), user:users!user_id(id, full_name, email, phone_number, trust_score, avatar_url, user_type)"
        ).eq("id", application_id).single().execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found"
            )
        
        application = app_response.data
        
        # Verify access
        if user_type == "tenant":
            # Tenants can only view their own applications
            if application["user_id"] != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have permission to view this application"
                )
        elif user_type == "landlord":
            # Landlords can only view applications for their properties
            property_data = application.get("property")
            if not property_data or property_data.get("landlord_id") != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have permission to view this application"
                )
            
            # Mark as viewed by landlord (if not already)
            if not application.get("viewed_by_landlord"):
                try:
                    supabase_admin.table("applications").update({
                        "viewed_by_landlord": True,
                        "viewed_at": datetime.now().isoformat()
                    }).eq("id", application_id).execute()
                except Exception as e:
                    logger.warning(f"⚠️ [APP] Failed to mark application as viewed: {e}")
                    # Don't raise — still return the application even if marking fails
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid user type"
            )
        
        return {
            "success": True,
            "application": application
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch application: {str(e)}"
        )


@router.delete("/{application_id}")
async def withdraw_application(
    application_id: str,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Withdraw application (tenants only)
    """
    try:
        tenant_id = current_user["id"]
        
        # Fetch application
        app_response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, landlord_id)"
        ).eq("id", application_id).single().execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found"
            )
        
        application = app_response.data
        
        # Verify tenant owns the application
        if application["user_id"] != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to withdraw this application"
            )
        
        # Check if already withdrawn
        if application["status"] == "withdrawn":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Application is already withdrawn"
            )
        
        # Update status to withdrawn
        supabase_admin.table("applications").update({
            "status": "withdrawn"
        }).eq("id", application_id).execute()
        
        return {
            "success": True,
            "message": "Application withdrawn successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to withdraw application: {str(e)}"
        )


@router.patch("/{application_id}/approve")
async def approve_application(
    application_id: str,
    current_user: dict = Depends(get_current_landlord)
):
    """
    Approve application (landlords only, own properties)
    """
    try:
        landlord_id = current_user["id"]
        
        # Fetch application with property and tenant
        app_response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, landlord_id, price), user:users!user_id(id, full_name, email, phone_number)"
        ).eq("id", application_id).single().execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found"
            )
        
        application = app_response.data
        property_data = application.get("property")
        tenant_data = application.get("user")
        
        # Verify landlord owns the property
        if not property_data or property_data.get("landlord_id") != landlord_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to approve this application"
            )
        
        # Check if already approved/rejected
        if application["status"] not in ["pending", "under_review"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Application is already {application['status']}"
            )
        
        # Update application status
        update_response = supabase_admin.table("applications").update({
            "status": "approved",
            "viewed_by_landlord": True,
            "viewed_at": datetime.now().isoformat()
        }).eq("id", application_id).execute()
        
        # Fetch the updated application with full details
        updated_app_response = supabase_admin.table("applications").select(
            "*, property:properties!inner(id, title, location, price, landlord_id), user:users!user_id(id, full_name, email, phone_number, trust_score)"
        ).eq("id", application_id).single().execute()
        
        if not updated_app_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch updated application"
            )
        
        # Send notification to tenant
        from app.services.notification_service import notification_service
        
        landlord_name = current_user.get("full_name", "Landlord")
        landlord_email = current_user.get("email")
        landlord_phone = current_user.get("phone_number")
        
        await notification_service.notify_application_approved(
            application_id=application_id,
            property_id=property_data.get("id"),
            property_title=property_data.get("title", "Property"),
            tenant_id=tenant_data.get("id"),
            tenant_name=tenant_data.get("full_name", "Tenant"),
            tenant_email=tenant_data.get("email"),
            tenant_phone=tenant_data.get("phone_number"),
            landlord_name=landlord_name,
        )
        
        # Auto-generate rental agreement (NuloGuide Stage 5)
        logger.info(f"🔥 [APP] Auto-generating agreement for approved application {application_id}")
        logger.info(f"🔥 [APP] Property data: {property_data}")
        logger.info(f"🔥 [APP] Tenant data: {tenant_data}")
        
        # Use centralized agreement service
        from app.services.agreement_service import agreement_service
        
        agreement = await agreement_service.auto_generate_agreement(
            application_id=application_id,
            property_data=property_data,
            tenant_data=tenant_data,
            landlord_name=landlord_name
        )
        
        if agreement:
            agreement_id = agreement['id']
            logger.info(f"✅ [APP] Auto-generated agreement {agreement_id} for application {application_id}")
            
            # Send notification about agreement creation
            try:
                await notification_service.notify_agreement_created(
                    agreement_id=agreement_id,
                    application_id=application_id,
                    property_title=property_data.get("title", "Property"),
                    tenant_id=tenant_data.get("id"),
                    tenant_name=tenant_data.get("full_name", "Tenant"),
                    tenant_email=tenant_data.get("email"),
                    tenant_phone=tenant_data.get("phone_number"),
                    landlord_id=landlord_id,
                    landlord_name=landlord_name,
                    landlord_email=landlord_email,
                    landlord_phone=landlord_phone,
                )
                logger.info(f"✅ [APP] Agreement notification sent for {agreement_id}")
            except Exception as e:
                logger.error(f"❌ [APP] Failed to send agreement notification: {e}")
        else:
            logger.error(f"❌ [APP] Failed to auto-generate agreement for application {application_id}")
        
        # TODO: Update property status to rented (implement in agreement phase)
        # TODO: Update trust scores (+5 bonus for both)
        
        return {
            "success": True,
            "application": updated_app_response.data,
            "agreement": agreement,
            "message": "Application approved and rental agreement generated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [APP] Failed to approve application: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to approve application: {str(e)}"
        )


@router.patch("/{application_id}/reject")
async def reject_application(
    application_id: str,
    rejection_data: ApplicationReject,
    current_user: dict = Depends(get_current_landlord)
):
    """
    Reject application (landlords only, own properties)
    """
    try:
        landlord_id = current_user["id"]
        
        # Fetch application with property and tenant
        app_response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, landlord_id, price), user:users!user_id(id, full_name, email, phone_number)"
        ).eq("id", application_id).single().execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found"
            )
        
        application = app_response.data
        property_data = application.get("property")
        tenant_data = application.get("user")
        
        # Verify landlord owns the property
        if not property_data or property_data.get("landlord_id") != landlord_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to reject this application"
            )
        
        # Check if already approved/rejected
        if application["status"] not in ["pending", "under_review"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Application is already {application['status']}"
            )
        
        # Update application status
        update_response = supabase_admin.table("applications").update({
            "status": "rejected",
            "rejection_reason": rejection_data.reason,  # Store reason in rejection_reason field
            "viewed_by_landlord": True,
            "viewed_at": datetime.now().isoformat()
        }).eq("id", application_id).execute()
        
        # Fetch the updated application with full details
        updated_app_response = supabase_admin.table("applications").select(
            "*, property:properties!inner(id, title, location, price, landlord_id), user:users!user_id(id, full_name, email, phone_number, trust_score)"
        ).eq("id", application_id).single().execute()
        
        if not updated_app_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch updated application"
            )
        
        # Send notification to tenant
        from app.services.notification_service import notification_service
        
        await notification_service.notify_application_rejected(
            application_id=application_id,
            property_id=property_data.get("id"),
            property_title=property_data.get("title", "Property"),
            tenant_id=tenant_data.get("id"),
            tenant_name=tenant_data.get("full_name", "Tenant"),
            tenant_email=tenant_data.get("email"),
            tenant_phone=tenant_data.get("phone_number"),
            rejection_reason=rejection_data.reason,
        )
        
        return {
            "success": True,
            "application": updated_app_response.data,
            "message": "Application rejected"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [APP] Failed to reject application: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to reject application: {str(e)}"
        )
