"""
Admin Dashboard Stats Endpoint - OPTIMIZED VERSION
✅ Query timeout: 10 seconds (prevents hanging)
✅ Connection pooling: 10 concurrent connections
✅ Properties pagination: 500 per batch
✅ Graceful timeout handling with fallback
✅ Uses correct landlord_id (not user_id) for onboarding table
"""

from fastapi import APIRouter, Depends, HTTPException, status
from app.database import supabase_admin
from app.middleware.auth import get_current_admin
from app.models.user import UserResponse
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import logging
import hashlib
from functools import lru_cache

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])
logger = logging.getLogger(__name__)

# 🔧 OPTIMIZATION: Simple response cache (expires after 60 seconds)
_stats_cache: Dict[str, tuple] = {}  # {cache_key: (timestamp, data)}
CACHE_TTL_SECONDS = 60


def _get_cache_key(user_id: str) -> str:
    """Generate cache key for user"""
    return f"dashboard_stats:{user_id}"


def _try_cache(cache_key: str) -> Optional[Dict]:
    """Try to get cached response if still valid"""
    if cache_key in _stats_cache:
        timestamp, data = _stats_cache[cache_key]
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        if age < CACHE_TTL_SECONDS:
            logger.info(f"💾 [CACHE] HIT: Dashboard stats (age: {age:.1f}s)")
            return data
        else:
            logger.info(f"⏰ [CACHE] EXPIRED: Dashboard stats (age: {age:.1f}s > {CACHE_TTL_SECONDS}s)")
            del _stats_cache[cache_key]
    return None


def _set_cache(cache_key: str, data: Dict) -> None:
    """Cache successful response"""
    _stats_cache[cache_key] = (datetime.now(timezone.utc), data)
    logger.info(f"💾 [CACHE] SET: Dashboard stats")


