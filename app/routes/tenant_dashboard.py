"""
Tenant Dashboard API Routes
Provides comprehensive dashboard data for tenants with bundled data fetching
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from uuid import UUID
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from ..database import supabase, supabase_admin
from ..middleware.auth import get_current_user
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenant", tags=["tenant-dashboard"])

CACHE_TTL = 300  # 5 minutes


# ============================================================================
# PYDANTIC MODELS 
# All fixed
# ============================================================================

class TenantStats(BaseModel):
    totalFavorites: int
    pendingViewings: int
    confirmedViewings: int
    completedViewings: int
    propertiesContacted: int
    totalConversations: int
    unreadMessages: int
    applicationsSubmitted: int
    pendingApplications: int
    approvedApplications: int
    rejectedApplications: int
    activeAgreements: int
    pendingSignatures: int
    paymentsDue: int
    totalPayments: int
    completedPayments: int
    engagementScore: int
    trustScore: int
    engagementLevel: str


class TenantFavorite(BaseModel):
    id: str
    property_id: str
    property_title: Optional[str]
    property_address: Optional[str]
    property_city: Optional[str]
    property_image: Optional[str]
    price: Optional[int]
    beds: Optional[int]
    baths: Optional[int]
    created_at: str


class TenantViewingRequest(BaseModel):
    id: str
    property_id: str
    property_title: str
    property_address: str
    landlord_id: str
    landlord_name: str
    status: str
    preferred_date: Optional[str]
    confirmed_date: Optional[str]
    time_slot: Optional[str]
    confirmed_time: Optional[str]
    viewing_type: str
    created_at: str
    updated_at: str


class TenantConversation(BaseModel):
    id: str
    property_id: Optional[str]
    property_title: Optional[str]
    other_user_id: str
    other_user_name: str
    other_user_avatar: Optional[str]
    last_message: Optional[str]
    last_message_time: str
    unread_count: int
    created_at: str
    updated_at: str


class TenantApplication(BaseModel):
    id: str
    property_id: str
    property_title: Optional[str]
    property_location: Optional[str]
    property_price: Optional[int]
    status: str
    move_in_date: Optional[str]
    created_at: str
    viewed_by_landlord: bool


class TenantAgreement(BaseModel):
    id: str
    property_id: str
    property_title: Optional[str]
    landlord_id: str
    landlord_name: str
    rent_amount: int
    deposit_amount: int
    status: str
    lease_start_date: Optional[str]
    lease_end_date: Optional[str]
    created_at: str
    updated_at: str


class TenantDashboardResponse(BaseModel):
    stats: TenantStats
    favorites: List[TenantFavorite] = []
    viewing_requests: List[TenantViewingRequest] = []
    conversations: List[TenantConversation] = []
    applications: List[TenantApplication] = []
    agreements: List[TenantAgreement] = []


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_tenant_stats(tenant_id: str) -> dict:
    """Calculate tenant statistics with per-query fault isolation"""
    stats = {
        "totalFavorites": 0,
        "pendingViewings": 0,
        "confirmedViewings": 0,
        "propertiesContacted": 0,
        "totalConversations": 0,
        "unreadMessages": 0,
        "applicationsSubmitted": 0,
        "pendingApplications": 0,
        "approvedApplications": 0,
        "rejectedApplications": 0,
        "activeAgreements": 0,
        "pendingSignatures": 0,
        "paymentsDue": 0,
        "totalPayments": 0,
        "completedPayments": 0,
        "engagementScore": 0,
        "trustScore": 50,
        "engagementLevel": "none",
        "_fetch_failed": False,
    }

    try:
        result = supabase_admin.table("favorites") \
            .select("id") \
            .eq("tenant_id", tenant_id).execute()
        stats["totalFavorites"] = len(result.data or [])
        logger.info(f"Total favorites for {tenant_id}: {stats['totalFavorites']}")
    except Exception as e:
        logger.error(f"Stats query failed (favorites): {e}")
        stats["_fetch_failed"] = True

    try:
        pending = supabase_admin.table("viewing_requests") \
            .select("id") \
            .eq("tenant_id", tenant_id) \
            .eq("status", "pending").execute()
        stats["pendingViewings"] = len(pending.data or [])
    except Exception as e:
        logger.error(f"Stats query failed (pending viewings): {e}")
        stats["_fetch_failed"] = True

    try:
        confirmed = supabase_admin.table("viewing_requests") \
            .select("id") \
            .eq("tenant_id", tenant_id) \
            .eq("status", "confirmed").execute()
        stats["confirmedViewings"] = len(confirmed.data or [])
    except Exception as e:
        logger.error(f"Stats query failed (confirmed viewings): {e}")
        stats["_fetch_failed"] = True

    try:
        completed = supabase_admin.table("viewing_requests") \
            .select("id") \
            .eq("tenant_id", tenant_id) \
            .eq("status", "completed").execute()
        stats["completedViewings"] = len(completed.data or [])
    except Exception as e:
        logger.error(f"Stats query failed (completed viewings): {e}")
        stats["completedViewings"] = 0  # Default value on error
        stats["_fetch_failed"] = True

    try:
        conversations = supabase_admin.table("conversations") \
            .select("id, property_id") \
            .eq("tenant_id", tenant_id).execute()
        stats["totalConversations"] = len(conversations.data or [])
        
        # Calculate propertiesContacted as unique properties from all forms of engagement:
        # Conversations (messages with landlord) + Viewing Requests (viewed/scheduled viewings) + Applications (applied to lease)
        properties_contacted = set()
        
        # Add properties from conversations
        for conv in (conversations.data or []):
            if conv.get("property_id"):
                properties_contacted.add(conv.get("property_id"))
        
        # Add properties from viewing requests
        viewing_reqs = supabase_admin.table("viewing_requests") \
            .select("property_id") \
            .eq("tenant_id", tenant_id).execute()
        for vr in (viewing_reqs.data or []):
            if vr.get("property_id"):
                properties_contacted.add(vr.get("property_id"))
        
        # Add properties from applications (strongest engagement - actual applications)
        applications = supabase_admin.table("applications") \
            .select("property_id") \
            .eq("user_id", tenant_id).execute()
        for app in (applications.data or []):
            if app.get("property_id"):
                properties_contacted.add(app.get("property_id"))
        
        stats["propertiesContacted"] = len(properties_contacted)
        logger.info(f"Properties contacted: {stats['propertiesContacted']} (from conversations + viewing requests + applications)")
    except Exception as e:
        logger.error(f"Stats query failed (conversations/properties contacted): {e}")
        stats["_fetch_failed"] = True

    try:
        unread = supabase_admin.table("messages") \
            .select("id") \
            .eq("recipient_id", tenant_id) \
            .eq("read", False).execute()
        stats["unreadMessages"] = len(unread.data or [])
    except Exception as e:
        logger.error(f"Stats query failed (unread messages): {e}")
        stats["_fetch_failed"] = True

    try:
        apps = supabase_admin.table("applications") \
            .select("id, status") \
            .eq("user_id", tenant_id).execute()
        stats["applicationsSubmitted"] = len(apps.data or [])
        for app in (apps.data or []):
            if app.get("status") == "pending":
                stats["pendingApplications"] += 1
            elif app.get("status") == "approved":
                stats["approvedApplications"] += 1
            elif app.get("status") == "rejected":
                stats["rejectedApplications"] += 1
    except Exception as e:
        logger.error(f"Stats query failed (applications): {e}")
        stats["_fetch_failed"] = True

    try:
        agreements = supabase_admin.table("agreements") \
            .select("id, status") \
            .eq("tenant_id", tenant_id).execute()
        for agreement in (agreements.data or []):
            if agreement.get("status") in ["ACTIVE", "SIGNED"]:
                stats["activeAgreements"] += 1
            elif agreement.get("status") == "PENDING_TENANT":
                stats["pendingSignatures"] += 1
    except Exception as e:
        logger.error(f"Stats query failed (agreements): {e}")
        stats["_fetch_failed"] = True

    # Calculate payment statistics from transactions table (rent payments)
    try:
        from datetime import date, timedelta
        import datetime as dt
        current_year = dt.datetime.now().year
        
        # Query all transactions for this tenant in current year
        transactions = supabase_admin.table("transactions") \
            .select("id, amount, status, created_at") \
            .eq("tenant_id", tenant_id) \
            .gte("created_at", f"{current_year}-01-01") \
            .lte("created_at", f"{current_year}-12-31").execute()
        
        if transactions.data:
            stats["totalPayments"] = len(transactions.data)
            completed = [t for t in transactions.data if t.get("status") == "completed"]
            stats["completedPayments"] = len(completed)
            stats["paymentsDue"] = len([t for t in transactions.data if t.get("status") in ["pending", "processing"]])
    except Exception as e:
        logger.error(f"Stats query failed (payments): {e}")
        # Don't set _fetch_failed for payments - it's optional data
        pass

    try:
        user = supabase_admin.table("users") \
            .select("trust_score") \
            .eq("id", tenant_id).single().execute()
        if user.data:
            stats["trustScore"] = user.data.get("trust_score", 50)
    except Exception as e:
        logger.error(f"Stats query failed (trust score): {e}")

    # Calculate engagement score from actual user activity
    # The user_engagement_metrics table is initialized with zeros and never updated,
    # so we compute engagement from actual activity tables
    try:
        activity_score = 0
        
        # Count favorites (saved properties) - indicates interest
        try:
            favs = supabase_admin.table("favorites") \
                .select("id") \
                .eq("tenant_id", tenant_id).execute()
            favorites_count = len(favs.data or [])
            activity_score += favorites_count * 3  # High weight
            logger.info(f"📌 Favorites: {favorites_count}")
        except Exception as e:
            logger.error(f"Failed to count favorites: {e}")
            favorites_count = 0
        
        # Count viewing requests confirmed/pending
        try:
            viewings = supabase_admin.table("viewing_requests") \
                .select("id") \
                .eq("tenant_id", tenant_id).execute()
            viewings_count = len(viewings.data or [])
            activity_score += viewings_count * 4  # Highest weight - shows active interest
            logger.info(f"👁️ Viewing Requests: {viewings_count}")
        except Exception as e:
            logger.error(f"Failed to count viewings: {e}")
            viewings_count = 0
        
        # Count messages sent by tenant
        try:
            messages = supabase_admin.table("messages") \
                .select("id") \
                .eq("sender_id", tenant_id).execute()
            messages_count = len(messages.data or [])
            activity_score += messages_count * 2  # Medium weight
            logger.info(f"💬 Messages Sent: {messages_count}")
        except Exception as e:
            logger.error(f"Failed to count messages: {e}")
            messages_count = 0
        
        # Count conversations initiated/active
        try:
            conversations = supabase_admin.table("conversations") \
                .select("id") \
                .eq("tenant_id", tenant_id).execute()
            conversations_count = len(conversations.data or [])
            activity_score += conversations_count * 2
            logger.info(f"🗨️ Conversations: {conversations_count}")
        except Exception as e:
            logger.error(f"Failed to count conversations: {e}")
            conversations_count = 0
        
        # Count applications submitted
        try:
            applications = supabase_admin.table("applications") \
                .select("id") \
                .eq("user_id", tenant_id).execute()
            applications_count = len(applications.data or [])
            activity_score += applications_count * 3  # High weight - shows commitment
            logger.info(f"📄 Applications: {applications_count}")
        except Exception as e:
            logger.error(f"Failed to count applications: {e}")
            applications_count = 0
        
        # Normalize engagement score to 0-100 with natural scaling
        # activity_score can be: 
        #   0 (no activity) = 0/100
        #   5-10 (some interest) = 25-50/100
        #   15+ (active) = 70-100/100
        stats["engagementScore"] = min(100, max(0, activity_score * 2))
        logger.info(f"📊 Engagement Score Calculation: activity_score={activity_score}, final_score={stats['engagementScore']}")
        
        # Determine engagement level based on calculated score
        if stats["engagementScore"] >= 70:
            stats["engagementLevel"] = "high"
        elif stats["engagementScore"] >= 40:
            stats["engagementLevel"] = "medium"
        else:
            stats["engagementLevel"] = "low"
        
        logger.info(f"✅ Engagement Level: {stats['engagementLevel']} (Score: {stats['engagementScore']}/100)")
    except Exception as e:
        logger.error(f"Stats query failed (engagement): {e}")
        logger.error(f"Full error details: {str(e)}")
        stats["engagementScore"] = 0
        stats["engagementLevel"] = "low"
        # Don't mark as failed - engagement metrics are derived, not critical

    return stats


def fetch_favorites(tenant_id: str) -> List[dict]:
    """Fetch tenant favorites with property details"""
    try:
        result = supabase_admin.table("favorites") \
            .select("id, property_id, created_at") \
            .eq("tenant_id", tenant_id) \
            .order("created_at", desc=True) \
            .limit(100).execute()
        
        if not result.data:
            logger.warning(f"No favorites found for user {tenant_id}")
            return []
        
        favorites = []
        # Get property details for each favorite
        property_ids = [f.get("property_id") for f in result.data]
        if property_ids:
            props = supabase_admin.table("properties") \
                .select("id, title, address, city, price, beds, baths, images") \
                .in_("id", property_ids).execute()
            prop_map = {p["id"]: p for p in (props.data or [])}
            
            for fav in result.data:
                prop = prop_map.get(fav.get("property_id"), {})
                images = prop.get("images") or []
                property_image = images[0] if images else None
                favorites.append({
                    "id": fav.get("id"),
                    "property_id": fav.get("property_id"),
                    "property_title": prop.get("title"),
                    "property_address": prop.get("address"),
                    "property_city": prop.get("city"),
                    "price": prop.get("price"),
                    "beds": prop.get("beds"),
                    "baths": prop.get("baths"),
                    "property_image": property_image,
                    "created_at": fav.get("created_at")
                })
        
        logger.info(f"Fetched {len(favorites)} favorites for user {tenant_id}")
        return favorites
    except Exception as e:
        logger.error(f"Failed to fetch favorites for {tenant_id}: {str(e)}")
        return []


def fetch_viewing_requests(tenant_id: str) -> List[dict]:
    """Fetch tenant viewing requests with property and landlord details"""
    try:
        result = supabase_admin.table("viewing_requests") \
            .select(
                "id, property_id, landlord_id, status, preferred_date, confirmed_date, "
                "confirmed_time, time_slot, viewing_type, created_at, updated_at"
            ) \
            .eq("tenant_id", tenant_id) \
            .order("created_at", desc=True).execute()
        
        if not result.data:
            logger.warning(f"No viewing requests found for user {tenant_id}")
            return []
        
        viewings = []
        # Get property and landlord details
        property_ids = [v.get("property_id") for v in result.data if v.get("property_id")]
        landlord_ids = [v.get("landlord_id") for v in result.data if v.get("landlord_id")]
        
        prop_map = {}
        landlord_map = {}
        
        if property_ids:
            props = supabase_admin.table("properties") \
                .select("id, title, address") \
                .in_("id", property_ids).execute()
            prop_map = {p["id"]: p for p in (props.data or [])}
        
        if landlord_ids:
            landlords = supabase_admin.table("users") \
                .select("id, full_name") \
                .in_("id", landlord_ids).execute()
            landlord_map = {u["id"]: u for u in (landlords.data or [])}
        
        for vr in result.data:
            prop = prop_map.get(vr.get("property_id"), {})
            landlord = landlord_map.get(vr.get("landlord_id"), {})
            viewings.append({
                "id": vr.get("id"),
                "property_id": vr.get("property_id"),
                "property_title": prop.get("title"),
                "property_address": prop.get("address"),
                "landlord_id": vr.get("landlord_id"),
                "landlord_name": landlord.get("full_name"),
                "status": vr.get("status"),
                "preferred_date": vr.get("preferred_date"),
                "confirmed_date": vr.get("confirmed_date"),
                "time_slot": vr.get("time_slot"),
                "confirmed_time": vr.get("confirmed_time"),
                "viewing_type": vr.get("viewing_type"),
                "created_at": vr.get("created_at"),
                "updated_at": vr.get("updated_at")
            })
        
        logger.info(f"Fetched {len(viewings)} viewing requests for user {tenant_id}")
        return viewings
    except Exception as e:
        logger.error(f"Failed to fetch viewing requests for {tenant_id}: {str(e)}")
        return []


def fetch_conversations(tenant_id: str) -> List[dict]:
    """Fetch tenant conversations"""
    try:
        result = supabase_admin.table("conversations") \
            .select(
                "id, property_id, landlord_id, last_message, last_message_at, "
                "created_at, updated_at"
            ) \
            .eq("tenant_id", tenant_id) \
            .order("updated_at", desc=True).execute()
        
        if not result.data:
            logger.warning(f"No conversations found for user {tenant_id}")
            return []
        
        conversations = []
        # Get property and landlord details
        property_ids = [c.get("property_id") for c in result.data if c.get("property_id")]
        landlord_ids = [c.get("landlord_id") for c in result.data if c.get("landlord_id")]
        
        prop_map = {}
        landlord_map = {}
        
        if property_ids:
            props = supabase_admin.table("properties") \
                .select("id, title") \
                .in_("id", property_ids).execute()
            prop_map = {p["id"]: p for p in (props.data or [])}
        
        if landlord_ids:
            landlords = supabase_admin.table("users") \
                .select("id, full_name, avatar_url") \
                .in_("id", landlord_ids).execute()
            landlord_map = {u["id"]: u for u in (landlords.data or [])}
        
        for conv in result.data:
            prop = prop_map.get(conv.get("property_id"), {})
            landlord = landlord_map.get(conv.get("landlord_id"), {})
            conversations.append({
                "id": conv.get("id"),
                "property_id": conv.get("property_id"),
                "property_title": prop.get("title"),
                "other_user_id": conv.get("landlord_id"),
                "other_user_name": landlord.get("full_name"),
                "other_user_avatar": landlord.get("avatar_url"),
                "last_message": conv.get("last_message"),
                "last_message_time": conv.get("last_message_at") or conv.get("updated_at"),
                "unread_count": 0,  # No unread_count column in conversations table
                "created_at": conv.get("created_at"),
                "updated_at": conv.get("updated_at")
            })
        
        logger.info(f"Fetched {len(conversations)} conversations for user {tenant_id}")
        return conversations
    except Exception as e:
        logger.error(f"Failed to fetch conversations for {tenant_id}: {str(e)}")
        return []


def fetch_applications(tenant_id: str) -> List[dict]:
    """Fetch tenant applications"""
    try:
        result = supabase_admin.table("applications") \
            .select(
                "id, property_id, status, move_in_date, created_at, viewed_by_landlord"
            ) \
            .eq("user_id", tenant_id) \
            .order("created_at", desc=True).execute()
        
        if not result.data:
            logger.warning(f"No applications found for user {tenant_id}")
            return []
        
        applications = []
        # Get property details
        property_ids = [a.get("property_id") for a in result.data if a.get("property_id")]
        prop_map = {}
        
        if property_ids:
            props = supabase_admin.table("properties") \
                .select("id, title, location, price") \
                .in_("id", property_ids).execute()
            prop_map = {p["id"]: p for p in (props.data or [])}
        
        for app in result.data:
            prop = prop_map.get(app.get("property_id"), {})
            applications.append({
                "id": app.get("id"),
                "property_id": app.get("property_id"),
                "property_title": prop.get("title"),
                "property_location": prop.get("location"),
                "property_price": prop.get("price"),
                "status": app.get("status"),
                "move_in_date": app.get("move_in_date"),
                "created_at": app.get("created_at"),
                "viewed_by_landlord": app.get("viewed_by_landlord", False)
            })
        
        logger.info(f"Fetched {len(applications)} applications for user {tenant_id}")
        return applications
    except Exception as e:
        logger.error(f"Failed to fetch applications for {tenant_id}: {str(e)}")
        return []


def fetch_agreements(tenant_id: str) -> List[dict]:
    """Fetch tenant agreements"""
    try:
        result = supabase_admin.table("agreements") \
            .select(
                "id, property_id, landlord_id, rent_amount, deposit_amount, status, "
                "lease_start_date, lease_end_date, created_at, updated_at"
            ) \
            .eq("tenant_id", tenant_id) \
            .order("created_at", desc=True).execute()
        
        if not result.data:
            logger.warning(f"No agreements found for user {tenant_id}")
            return []
        
        agreements = []
        # Get property and landlord details
        property_ids = [a.get("property_id") for a in result.data if a.get("property_id")]
        landlord_ids = [a.get("landlord_id") for a in result.data if a.get("landlord_id")]
        
        prop_map = {}
        landlord_map = {}
        
        if property_ids:
            props = supabase_admin.table("properties") \
                .select("id, title") \
                .in_("id", property_ids).execute()
            prop_map = {p["id"]: p for p in (props.data or [])}
        
        if landlord_ids:
            landlords = supabase_admin.table("users") \
                .select("id, full_name") \
                .in_("id", landlord_ids).execute()
            landlord_map = {u["id"]: u for u in (landlords.data or [])}
        
        for agr in result.data:
            prop = prop_map.get(agr.get("property_id"), {})
            landlord = landlord_map.get(agr.get("landlord_id"), {})
            agreements.append({
                "id": agr.get("id"),
                "property_id": agr.get("property_id"),
                "property_title": prop.get("title"),
                "landlord_id": agr.get("landlord_id"),
                "landlord_name": landlord.get("full_name"),
                "rent_amount": agr.get("rent_amount", 0),
                "deposit_amount": agr.get("deposit_amount", 0),
                "status": agr.get("status"),
                "lease_start_date": agr.get("lease_start_date"),
                "lease_end_date": agr.get("lease_end_date"),
                "created_at": agr.get("created_at"),
                "updated_at": agr.get("updated_at")
            })
        
        logger.info(f"Fetched {len(agreements)} agreements for user {tenant_id}")
        return agreements
    except Exception as e:
        logger.error(f"Failed to fetch agreements for {tenant_id}: {str(e)}")
        return []


# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.get("/dashboard", response_model=TenantDashboardResponse)
async def get_tenant_dashboard(current_user = Depends(get_current_user)):
    """Get comprehensive tenant dashboard data with bundled fetching"""
    
    try:
        tenant_id = current_user['id']
        
        if current_user.get('user_type') != 'tenant':
            raise HTTPException(status_code=403, detail="Access denied. Tenant access required.")
        
        print(f"[TENANT DASHBOARD] Fetching dashboard for user: {tenant_id}")
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            stats_future = executor.submit(calculate_tenant_stats, tenant_id)
            favorites_future = executor.submit(fetch_favorites, tenant_id)
            viewings_future = executor.submit(fetch_viewing_requests, tenant_id)
            conversations_future = executor.submit(fetch_conversations, tenant_id)
            applications_future = executor.submit(fetch_applications, tenant_id)
            agreements_future = executor.submit(fetch_agreements, tenant_id)
            
            stats = stats_future.result()
            fetch_failed = stats.pop("_fetch_failed", False)
            
            return TenantDashboardResponse(
                stats=TenantStats(**stats),
                favorites=favorites_future.result(),
                viewing_requests=viewings_future.result(),
                conversations=conversations_future.result(),
                applications=applications_future.result(),
                agreements=agreements_future.result()
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching tenant dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch dashboard data")
