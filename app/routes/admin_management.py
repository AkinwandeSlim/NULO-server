"""
Admin management routes for user operations
"""
from fastapi import APIRouter, Depends, HTTPException, status
from app.database import supabase_admin
from app.middleware.auth import get_current_admin
from app.models.user import UserResponse
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

router = APIRouter(prefix="/admin", tags=["admin-management"])

class UserDeleteRequest(BaseModel):
    email: str

class UserDeleteResponse(BaseModel):
    success: bool
    message: str

@router.delete("/users/delete-by-email", response_model=UserDeleteResponse)
async def delete_user_by_email(
    request: UserDeleteRequest,
    current_admin: UserResponse = Depends(get_current_admin)
):
    """
    Delete user by email (from both auth.users and public.users)
    """
    try:
        email = request.email
        print(f"🗑️ [ADMIN API] Deleting user: {email}")
        
        # Step 1: Find user in auth.users
        users_response = supabase_admin.auth.admin.listUsers()
        
        if users_response.error:
            print(f"❌ [ADMIN API] Error listing users: {users_response.error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to access user database"
            )
        
        target_user = None
        for user in users_response.data.users:
            if user.email == email:
                target_user = user
                break
        
        if not target_user:
            print(f"⚠️ [ADMIN API] User not found in auth system: {email}")
            return UserDeleteResponse(
                success=False,
                message="User not found in auth system"
            )
        
        # Step 2: Delete from public.users first (to avoid foreign key issues)
        try:
            profile_error = supabase_admin.table("users").delete().eq("id", target_user.id).execute()
            if profile_error:
                print(f"❌ [ADMIN API] Error deleting user profile: {profile_error}")
            else:
                print(f"✅ [ADMIN API] Deleted user from public users table")
        except Exception as e:
            print(f"❌ [ADMIN API] Exception deleting user profile: {e}")
        
        # Step 3: Delete from auth.users
        delete_response = supabase_admin.auth.admin.deleteUser(target_user.id)
        
        if delete_response.error:
            print(f"❌ [ADMIN API] Error deleting auth user: {delete_response.error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete auth user: {delete_response.error.message}"
            )
        
        print(f"✅ [ADMIN API] Successfully deleted user from auth system")
        
        return UserDeleteResponse(
            success=True,
            message=f"Successfully deleted user: {email}. You can now retry signup."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ADMIN API] Unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server error: {str(e)}"
        )

@router.get("/users/all")
async def get_all_users(
    current_admin: UserResponse = Depends(get_current_admin),
    user_type: Optional[str] = None,
    verification_status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """
    Get all users with optional filtering
    """
    try:
        query = supabase_admin.table("users").select(
            """
            id, email, full_name, user_type, verification_status,
            trust_score, avatar_url, phone_number, location,
            created_at, updated_at
            """
        )
        
        # Apply filters
        if user_type:
            query = query.eq("user_type", user_type)
        
        if verification_status:
            query = query.eq("verification_status", verification_status)
        
        # Apply pagination
        query = query.range(offset, offset + limit - 1).order("created_at", desc=True)
        
        result = query.execute()
        
        if result.error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch users"
            )
        
        return {
            "success": True,
            "users": result.data or [],
            "total": len(result.data or [])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ADMIN API] Error fetching users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch users"
        )

@router.post("/users/{user_id}/verify")
async def verify_user(
    user_id: str,
    current_admin: UserResponse = Depends(get_current_admin)
):
    """
    Manually verify a user
    """
    try:
        result = supabase_admin.table("users").update({
            "verification_status": "approved",
            "verification_approved_at": datetime.now().isoformat()
        }).eq("id", user_id).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return {
            "success": True,
            "message": "User verified successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ADMIN API] Error verifying user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify user"
        )

@router.post("/users/{user_id}/unverify")
async def unverify_user(
    user_id: str,
    current_admin: UserResponse = Depends(get_current_admin)
):
    """
    Unverify a user (set back to pending)
    """
    try:
        result = supabase_admin.table("users").update({
            "verification_status": "pending",
            "verification_approved_at": None
        }).eq("id", user_id).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return {
            "success": True,
            "message": "User verification status reset to pending"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ADMIN API] Error unverifying user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unverify user"
        )
