"""
Admin management routes for user operations
"""
from fastapi import APIRouter, Depends, HTTPException, status
from app.database import supabase_admin
from app.middleware.auth import get_current_admin
from app.models.user import UserResponse
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import asyncio
import logging

router = APIRouter(prefix="/admin", tags=["admin-management"])
logger = logging.getLogger(__name__)

class UserDeleteRequest(BaseModel):
    email: str

class UserDeleteResponse(BaseModel):
    success: bool
    message: str

class SimulatePayoutRequest(BaseModel):
    merchant_tx_ref: str

class SimulatePayoutResponse(BaseModel):
    success: bool
    message: str
    transaction_id: Optional[str] = None
    status: Optional[str] = None

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
        error_msg = str(e)
        print(f"❌ [ADMIN API] Unexpected error: {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again."
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


# ============================================================================
# ROLE-BASED ADMIN MANAGEMENT (Using existing admins table)
# ============================================================================

# Role levels (must match DB constraint)
ROLE_LEVELS = {
    "super_admin": 1,
    "admin": 2,
    "limited_admin": 3
}

class AdminRoleUpdate(BaseModel):
    """Update admin role level"""
    role_level: int  # 1=super_admin, 2=admin, 3=limited_admin
    reason: Optional[str] = None

def get_admin_role_level(admin_id: str) -> Optional[int]:
    """Get admin's role level from admins table"""
    try:
        result = supabase_admin.table("admins").select("role_level").eq("id", admin_id).execute()
        if result.data and len(result.data) > 0:
            # data is a list, get first item
            admin_record = result.data[0]
            if isinstance(admin_record, dict):
                return admin_record.get("role_level")
        return None
    except Exception as e:
        print(f"❌ [get_admin_role_level] Error: {e}")
        return None

def check_super_admin(current_admin: UserResponse) -> bool:
    """Verify current user is super admin (role_level = 1)"""
    # Handle both dict and object formats for current_admin
    admin_id = current_admin.get("id") if isinstance(current_admin, dict) else current_admin.id
    admin_role = get_admin_role_level(admin_id)
    return admin_role == 1

@router.get("/role-accounts")
async def get_admin_accounts(
    current_admin: UserResponse = Depends(get_current_admin),
    limit: int = 50,
    offset: int = 0
):
    """
    Get list of all admin accounts with their details
    Only Super Admins can view all admins
    Uses admins table joined with users table
    """
    try:
        # Handle both dict and object formats for current_admin
        admin_id = current_admin.get("id") if isinstance(current_admin, dict) else current_admin.id
        print(f"🔍 [GET_ADMIN_ACCOUNTS] Starting - current_admin type: {type(current_admin)}, admin_id: {admin_id}")
        
        if not check_super_admin(current_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Super Admins can view admin accounts"
            )
        
        print(f"✅ [GET_ADMIN_ACCOUNTS] Super admin check passed")
        
        # Fetch admins with user details - use try-except for error handling (not .error attribute)
        result = supabase_admin.table("admins").select(
            "id, role_level, permissions, last_action_at, created_at, updated_at, "
            "users(email, full_name, avatar_url)"
        ).order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        
        print(f"✅ [GET_ADMIN_ACCOUNTS] Query executed - result type: {type(result)}")
        print(f"📊 [GET_ADMIN_ACCOUNTS] Result data type: {type(result.data)}, length: {len(result.data) if result.data else 0}")
        
        # Transform response to include user data
        admins_with_users = []
        for idx, admin in enumerate(result.data or []):
            print(f"📝 [GET_ADMIN_ACCOUNTS] Processing admin {idx} - type: {type(admin)}")
            print(f"📝 [GET_ADMIN_ACCOUNTS] Admin data: {admin}")
            
            try:
                # Make sure admin is a dict
                if not isinstance(admin, dict):
                    print(f"⚠️ [GET_ADMIN_ACCOUNTS] Admin is not dict! Type: {type(admin)}")
                    admin = dict(admin) if hasattr(admin, '__dict__') else {}
                
                user = admin.get("users", {})
                print(f"👤 [GET_ADMIN_ACCOUNTS] User data type: {type(user)}, value: {user}")
                
                admin_obj = {
                    "id": admin.get("id"),
                    "email": user.get("email") if isinstance(user, dict) else (user.email if hasattr(user, 'email') else None),
                    "full_name": user.get("full_name") if isinstance(user, dict) else (user.full_name if hasattr(user, 'full_name') else None),
                    "avatar_url": user.get("avatar_url") if isinstance(user, dict) else (user.avatar_url if hasattr(user, 'avatar_url') else None),
                    "role_level": admin.get("role_level"),
                    "permissions": admin.get("permissions", {}),
                    "last_action_at": admin.get("last_action_at"),
                    "created_at": admin.get("created_at"),
                    "updated_at": admin.get("updated_at")
                }
                admins_with_users.append(admin_obj)
                print(f"✅ [GET_ADMIN_ACCOUNTS] Added admin: {admin_obj['id']}")
                
            except Exception as e:
                print(f"❌ [GET_ADMIN_ACCOUNTS] Error processing admin {idx}: {str(e)}")
                print(f"❌ [GET_ADMIN_ACCOUNTS] Admin object: {admin}")
                raise
        
        print(f"✅ [GET_ADMIN_ACCOUNTS] Completed - returning {len(admins_with_users)} admins")
        
        return {
            "success": True,
            "admins": admins_with_users,
            "total": len(admins_with_users)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ADMIN API] Error fetching admin accounts: {e}")
        print(f"❌ [ADMIN API] Error type: {type(e)}")
        import traceback
        print(f"❌ [ADMIN API] Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch admin accounts: {str(e)}"
        )

@router.post("/admin-accounts/{admin_id}/role")
async def update_admin_role(
    admin_id: str,
    role_update: AdminRoleUpdate,
    current_admin: UserResponse = Depends(get_current_admin)
):
    """
    Update admin role level in admins table
    Only Super Admins can change admin roles
    role_level: 1=super_admin, 2=admin, 3=limited_admin
    """
    try:
        if not check_super_admin(current_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Super Admins can update admin roles"
            )
        
        # Handle both dict and object formats for current_admin
        current_admin_id = current_admin.get("id") if isinstance(current_admin, dict) else current_admin.id
        
        if admin_id == current_admin_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify your own admin role"
            )
        
        # Validate role_level
        if role_update.role_level not in [1, 2, 3]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role_level. Must be 1 (super_admin), 2 (admin), or 3 (limited_admin)"
            )
        
        # Update admin role in admins table
        result = supabase_admin.table("admins").update(
            {
                "role_level": role_update.role_level,
                "updated_at": datetime.now().isoformat()
            }
        ).eq("id", admin_id).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update admin role"
            )
        
        role_names = {1: "super_admin", 2: "admin", 3: "limited_admin"}
        
        return {
            "success": True,
            "message": f"Admin role updated to {role_names.get(role_update.role_level)}",
            "admin_id": admin_id,
            "role_level": role_update.role_level
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ADMIN API] Error updating admin role: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update admin role"
        )

