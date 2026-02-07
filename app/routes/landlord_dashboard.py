"""
Landlord Dashboard API Routes
Provides comprehensive dashboard data for landlords
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from uuid import UUID
import logging
from datetime import datetime, timedelta

from ..database import supabase, supabase_admin
from ..middleware.auth import get_current_user
from ..models.landlord_onboarding import LandlordOnboardingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/landlord", tags=["landlord-dashboard"])


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class LandlordProfile(BaseModel):
    id: str
    user_id: str
    full_name: str
    email: str
    phone_number: Optional[str]
    avatar_url: Optional[str]
    account_type: str
    company_name: Optional[str]
    verification_status: str
    verification_fee_paid: bool
    verification_submitted_at: Optional[datetime]
    verification_approved_at: Optional[datetime]
    trust_score: int
    onboarding_started: bool
    first_time_visit: bool
    created_at: datetime
    updated_at: datetime

class LandlordStats(BaseModel):
    total_properties: int
    active_listings: int
    pending_viewings: int
    unread_messages: int
    total_views: int
    occupancy_rate: float
    monthly_revenue: float
    avg_response_time: str
    applications_pending: int
    applications_approved: int
    properties_vacant: int
    properties_occupied: int

class LandlordProperty(BaseModel):
    id: str
    title: str
    property_type: str
    address: str
    city: str
    state: str
    price: float
    status: str
    verification_status: str
    beds: int
    baths: int
    sqft: Optional[int]
    images: List[str]
    amenities: List[str]
    created_at: datetime
    view_count: int = 0  # Map from view_count field
    application_count: int = 0  # Map from application_count field
    favorite_count: int = 0  # Will be calculated from favorites table

class RecentActivity(BaseModel):
    id: str
    type: str
    title: str
    description: str
    property_id: Optional[str]
    property_title: Optional[str]
    tenant_id: Optional[str]
    tenant_name: Optional[str]
    created_at: datetime
    read: bool

class Notification(BaseModel):
    id: str
    type: str
    title: str
    message: str
    action_url: Optional[str]
    created_at: datetime
    read: bool

class DashboardResponse(BaseModel):
    profile: LandlordProfile
    onboarding: Optional[LandlordOnboardingResponse]
    stats: LandlordStats
    properties: List[LandlordProperty]
    recent_activity: List[RecentActivity]
    notifications: List[Notification]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_landlord_profile(landlord_id: str) -> dict:
    """Get landlord profile with user data"""
    try:
        # Get user data
        user_result = supabase_admin.table("users").select("*").eq("id", landlord_id).single().execute()
        user = user_result.data if user_result.data else {}
        
        # Get landlord profile - use id as primary key, not user_id
        profile_result = supabase_admin.table("landlord_profiles").select("*").eq("id", landlord_id).single().execute()
        profile = profile_result.data if profile_result.data else {}
        
        # Combine data
        combined = {
            **user,
            **profile,
            "id": profile.get("id") or user.get("id"),
            "user_id": landlord_id,  # Add user_id for frontend compatibility
            "full_name": user.get("full_name", ""),
            "email": user.get("email", ""),
            "phone_number": user.get("phone_number"),
            "avatar_url": user.get("avatar_url"),
            "trust_score": user.get("trust_score", 50),
            # Map profile fields to expected frontend fields
            "account_type": profile.get("account_type", "individual"),
            "company_name": profile.get("company_name"),
            "verification_status": "approved" if user.get("verification_status") == "approved" else "pending",
            "verification_fee_paid": profile.get("verification_fee_paid", False),
            "verification_submitted_at": profile.get("verification_submitted_at"),
            "verification_approved_at": profile.get("verification_reviewed_at"),
            "onboarding_started": profile.get("onboarding_started", False),
            "first_time_visit": profile.get("first_time_visit", True),
            "created_at": profile.get("created_at") or user.get("created_at"),
            "updated_at": profile.get("updated_at") or user.get("updated_at")
        }
        
        return combined
    except Exception as e:
        logger.error(f"Error getting landlord profile: {str(e)}")
        # Return basic user data if profile doesn't exist
        try:
            user_result = supabase_admin.table("users").select("*").eq("id", landlord_id).single().execute()
            user = user_result.data if user_result.data else {}
            return {
                "id": user.get("id"),
                "user_id": landlord_id,
                "full_name": user.get("full_name", ""),
                "email": user.get("email", ""),
                "phone_number": user.get("phone_number"),
                "avatar_url": user.get("avatar_url"),
                "trust_score": user.get("trust_score", 50),
                "account_type": "individual",
                "company_name": None,
                "verification_status": user.get("verification_status", "pending"),
                "verification_fee_paid": False,
                "verification_submitted_at": None,
                "verification_approved_at": None,
                "onboarding_started": False,
                "first_time_visit": True,
                "created_at": user.get("created_at"),
                "updated_at": user.get("updated_at")
            }
        except:
            return {}

def calculate_landlord_stats(landlord_id: str) -> dict:
    """Calculate comprehensive landlord statistics"""
    try:
        stats = {
            "total_properties": 0,
            "active_listings": 0,
            "pending_viewings": 0,
            "unread_messages": 0,
            "total_views": 0,
            "occupancy_rate": 0.0,
            "monthly_revenue": 0.0,
            "avg_response_time": "2.5h",
            "applications_pending": 0,
            "applications_approved": 0,
            "properties_vacant": 0,
            "properties_occupied": 0
        }
        
        # Get properties
        properties_result = supabase_admin.table("properties").select("*").eq("landlord_id", landlord_id).execute()
        properties = properties_result.data or []
        
        stats["total_properties"] = len(properties)
        
        # Calculate property stats
        for prop in properties:
            if prop.get("status") == "vacant":
                stats["properties_vacant"] += 1
                stats["active_listings"] += 1
            elif prop.get("status") == "occupied":
                stats["properties_occupied"] += 1
            
            stats["total_views"] += prop.get("views_count", 0)
            stats["monthly_revenue"] += prop.get("price", 0)
        
        # Calculate occupancy rate
        if stats["total_properties"] > 0:
            stats["occupancy_rate"] = (stats["properties_occupied"] / stats["total_properties"]) * 100
        
        # Get viewing requests
        viewings_result = supabase_admin.table("viewing_requests").select("*").eq("landlord_id", landlord_id).eq("status", "pending").execute()
        stats["pending_viewings"] = len(viewings_result.data or [])
        
        # Get unread messages
        conversations_result = supabase_admin.table("conversations").select("*").eq("landlord_id", landlord_id).execute()
        conversations = conversations_result.data or []
        
        for conv in conversations:
            messages_result = supabase_admin.table("messages").select("*").eq("conversation_id", conv["id"]).eq("recipient_id", landlord_id).eq("read", False).execute()
            stats["unread_messages"] += len(messages_result.data or [])
        
        # Get applications - join through properties to get landlord's applications
        applications_result = supabase_admin.table("applications").select("*").in_("property_id", [p["id"] for p in properties]).execute()
        applications = applications_result.data or []
        
        for app in applications:
            if app.get("status") == "pending":
                stats["applications_pending"] += 1
            elif app.get("status") == "approved":
                stats["applications_approved"] += 1
        
        return stats
    except Exception as e:
        logger.error(f"Error calculating landlord stats: {str(e)}")
        return {}

def get_landlord_properties(landlord_id: str) -> List[dict]:
    """Get all properties for a landlord with complete data"""
    try:
        result = supabase_admin.table("properties").select("*").eq("landlord_id", landlord_id).order("created_at", desc=True).execute()
        properties = result.data or []
        
        # Transform properties and calculate favorite counts
        transformed_properties = []
        for prop in properties:
            # Get favorite count for this property
            favorites_result = supabase_admin.table("favorites").select("id", count="exact").eq("property_id", prop["id"]).execute()
            favorite_count = favorites_result.count if hasattr(favorites_result, 'count') and favorites_result.count is not None else 0
            
            # Transform the property data
            transformed_prop = {
                "id": prop.get("id"),
                "title": prop.get("title", ""),
                "property_type": prop.get("property_type", ""),
                "address": prop.get("address", ""),
                "city": prop.get("city", ""),
                "state": prop.get("state", ""),
                "price": prop.get("price", 0),
                "status": prop.get("status", ""),
                "verification_status": prop.get("verification_status", "pending"),
                "beds": prop.get("beds", 0),
                "baths": prop.get("baths", 0),
                "sqft": prop.get("sqft"),
                "images": prop.get("images", []),
                "amenities": prop.get("amenities", []),
                "created_at": prop.get("created_at"),
                "view_count": prop.get("view_count", 0),  # Use actual field name from database
                "application_count": prop.get("application_count", 0),  # Use actual field name from database
                "favorite_count": favorite_count  # Calculate from favorites table
            }
            transformed_properties.append(transformed_prop)
        
        return transformed_properties
    except Exception as e:
        logger.error(f"Error getting landlord properties: {str(e)}")
        return []

def get_recent_activity(landlord_id: str, limit: int = 10) -> List[dict]:
    """Get recent activity for landlord"""
    try:
        activities = []
        
        # Get landlord properties first
        properties_result = supabase_admin.table("properties").select("id").eq("landlord_id", landlord_id).execute()
        property_ids = [p["id"] for p in properties_result.data or []]
        
        if not property_ids:
            return activities
        
        # Get recent viewing requests
        viewings_result = supabase_admin.table("viewing_requests").select("*").eq("landlord_id", landlord_id).order("created_at", desc=True).limit(limit).execute()
        
        for viewing in viewings_result.data or []:
            # Get tenant info
            tenant_result = supabase_admin.table("users").select("full_name").eq("id", viewing["tenant_id"]).single().execute()
            tenant_name = tenant_result.data.get("full_name", "Unknown") if tenant_result.data else "Unknown"
            
            # Get property info
            prop_result = supabase_admin.table("properties").select("title").eq("id", viewing["property_id"]).single().execute()
            prop_title = prop_result.data.get("title", "Unknown Property") if prop_result.data else "Unknown Property"
            
            activities.append({
                "id": f"viewing_{viewing['id']}",
                "type": "viewing_request",
                "title": "New Viewing Request",
                "description": f"{tenant_name} requested to view {prop_title}",
                "property_id": viewing["property_id"],
                "property_title": prop_title,
                "tenant_id": viewing["tenant_id"],
                "tenant_name": tenant_name,
                "created_at": viewing["created_at"],
                "read": False
            })
        
        # Get recent applications - join through properties
        applications_result = supabase_admin.table("applications").select("*").in_("property_id", property_ids).order("created_at", desc=True).limit(limit).execute()
        
        for app in applications_result.data or []:
            # Get tenant info
            tenant_result = supabase_admin.table("users").select("full_name").eq("id", app["user_id"]).single().execute()
            tenant_name = tenant_result.data.get("full_name", "Unknown") if tenant_result.data else "Unknown"
            
            # Get property info
            prop_result = supabase_admin.table("properties").select("title").eq("id", app["property_id"]).single().execute()
            prop_title = prop_result.data.get("title", "Unknown Property") if prop_result.data else "Unknown Property"
            
            activities.append({
                "id": f"application_{app['id']}",
                "type": "application",
                "title": "New Application Received",
                "description": f"{tenant_name} applied for {prop_title}",
                "property_id": app["property_id"],
                "property_title": prop_title,
                "tenant_id": app["user_id"],
                "tenant_name": tenant_name,
                "created_at": app["created_at"],
                "read": False
            })
        
        # Sort by date and limit
        activities.sort(key=lambda x: x["created_at"], reverse=True)
        return activities[:limit]
    except Exception as e:
        logger.error(f"Error getting recent activity: {str(e)}")
        return []

def get_notifications(landlord_id: str) -> List[dict]:
    """Get notifications for landlord"""
    try:
        result = supabase_admin.table("notifications").select("*").eq("user_id", landlord_id).order("created_at", desc=True).limit(20).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Error getting notifications: {str(e)}")
        return []


# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.get("/dashboard", response_model=DashboardResponse)
async def get_landlord_dashboard(
    current_user = Depends(get_current_user)
):
    """Get comprehensive landlord dashboard data"""
    print(f"\n✅ [LANDLORD DASHBOARD] Fetching dashboard for user: {current_user['id']}")
    
    try:
        landlord_id = current_user['id']
        
        # Verify user is a landlord
        if current_user.get('user_type') != 'landlord':
            raise HTTPException(status_code=403, detail="Access denied. Landlord access required.")
        
        # Get all dashboard data
        profile_data = get_landlord_profile(landlord_id)
        stats_data = calculate_landlord_stats(landlord_id)
        properties_data = get_landlord_properties(landlord_id)
        activity_data = get_recent_activity(landlord_id)
        notifications_data = get_notifications(landlord_id)
        
        # Get onboarding data
        onboarding_data = None
        onboarding_result = supabase_admin.table("landlord_onboarding").select("*").eq("landlord_id", landlord_id).single().execute()
        if onboarding_result.data:
            onboarding_data = onboarding_result.data
        
        # Build response
        dashboard_data = {
            "profile": profile_data,
            "onboarding": onboarding_data,
            "stats": stats_data,
            "properties": properties_data,
            "recent_activity": activity_data,
            "notifications": notifications_data
        }
        
        print(f"✅ [LANDLORD DASHBOARD] Dashboard data retrieved successfully")
        return dashboard_data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [LANDLORD DASHBOARD] Error fetching dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profile")
async def get_landlord_profile_only(
    current_user = Depends(get_current_user)
):
    """Get landlord profile information"""
    try:
        landlord_id = current_user['id']
        
        if current_user.get('user_type') != 'landlord':
            raise HTTPException(status_code=403, detail="Access denied. Landlord access required.")
        
        profile_data = get_landlord_profile(landlord_id)
        
        if not profile_data:
            raise HTTPException(status_code=404, detail="Landlord profile not found")
        
        return {"profile": profile_data}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching landlord profile: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/onboarding")
async def get_landlord_onboarding_status(
    current_user = Depends(get_current_user)
):
    """Get landlord onboarding status"""
    try:
        landlord_id = current_user['id']
        
        if current_user.get('user_type') != 'landlord':
            raise HTTPException(status_code=403, detail="Access denied. Landlord access required.")
        
        result = supabase_admin.table("landlord_onboarding").select("*").eq("landlord_id", landlord_id).single().execute()
        
        if not result.data:
            return {"onboarding": None}
        
        return {"onboarding": result.data}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching onboarding status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_landlord_statistics(
    current_user = Depends(get_current_user)
):
    """Get landlord statistics"""
    try:
        landlord_id = current_user['id']
        
        if current_user.get('user_type') != 'landlord':
            raise HTTPException(status_code=403, detail="Access denied. Landlord access required.")
        
        stats_data = calculate_landlord_stats(landlord_id)
        
        return {"stats": stats_data}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching landlord stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/properties")
async def get_landlord_properties_list(
    current_user = Depends(get_current_user)
):
    """Get landlord properties"""
    try:
        landlord_id = current_user['id']
        
        if current_user.get('user_type') != 'landlord':
            raise HTTPException(status_code=403, detail="Access denied. Landlord access required.")
        
        properties_data = get_landlord_properties(landlord_id)
        
        return {"properties": properties_data}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching landlord properties: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/activity")
async def get_landlord_activity(
    limit: int = Query(10, le=50),
    current_user = Depends(get_current_user)
):
    """Get recent activity for landlord"""
    try:
        landlord_id = current_user['id']
        
        if current_user.get('user_type') != 'landlord':
            raise HTTPException(status_code=403, detail="Access denied. Landlord access required.")
        
        activity_data = get_recent_activity(landlord_id, limit)
        
        return {"activity": activity_data}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching recent activity: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications")
async def get_landlord_notifications(
    current_user = Depends(get_current_user)
):
    """Get notifications for landlord"""
    try:
        landlord_id = current_user['id']
        
        if current_user.get('user_type') != 'landlord':
            raise HTTPException(status_code=403, detail="Access denied. Landlord access required.")
        
        notifications_data = get_notifications(landlord_id)
        
        return {"notifications": notifications_data}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching notifications: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/notifications/{notification_id}/read")
async def mark_notification_as_read(
    notification_id: str,
    current_user = Depends(get_current_user)
):
    """Mark notification as read"""
    try:
        landlord_id = current_user['id']
        
        if current_user.get('user_type') != 'landlord':
            raise HTTPException(status_code=403, detail="Access denied. Landlord access required.")
        
        # Update notification
        result = supabase_admin.table("notifications").update({"read": True}).eq("id", notification_id).eq("user_id", landlord_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        return {"success": True, "message": "Notification marked as read"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking notification as read: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
