"""
Notification API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
import logging
from datetime import datetime

from ..middleware.auth import get_current_user
from ..database import supabase_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/")
async def get_notifications(
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    notification_type: Optional[str] = Query(None),
    current_user = Depends(get_current_user)
):
    """Get notifications for current user"""
    try:
        user_id = current_user["id"]
        logger.info(f"🔔 [NOTIF] Fetching notifications for user: {user_id}")
        
        # Build query
        # Build query efficiently
        query = supabase_admin.table("notifications").select("*").eq("user_id", user_id)
        
        # Apply filters
        if unread_only:
            query = query.eq("read", False)
        
        if notification_type:
            query = query.eq("type", notification_type)
        
        # Apply pagination and ordering
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
    
    except Exception as e:
        logger.error(f"🔔 [NOTIF] Error fetching notifications: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


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
