"""
Admin signup and profile management routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from app.database import supabase_admin
from app.middleware.auth import get_current_user
from app.models.user import UserResponse
from typing import Dict, Any
from datetime import datetime
from pydantic import BaseModel

router = APIRouter(prefix="/admin", tags=["admin-signup"])

@router.get("/health")
async def admin_health():
    """Health check for admin routes"""
    return {"status": "admin routes healthy", "message": "Admin signup routes are working"}

class AdminProfileRequest(BaseModel):
    user_id: str
    email: str
    full_name: str
    role_level: int = 1
    permissions: Dict[str, Any]

@router.post("/create-profile")
async def create_admin_profile(
    profile_data: AdminProfileRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Create admin profile in users and admins tables
    This should be called after Supabase Auth signup
    """
    try:
        print(f"👤 [ADMIN SIGNUP] Creating admin profile for user: {profile_data.user_id}")
        print(f"📧 [ADMIN SIGNUP] Email: {profile_data.email}")
        print(f"👑 [ADMIN SIGNUP] Authenticated user: {current_user.get('email') if current_user else 'None'}")
        
        # Step 1: Create/Update user profile in users table
        user_record = {
            "id": profile_data.user_id,
            "email": profile_data.email,
            "phone_number": "",
            "password_hash": "",  # Handled by auth.users
            "full_name": profile_data.full_name,
            "avatar_url": "",
            "trust_score": 100,
            "verification_status": "approved",
            "user_type": "admin",
            "last_login_at": datetime.now().isoformat(),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "phone_verified": True,
            "location": "System Admin",
            "onboarding_completed": True
        }
        
        # Insert or update user record
        user_result = supabase_admin.table("users").upsert(user_record).execute()
        
        if not user_result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user profile"
            )
        
        print(f"✅ [ADMIN SIGNUP] User profile created: {user_result.data}")
        
        # Step 2: Create admin record
        admin_record = {
            "user_id": profile_data.user_id,
            "role_level": profile_data.role_level,
            "permissions": profile_data.permissions,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        admin_result = supabase_admin.table("admins").upsert(admin_record).execute()
        
        if not admin_result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create admin record"
            )
        
        print(f"✅ [ADMIN SIGNUP] Admin record created: {admin_result.data}")
        
        return {
            "success": True,
            "message": "Admin profile created successfully",
            "user_id": profile_data.user_id,
            "user": user_result.data[0] if user_result.data else None,
            "admin": admin_result.data[0] if admin_result.data else None
        }
        
    except Exception as e:
        print(f"❌ [ADMIN SIGNUP] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create admin profile: {str(e)}"
        )

@router.post("/create-profile-dev")
async def create_admin_profile_dev(
    profile_data: AdminProfileRequest
):
    """
    Development-only route: Create admin profile without authentication
    Remove this in production!
    """
    try:
        print(f"🚀 [ADMIN SIGNUP DEV] Creating admin profile for user: {profile_data.user_id}")
        print(f"📧 [ADMIN SIGNUP DEV] Email: {profile_data.email}")
        
        # Step 1: Create/Update user profile in users table
        user_record = {
            "id": profile_data.user_id,
            "email": profile_data.email,
            "phone_number": "",
            "password_hash": "",  # Handled by auth.users
            "full_name": profile_data.full_name,
            "avatar_url": "",
            "trust_score": 100,
            "verification_status": "approved",
            "user_type": "admin",
            "last_login_at": datetime.now().isoformat(),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "phone_verified": True,
            "location": "System Admin",
            "onboarding_completed": True
        }
        
        # Insert or update user record
        user_result = supabase_admin.table("users").upsert(user_record).execute()
        
        if not user_result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user profile"
            )
        
        print(f"✅ [ADMIN SIGNUP DEV] User profile created: {user_result.data}")
        
        # Step 2: Create admin record
        admin_record = {
            "user_id": profile_data.user_id,
            "role_level": profile_data.role_level,
            "permissions": profile_data.permissions,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        admin_result = supabase_admin.table("admins").upsert(admin_record).execute()
        
        if not admin_result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create admin record"
            )
        
        print(f"✅ [ADMIN SIGNUP DEV] Admin record created: {admin_result.data}")
        
        return {
            "success": True,
            "message": "Admin profile created successfully (DEV MODE)",
            "user_id": profile_data.user_id,
            "user": user_result.data[0] if user_result.data else None,
            "admin": admin_result.data[0] if admin_result.data else None
        }
        
    except Exception as e:
        print(f"❌ [ADMIN SIGNUP DEV] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create admin profile: {str(e)}"
        )
