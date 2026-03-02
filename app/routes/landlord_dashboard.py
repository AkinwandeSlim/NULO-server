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

# 🚀 OPTIMIZATION: Simple in-memory cache for dashboard data (2 minute TTL)
# Reduced from 5 minutes to 2 minutes for fresher data but still fast responses
_dashboard_cache = {}
CACHE_TTL = 300  # 5 minutes


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
    link: Optional[str]  # Changed from action_url to link to match database
    read: bool
    read_at: Optional[datetime]
    data: Optional[dict]
    user_id: str
    created_at: datetime

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
    """Get landlord profile with user data - OPTIMIZED with parallel query setup"""
    try:
        # 🚀 OPTIMIZATION: Get both user and profile data with minimal fields needed
        user_result = supabase_admin.table("users").select("id, full_name, email, phone_number, avatar_url, trust_score, verification_status, created_at, updated_at").eq("id", landlord_id).single().execute()
        user = user_result.data if user_result.data else {}
        
        # Get landlord profile - use id as primary key
        profile_result = supabase_admin.table("landlord_profiles").select("*").eq("id", landlord_id).single().execute()
        profile = profile_result.data if profile_result.data else {}
        
        # Combine data efficiently
        combined = {
            **user,
            **profile,
            "id": profile.get("id") or user.get("id"),
            "user_id": landlord_id,
            "full_name": user.get("full_name", ""),
            "email": user.get("email", ""),
            "phone_number": user.get("phone_number"),
            "avatar_url": user.get("avatar_url"),
            "trust_score": user.get("trust_score", 50),
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
            user_result = supabase_admin.table("users").select("id, full_name, email, phone_number, avatar_url, trust_score, verification_status, created_at, updated_at").eq("id", landlord_id).single().execute()
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
        except Exception as fallback_err:
            # Both DB calls timed out. Return a safe skeleton so Pydantic never
            # sees {} and the dashboard renders a degraded-but-working state.
            logger.error(f"Profile fallback also failed: {str(fallback_err)}")
            now = datetime.utcnow().isoformat()
            return {
                "id": landlord_id,
                "user_id": landlord_id,
                "full_name": "Unknown",
                "email": "",
                "phone_number": None,
                "avatar_url": None,
                "trust_score": 50,
                "account_type": "individual",
                "company_name": None,
                "verification_status": "pending",
                "verification_fee_paid": False,
                "verification_submitted_at": None,
                "verification_approved_at": None,
                "onboarding_started": False,
                "first_time_visit": True,
                "created_at": now,
                "updated_at": now,
            }

def calculate_landlord_stats(landlord_id: str) -> dict:
    """
    Calculate landlord statistics with per-query fault isolation.

    Each Supabase call has its own try/except so a timeout on one query
    (e.g. messages) never zeros out the others (e.g. properties).

    Returns a _fetch_failed flag so the caller knows not to cache the result
    when any query failed -- prevents zeros being cached for 5 minutes.
    """
    stats = {
        "total_properties": 0,
        "properties_vacant": 0,
        "properties_occupied": 0,
        "active_listings": 0,
        "pending_viewings": 0,
        "unread_messages": 0,
        "applications_pending": 0,
        "applications_approved": 0,
        "total_views": 0,
        "monthly_revenue": 0.0,
        "occupancy_rate": 0.0,
        "avg_response_time": "0 hours",
        # Internal flag -- stripped before returning to caller if all OK.
        # Set True if any sub-query fails so the dashboard knows not to cache.
        "_fetch_failed": False,
    }

    # ── Query 1: Properties (most important) ────────────────────────────────
    try:
        properties_result = supabase_admin.table("properties") \
            .select("id, status, view_count, price") \
            .eq("landlord_id", landlord_id).execute()
        properties = properties_result.data or []

        stats["total_properties"] = len(properties)
        for prop in properties:
            if prop.get("status") == "vacant":
                stats["properties_vacant"] += 1
                stats["active_listings"] += 1
            elif prop.get("status") == "occupied":
                stats["properties_occupied"] += 1
            stats["total_views"] += prop.get("view_count", 0)
            stats["monthly_revenue"] += float(prop.get("price", 0))

        if stats["total_properties"] > 0:
            stats["occupancy_rate"] = (
                stats["properties_occupied"] / stats["total_properties"]
            ) * 100
    except Exception as e:
        logger.error(f"Stats query failed (properties): {e}")
        stats["_fetch_failed"] = True

    # ── Query 2: Pending viewings ────────────────────────────────────────────
    try:
        vr = supabase_admin.table("viewing_requests") \
            .select("id") \
            .eq("landlord_id", landlord_id) \
            .eq("status", "pending").execute()
        stats["pending_viewings"] = len(vr.data or [])
    except Exception as e:
        logger.error(f"Stats query failed (viewings): {e}")
        stats["_fetch_failed"] = True

    # ── Query 3: Unread messages ─────────────────────────────────────────────
    try:
        msgs = supabase_admin.table("messages") \
            .select("id") \
            .eq("recipient_id", landlord_id) \
            .eq("read", False).execute()
        stats["unread_messages"] = len(msgs.data or [])
    except Exception as e:
        logger.error(f"Stats query failed (messages): {e}")
        stats["_fetch_failed"] = True

    # ── Query 4: Applications ────────────────────────────────────────────────
    try:
        apps = supabase_admin.table("applications") \
            .select("id, status") \
            .eq("landlord_id", landlord_id).execute()
        for app in (apps.data or []):
            if app.get("status") == "pending":
                stats["applications_pending"] += 1
            elif app.get("status") == "approved":
                stats["applications_approved"] += 1
    except Exception as e:
        logger.error(f"Stats query failed (applications): {e}")
        # Non-fatal -- applications table may not have landlord_id column yet
        # Don't mark _fetch_failed for this one

    return stats

def get_landlord_properties(landlord_id: str) -> List[dict]:
    """Get all properties for a landlord with complete data - OPTIMIZED"""
    try:
        # 🚀 OPTIMIZATION: Get properties in one query
        result = supabase_admin.table("properties").select("*").eq("landlord_id", landlord_id).order("created_at", desc=True).execute()
        properties = result.data or []
        
        if not properties:
            return []
        
        # 🚀 OPTIMIZATION: Get ALL favorite counts in one batch query instead of one per property
        property_ids = [p["id"] for p in properties]
        favorites_result = supabase_admin.table("favorites").select("property_id", count="exact").in_("property_id", property_ids).execute()
        
        # Build favorite count map
        favorite_counts = {}
        if favorites_result.data:
            # Group by property_id and count occurrences
            for fav in favorites_result.data:
                prop_id = fav["property_id"]
                favorite_counts[prop_id] = favorite_counts.get(prop_id, 0) + 1
        
        # Transform properties
        transformed_properties = []
        for prop in properties:
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
                "view_count": prop.get("view_count", 0),
                "application_count": prop.get("application_count", 0),
                "favorite_count": favorite_counts.get(prop["id"], 0)  # Use pre-calculated counts
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
        
        # Get recent viewing requests with minimal data
        viewings_result = supabase_admin.table("viewing_requests").select("id, tenant_id, property_id, created_at").eq("landlord_id", landlord_id).order("created_at", desc=True).limit(limit).execute()
        
        # Batch fetch tenant and property data to reduce queries
        tenant_ids = list(set([v["tenant_id"] for v in viewings_result.data or []]))
        property_ids = list(set([v["property_id"] for v in viewings_result.data or []]))
        
        tenants = {}
        properties = {}
        
        if tenant_ids:
            tenants_result = supabase_admin.table("users").select("id, full_name").in_("id", tenant_ids).execute()
            tenants = {t["id"]: t["full_name"] for t in tenants_result.data or []}
        
        if property_ids:
            props_result = supabase_admin.table("properties").select("id, title").in_("id", property_ids).execute()
            properties = {p["id"]: p["title"] for p in props_result.data or []}
        
        for viewing in viewings_result.data or []:
            tenant_name = tenants.get(viewing["tenant_id"], "Unknown")
            prop_title = properties.get(viewing["property_id"], "Unknown Property")
            
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
        
        # Get recent applications with optimized queries
        applications_result = supabase_admin.table("applications").select("id, user_id, property_id, created_at").in_("property_id", property_ids).order("created_at", desc=True).limit(limit).execute()
        
        for app in applications_result.data or []:
            tenant_name = tenants.get(app["user_id"], "Unknown")
            prop_title = properties.get(app["property_id"], "Unknown Property")
            
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
        
        # 🚀 OPTIMIZATION: Check cache first
        cache_key = f"dashboard_{landlord_id}"
        if cache_key in _dashboard_cache:
            cached_data, cache_time = _dashboard_cache[cache_key]
            if datetime.now().timestamp() - cache_time < CACHE_TTL:
                print(f"💾 [LANDLORD DASHBOARD] Cache hit - returning cached data")
                return cached_data
            else:
                # Cache expired, remove it
                del _dashboard_cache[cache_key]
        
        print(f"🔄 [LANDLORD DASHBOARD] Cache miss or expired - fetching fresh data")
        
        # 🚀 PARALLEL FETCH: Run all Supabase calls concurrently via thread pool.
        # Previously sequential → 10+ round trips × 500-1500ms each = 10-15s total.
        # Now parallel → slowest single call determines total time = ~2-4s.
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        def fetch_onboarding():
            try:
                result = supabase_admin.table("landlord_onboarding").select("*").eq("landlord_id", landlord_id).single().execute()
                return result.data if result.data else None
            except Exception as e:
                logger.error(f"Failed to get onboarding: {str(e)}")
                return None

        def fetch_stats():
            try:
                result = calculate_landlord_stats(landlord_id)
                # _fetch_failed is an internal signal -- strip it so Pydantic
                # never sees it, but first record it for the cache decision below.
                fetch_stats._failed = result.pop("_fetch_failed", False)
                return result
            except Exception as e:
                logger.error(f"Failed to calculate stats: {str(e)}")
                fetch_stats._failed = True
                return {
                    "total_properties": 0, "active_listings": 0, "pending_viewings": 0,
                    "unread_messages": 0, "total_views": 0, "occupancy_rate": 0.0,
                    "monthly_revenue": 0.0, "avg_response_time": "0 hours",
                    "applications_pending": 0, "applications_approved": 0,
                    "properties_vacant": 0, "properties_occupied": 0,
                }
        fetch_stats._failed = False  # default

        def fetch_properties():
            try:
                return get_landlord_properties(landlord_id)
            except Exception as e:
                logger.error(f"Failed to get properties: {str(e)}")
                return []

        def fetch_activity():
            try:
                return get_recent_activity(landlord_id)
            except Exception as e:
                logger.error(f"Failed to get activity: {str(e)}")
                return []

        def fetch_notifications():
            try:
                return get_notifications(landlord_id)
            except Exception as e:
                logger.error(f"Failed to get notifications: {str(e)}")
                return []

        # profile is needed to build the response model -- fetch first if not cached
        try:
            profile_data = get_landlord_profile(landlord_id)
        except Exception as e:
            logger.error(f"Failed to get profile: {str(e)}")
            # get_landlord_profile already returns a safe skeleton on timeout,
            # but if it throws instead, build the fallback here too.
            now = datetime.utcnow().isoformat()
            profile_data = {
                "id": landlord_id,
                "user_id": landlord_id,
                "full_name": "Unknown",
                "email": "",
                "phone_number": None,
                "avatar_url": None,
                "trust_score": 50,
                "account_type": "individual",
                "company_name": None,
                "verification_status": "pending",
                "verification_fee_paid": False,
                "verification_submitted_at": None,
                "verification_approved_at": None,
                "onboarding_started": False,
                "first_time_visit": True,
                "created_at": now,
                "updated_at": now,
            }

        # Run remaining 5 fetches in parallel
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                loop.run_in_executor(executor, fetch_onboarding),
                loop.run_in_executor(executor, fetch_stats),
                loop.run_in_executor(executor, fetch_properties),
                loop.run_in_executor(executor, fetch_activity),
                loop.run_in_executor(executor, fetch_notifications),
            ]
            results = await asyncio.gather(*futures)

        onboarding_data, stats_data, properties_data, activity_data, notifications_data = results
        print(f"✅ [LANDLORD DASHBOARD] All parallel fetches complete")

        
        # Build response
        dashboard_data = {
            "profile": profile_data,
            "onboarding": onboarding_data,
            "stats": stats_data,
            "properties": properties_data,
            "recent_activity": activity_data,
            "notifications": notifications_data
        }
        
        # Only cache when stats fetched cleanly -- never cache a degraded response
        # with zeros caused by timeouts, or the zeros persist for CACHE_TTL seconds.
        if not fetch_stats._failed:
            _dashboard_cache[cache_key] = (dashboard_data, datetime.now().timestamp())
            print(f"✅ [LANDLORD DASHBOARD] Dashboard data cached successfully")
        else:
            print(f"⚠️ [LANDLORD DASHBOARD] Stats fetch had failures -- skipping cache so next request retries")

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