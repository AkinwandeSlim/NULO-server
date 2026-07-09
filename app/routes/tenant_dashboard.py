"""
Tenant Dashboard API Routes
Provides comprehensive dashboard data for tenants with bundled data fetching
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from uuid import UUID
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from ..database import supabase, supabase_admin
from ..middleware.auth import get_current_user
from ..services.agreement_service import AgreementService
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenant", tags=["tenant-dashboard"])

CACHE_TTL = 60  # 1 minute (faster updates)
dashboard_cache = {}  # key: tenant_id, value: (data, timestamp)


def invalidate_tenant_cache(tenant_id: str) -> None:
    """
    Drop the cached tenant dashboard for a given tenant.

    Call this whenever something happens that should reflect immediately
    on the tenant dashboard (e.g. agreement signed by either party,
    application status change, new payment, etc.) so the next
    GET /tenant/dashboard call returns fresh data instead of stale.
    """
    if tenant_id and tenant_id in dashboard_cache:
        dashboard_cache.pop(tenant_id, None)
        logger.info(f"[TENANT DASHBOARD] Cache invalidated for user {tenant_id}")


# ============================================================================
# PYDANTIC MODELS 
# All fixed
# ============================================================================

class TenantStats(BaseModel):
    totalFavorites: int = Field(0, description="Total number of favorite properties")
    pendingViewings: int = Field(0, description="Number of pending viewing requests")
    confirmedViewings: int = Field(0, description="Number of confirmed viewing requests")
    completedViewings: int = Field(0, description="Number of completed viewings")
    propertiesContacted: int = Field(0, description="Number of unique properties contacted")
    totalConversations: int = Field(0, description="Total number of conversations")
    unreadMessages: int = Field(0, description="Number of unread messages")
    applicationsSubmitted: int = Field(0, description="Total applications submitted")
    pendingApplications: int = Field(0, description="Pending applications")
    approvedApplications: int = Field(0, description="Approved applications")
    rejectedApplications: int = Field(0, description="Rejected applications")
    withdrawnApplications: int = Field(0, description="Withdrawn applications")
    activeAgreements: int = Field(0, description="Active lease agreements")
    pendingSignatures: int = Field(0, description="Agreements pending signature")
    paymentsDue: int = Field(0, description="Pending payments")
    totalPayments: int = Field(0, description="Total payments made")
    completedPayments: int = Field(0, description="Completed payments")
    engagementScore: int = Field(0, description="Tenant engagement score 0-100")
    trustScore: int = Field(50, description="Tenant trust score 0-100")
    engagementLevel: str = Field("low", description="Engagement level (low/medium/high)")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "totalFavorites": 5,
                "pendingViewings": 2,
                "confirmedViewings": 1,
                "completedViewings": 3,
                "propertiesContacted": 8,
                "totalConversations": 6,
                "unreadMessages": 2,
                "applicationsSubmitted": 3,
                "pendingApplications": 1,
                "approvedApplications": 1,
                "rejectedApplications": 1,
                "activeAgreements": 1,
                "pendingSignatures": 0,
                "paymentsDue": 0,
                "totalPayments": 12,
                "completedPayments": 12,
                "engagementScore": 75,
                "trustScore": 85,
                "engagementLevel": "high"
            }]
        }
    }


class TenantFavorite(BaseModel):
    id: str = Field(..., description="Favorite ID")
    property_id: str = Field(..., description="Property ID")
    property_title: Optional[str] = Field(None, description="Property title")
    property_address: Optional[str] = Field(None, description="Property address")
    property_city: Optional[str] = Field(None, description="Property city")
    property_image: Optional[str] = Field(None, description="Property image URL")
    price: Optional[int] = Field(None, description="Property price in NGN")
    beds: Optional[int] = Field(None, description="Number of bedrooms")
    baths: Optional[int] = Field(None, description="Number of bathrooms")
    created_at: str = Field(..., description="Creation timestamp")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "property_id": "123e4567-e89b-12d3-a456-426614174000",
                "property_title": "Modern 3-Bedroom Apartment",
                "property_address": "123 Main St, Lagos",
                "property_city": "Lagos",
                "property_image": "https://example.com/image.jpg",
                "price": 800000,
                "beds": 3,
                "baths": 2,
                "created_at": "2024-01-01T00:00:00Z"
            }]
        }
    }


class TenantViewingRequest(BaseModel):
    id: str = Field(..., description="Viewing request ID")
    property_id: str = Field(..., description="Property ID")
    property_title: str = Field(..., description="Property title")
    property_address: str = Field(..., description="Property address")
    landlord_id: str = Field(..., description="Landlord user ID")
    landlord_name: str = Field(..., description="Landlord full name")
    status: str = Field(..., description="Viewing status (pending/confirmed/completed/cancelled)")
    preferred_date: Optional[str] = Field(None, description="Preferred viewing date")
    confirmed_date: Optional[str] = Field(None, description="Confirmed viewing date")
    time_slot: Optional[str] = Field(None, description="Preferred time slot")
    confirmed_time: Optional[str] = Field(None, description="Confirmed viewing time")
    viewing_type: str = Field(..., description="Type of viewing (in-person/virtual)")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "property_id": "123e4567-e89b-12d3-a456-426614174000",
                "property_title": "Cozy 2-Bedroom Flat",
                "property_address": "456 Oak Ave, Abuja",
                "landlord_id": "landlord-123",
                "landlord_name": "John Doe",
                "status": "confirmed",
                "preferred_date": "2024-02-15",
                "confirmed_date": "2024-02-15",
                "time_slot": "10:00 AM",
                "confirmed_time": "10:00 AM",
                "viewing_type": "in-person",
                "created_at": "2024-02-10T10:00:00Z",
                "updated_at": "2024-02-12T14:30:00Z"
            }]
        }
    }


class TenantConversation(BaseModel):
    id: str = Field(..., description="Conversation ID")
    property_id: Optional[str] = Field(None, description="Property ID")
    property_title: Optional[str] = Field(None, description="Property title")
    other_user_id: str = Field(..., description="Other user's ID")
    other_user_name: str = Field(..., description="Other user's name")
    other_user_avatar: Optional[str] = Field(None, description="Other user's avatar URL")
    last_message: Optional[str] = Field(None, description="Last message content")
    last_message_time: str = Field(..., description="Last message timestamp")
    unread_count: int = Field(..., description="Number of unread messages")
    created_at: str = Field(..., description="Conversation creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "conv-123",
                "property_id": "123e4567-e89b-12d3-a456-426614174000",
                "property_title": "Luxury Studio",
                "other_user_id": "landlord-456",
                "other_user_name": "Jane Smith",
                "other_user_avatar": "https://example.com/avatar.jpg",
                "last_message": "Thanks for your interest!",
                "last_message_time": "2024-02-15T16:45:00Z",
                "unread_count": 2,
                "created_at": "2024-02-10T09:00:00Z",
                "updated_at": "2024-02-15T16:45:00Z"
            }]
        }
    }


class TenantApplication(BaseModel):
    id: str = Field(..., description="Application ID")
    property_id: str = Field(..., description="Property ID")
    property_title: Optional[str] = Field(None, description="Property title")
    property_location: Optional[str] = Field(None, description="Property location")
    property_price: Optional[int] = Field(None, description="Property price in NGN")
    status: str = Field(..., description="Application status (pending/approved/rejected)")
    move_in_date: Optional[str] = Field(None, description="Proposed move-in date")
    created_at: str = Field(..., description="Application submission timestamp")
    viewed_by_landlord: bool = Field(..., description="Whether landlord viewed application")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "app-789",
                "property_id": "123e4567-e89b-12d3-a456-426614174000",
                "property_title": "Spacious 1-Bedroom",
                "property_location": "Victoria Island, Lagos",
                "property_price": 600000,
                "status": "pending",
                "move_in_date": "2024-03-01",
                "created_at": "2024-02-12T10:30:00Z",
                "viewed_by_landlord": False
            }]
        }
    }


class TenantAgreement(BaseModel):
    id: str = Field(..., description="Agreement ID")
    property_id: str = Field(..., description="Property ID")
    property_title: Optional[str] = Field(None, description="Property title")
    landlord_id: str = Field(..., description="Landlord user ID")
    landlord_name: str = Field(..., description="Landlord full name")
    rent_amount: int = Field(..., description="Monthly rent in NGN")
    deposit_amount: int = Field(..., description="Security deposit in NGN")
    status: str = Field(..., description="Agreement status (pending/active/terminated)")
    raw_status: Optional[str] = Field(None, description="Raw agreement status from the database")
    tenant_signed_at: Optional[str] = Field(None, description="Tenant signature timestamp")
    landlord_signed_at: Optional[str] = Field(None, description="Landlord signature timestamp")
    lease_start_date: Optional[str] = Field(None, description="Lease start date")
    lease_end_date: Optional[str] = Field(None, description="Lease end date")
    payment_frequency: Optional[str] = Field(None, description="Payment frequency (MONTHLY/QUARTERLY/SEMI_ANNUAL/ANNUAL)")
    expected_payment_amount: Optional[int] = Field(None, description="Expected payment amount")
    total_received_amount: Optional[int] = Field(None, description="Total received amount")
    reconciliation_status: Optional[str] = Field(None, description="Reconciliation status")
    virtual_account_number: Optional[str] = Field(None, description="Virtual account number")
    virtual_account_name: Optional[str] = Field(None, description="Virtual account name")
    nomba_account_ref: Optional[str] = Field(None, description="Nomba account reference")
    disbursement_status: Optional[str] = Field(None, description="Disbursement status")
    disbursement_merchant_tx_ref: Optional[str] = Field(None, description="Disbursement merchant transaction reference")
    disbursement_amount: Optional[int] = Field(None, description="Disbursement amount")
    created_at: str = Field(..., description="Agreement creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "agree-456",
                "property_id": "123e4567-e89b-12d3-a456-426614174000",
                "property_title": "Modern 3-Bedroom",
                "landlord_id": "landlord-123",
                "landlord_name": "John Doe",
                "rent_amount": 800000,
                "deposit_amount": 1600000,
                "status": "active",
                "lease_start_date": "2024-03-01",
                "lease_end_date": "2025-02-28",
                "payment_frequency": "MONTHLY",
                "expected_payment_amount": 800000,
                "total_received_amount": 0,
                "created_at": "2024-02-18T12:00:00Z",
                "updated_at": "2024-02-20T14:00:00Z"
            }]
        }
    }


class TenantDashboardResponse(BaseModel):
    stats: TenantStats = Field(..., description="Tenant dashboard statistics")
    favorites: List[TenantFavorite] = Field(default_factory=list, description="List of favorite properties")
    viewing_requests: List[TenantViewingRequest] = Field(default_factory=list, description="List of viewing requests")
    conversations: List[TenantConversation] = Field(default_factory=list, description="List of conversations")
    applications: List[TenantApplication] = Field(default_factory=list, description="List of rental applications")
    agreements: List[TenantAgreement] = Field(default_factory=list, description="List of lease agreements")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "stats": {
                    "totalFavorites": 5,
                    "pendingViewings": 2,
                    "confirmedViewings": 1,
                    "completedViewings": 3,
                    "propertiesContacted": 8,
                    "totalConversations": 6,
                    "unreadMessages": 2,
                    "applicationsSubmitted": 3,
                    "pendingApplications": 1,
                    "approvedApplications": 1,
                    "rejectedApplications": 1,
                    "activeAgreements": 1,
                    "pendingSignatures": 0,
                    "paymentsDue": 0,
                    "totalPayments": 12,
                    "completedPayments": 12,
                    "engagementScore": 75,
                    "trustScore": 85,
                    "engagementLevel": "high"
                },
                "favorites": [],
                "viewing_requests": [],
                "conversations": [],
                "applications": [],
                "agreements": []
            }]
        }
    }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_tenant_stats(tenant_id: str) -> dict:
    """Calculate tenant statistics with optimized queries"""
    stats = {
        "totalFavorites": 0,
        "pendingViewings": 0,
        "confirmedViewings": 0,
        "completedViewings": 0,
        "propertiesContacted": 0,
        "totalConversations": 0,
        "unreadMessages": 0,
        "applicationsSubmitted": 0,
        "pendingApplications": 0,
        "approvedApplications": 0,
        "rejectedApplications": 0,
        "withdrawnApplications": 0,
        "activeAgreements": 0,
        "pendingSignatures": 0,
        "paymentsDue": 0,
        "totalPayments": 0,
        "completedPayments": 0,
        "engagementScore": 0,
        "trustScore": 50,
        "engagementLevel": "low",
        "_fetch_failed": False,
    }

    try:
        # Fetch all data we need in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Submit all queries
            fav_future = executor.submit(
                lambda: supabase_admin.table("favorites").select("id, property_id").eq("tenant_id", tenant_id).execute()
            )
            viewing_future = executor.submit(
                lambda: supabase_admin.table("viewing_requests").select("id, property_id, status").eq("tenant_id", tenant_id).execute()
            )
            conv_future = executor.submit(
                lambda: supabase_admin.table("conversations").select("id, property_id").eq("tenant_id", tenant_id).execute()
            )
            unread_future = executor.submit(
                lambda: supabase_admin.table("messages").select("id").eq("recipient_id", tenant_id).eq("read", False).execute()
            )
            apps_future = executor.submit(
                lambda: supabase_admin.table("applications").select("id, status, property_id").eq("user_id", tenant_id).execute()
            )
            agreements_future = executor.submit(
                lambda: supabase_admin.table("agreements").select("id, status, tenant_signed_at, landlord_signed_at").eq("tenant_id", tenant_id).execute()
            )
            transactions_future = executor.submit(
                lambda: supabase_admin.table("transactions").select("id, status").eq("tenant_id", tenant_id).execute()
            )
            user_future = executor.submit(
                lambda: supabase_admin.table("users").select("trust_score").eq("id", tenant_id).single().execute()
            )
            messages_sent_future = executor.submit(
                lambda: supabase_admin.table("messages").select("id").eq("sender_id", tenant_id).execute()
            )

            # Get results
            fav_result = fav_future.result()
            viewing_result = viewing_future.result()
            conv_result = conv_future.result()
            unread_result = unread_future.result()
            apps_result = apps_future.result()
            agreements_result = agreements_future.result()
            transactions_result = transactions_future.result()
            user_result = user_future.result()
            messages_sent_result = messages_sent_future.result()

        # Process results
        # Favorites
        favorites = fav_result.data or []
        stats["totalFavorites"] = len(favorites)
        
        # Viewings
        viewings = viewing_result.data or []
        stats["pendingViewings"] = sum(1 for v in viewings if v.get("status") == "pending")
        stats["confirmedViewings"] = sum(1 for v in viewings if v.get("status") == "confirmed")
        stats["completedViewings"] = sum(1 for v in viewings if v.get("status") == "completed")
        
        # Conversations
        conversations = conv_result.data or []
        stats["totalConversations"] = len(conversations)
        
        # Properties Contacted
        properties_contacted = set()
        for conv in conversations:
            if conv.get("property_id"): properties_contacted.add(conv["property_id"])
        for v in viewings:
            if v.get("property_id"): properties_contacted.add(v["property_id"])
        apps = apps_result.data or []
        for app in apps:
            if app.get("property_id"): properties_contacted.add(app["property_id"])
        stats["propertiesContacted"] = len(properties_contacted)
        
        # Unread messages
        stats["unreadMessages"] = len(unread_result.data or [])
        
        # Applications
        stats["applicationsSubmitted"] = len(apps)
        for app in apps:
            if app.get("status") in ("submitted", "pending"): stats["pendingApplications"] +=1
            elif app.get("status") == "approved": stats["approvedApplications"] +=1
            elif app.get("status") == "rejected": stats["rejectedApplications"] +=1
            elif app.get("status") == "withdrawn": stats["withdrawnApplications"] +=1
            
        # Agreements
        agreements = agreements_result.data or []
        for agr in agreements:
            effective_status = AgreementService.derive_effective_status(agr)
            if effective_status in ["ACTIVE", "SIGNED"]:
                stats["activeAgreements"] += 1
            elif effective_status == "PENDING_TENANT":
                stats["pendingSignatures"] += 1
            
        # Payments
        transactions = transactions_result.data or []
        stats["totalPayments"] = len(transactions)
        stats["completedPayments"] = sum(1 for t in transactions if t.get("status") == "completed")
        stats["paymentsDue"] = sum(1 for t in transactions if t.get("status") in ["pending", "processing"])
        
        # Trust Score
        if user_result.data:
            stats["trustScore"] = user_result.data.get("trust_score", 50)
            
        # Engagement Score
        messages_sent = len(messages_sent_result.data or [])
        activity_score = (
            stats["totalFavorites"] * 3 +
            len(viewings) * 4 +
            messages_sent * 2 +
            stats["totalConversations"] * 2 +
            stats["applicationsSubmitted"] * 3
        )
        stats["engagementScore"] = min(100, max(0, activity_score * 2))
        
        # Engagement Level
        if stats["engagementScore"] >=70:
            stats["engagementLevel"] = "high"
        elif stats["engagementScore"] >=40:
            stats["engagementLevel"] = "medium"
        else:
            stats["engagementLevel"] = "low"
            
    except Exception as e:
        logger.error(f"Error calculating tenant stats: {e}")
        stats["_fetch_failed"] = True
        
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
                "tenant_signed_at, landlord_signed_at, lease_start_date, lease_end_date, "
                "payment_frequency, expected_payment_amount, total_received_amount, "
                "reconciliation_status, virtual_account_number, virtual_account_name, "
                "nomba_account_ref, created_at, updated_at"
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
                .select("id, title, payment_frequency") \
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
            # Prioritize property's payment_frequency over agreement's
            payment_frequency = prop.get("payment_frequency") or agr.get("payment_frequency")
            effective_status = AgreementService.derive_effective_status(agr)
            agreements.append({
                "id": agr.get("id"),
                "property_id": agr.get("property_id"),
                "property_title": prop.get("title"),
                "landlord_id": agr.get("landlord_id"),
                "landlord_name": landlord.get("full_name"),
                "rent_amount": agr.get("rent_amount", 0),
                "deposit_amount": agr.get("deposit_amount", 0),
                "status": effective_status,
                "raw_status": agr.get("status"),
                "tenant_signed_at": agr.get("tenant_signed_at"),
                "landlord_signed_at": agr.get("landlord_signed_at"),
                "lease_start_date": agr.get("lease_start_date"),
                "lease_end_date": agr.get("lease_end_date"),
                "payment_frequency": payment_frequency,
                "expected_payment_amount": agr.get("expected_payment_amount"),
                "total_received_amount": agr.get("total_received_amount"),
                "reconciliation_status": agr.get("reconciliation_status"),
                "virtual_account_number": agr.get("virtual_account_number"),
                "virtual_account_name": agr.get("virtual_account_name"),
                "nomba_account_ref": agr.get("nomba_account_ref"),
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
    """Get comprehensive tenant dashboard data with bundled fetching and caching"""
    
    try:
        tenant_id = current_user['id']
        
        if current_user.get('user_type') != 'tenant':
            raise HTTPException(status_code=403, detail="Access denied. Tenant access required.")
        
        # Check cache
        now = datetime.utcnow()
        if tenant_id in dashboard_cache:
            cached_data, cached_time = dashboard_cache[tenant_id]
            if (now - cached_time).total_seconds() < CACHE_TTL:
                logger.info(f"[TENANT DASHBOARD] Using cached data for user {tenant_id}")
                return cached_data
        
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
            
            response = TenantDashboardResponse(
                stats=TenantStats(**stats),
                favorites=favorites_future.result(),
                viewing_requests=viewings_future.result(),
                conversations=conversations_future.result(),
                applications=applications_future.result(),
                agreements=agreements_future.result()
            )
            
            # Save to cache
            dashboard_cache[tenant_id] = (response, now)
            
            return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching tenant dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch dashboard data")
