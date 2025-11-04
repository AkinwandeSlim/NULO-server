"""
Application routes
"""
from fastapi import APIRouter, HTTPException, Depends, status
from app.database import supabase_admin
from app.middleware.auth import get_current_user, get_current_tenant, get_current_landlord
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter(prefix="/applications")


class ApplicationCreate(BaseModel):
    property_id: str
    message: Optional[str] = None
    proposed_move_in_date: Optional[str] = None


class ApplicationApprove(BaseModel):
    pass


class ApplicationReject(BaseModel):
    reason: str
    reason_code: str


@router.post("/")
async def create_application(
    application_data: ApplicationCreate,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Submit rental application (tenants only)
    Requires 100% profile completion (deferred KYC gate)
    """
    try:
        tenant_id = current_user["id"]
        
        # Check tenant profile completion
        tenant_profile = supabase_admin.table("tenants").select("profile_completion").eq(
            "id", tenant_id
        ).single().execute()
        
        if not tenant_profile.data or tenant_profile.data.get("profile_completion", 0) < 100:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must complete your profile (100%) before applying for properties"
            )
        
        # Check if property exists
        property_check = supabase_admin.table("properties").select("id, landlord_id, title, rent_amount").eq(
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
            "tenant_id", tenant_id
        ).eq("property_id", application_data.property_id).execute()
        
        if existing_app.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already applied for this property"
            )
        
        # Create application
        app_dict = {
            "tenant_id": tenant_id,
            "property_id": application_data.property_id,
            "status": "submitted",
            "message": application_data.message,
            "proposed_move_in_date": application_data.proposed_move_in_date,
            "documents": {}
        }
        
        app_response = supabase_admin.table("applications").insert(app_dict).execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create application"
            )
        
        application = app_response.data[0]
        
        # Create mock escrow transaction
        transaction_dict = {
            "application_id": application["id"],
            "tenant_id": tenant_id,
            "landlord_id": property_data["landlord_id"],
            "property_id": application_data.property_id,
            "amount": property_data["rent_amount"],
            "currency": "NGN",
            "status": "held",
            "payment_gateway": "paystack",
            "transaction_type": "rent_payment",
            "held_at": datetime.now().isoformat(),
            "notes": "Mock escrow - payment held pending approval"
        }
        
        transaction_response = supabase_admin.table("transactions").insert(transaction_dict).execute()
        
        # Increment application count on property
        supabase_admin.table("properties").update({
            "application_count": supabase_admin.table("properties").select("application_count").eq(
                "id", application_data.property_id
            ).single().execute().data.get("application_count", 0) + 1
        }).eq("id", application_data.property_id).execute()
        
        # TODO: Send notification to landlord
        
        return {
            "success": True,
            "application": application,
            "transaction": transaction_response.data[0] if transaction_response.data else None,
            "message": "Application submitted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to submit application: {str(e)}"
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
                "*, property:properties(id, title, location, rent_amount, photos, landlord:users!landlord_id(id, full_name, avatar_url, trust_score))"
            ).eq("tenant_id", user_id).order("created_at", desc=True).execute()
            
        elif user_type == "landlord":
            # Fetch applications for landlord's properties
            response = supabase_admin.table("applications").select(
                "*, property:properties!inner(id, title, location, rent_amount, photos, landlord_id), tenant:users!tenant_id(id, full_name, avatar_url, trust_score)"
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
        
        # Fetch application with property
        app_response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, landlord_id)"
        ).eq("id", application_id).single().execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found"
            )
        
        application = app_response.data
        property_data = application.get("property")
        
        # Verify landlord owns the property
        if not property_data or property_data.get("landlord_id") != landlord_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to approve this application"
            )
        
        # Check if already approved/rejected
        if application["status"] not in ["submitted", "under_review"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Application is already {application['status']}"
            )
        
        # Update application status
        supabase_admin.table("applications").update({
            "status": "approved",
            "reviewed_at": datetime.now().isoformat(),
            "reviewed_by": landlord_id
        }).eq("id", application_id).execute()
        
        # Update transaction status to released
        supabase_admin.table("transactions").update({
            "status": "released",
            "released_at": datetime.now().isoformat()
        }).eq("application_id", application_id).execute()
        
        # Update property status to rented
        supabase_admin.table("properties").update({
            "status": "rented"
        }).eq("id", application["property_id"]).execute()
        
        # TODO: Update trust scores (+5 bonus for both)
        # TODO: Send notification to tenant
        
        return {
            "success": True,
            "message": "Application approved successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
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
        
        # Fetch application with property
        app_response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, landlord_id)"
        ).eq("id", application_id).single().execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found"
            )
        
        application = app_response.data
        property_data = application.get("property")
        
        # Verify landlord owns the property
        if not property_data or property_data.get("landlord_id") != landlord_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to reject this application"
            )
        
        # Check if already approved/rejected
        if application["status"] not in ["submitted", "under_review"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Application is already {application['status']}"
            )
        
        # Update application status
        supabase_admin.table("applications").update({
            "status": "rejected",
            "rejection_reason": rejection_data.reason,
            "reason_code": rejection_data.reason_code,
            "reviewed_at": datetime.now().isoformat(),
            "reviewed_by": landlord_id
        }).eq("id", application_id).execute()
        
        # Update transaction status to refunded
        supabase_admin.table("transactions").update({
            "status": "refunded",
            "refunded_at": datetime.now().isoformat()
        }).eq("application_id", application_id).execute()
        
        # TODO: Send notification to tenant
        
        return {
            "success": True,
            "message": "Application rejected"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to reject application: {str(e)}"
        )
