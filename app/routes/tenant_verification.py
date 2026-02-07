"""
Tenant verification management routes for admin
"""
from fastapi import APIRouter, Depends, HTTPException, status
from app.database import supabase_admin
from app.middleware.auth import get_current_user, get_current_admin
from app.models.user import UserResponse
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

router = APIRouter(prefix="/tenant-verifications", tags=["tenant-verification"])

class TenantApprovalRequest(BaseModel):
    verification_notes: Optional[str] = None

class TenantRejectionRequest(BaseModel):
    reason: str
    verification_notes: Optional[str] = None

@router.get("/")
async def get_tenants_for_verification(
    current_user: UserResponse = Depends(get_current_admin),
    status: Optional[str] = None
):
    """
    Get all tenants for admin verification
    """
    try:
        # Build query
        query = supabase_admin.table("users").select(
            """
            id, email, full_name, phone_number, location, user_type,
            verification_status, trust_score, created_at, updated_at
            """
        )
        
        # Filter by user_type = 'tenant'
        query = query.eq("user_type", "tenant")
        
        # Filter by status if provided
        if status:
            query = query.eq("verification_status", status)
        else:
            # Default to pending verification
            query = query.in_("verification_status", ["pending", "approved", "rejected"])
        
        # Order by creation date
        query = query.order("created_at", desc=True)
        
        result = query.execute()
        
        # Format the response
        tenants = []
        if result.data:
            for tenant in result.data:
                tenants.append({
                    "id": tenant["id"],
                    "email": tenant["email"],
                    "full_name": tenant["full_name"],
                    "user_type": tenant["user_type"],
                    "verification_status": tenant["verification_status"],
                    "phone": tenant.get("phone_number"),
                    "location": tenant.get("location"),
                    "trust_score": tenant.get("trust_score"),
                    "created_at": tenant["created_at"],
                    "updated_at": tenant["updated_at"]
                })
        
        return {
            "success": True,
            "verifications": tenants
        }
    except Exception as e:
        print(f"❌ [TENANT-VERIFICATION] Error fetching tenants: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch tenants"
        )

@router.post("/{tenant_id}/approve")
async def approve_tenant(
    tenant_id: str,
    approval_data: TenantApprovalRequest,
    current_user: UserResponse = Depends(get_current_admin)
):
    """
    Approve a tenant verification
    """
    try:
        # Update tenant verification status
        result = supabase_admin.table("users").update({
            "verification_status": "approved",
            "updated_at": datetime.now().isoformat()
        }).eq("id", tenant_id).eq("user_type", "tenant").execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found"
            )
        
        # TODO: Send notification email to tenant
        # TODO: Update tenant search index
        
        return {
            "success": True,
            "message": "Tenant verification approved successfully"
        }
    except Exception as e:
        print(f"❌ [TENANT-VERIFICATION] Error approving tenant: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve tenant"
        )

@router.post("/{tenant_id}/reject")
async def reject_tenant(
    tenant_id: str,
    rejection_data: TenantRejectionRequest,
    current_user: UserResponse = Depends(get_current_admin)
):
    """
    Reject a tenant verification
    """
    try:
        # Update tenant verification status
        result = supabase_admin.table("users").update({
            "verification_status": "rejected",
            "updated_at": datetime.now().isoformat()
        }).eq("id", tenant_id).eq("user_type", "tenant").execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found"
            )
        
        # TODO: Send notification email to tenant with rejection reason
        # TODO: Log rejection for audit trail
        
        return {
            "success": True,
            "message": "Tenant verification rejected successfully"
        }
    except Exception as e:
        print(f"❌ [TENANT-VERIFICATION] Error rejecting tenant: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject tenant"
        )
