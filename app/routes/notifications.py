"""
Notification API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional

from ..middleware.auth import get_current_user
from ..database import supabase_admin

router = APIRouter(tags=["notifications"])


@router.get("/")
async def get_notifications(
    unread_only: bool = False,
    limit: int = 50,
    current_user = Depends(get_current_user)
):
    """Get notifications for current user"""
    try:
        query = supabase_admin.table("notifications").select("*").eq(
            "user_id", current_user['id']
        )
        
        if unread_only:
            query = query.eq("read", False)
        
        result = query.order("created_at", desc=True).limit(limit).execute()
        
        return {"notifications": result.data or []}
    
    except Exception as e:
        print(f"❌ [NOTIFICATIONS] Error fetching: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/unread-count")
async def get_unread_count(
    current_user = Depends(get_current_user)
):
    """Get count of unread notifications"""
    try:
        result = supabase_admin.table("notifications").select(
            "id", count="exact"
        ).eq("user_id", current_user['id']).eq("read", False).execute()
        
        return {"count": result.count or 0}
    
    except Exception as e:
        print(f"❌ [NOTIFICATIONS] Error getting count: {str(e)}")
        return {"count": 0}


@router.put("/{notification_id}/read")
async def mark_as_read(
    notification_id: str,
    current_user = Depends(get_current_user)
):
    """Mark a notification as read"""
    try:
        result = supabase_admin.table("notifications").update({
            "read": True,
            "read_at": "now()"
        }).eq("id", notification_id).eq("user_id", current_user['id']).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        return {"success": True, "message": "Notification marked as read"}
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [NOTIFICATIONS] Error marking as read: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/mark-all-read")
async def mark_all_read(
    current_user = Depends(get_current_user)
):
    """Mark all notifications as read for current user"""
    try:
        result = supabase_admin.table("notifications").update({
            "read": True,
            "read_at": "now()" 
        }).eq("user_id", current_user['id']).eq("read", False).execute()
        
        count = len(result.data) if result.data else 0
        
        return {
            "success": True, 
            "message": f"Marked {count} notifications as read"
        }
    
    except Exception as e:
        print(f"❌ [NOTIFICATIONS] Error marking all as read: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
