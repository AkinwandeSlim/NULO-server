"""
Notification API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from pydantic import BaseModel
from typing import List, Optional
import logging
import os
from datetime import datetime

from ..middleware.auth import get_current_user
from ..database import supabase_admin
from ..services.notification_service import notification_service
from ..services.notification_helpers import create_notification

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])


# ─────────────────────────────────────────────────────────────────────────────
# Internal service key auth
# ─────────────────────────────────────────────────────────────────────────────

def _verify_internal_key(x_internal_service_key: str = Header(default="")):
    """
    Verifies server-to-server calls from Next.js route handlers.
    Set INTERNAL_SERVICE_KEY in both FastAPI and Next.js env vars.
    If no key is configured (dev), the check is skipped.
    """
    expected = os.getenv("INTERNAL_SERVICE_KEY", "")
    if expected and x_internal_service_key != expected:
        raise HTTPException(status_code=401, detail="Invalid internal service key")


# ─────────────────────────────────────────────────────────────────────────────
# Internal request models
# ─────────────────────────────────────────────────────────────────────────────

class InternalNotificationCreate(BaseModel):
    user_id: str
    title: str
    message: str
    type: str
    link: Optional[str] = None
    data: Optional[dict] = None


class SignupNotificationRequest(BaseModel):
    user_id: str
    user_email: str
    user_name: str
    user_type: str                    # landlord | tenant
    is_oauth: bool = False            # True = Google OAuth (email already verified, send welcome email)
                                      # False = manual email signup (email not yet verified, in-app only)


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: called by Next.js auth/callback/route.ts after email verification
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/internal/create")
async def create_internal_notification(
    payload: InternalNotificationCreate,
    _key: None = Depends(_verify_internal_key),
):
    """
    Create a welcome notification after email verification.
    Called by route.ts immediately after the user clicks their email link.
    Fires notify_email_verified() which sends email + in-app notification.
    """
    try:
        # Fetch full user data from DB so we can personalise the email
        user_r = supabase_admin.table("users").select(
            "email, full_name, user_type"
        ).eq("id", payload.user_id).execute()

        user_data = user_r.data[0] if user_r.data else None

        if user_data:
            await notification_service.notify_email_verified(
                user_id=payload.user_id,
                user_email=user_data.get("email", ""),
                user_name=user_data.get("full_name") or "there",
                user_type=user_data.get("user_type", "tenant"),
            )
        else:
            # Fallback: plain in-app insert with what route.ts provided
            create_notification(
                user_id=payload.user_id,
                notif_type=payload.type,
                title=payload.title,
                message=payload.message,
                link=payload.link,
                data=payload.data or {},
            )

        logger.info(f"✅ [NOTIF] email_verified notification fired for {payload.user_id}")
        return {"success": True, "message": "Notification created"}

    except Exception as e:
        logger.error(f"❌ [NOTIF] internal/create failed: {e}")
        # Return 200 so the auth flow is never blocked by a notification failure
        return {"success": False, "error": str(e)}


@router.post("/signup")
async def notify_signup(
    payload: SignupNotificationRequest,
    _key: None = Depends(_verify_internal_key),
):
    """
    Signup notification — behaviour differs by auth flow:

    Manual email signup (is_oauth=False):
      - In-app ONLY: "Account created, check your email to verify"
      - No welcome email — Supabase already sent the verification link,
        and notify_email_verified() sends the welcome email once they click it.
        Sending an email here would mean 3 emails in quick succession (bad UX).

    Google OAuth (is_oauth=True):
      - In-app notification (welcome message)
      - Welcome EMAIL via notify_signup() — because notify_email_verified()
        never fires for OAuth users (their email was verified by Google,
        they never click a verification link). This is their only welcome email.
    """
    try:
        if payload.is_oauth:
            # OAuth path: in-app + welcome email
            await notification_service.notify_signup(
                user_id=payload.user_id,
                user_email=payload.user_email,
                user_name=payload.user_name,
                user_type=payload.user_type,
            )
            logger.info(f"✅ [NOTIF] OAuth signup: in-app + welcome email for {payload.user_id} ({payload.user_type})")
        else:
            # Manual email path: in-app only
            is_landlord = payload.user_type == "landlord"
            create_notification(
                user_id=payload.user_id,
                notif_type="system",
                title="🏠 Welcome to NuloAfrica!" if is_landlord else "👋 Welcome to NuloAfrica!",
                message=(
                    "Your landlord account has been created. Check your email for the verification link to get started."
                    if is_landlord
                    else "Your account has been created. Check your email for the verification link, then start exploring properties."
                ),
                link=(
                    "/signup/landlord/confirmation"
                    if is_landlord
                    else "/signup/tenant/confirmation"
                ),
            )
            logger.info(f"✅ [NOTIF] Manual signup: in-app only for {payload.user_id} ({payload.user_type})")

        return {"success": True}

    except Exception as e:
        logger.error(f"❌ [NOTIF] signup notification failed: {e}")
        return {"success": False, "error": str(e)}





@router.get("/")
async def get_notifications(
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    notification_type: Optional[str] = Query(None),
    current_user = Depends(get_current_user)
):
    """Get notifications for current user with timeout protection"""
    try:
        user_id = current_user["id"]
        logger.info(f"🔔 [NOTIF] Fetching notifications for user: {user_id}")
        
        try:
            # Build query efficiently with timeout protection
            query = supabase_admin.table("notifications").select("*").eq("user_id", user_id)
            
            # Apply filters
            if unread_only:
                query = query.eq("read", False)
            
            if notification_type:
                query = query.eq("type", notification_type)
            
            # Apply pagination and ordering - wrapp in try/except for timeout
            result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
            
            notifications = result.data or []
            total_count = len(notifications)
            
            # Calculate unread count from fetched data (no extra DB call!)
            unread_count = len([n for n in notifications if not n.get("read", False)])
            
            logger.info(f"🔔 [NOTIF] Retrieved {total_count} notifications ({unread_count} unread)")
            
            return {
                "success": True,
                "notifications": notifications,
                "unread_count": unread_count,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            }
            
        except (TimeoutError, Exception) as db_error:
            # Timeout or DB error - return empty list with 200 (graceful degradation)
            if "timed out" in str(db_error).lower() or "timeout" in str(db_error).lower():
                logger.warning(f"⚠️ [NOTIF] Database query timed out: {str(db_error)}")
                return {
                    "success": True,
                    "notifications": [],  # Empty list on timeout
                    "unread_count": 0,
                    "total_count": 0,
                    "limit": limit,
                    "offset": offset,
                    "warning": "Data temporarily unavailable - database timeout"
                }
            else:
                # Re-raise other errors
                raise db_error
    
    except Exception as e:
        logger.error(f"🔔 [NOTIF] Error fetching notifications: {type(e).__name__}: {str(e)}")
        # Return 401 if it's an auth error
        if "Unauthorized" in str(e) or "401" in str(e):
            raise HTTPException(status_code=401, detail="Authentication failed")
        # Return graceful error for other issues
        raise HTTPException(status_code=200, detail={
            "success": False,
            "notifications": [],
            "unread_count": 0,
            "error": "Unable to fetch notifications"
        })


@router.get("/unread-count")
async def get_unread_count(
    current_user = Depends(get_current_user)
):
    """Get count of unread notifications"""
    try:
        user_id = current_user["id"]
        logger.info(f"🔔 [NOTIF] Getting unread count for user: {user_id}")
        
        result = supabase_admin.table("notifications").select(
            "id", count="exact"
        ).eq("user_id", user_id).eq("read", False).execute()
        
        count = result.count or 0
        logger.info(f"🔔 [NOTIF] User has {count} unread notifications")
        
        return {"success": True, "unread_count": count}
    
    except Exception as e:
        logger.error(f"🔔 [NOTIF] Error getting unread count: {str(e)}")
        return {"success": True, "unread_count": 0}


@router.patch("/{notification_id}/read")
async def mark_as_read(
    notification_id: str,
    current_user = Depends(get_current_user)
):
    """Mark a notification as read"""
    try:
        user_id = current_user["id"]
        logger.info(f"🔔 [NOTIF] Marking notification {notification_id} as read for user: {user_id}")
        
        # Verify notification belongs to user
        check_response = supabase_admin.table("notifications").select("id").eq("id", notification_id).eq("user_id", user_id).execute()
        
        if not check_response.data:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        # Update with proper timestamps
        result = supabase_admin.table("notifications").update({
            "read": True,
            "read_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }).eq("id", notification_id).eq("user_id", user_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        logger.info(f"🔔 [NOTIF] Notification {notification_id} marked as read")
        
        return {"success": True, "message": "Notification marked as read"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"🔔 [NOTIF] Error marking as read: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/mark-all-read")
async def mark_all_read(
    current_user = Depends(get_current_user)
):
    """Mark all notifications as read for current user"""
    try:
        user_id = current_user["id"]
        logger.info(f"🔔 [NOTIF] Marking all notifications as read for user: {user_id}")
        
        # Update with proper timestamps
        result = supabase_admin.table("notifications").update({
            "read": True,
            "read_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }).eq("user_id", user_id).eq("read", False).execute()
        
        count = len(result.data) if result.data else 0
        
        logger.info(f"🔔 [NOTIF] Marked {count} notifications as read")
        
        return {
            "success": True, 
            "message": f"Marked {count} notifications as read",
            "updated_count": count
        }
    
    except Exception as e:
        logger.error(f"🔔 [NOTIF] Error marking all as read: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user = Depends(get_current_user)
):
    """Delete a specific notification"""
    try:
        user_id = current_user["id"]
        logger.info(f"🔔 [NOTIF] Deleting notification {notification_id} for user: {user_id}")
        
        # Verify notification belongs to user
        check_response = supabase_admin.table("notifications").select("id").eq("id", notification_id).eq("user_id", user_id).execute()
        
        if not check_response.data:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        # Delete notification
        delete_response = supabase_admin.table("notifications").delete().eq("id", notification_id).eq("user_id", user_id).execute()
        
        if not delete_response.data:
            raise HTTPException(status_code=400, detail="Failed to delete notification")
        
        logger.info(f"🔔 [NOTIF] Notification {notification_id} deleted")
        
        return {
            "success": True,
            "message": "Notification deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"🔔 [NOTIF] Error deleting notification: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))