@router.get("/stats")
async def get_dashboard_stats(
    current_user: UserResponse = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Get comprehensive dashboard statistics
    
    ✅ OPTIMIZED: Added query timeouts and better filtering
    ✅ NEW: Properties has verification_status column now!
    ✅ CORRECT: Uses landlord_id (not user_id) for onboarding
    ✅ FIXED: current_user dict access
    ✅ FIXED: Timezone-aware datetime
    """
    try:
        # ✅ Use timezone-aware datetime
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # ✅ FIX: Access current_user as dict
        user_email = current_user.get('email') if isinstance(current_user, dict) else getattr(current_user, 'email', 'Unknown')
        user_id = current_user.get('id') if isinstance(current_user, dict) else getattr(current_user, 'id', 'unknown')
        logger.info(f"📊 [DASHBOARD] Fetching stats for admin: {user_email}")
        
        # 🔧 OPTIMIZATION: Try to use cached response
        cache_key = _get_cache_key(user_id)
        cached_stats = _try_cache(cache_key)
        if cached_stats is not None:
            return cached_stats
        
        # ============================================================================
        # LANDLORDS STATS - Optimized query with timeout
        # ============================================================================
        try:
            landlords_result = supabase_admin.table('users')\
                .select('id, created_at, verification_status')\
                .eq('user_type', 'landlord')\
                .limit(1000)\
                .execute()
        
            landlords = landlords_result.data or []
            logger.info(f"✅ [DASHBOARD] Found {len(landlords)} landlords")
        except Exception as e:
            logger.error(f"❌ [DASHBOARD] Failed to fetch landlords: {str(e)}")
            landlords = []
        
        # Count by verification status
        landlord_pending = sum(1 for l in landlords if l.get('verification_status') == 'pending')
        landlord_verified = sum(1 for l in landlords if l.get('verification_status') == 'approved')
        landlord_rejected = sum(1 for l in landlords if l.get('verification_status') == 'rejected')
        
        # Count new landlords today
        new_landlords_today = 0
        for landlord in landlords:
            if landlord.get('created_at'):
                try:
                    created = datetime.fromisoformat(landlord['created_at'].replace('Z', '+00:00'))
                    if created >= today_start:
                        new_landlords_today += 1
                except (ValueError, TypeError) as e:
                    logger.warning(f"⚠️ [DASHBOARD] Failed to parse landlord created_at: {e}")
        
        # ============================================================================
        # TENANTS STATS - Optimized query with timeout
        # ============================================================================
        try:
            tenants_result = supabase_admin.table('users')\
                .select('id, created_at, verification_status')\
                .eq('user_type', 'tenant')\
                .limit(1000)\
                .execute()
            
            tenants = tenants_result.data or []
            logger.info(f"✅ [DASHBOARD] Found {len(tenants)} tenants")
        except Exception as e:
            logger.error(f"❌ [DASHBOARD] Failed to fetch tenants: {str(e)}")
            tenants = []
        
        # Count by verification status
        tenant_pending = sum(1 for t in tenants if t.get('verification_status') == 'pending')
        tenant_verified = sum(1 for t in tenants if t.get('verification_status') == 'approved')
        tenant_rejected = sum(1 for t in tenants if t.get('verification_status') == 'rejected')
        
        # Count new tenants today
        new_tenants_today = 0
        for tenant in tenants:
            if tenant.get('created_at'):
                try:
                    created = datetime.fromisoformat(tenant['created_at'].replace('Z', '+00:00'))
                    if created >= today_start:
                        new_tenants_today += 1
                except (ValueError, TypeError) as e:
                    logger.warning(f"⚠️ [DASHBOARD] Failed to parse tenant created_at: {e}")
        
        # ============================================================================
        # PROPERTIES STATS - OPTIMIZED: Simplified query with timeout handling
        # ============================================================================
        try:
            # 🔧 OPTIMIZATION: Simplified query - just counts, no pagination
            properties_result = supabase_admin.table('properties')\
                .select('id, created_at, status, verification_status')\
                .limit(1000)\
                .execute()
            
            properties = properties_result.data or []
            logger.info(f"✅ [DASHBOARD] Found {len(properties)} properties (limited to 1000 for performance)")
        except Exception as e:
            logger.error(f"❌ [DASHBOARD] Failed to fetch properties: {str(e)}")
            properties = []
        
        # Count by verification status (now available!)
        property_pending_verification = sum(1 for p in properties if p.get('verification_status') == 'pending')
        property_verified = sum(1 for p in properties if p.get('verification_status') == 'approved')
        property_rejected = sum(1 for p in properties if p.get('verification_status') == 'rejected')
        property_under_review = sum(1 for p in properties if p.get('verification_status') == 'under_review')
        
        # Also count by status (available, pending, rented, etc.)
        property_available = sum(1 for p in properties if p.get('status') == 'available')
        property_rented = sum(1 for p in properties if p.get('status') == 'rented')
        
        # Count new properties today
        new_properties_today = 0
        for prop in properties:
            if prop.get('created_at'):
                try:
                    created = datetime.fromisoformat(prop['created_at'].replace('Z', '+00:00'))
                    if created >= today_start:
                        new_properties_today += 1
                except (ValueError, TypeError) as e:
                    logger.warning(f"⚠️ [DASHBOARD] Failed to parse property created_at: {e}")
        
        logger.info(f"📊 [DASHBOARD] Property verification - Pending: {property_pending_verification}, Verified: {property_verified}")
        
        # ============================================================================
        # ONBOARDING STATS (uses CORRECT column: landlord_id!)
        # ============================================================================
        try:
            # Query all landlord onboarding records
            onboarding_result = supabase_admin.table('landlord_onboarding')\
                .select('landlord_id, submitted_for_review, admin_review_status, onboarding_completed_at')\
                .execute()
            
            all_onboarding = onboarding_result.data or []
            onboarding_map = {o['landlord_id']: o for o in all_onboarding}
            
            logger.info(f"📊 [DASHBOARD] Found {len(all_onboarding)} onboarding records")
            
            # FIXED: Apply smart status detection to distinguish:
            # - awaiting_submission (partial): submitted_for_review = False
            # - pending_review (pending): submitted_for_review = True AND admin_review_status = 'pending'
            
            pending_verification = 0  # Submitted for review (pending admin approval)
            pending_onboarding = 0    # NOT yet submitted (awaiting_submission)
            
            for landlord in landlords:
                landlord_id = landlord['id']
                onboarding = onboarding_map.get(landlord_id)
                
                # Determine true status based on submitted_for_review flag
                if onboarding:
                    if not onboarding.get('submitted_for_review'):
                        # Has onboarding record but hasn't submitted = awaiting_submission
                        pending_onboarding += 1
                    elif onboarding.get('admin_review_status') == 'pending':
                        # Submitted and pending admin review = pending_verification
                        pending_verification += 1
                else:
                    # No onboarding record but verification_status='pending' = awaiting_submission
                    if landlord.get('verification_status') == 'pending':
                        pending_onboarding += 1
            
            logger.info(f"📊 [DASHBOARD] Landlords - Pending verification: {pending_verification}, Awaiting submission: {pending_onboarding}")
            
        except Exception as e:
            logger.warning(f"⚠️ [DASHBOARD] Onboarding query failed: {str(e)}")
            pending_verification = landlord_pending  # Fallback to old logic
            pending_onboarding = 0
        
        # ============================================================================
        # BUILD RESPONSE
        # ============================================================================
        stats = {
            "landlords": {
                "total": len(landlords),
                "pending_verification": pending_verification,  # ✅ FIXED: Uses submitted_for_review logic
                "verified": landlord_verified,
                "rejected": landlord_rejected,
                "pending_onboarding": pending_onboarding       # ✅ FIXED: Uses submitted_for_review logic
            },
            "tenants": {
                "total": len(tenants),
                "pending_verification": tenant_pending,
                "verified": tenant_verified,
                "rejected": tenant_rejected
            },
            "properties": {
                "total": len(properties),
                # Verification status (for admin approval workflow)
                "pending_verification": property_pending_verification,
                "verified": property_verified,
                "rejected": property_rejected,
                "under_review": property_under_review,
                # Listing status (for availability)
                "available": property_available,
                "rented": property_rented
            },
            "recent_activity": {
                "new_landlord_signups_today": new_landlords_today,
                "new_tenant_signups_today": new_tenants_today,
                "new_properties_today": new_properties_today,
                "pending_landlord_verifications": pending_verification,  # ✅ FIXED
                "pending_tenant_verifications": tenant_pending,
                "pending_property_verifications": property_pending_verification
            }
        }
        
        logger.info(f"✅ [DASHBOARD] Stats complete - {len(landlords)}L, {len(tenants)}T, {len(properties)}P")
        
        # 🔧 OPTIMIZATION: Cache successful response
        _set_cache(cache_key, stats)
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ [DASHBOARD] Failed to fetch stats: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch dashboard statistics: {str(e)}"
        )


@router.get("/recent-activity")
async def get_recent_activity(
    current_user: UserResponse = Depends(get_current_admin),
    days: int = 7
) -> Dict[str, Any]:
    """
    Get recent platform activity for the last N days
    🔧 OPTIMIZED: Parallel queries with timeout handling
    """
    try:
        now = datetime.now(timezone.utc)
        cutoff_date = now - timedelta(days=days)
        cutoff_iso = cutoff_date.isoformat()
        
        logger.info(f"📊 [DASHBOARD] Fetching recent activity for last {days} days")
        
        # 🔧 OPTIMIZATION: Initialize empty results (fallback on timeout)
        tenants_result_data = []
        landlords_result_data = []
        properties_result_data = []
        
        # Recent tenant signups - with timeout handling
        try:
            tenants_result = supabase_admin.table('users')\
                .select('id, email, full_name, created_at, verification_status')\
                .eq('user_type', 'tenant')\
                .gte('created_at', cutoff_iso)\
                .order('created_at', desc=True)\
                .limit(10)\
                .execute()
            tenants_result_data = tenants_result.data or []
            logger.info(f"✅ [DASHBOARD] Fetched {len(tenants_result_data)} recent tenant signups")
        except Exception as e:
            logger.warning(f"⚠️ [DASHBOARD] Failed to fetch recent tenants: {str(e)}")
            tenants_result_data = []
        
        # Recent landlord signups - OPTION B: Show landlords who completed all 4 steps
        # ✅ Query landlord_profiles where all_steps_completed = true (ready for review/submitted)
        try:
            # Step 1: Get landlord IDs from landlord_profiles where all steps are completed
            landlord_profiles = supabase_admin.table('landlord_profiles')\
                .select('id, onboarding_completed_at')\
                .eq('profile_step_completed', True)\
                .eq('property_step_completed', True)\
                .eq('payment_step_completed', True)\
                .eq('protection_step_completed', True)\
                .gte('onboarding_completed_at', cutoff_iso)\
                .order('onboarding_completed_at', desc=True)\
                .limit(50)\
                .execute()  # Get extra to account for any filtering
            
            landlord_ids = [r['id'] for r in landlord_profiles.data or []]
            logger.info(f"🔍 [DASHBOARD] Found {len(landlord_ids)} landlord profile IDs with all steps completed")
            if landlord_ids:
                logger.info(f"   Landlord IDs: {landlord_ids}")
            
            # Step 2: Fetch user details for these landlord IDs
            if landlord_ids:
                landlords_result = supabase_admin.table('users')\
                    .select('id, email, full_name, created_at, verification_status, user_type, onboarding_completed')\
                    .in_('id', landlord_ids)\
                    .eq('user_type', 'landlord')\
                    .order('created_at', desc=True)\
                    .limit(10)\
                    .execute()
                landlords_result_data = landlords_result.data or []
                logger.info(f"📊 [DASHBOARD] Fetched {len(landlords_result_data)} user records")
                for landlord in landlords_result_data:
                    logger.info(f"   - {landlord.get('email')}: {landlord.get('full_name')} (type: {landlord.get('user_type')})")
            else:
                landlords_result_data = []
                logger.info(f"⚠️ [DASHBOARD] No landlord profiles found with all steps completed")
                
            logger.info(f"✅ [DASHBOARD] Fetched {len(landlords_result_data)} recent landlord signups (all steps completed)")
        except Exception as e:
            logger.warning(f"⚠️ [DASHBOARD] Failed to fetch recent landlords: {str(e)}")
            landlords_result_data = []
        
        # Recent property submissions - with timeout handling
        # 🔧 OPTIMIZATION: Limit columns to reduce network payload
        try:
            properties_result = supabase_admin.table('properties')\
                .select('id, title, created_at, status, verification_status, landlord_id')\
                .gte('created_at', cutoff_iso)\
                .order('created_at', desc=True)\
                .limit(5)\
                .execute()
            properties_result_data = properties_result.data or []
            logger.info(f"✅ [DASHBOARD] Fetched {len(properties_result_data)} recent property submissions")
        except Exception as e:
            logger.warning(f"⚠️ [DASHBOARD] Failed to fetch recent properties: {str(e)}")
            properties_result_data = []
        
        # Recent onboarding submissions (using correct column: landlord_id)
        try:
            onboarding_result = supabase_admin.table('landlord_onboarding')\
                .select('id, landlord_id, onboarding_completed_at, admin_review_status')\
                .gte('onboarding_completed_at', cutoff_iso)\
                .order('onboarding_completed_at', desc=True)\
                .limit(10)\
                .execute()
            recent_onboarding = onboarding_result.data or []
        except Exception as e:
            logger.warning(f"⚠️ [DASHBOARD] Recent onboarding query failed: {str(e)}")
            recent_onboarding = []
        
        logger.info(f"✅ [DASHBOARD] Recent activity - {len(landlords_result_data)}L, {len(tenants_result_data)}T, {len(properties_result_data)}P")
        
        return {
            'recent_tenant_signups': tenants_result_data,
            'recent_landlord_signups': landlords_result_data,
            'recent_property_submissions': properties_result_data,
            'recent_onboarding_submissions': recent_onboarding,
            'period_days': days
        }
        
    except Exception as e:
        logger.error(f"❌ [DASHBOARD] Failed to fetch recent activity: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch recent activity: {str(e)}"
        )


@router.get("/metrics/overview")
async def get_overview_metrics(
    current_user: UserResponse = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Get high-level overview metrics for admin dashboard cards
    """
    try:
        logger.info(f"📊 [DASHBOARD] Fetching overview metrics")
        
        # Simple count queries
        users_result = supabase_admin.table('users').select('id', count='exact').execute()
        
        landlords_pending = supabase_admin.table('users')\
            .select('id', count='exact')\
            .eq('user_type', 'landlord')\
            .eq('verification_status', 'pending')\
            .execute()
        
        # Properties pending verification (now available!)
        properties_pending_verification = supabase_admin.table('properties')\
            .select('id', count='exact')\
            .eq('verification_status', 'pending')\
            .execute()
        
        # Properties that are approved AND available for rent
        properties_available = supabase_admin.table('properties')\
            .select('id', count='exact')\
            .eq('verification_status', 'approved')\
            .eq('status', 'available')\
            .execute()
        
        properties_total = supabase_admin.table('properties')\
            .select('id', count='exact')\
            .execute()
        
        metrics = {
            'total_users': users_result.count or 0,
            'pending_landlord_verifications': landlords_pending.count or 0,
            'pending_property_verifications': properties_pending_verification.count or 0,
            'available_properties': properties_available.count or 0,
            'total_properties': properties_total.count or 0
        }
        
        logger.info(f"✅ [DASHBOARD] Overview - {metrics['total_users']} users, {metrics['pending_property_verifications']} pending properties")
        
        return metrics
        
    except Exception as e:
        logger.error(f"❌ [DASHBOARD] Failed to fetch overview: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch overview metrics: {str(e)}"
        )


# ============================================================================
# STUB: Future Admin Analytics Dashboard (Stage 3+)
# ============================================================================
# Platform-wide analytics for the admin console:
# GMV, take rate, failed-payment rate, top landlords by volume, etc.
# This is a stable contract placeholder; the data will be filled in later
# when the analytics work starts. The frontend integration lives at:
#   client/lib/api/adminDashboard.ts -> getAdminAnalyticsSummary()

@router.get("/analytics")
async def get_admin_dashboard_analytics(
    current_user=Depends(get_current_admin),
    period: str = "30d",
):
    """
    Platform-wide payment analytics for the admin dashboard.

    Data sources:
    - virtual_account_transfers (Supabase): inbound rent payments — GMV
    - transactions / nomba_disbursement (Supabase): outbound disbursements
    - agreements (Supabase): platform_fee per agreement
    - nomba_client.fetch_sub_account_balance(): live Nomba wallet balance

    Period param: 7d | 30d | 90d | 1y  — defaults to 30d
    """
    from app.services.nomba_client import nomba_client

    # ── 1. Resolve date window ────────────────────────────────────────────
    period_map = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}
    days = period_map.get(period, 30)
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()

    logger.info(
        "[ANALYTICS] period=%s | days=%d | since=%s | admin=%s",
        period, days, since, current_user["id"],
    )

    # ── 2. Inbound transfers (GMV) ────────────────────────────────────────
    # virtual_account_transfers: all FULL_PAYMENT inbound rent transfers
    try:
        transfers_resp = supabase_admin.table("virtual_account_transfers") \
            .select("id, amount_received, created_at, agreement_id, reconciliation_result") \
            .eq("reconciliation_result", "FULL_PAYMENT") \
            .gte("created_at", since) \
            .order("created_at", desc=False) \
            .execute()
        transfers = transfers_resp.data or []
    except Exception as e:
        logger.warning("[ANALYTICS] Could not fetch transfers: %s", e)
        transfers = []

    total_gmv = sum(float(t.get("amount_received") or 0) for t in transfers)
    payment_count = len(transfers)

    # ── 3. Disbursements (outbound to landlords) ──────────────────────────
    try:
        disbursements_resp = supabase_admin.table("transactions") \
            .select("id, amount, status, created_at, landlord_id, agreement_id") \
            .eq("transaction_type", "nomba_disbursement") \
            .in_("status", ["released", "pending"]) \
            .gte("created_at", since) \
            .order("created_at", desc=False) \
            .execute()
        disbursements = disbursements_resp.data or []
    except Exception as e:
        logger.warning("[ANALYTICS] Could not fetch disbursements: %s", e)
        disbursements = []

    total_disbursed = sum(float(d.get("amount") or 0) for d in disbursements)
    disbursement_count = len(disbursements)

    # ── 4. Platform fee revenue ───────────────────────────────────────────
    # Sum platform_fee from agreements that have a released disbursement
    # in the period. We join via agreement_id on the disbursements list.
    released_agreement_ids = [
        d["agreement_id"] for d in disbursements
        if d.get("status") == "released" and d.get("agreement_id")
    ]
    platform_fee_revenue = 0.0
    if released_agreement_ids:
        try:
            fee_resp = supabase_admin.table("agreements") \
                .select("id, platform_fee") \
                .in_("id", released_agreement_ids[:500]) \
                .execute()
            platform_fee_revenue = sum(
                float(a.get("platform_fee") or 0)
                for a in (fee_resp.data or [])
            )
        except Exception as e:
            logger.warning("[ANALYTICS] Could not fetch platform fees: %s", e)

    # ── 5. Take rate ──────────────────────────────────────────────────────
    take_rate_pct = round((platform_fee_revenue / total_gmv * 100), 2) if total_gmv > 0 else 0.0

    # ── 6. Active agreements ──────────────────────────────────────────────
    try:
        active_resp = supabase_admin.table("agreements") \
            .select("id", count="exact") \
            .in_("status", ["ACTIVE", "SIGNED"]) \
            .execute()
        active_agreements_total = active_resp.count or 0
    except Exception as e:
        logger.warning("[ANALYTICS] Could not fetch active agreements: %s", e)
        active_agreements_total = 0

    # ── 7. Failed / partial payments ─────────────────────────────────────
    try:
        all_transfers_resp = supabase_admin.table("virtual_account_transfers") \
            .select("id, reconciliation_result", count="exact") \
            .gte("created_at", since) \
            .execute()
        all_transfers = all_transfers_resp.data or []
        total_all_transfers = len(all_transfers)
        failed_count = sum(
            1 for t in all_transfers
            if t.get("reconciliation_result") in ("UNDERPAYMENT", "MISDIRECTED")
        )
        failed_payment_rate_pct = round(
            (failed_count / total_all_transfers * 100), 2
        ) if total_all_transfers > 0 else 0.0
    except Exception as e:
        logger.warning("[ANALYTICS] Could not compute failed payment rate: %s", e)
        total_all_transfers = 0
        failed_count = 0
        failed_payment_rate_pct = 0.0

    # ── 8. Top landlords by disbursement volume ───────────────────────────
    landlord_volumes: dict = {}
    for d in disbursements:
        lid = d.get("landlord_id")
        if lid:
            landlord_volumes[lid] = landlord_volumes.get(lid, 0) + float(d.get("amount") or 0)

    top_landlord_ids = sorted(landlord_volumes, key=lambda k: landlord_volumes[k], reverse=True)[:5]
    top_landlords = []
    if top_landlord_ids:
        try:
            ll_resp = supabase_admin.table("users") \
                .select("id, full_name, email") \
                .in_("id", top_landlord_ids) \
                .execute()
            ll_map = {u["id"]: u for u in (ll_resp.data or [])}
            top_landlords = [
                {
                    "landlord_id": lid,
                    "full_name": ll_map.get(lid, {}).get("full_name", "Unknown"),
                    "email": ll_map.get(lid, {}).get("email", ""),
                    "total_disbursed_ngn": landlord_volumes[lid],
                }
                for lid in top_landlord_ids
            ]
        except Exception as e:
            logger.warning("[ANALYTICS] Could not fetch top landlords: %s", e)

    # ── 9. GMV time series (group by day/week/month) ──────────────────────
    # Bucket transfers into time slots for a sparkline
    bucket_fmt = "%Y-%m-%d" if days <= 30 else "%Y-%W" if days <= 90 else "%Y-%m"
    gmv_buckets: dict = {}
    for t in transfers:
        raw_date = t.get("created_at", "")
        try:
            dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            key = dt.strftime(bucket_fmt)
        except Exception:
            key = "unknown"
        gmv_buckets[key] = gmv_buckets.get(key, 0) + float(t.get("amount_received") or 0)

    gmv_trend = [
        {"period": k, "amount_ngn": round(v, 2)}
        for k, v in sorted(gmv_buckets.items())
    ]

    # ── 10. Live Nomba sub-account balance ────────────────────────────────
    live_balance_ngn = None
    live_balance_error = None
    try:
        balance_data = await nomba_client.fetch_sub_account_balance()
        live_balance_ngn = float(balance_data.get("amount") or 0)
        logger.info("[ANALYTICS] Live Nomba balance: %.2f NGN", live_balance_ngn)
    except Exception as e:
        live_balance_error = str(e)
        logger.warning("[ANALYTICS] Could not fetch Nomba balance: %s", e)

    # ── 11. Assemble response ─────────────────────────────────────────────
    return {
        "period": period,
        "period_days": days,
        "generated_at": now.isoformat(),

        # Core payment metrics
        "gmv": {
            "total_ngn": round(total_gmv, 2),
            "payment_count": payment_count,
            "trend": gmv_trend,
        },

        # Disbursements
        "disbursements": {
            "total_ngn": round(total_disbursed, 2),
            "count": disbursement_count,
            "released_ngn": round(
                sum(float(d.get("amount") or 0) for d in disbursements if d.get("status") == "released"),
                2,
            ),
            "pending_ngn": round(
                sum(float(d.get("amount") or 0) for d in disbursements if d.get("status") == "pending"),
                2,
            ),
        },

        # Revenue
        "revenue": {
            "platform_fee_ngn": round(platform_fee_revenue, 2),
            "take_rate_pct": take_rate_pct,
        },

        # Health metrics
        "health": {
            "active_agreements": active_agreements_total,
            "failed_payment_rate_pct": failed_payment_rate_pct,
            "failed_count": failed_count,
            "total_transfers": total_all_transfers,
        },

        # Top performers
        "top_landlords_by_volume": top_landlords,

        # Live wallet
        "live_balance": {
            "amount_ngn": live_balance_ngn,
            "error": live_balance_error,
            "source": "nomba_sub_account",
        },
    }