@router.delete("/admin-accounts/{admin_id}")
async def delete_admin_account(
    admin_id: str,
    current_admin: UserResponse = Depends(get_current_admin)
):
    """
    Delete admin account (soft delete from admins table)
    Only Super Admins can delete admins
    Cannot delete yourself
    """
    try:
        if not check_super_admin(current_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Super Admins can delete admin accounts"
            )
        
        # Handle both dict and object formats for current_admin
        current_admin_id = current_admin.get("id") if isinstance(current_admin, dict) else current_admin.id
        
        if admin_id == current_admin_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete your own admin account"
            )
        
        # Soft delete: remove from admins table (user account remains in users table)
        result = supabase_admin.table("admins").delete().eq("id", admin_id).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete admin account"
            )
        
        return {
            "success": True,
            "message": "Admin account deleted. User account remains in system.",
            "admin_id": admin_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ADMIN API] Error deleting admin account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete admin account"
        )

@router.post("/simulate-payout-webhook", response_model=SimulatePayoutResponse)
async def simulate_payout_webhook(
    request: SimulatePayoutRequest,
    current_admin: UserResponse = Depends(get_current_admin)
):
    """
    Simulate a payout_success webhook for demo/testing purposes.
    
    This allows testing the complete disbursement flow without waiting
    for the actual Nomba webhook. It directly updates the transaction
    status to 'released' and sets the released_at timestamp.
    
    Only admins can use this endpoint for demo purposes.
    """
    try:
        merchant_tx_ref = request.merchant_tx_ref
        logger.info(f"[ADMIN API] Simulating payout_success webhook for ref: {merchant_tx_ref}")
        
        # Find the transaction by merchant_tx_ref
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin
                .table("transactions")
                .select("id, status, amount, agreement_id")
                .eq("nomba_transfer_ref", merchant_tx_ref)
                .maybe_single()
                .execute(),
        )
        
        transaction = result.data
        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Transaction with merchant_tx_ref '{merchant_tx_ref}' not found"
            )
        
        # Check if already released
        if transaction.get("status") == "released":
            return SimulatePayoutResponse(
                success=True,
                message="Transaction already in released state",
                transaction_id=transaction.get("id"),
                status="released"
            )
        
        # Update transaction to released
        now_iso = datetime.now(timezone.utc).isoformat()
        update_result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin
                .table("transactions")
                .update({
                    "status": "released",
                    "released_at": now_iso,
                    "nomba_transfer_id": f"simulated-{merchant_tx_ref[:8]}",
                })
                .eq("id", transaction.get("id"))
                .execute(),
        )
        
        logger.info(
            f"[ADMIN API] Simulated payout_success | tx_id={transaction.get('id')} | "
            f"ref={merchant_tx_ref} | amount={transaction.get('amount')}"
        )
        
        return SimulatePayoutResponse(
            success=True,
            message="Payout webhook simulated successfully",
            transaction_id=transaction.get("id"),
            status="released"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ADMIN API] Error simulating payout webhook: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to simulate payout webhook: {str(e)}"
        )
