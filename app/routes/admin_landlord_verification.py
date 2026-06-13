"""
Landlord Verification Routes (OPTIMIZED)
Handles verification workflow - different from user management
Focus: Review and approve/reject landlord onboarding applications

🔧 FIX APPLIED: Added /recent endpoint with correct route ordering
✅ PRESERVED: All existing endpoints and functionality unchanged
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from app.database import supabase_admin
from app.middleware.auth import get_current_admin
from app.models.user import UserResponse
from app.services.notification_service import notification_service
from app.config import settings
from app.middleware.token_cache import token_cache
from typing import Dict, Any, Optional, Literal
from datetime import datetime, timedelta, timezone
import time
import asyncio

router = APIRouter(prefix="/landlord-verifications", tags=["Admin Landlord Verification"])

# In-memory cache
_cache = {}
_cache_ttl = {}

def get_cached(key: str, ttl_seconds: int = 60):
    """Get cached value if not expired"""
    if key in _cache and key in _cache_ttl:
        if time.time() < _cache_ttl[key]:
            print(f"💾 [CACHE HIT] {key}")
            return _cache[key]
    print(f"❌ [CACHE MISS] {key}")
    return None

def set_cached(key: str, value: Any, ttl_seconds: int = 60):
    """Set cached value with TTL"""
    _cache[key] = value
    _cache_ttl[key] = time.time() + ttl_seconds
    print(f"💾 [CACHE SET] {key} (TTL: {ttl_seconds}s)")


async def sync_verification_status(landlord_id: str, onboarding_id: str, new_status: str):
    """
    Sync verification status across tables.
    Critical: Keep users.verification_status in sync with landlord_onboarding.admin_review_status
    Handles: approved | rejected | needs_correction
    """
    try:
        print(f"🔄 [SYNC] Syncing verification status for landlord {landlord_id}")

        if new_status == 'approved':
            print(f"🔄 [SYNC] Updating user_type to 'landlord' and verification_status to 'approved' for landlord {landlord_id}")
            supabase_admin.table('users')\
                .update({
                    "user_type": "landlord",  # CRITICAL FIX: Ensure user_type remains landlord
                    "verification_status": "approved",
                    "trust_score": 80,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })\
                .eq('id', landlord_id)\
                .execute()
            print(f"✅ [SYNC] User table updated - user_type='landlord', verification_status='approved'")

            supabase_admin.table('landlord_profiles')\
                .update({
                    "verification_submitted_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })\
                .eq('id', landlord_id)\
                .execute()

            # CRITICAL: Sync Supabase auth metadata immediately after approval
            # This ensures frontend gets the updated verification_status without race conditions
            try:
                print(f"🔄 [SYNC] Updating Supabase auth metadata for landlord {landlord_id}")
                # Reset client to service role key BEFORE admin operations.
                # This is required — other requests mutate the shared client's
                # auth state and may leave it with the anon key.
                supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
                supabase_admin.auth.admin.update_user_by_id(
                    landlord_id,
                    {
                        "user_metadata": {
                            "verification_status": "approved",
                            "user_type": "landlord",  # reinforce correct type
                            "trust_score": 80
                        },
                        "app_metadata": {
                            "verification_status": "approved",
                            "user_type": "landlord",  # reinforce correct type
                            "trust_score": 80
                        }
                    }
                )
                print(f"✅ [SYNC] Auth metadata updated successfully for {landlord_id}")
            except Exception as auth_err:
                # Non-fatal — DB is already correct. Frontend reads user_type
                # and verification_status from DB, not JWT. The JWT will
                # self-heal when frontend calls supabase.auth.refreshSession().
                print(f"⚠️ [SYNC] Auth metadata update failed (non-fatal): {str(auth_err)}")

            print(f"✅ [SYNC] Approved: user.verification_status='approved', trust_score=80")

        elif new_status == 'rejected':
            supabase_admin.table('users')\
                .update({
                    "verification_status": "rejected",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })\
                .eq('id', landlord_id)\
                .execute()

            print(f"✅ [SYNC] Rejected: user.verification_status='rejected'")
            
            try:
                supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
                supabase_admin.auth.admin.update_user_by_id(
                    landlord_id,
                    {
                        "user_metadata": {
                            "verification_status": "rejected",
                            "user_type": "landlord"
                        }
                    }
                )
                print(f" [SYNC] Auth metadata updated for rejected landlord {landlord_id}")
            except Exception as auth_err:
                print(f" [SYNC] Auth metadata update failed for rejection (non-fatal): {str(auth_err)}")

        elif new_status == 'needs_correction':
            # Reset to pending so landlord can fix and resubmit
            supabase_admin.table('users')\
                .update({
                    "verification_status": "pending",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })\
                .eq('id', landlord_id)\
                .execute()

            print(f" [SYNC] Needs-correction: user.verification_status reset to 'pending'")
            
            try:
                supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
                supabase_admin.auth.admin.update_user_by_id(
                    landlord_id,
                    {
                        "user_metadata": {
                            "verification_status": "pending",
                            "user_type": "landlord"
                        }
                    }
                )
                print(f" [SYNC] Auth metadata updated for needs_correction landlord {landlord_id}")
            except Exception as auth_err:
                print(f" [SYNC] Auth metadata update failed for needs_correction (non-fatal): {str(auth_err)}")

        # Clear local route cache
        _cache.clear()
        _cache_ttl.clear()

        # Clear token cache so next API request re-reads user from DB
        # instead of returning cached stale data (user_type, verification_status)
        try:
            asyncio.create_task(token_cache.clear())
            print(" [SYNC] Token cache cleared — next request re-reads from DB")
        except Exception as cache_err:
            print(f" [SYNC] Token cache clear failed (non-fatal): {cache_err}")

    except Exception as e:
        print(f" [SYNC] Failed to sync: {str(e)}")
        # Don't raise - let the main operation succeed even if sync fails


@router.get("")
async def list_verifications(
    current_admin: UserResponse = Depends(get_current_admin),
    status_filter: Optional[Literal["partial", "pending", "in_review", "approved", "rejected", "needs_correction"]] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
) -> Dict[str, Any]:
    """
    Get landlord verification queue
    FIXED: Now queries from users table first (like management endpoint)
    Then enriches with landlord_onboarding details
    This ensures we capture pending_onboarding (partial) landlords too
    
    ✅ SAME SOURCE as landlord management endpoint for consistency
    """
    try:
        start_time = time.time()
        
        # Build cache key
        cache_key = f"verifications_s{status_filter}_p{page}_l{limit}"
        cached_result = get_cached(cache_key, ttl_seconds=30)
        if cached_result:
            return cached_result
        
        print(f"🔍 [VERIFICATION] Fetching verifications from users table...")
        
        # FIXED: Query ALL landlords FIRST (don't filter yet!)
        # We must apply smart status detection BEFORE filtering
        query = supabase_admin.table('users').select('*').eq('user_type', 'landlord')
        
        # ❌ DO NOT filter here - we need to apply smart detection logic first
        # if status_filter:
        #     query = query.eq('verification_status', status_filter)
        
        # Execute - get all landlords
        result = query.execute()
        all_users = result.data or []
        
        print(f"✅ [VERIFICATION] Found {len(all_users)} total landlords in users table")
        
        # Get all onboarding records for enrichment
        user_ids = [u['id'] for u in all_users]
        onboarding_map = {}
        
        if user_ids:
            onboarding_result = supabase_admin.table('landlord_onboarding')\
                .select('*')\
                .in_('landlord_id', user_ids)\
                .order('created_at', desc=True)\
                .execute()
            
            # Create map of landlord_id -> latest onboarding
            for ob in (onboarding_result.data or []):
                landlord_id = ob['landlord_id']
                if landlord_id not in onboarding_map:
                    onboarding_map[landlord_id] = ob
            
            print(f"✅ [VERIFICATION] Fetched {len(onboarding_map)} onboarding records")
        
        # IMPORTANT: Convert users to verification format with proper status distinction FIRST
        # This must happen BEFORE filtering so we can filter on the SMART status, not raw status
        # Key distinction:
        # - submitted_for_review=False → "awaiting_submission" (partial)
        # - submitted_for_review=True → "pending_review" (pending)
        all_verifications = []
        for user in all_users:
            user_id = user['id']
            onboarding = onboarding_map.get(user_id, {})
            
            # Determine true status based on onboarding submission
            true_status = user.get('verification_status')
            
            if onboarding:
                # If onboarding record exists, check if they submitted
                if not onboarding.get('submitted_for_review'):
                    true_status = 'partial'  # Awaiting submission
                elif onboarding.get('admin_review_status') == 'pending':
                    true_status = 'pending'  # Pending review
                else:
                    # Use the admin_review_status as truth source if submitted
                    true_status = onboarding.get('admin_review_status', true_status)
            else:
                # No onboarding record = just signed up = awaiting submission
                if user.get('verification_status') == 'pending':
                    true_status = 'partial'
            
            verification = {
                'id': f"verification_{user_id}",
                'landlord_id': user_id,
                'admin_review_status': true_status,  # Use corrected status
                'submitted_for_review': onboarding.get('submitted_for_review', False),
                'created_at': user.get('created_at'),
                'updated_at': user.get('updated_at'),
                'landlord': {
                    'id': user_id,
                    'email': user.get('email'),
                    'full_name': user.get('full_name'),
                    'avatar_url': user.get('avatar_url'),
                    'trust_score': user.get('trust_score', 50),
                    'verification_status': user.get('verification_status'),
                },
                'phone_number': user.get('phone_number') or onboarding.get('phone'),
                'account_type': onboarding.get('landlord_type') or 'individual',
                'company_name': onboarding.get('company_name'),
                'submitted_for_review_at': onboarding.get('submitted_for_review_at'),
                'submitted_at': onboarding.get('submitted_for_review_at'),
                'verification_submitted_at': onboarding.get('submitted_for_review_at'),
                # Debug info (optional, remove in production)
                'debug': {
                    'user_status': user.get('verification_status'),
                    'onboarding_exists': bool(onboarding),
                    'submitted_for_review': onboarding.get('submitted_for_review', False),
                }
            }
            
            all_verifications.append(verification)
        
        # NOW apply status filter on the SMART status, not raw user status
        # This ensures we filter by true_status (which includes submitted_for_review logic)
        if status_filter:
            # Map UI status to smart status
            smart_filter_status = 'partial' if status_filter == 'awaiting_submission' else status_filter
            all_verifications = [v for v in all_verifications if v.get('admin_review_status') == smart_filter_status]
            print(f"✅ [VERIFICATION] Filtered to {len(all_verifications)} with smart status '{smart_filter_status}'")
        
        # Paginate
        total = len(all_verifications)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated = all_verifications[start_idx:end_idx]
        
        response = {
            "success": True,
            "verifications": paginated,
            "pagination": {
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": (total + limit - 1) // limit
            }
        }
        
        # Cache result
        set_cached(cache_key, response, ttl_seconds=30)
        
        elapsed = time.time() - start_time
        print(f"✅ [VERIFICATION] Total time: {elapsed:.2f}s")
        
        return response
        
    except Exception as e:
        print(f"❌ [VERIFICATION] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch verifications: {str(e)}"
        )


@router.get("/stats")
async def get_verification_stats(
    current_admin: UserResponse = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Get verification statistics (cached for 60s)
    FIXED: Now properly distinguishes:
    - partial (awaiting_submission): verified_status='partial' OR onboarding.submitted_for_review=False
    - pending (pending_review): onboarding.submitted_for_review=True AND admin_review_status='pending'
    
    Key insight: Use landlord_onboarding.submitted_for_review as truth source
    """
    try:
        cache_key = "verification_stats"
        cached_result = get_cached(cache_key, ttl_seconds=60)
        if cached_result:
            return cached_result
        
        print(f"📊 [VERIFICATION-STATS] Calculating stats...")
        start_time = time.time()
        
        # Query all landlords from users table
        result = supabase_admin.table('users')\
            .select('id, verification_status')\
            .eq('user_type', 'landlord')\
            .execute()
        
        all_landlords = result.data or []
        
        # Get all onboarding records for status differentiation
        user_ids = [u['id'] for u in all_landlords]
        onboarding_map = {}
        
        if user_ids:
            onboarding_result = supabase_admin.table('landlord_onboarding')\
                .select('landlord_id, submitted_for_review, admin_review_status')\
                .in_('landlord_id', user_ids)\
                .execute()
            
            for ob in (onboarding_result.data or []):
                landlord_id = ob['landlord_id']
                if landlord_id not in onboarding_map:
                    onboarding_map[landlord_id] = ob
        
        # Categorize by true status (using submitted_for_review as key differentiator)
        stats = {
            "total": len(all_landlords),
            "partial": 0,      # Not submitted for review yet (awaiting submission)
            "pending": 0,      # Submitted but pending review
            "approved": 0,
            "rejected": 0,
            # Keep these for backward compatibility
            "in_review": 0,
            "needs_correction": 0,
            "not_submitted": 0,
            "awaiting_submission": 0
        }
        
        for user in all_landlords:
            user_id = user['id']
            user_status = user.get('verification_status')
            onboarding = onboarding_map.get(user_id)
            
            # Determine true status
            if onboarding:
                if not onboarding.get('submitted_for_review'):
                    # Has onboarding record but hasn't submitted = partial/awaiting
                    stats["partial"] += 1
                    stats["awaiting_submission"] += 1
                elif onboarding.get('admin_review_status') == 'pending':
                    # Submitted but not yet reviewed = pending
                    stats["pending"] += 1
                elif onboarding.get('admin_review_status') == 'approved':
                    stats["approved"] += 1
                elif onboarding.get('admin_review_status') == 'rejected':
                    stats["rejected"] += 1
                elif onboarding.get('admin_review_status') == 'needs_correction':
                    stats["needs_correction"] += 1
            else:
                # No onboarding record = just signed up = partial
                if user_status == 'pending':
                    stats["partial"] += 1
                    stats["awaiting_submission"] += 1
                elif user_status == 'approved':
                    stats["approved"] += 1
                elif user_status == 'rejected':
                    stats["rejected"] += 1
        
        # Cache result
        set_cached(cache_key, stats, ttl_seconds=60)
        
        elapsed = time.time() - start_time
        print(f"✅ [VERIFICATION-STATS] Stats: {stats} ({elapsed:.2f}s)")
        
        return stats
        
    except Exception as e:
        print(f"❌ [VERIFICATION-STATS] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch stats: {str(e)}"
        )


@router.get("/awaiting-submission")
async def get_awaiting_submission_landlords(
    current_admin: UserResponse = Depends(get_current_admin),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
) -> Dict[str, Any]:
    """
    Get landlords awaiting submission (in onboarding, haven't submitted docs yet)
    These are landlords with verification_status = 'pending_onboarding'
    Shows them with admin_review_status = 'awaiting_submission' for UI consistency
    """
    try:
        start_time = time.time()
        
        cache_key = f"awaiting_submission_p{page}_l{limit}"
        cached_result = get_cached(cache_key, ttl_seconds=30)
        if cached_result:
            return cached_result
        
        print(f"🔍 [AWAITING-SUBMISSION] Fetching landlords in onboarding...")
        
        # Get all landlords in pending_onboarding status (just signed up, not completed onboarding)
        users_result = supabase_admin.table('users')\
            .select('id, email, full_name, avatar_url, trust_score, phone_number, created_at')\
            .eq('verification_status', 'pending_onboarding')\
            .eq('user_type', 'landlord')\
            .order('created_at', desc=True)\
            .execute()
        
        all_landlords = users_result.data or []
        print(f"✅ [AWAITING-SUBMISSION] Found {len(all_landlords)} landlords awaiting submission")
        
        # Format response to match verification format
        formatted_landlords = []
        for idx, landlord in enumerate(all_landlords):
            formatted_landlords.append({
                'id': f"awaiting_{landlord['id']}_{idx}",
                'landlord_id': landlord['id'],
                'admin_review_status': 'awaiting_submission',
                'submitted_for_review': False,
                'created_at': landlord['created_at'],
                'landlord': {
                    'id': landlord['id'],
                    'email': landlord['email'],
                    'full_name': landlord['full_name'],
                    'avatar_url': landlord['avatar_url'],
                    'trust_score': landlord['trust_score'],
                    'verification_status': 'pending_onboarding'
                },
                'phone_number': landlord.get('phone_number'),
                'account_type': 'individual'
            })
        
        # Paginate
        total = len(all_landlords)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated = formatted_landlords[start_idx:end_idx]
        
        response = {
            "success": True,
            "verifications": paginated,
            "pagination": {
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": (total + limit - 1) // limit
            }
        }
        
        set_cached(cache_key, response, ttl_seconds=30)
        elapsed = time.time() - start_time
        print(f"✅ [AWAITING-SUBMISSION] Total time: {elapsed:.2f}s")
        
        return response
        
    except Exception as e:
        print(f"❌ [AWAITING-SUBMISSION] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch awaiting submission landlords: {str(e)}"
        )


@router.get("/recent")
async def get_recent_verifications(
    current_admin: UserResponse = Depends(get_current_admin),
    days: int = Query(7, ge=1, le=90)
) -> Dict[str, Any]:
    """
    Get recent verification submissions
    
    🆕 NEW ENDPOINT: Added to fix the 500 error
    ⚠️ CRITICAL: This route MUST be defined BEFORE /{verification_id}
    Otherwise FastAPI treats "recent" as a verification_id parameter!
    """
    try:
        print(f"🔍 [VERIFICATION-RECENT] Fetching submissions from last {days} days")
        start_time = time.time()
        
        # Build cache key
        cache_key = f"verification_recent_{days}"
        cached_result = get_cached(cache_key, ttl_seconds=60)
        if cached_result:
            return cached_result
        
        # Calculate cutoff date
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        # Query recent submissions
        result = supabase_admin.table('landlord_onboarding')\
            .select('*')\
            .gte('submitted_for_review_at', cutoff_date)\
            .not_.is_('submitted_for_review_at', 'null')\
            .order('submitted_for_review_at', desc=True)\
            .limit(50)\
            .execute()
        
        submissions = result.data or []
        
        # Enrich with landlord details
        if submissions:
            landlord_ids = [s['landlord_id'] for s in submissions if s.get('landlord_id')]
            
            if landlord_ids:
                landlords_result = supabase_admin.table('users')\
                    .select('id, email, full_name, avatar_url, trust_score')\
                    .in_('id', landlord_ids)\
                    .execute()
                
                landlords_map = {l['id']: l for l in (landlords_result.data or [])}
                
                # Enrich submissions with landlord info
                for submission in submissions:
                    landlord_id = submission.get('landlord_id')
                    if landlord_id and landlord_id in landlords_map:
                        submission['landlord'] = landlords_map[landlord_id]
        
        response = {
            "success": True,
            "submissions": submissions,
            "period_days": days,
            "count": len(submissions)
        }
        
        # Cache result
        set_cached(cache_key, response, ttl_seconds=60)
        
        elapsed = time.time() - start_time
        print(f"✅ [VERIFICATION-RECENT] Found {len(submissions)} recent submissions ({elapsed:.2f}s)")
        
        return response
        
    except Exception as e:
        print(f"❌ [VERIFICATION-RECENT] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch recent verifications: {str(e)}"
        )


@router.get("/{verification_id}")
async def get_verification_detail(
    verification_id: str,
    current_admin: UserResponse = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Get detailed verification information
    
    ⚠️ CRITICAL: This route MUST be defined AFTER /stats and /recent
    Otherwise it will intercept those routes!
    
    ✅ UNCHANGED: This endpoint remains exactly the same
    """
    try:
        print(f"🔍 [VERIFICATION-DETAIL] Fetching verification {verification_id}")
        
        # Get onboarding record
        onboarding_result = supabase_admin.table('landlord_onboarding')\
            .select('*')\
            .eq('id', verification_id)\
            .single()\
            .execute()
        
        if not onboarding_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Verification not found"
            )
        
        onboarding = onboarding_result.data
        landlord_id = onboarding['landlord_id']
        
        # Get user info - select only needed fields to speed up query
        user_result = supabase_admin.table('users')\
            .select('id, email, full_name, avatar_url, trust_score, phone_number')\
            .eq('id', landlord_id)\
            .single()\
            .execute()
        
        user = user_result.data if user_result.data else {}
        
        # Get document processing jobs - select only needed fields
        jobs = []
        try:
            jobs_result = supabase_admin.table('document_processing_jobs')\
                .select('id, job_status, document_type')\
                .eq('onboarding_id', verification_id)\
                .execute()
            jobs = jobs_result.data or []
        except Exception as jobs_err:
            print(f"⚠️ [VERIFICATION-DETAIL] Failed to fetch jobs: {str(jobs_err)}")
            # Continue without jobs data - don't fail the whole request
            jobs = []
        
        # Get properties if first_property_id exists
        property_info = None
        if onboarding.get('first_property_id'):
            try:
                property_result = supabase_admin.table('properties')\
                    .select('id, title, rent_amount, location, status')\
                    .eq('id', onboarding['first_property_id'])\
                    .single()\
                    .execute()
                property_info = property_result.data if property_result.data else None
            except Exception as prop_err:
                print(f"⚠️ [VERIFICATION-DETAIL] Failed to fetch property: {str(prop_err)}")
                property_info = None
        
        response = {
            "success": True,
            "verification": {
                **onboarding,
                # Create nested landlord object as expected by frontend
                "landlord": {
                    "id": landlord_id,
                    "email": user.get('email'),
                    "full_name": user.get('full_name'),
                    "avatar_url": user.get('avatar_url'),
                    "trust_score": user.get('trust_score', 50)
                },
                # Map backend fields to frontend expectations
                "phone_number": user.get('phone_number', onboarding.get('phone_number')),  # Use user phone_number first, fallback to onboarding
                "admin_notes": onboarding.get('admin_feedback'),
                "document_jobs": jobs,
                "first_property": property_info,
                "documents_count": {
                    "total": len(jobs),
                    "completed": len([j for j in jobs if j.get('job_status') == 'completed']),
                    "processing": len([j for j in jobs if j.get('job_status') == 'processing']),
                    "failed": len([j for j in jobs if j.get('job_status') == 'failed'])
                }
            }
        }
        
        print(f"✅ [VERIFICATION-DETAIL] Retrieved verification details")
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        print(f"❌ [VERIFICATION-DETAIL] Error: {error_msg}")
        
        # Handle SSL timeout specifically
        if "SSL handshake" in error_msg or "timeout" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service temporarily unavailable due to network issues. Please try again."
            )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch verification details: {error_msg}"
        )


@router.post("/{verification_id}/review")
async def review_verification(
    verification_id: str,
    review_data: Dict[str, Any],
    background_tasks: BackgroundTasks,
    current_admin: UserResponse = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Approve or reject a landlord verification
    
    IMPORTANT: This syncs status across all related tables
    
    Request body:
    {
      "admin_review_status": "approved" | "rejected" | "needs_correction",
      "admin_feedback": "Optional feedback message",
      "nin_verified": true,
      "bvn_verified": true,
      "id_document_verified": true,
      "selfie_verified": true,
      "bank_verification_status": "verified"
    }
    
    ✅ UNCHANGED: This endpoint remains exactly the same
    """
    try:
        print(f"✏️ [VERIFICATION-REVIEW] Reviewing verification {verification_id}")
        
        # Get onboarding record
        onboarding_result = supabase_admin.table('landlord_onboarding')\
            .select('landlord_id, admin_review_status')\
            .eq('id', verification_id)\
            .single()\
            .execute()
        
        if not onboarding_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Verification not found"
            )
        
        landlord_id = onboarding_result.data['landlord_id']
        new_status = review_data.get('admin_review_status')
        
        if not new_status:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="admin_review_status is required"
            )
        
        # Get admin ID safely
        admin_id = current_admin.get('id') if isinstance(current_admin, dict) else current_admin.id
        
        # Prepare update
        update_dict = {
            "admin_review_status": new_status,
            "admin_reviewer_id": admin_id,
            "admin_reviewed_at": datetime.now(timezone.utc).isoformat(),
            "last_updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add optional fields
        if 'admin_feedback' in review_data:
            update_dict['admin_feedback'] = review_data['admin_feedback']
        
        if 'nin_verified' in review_data:
            update_dict['nin_verified'] = review_data['nin_verified']
        
        if 'bvn_verified' in review_data:
            update_dict['bvn_verified'] = review_data['bvn_verified']
        
        if 'id_document_verified' in review_data:
            update_dict['id_document_verified'] = review_data['id_document_verified']
        
        if 'selfie_verified' in review_data:
            update_dict['selfie_verified'] = review_data['selfie_verified']
        
        if 'bank_verification_status' in review_data:
            update_dict['bank_verification_status'] = review_data['bank_verification_status']
        
        # Update onboarding record
        update_result = supabase_admin.table('landlord_onboarding')\
            .update(update_dict)\
            .eq('id', verification_id)\
            .execute()
        
        if not update_result.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update verification"
            )
        
        # Sync status across tables
        await sync_verification_status(
            landlord_id=landlord_id,
            onboarding_id=verification_id,
            new_status=new_status
        )

        # Fetch landlord details for notifications (email + full_name)
        landlord_row = supabase_admin.table('users')\
            .select('email, full_name')\
            .eq('id', landlord_id)\
            .execute()
        landlord = landlord_row.data[0] if landlord_row.data else {}
        landlord_email = landlord.get('email', '')
        landlord_name  = landlord.get('full_name') or 'Landlord'

        if new_status == 'approved':
            background_tasks.add_task(
                notification_service.notify_verification_approved,
                user_id=landlord_id,
                user_email=landlord_email,
                user_name=landlord_name,
                trust_score=80,
            )
            print(f"✅ [VERIFICATION-REVIEW] Approval notification queued for {landlord_email}")

        elif new_status == 'rejected':
            background_tasks.add_task(
                notification_service.notify_verification_rejected,
                user_id=landlord_id,
                user_email=landlord_email,
                user_name=landlord_name,
                rejection_reason=review_data.get('admin_feedback') or 'Your documents could not be verified.',
                onboarding_id=verification_id,
            )
            print(f"✅ [VERIFICATION-REVIEW] Rejection notification queued for {landlord_email}")

        elif new_status == 'needs_correction':
            background_tasks.add_task(
                notification_service.notify_verification_needs_correction,
                user_id=landlord_id,
                user_email=landlord_email,
                user_name=landlord_name,
                admin_feedback=review_data.get('admin_feedback') or 'Please review and resubmit your documents.',
                onboarding_id=verification_id,
            )
            print(f"✅ [VERIFICATION-REVIEW] Needs-correction notification queued for {landlord_email}")

        print(f"✅ [VERIFICATION-REVIEW] Review completed: {new_status}")
        
        return {
            "success": True,
            "message": f"Verification {new_status}",
            "verification": update_result.data[0]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [VERIFICATION-REVIEW] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to review verification: {str(e)}"
        )


@router.post("/{verification_id}/request-correction")
async def request_correction(
    verification_id: str,
    correction_data: Dict[str, Any],
    current_admin: UserResponse = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Request corrections from landlord
    
    ✅ UNCHANGED: This endpoint remains exactly the same
    """
    try:
        print(f"📝 [CORRECTION] Requesting correction for {verification_id}")
        
        feedback = correction_data.get('feedback', '')
        corrections_needed = correction_data.get('corrections_needed', [])
        
        # Get admin ID safely
        admin_id = current_admin.get('id') if isinstance(current_admin, dict) else current_admin.id
        
        # Update onboarding
        update_dict = {
            "admin_review_status": "needs_correction",
            "admin_feedback": feedback,
            "admin_reviewer_id": admin_id,
            "admin_reviewed_at": datetime.now(timezone.utc).isoformat(),
            "last_updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add corrections metadata
        if corrections_needed:
            update_dict['documents'] = {
                "corrections_needed": corrections_needed,
                "requested_at": datetime.now(timezone.utc).isoformat()
            }
        
        update_result = supabase_admin.table('landlord_onboarding')\
            .update(update_dict)\
            .eq('id', verification_id)\
            .execute()
        
        # Clear caches
        _cache.clear()
        _cache_ttl.clear()
        
        print(f"✅ [CORRECTION] Correction requested")
        
        return {
            "success": True,
            "message": "Correction requested successfully",
            "verification": update_result.data[0] if update_result.data else None
        }
        
    except Exception as e:
        print(f"❌ [CORRECTION] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to request correction: {str(e)}"
        )













# """
# Landlord Verification Routes (OPTIMIZED)
# Handles verification workflow - different from user management
# Focus: Review and approve/reject landlord onboarding applications

# 🔧 FIX APPLIED: Added /recent endpoint with correct route ordering
# ✅ PRESERVED: All existing endpoints and functionality unchanged
# """

# from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
# from app.database import supabase_admin
# from app.middleware.auth import get_current_admin
# from app.models.user import UserResponse
# from app.services.notification_service import notification_service
# from app.config import settings
# from app.middleware.token_cache import token_cache
# from typing import Dict, Any, Optional, Literal
# from datetime import datetime, timedelta, timezone
# import time
# import asyncio

# router = APIRouter(prefix="/landlord-verifications", tags=["Admin Landlord Verification"])

# # In-memory cache
# _cache = {}
# _cache_ttl = {}

# def get_cached(key: str, ttl_seconds: int = 60):
#     """Get cached value if not expired"""
#     if key in _cache and key in _cache_ttl:
#         if time.time() < _cache_ttl[key]:
#             print(f"💾 [CACHE HIT] {key}")
#             return _cache[key]
#     print(f"❌ [CACHE MISS] {key}")
#     return None

# def set_cached(key: str, value: Any, ttl_seconds: int = 60):
#     """Set cached value with TTL"""
#     _cache[key] = value
#     _cache_ttl[key] = time.time() + ttl_seconds
#     print(f"💾 [CACHE SET] {key} (TTL: {ttl_seconds}s)")


# async def sync_verification_status(landlord_id: str, onboarding_id: str, new_status: str):
#     """
#     Sync verification status across tables.
#     Critical: Keep users.verification_status in sync with landlord_onboarding.admin_review_status
#     Handles: approved | rejected | needs_correction
#     """
#     try:
#         print(f"🔄 [SYNC] Syncing verification status for landlord {landlord_id}")

#         if new_status == 'approved':
#             print(f"🔄 [SYNC] Updating user_type to 'landlord' and verification_status to 'approved' for landlord {landlord_id}")
#             supabase_admin.table('users')\
#                 .update({
#                     "user_type": "landlord",  # CRITICAL FIX: Ensure user_type remains landlord
#                     "verification_status": "approved",
#                     "trust_score": 80,
#                     "updated_at": datetime.now(timezone.utc).isoformat()
#                 })\
#                 .eq('id', landlord_id)\
#                 .execute()
#             print(f"✅ [SYNC] User table updated - user_type='landlord', verification_status='approved'")

#             supabase_admin.table('landlord_profiles')\
#                 .update({
#                     "verification_submitted_at": datetime.now(timezone.utc).isoformat(),
#                     "updated_at": datetime.now(timezone.utc).isoformat()
#                 })\
#                 .eq('id', landlord_id)\
#                 .execute()

#             # CRITICAL: Sync Supabase auth metadata immediately after approval
#             # This ensures frontend gets the updated verification_status without race conditions
#             try:
#                 print(f"🔄 [SYNC] Updating Supabase auth metadata for landlord {landlord_id}")
#                 # Reset client to service role key BEFORE admin operations.
#                 # This is required — other requests mutate the shared client's
#                 # auth state and may leave it with the anon key.
#                 supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
#                 supabase_admin.auth.admin.update_user_by_id(
#                     landlord_id,
#                     {
#                         "user_metadata": {
#                             "verification_status": "approved",
#                             "user_type": "landlord",  # reinforce correct type
#                             "trust_score": 80
#                         },
#                         "app_metadata": {
#                             "verification_status": "approved",
#                             "user_type": "landlord",  # reinforce correct type
#                             "trust_score": 80
#                         }
#                     }
#                 )
#                 print(f"✅ [SYNC] Auth metadata updated successfully for {landlord_id}")
#             except Exception as auth_err:
#                 # Non-fatal — DB is already correct. Frontend reads user_type
#                 # and verification_status from DB, not JWT. The JWT will
#                 # self-heal when frontend calls supabase.auth.refreshSession().
#                 print(f"⚠️ [SYNC] Auth metadata update failed (non-fatal): {str(auth_err)}")

#             print(f"✅ [SYNC] Approved: user.verification_status='approved', trust_score=80")

#         elif new_status == 'rejected':
#             supabase_admin.table('users')\
#                 .update({
#                     "verification_status": "rejected",
#                     "updated_at": datetime.now(timezone.utc).isoformat()
#                 })\
#                 .eq('id', landlord_id)\
#                 .execute()

#             print(f"✅ [SYNC] Rejected: user.verification_status='rejected'")
            
#             try:
#                 supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
#                 supabase_admin.auth.admin.update_user_by_id(
#                     landlord_id,
#                     {
#                         "user_metadata": {
#                             "verification_status": "rejected",
#                             "user_type": "landlord"
#                         }
#                     }
#                 )
#                 print(f" [SYNC] Auth metadata updated for rejected landlord {landlord_id}")
#             except Exception as auth_err:
#                 print(f" [SYNC] Auth metadata update failed for rejection (non-fatal): {str(auth_err)}")

#         elif new_status == 'needs_correction':
#             # Reset to pending so landlord can fix and resubmit
#             supabase_admin.table('users')\
#                 .update({
#                     "verification_status": "pending",
#                     "updated_at": datetime.now(timezone.utc).isoformat()
#                 })\
#                 .eq('id', landlord_id)\
#                 .execute()

#             print(f" [SYNC] Needs-correction: user.verification_status reset to 'pending'")
            
#             try:
#                 supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
#                 supabase_admin.auth.admin.update_user_by_id(
#                     landlord_id,
#                     {
#                         "user_metadata": {
#                             "verification_status": "pending",
#                             "user_type": "landlord"
#                         }
#                     }
#                 )
#                 print(f" [SYNC] Auth metadata updated for needs_correction landlord {landlord_id}")
#             except Exception as auth_err:
#                 print(f" [SYNC] Auth metadata update failed for needs_correction (non-fatal): {str(auth_err)}")

#         # Clear local route cache
#         _cache.clear()
#         _cache_ttl.clear()

#         # Clear token cache so next API request re-reads user from DB
#         # instead of returning cached stale data (user_type, verification_status)
#         try:
#             asyncio.create_task(token_cache.clear())
#             print(" [SYNC] Token cache cleared — next request re-reads from DB")
#         except Exception as cache_err:
#             print(f" [SYNC] Token cache clear failed (non-fatal): {cache_err}")

#     except Exception as e:
#         print(f" [SYNC] Failed to sync: {str(e)}")
#         # Don't raise - let the main operation succeed even if sync fails


# @router.get("")
# async def list_verifications(
#     current_admin: UserResponse = Depends(get_current_admin),
#     status_filter: Optional[Literal["pending", "in_review", "approved", "rejected", "needs_correction"]] = None,
#     page: int = Query(1, ge=1),
#     limit: int = Query(20, ge=1, le=100)
# ) -> Dict[str, Any]:
#     """
#     Get landlord verification queue
#     Uses v_admin_onboarding_queue view for optimized queries
    
#     ✅ UNCHANGED: This endpoint remains exactly the same
#     """
#     try:
#         start_time = time.time()
        
#         # Build cache key
#         cache_key = f"verifications_s{status_filter}_p{page}_l{limit}"
#         cached_result = get_cached(cache_key, ttl_seconds=30)
#         if cached_result:
#             return cached_result
        
#         print(f"🔍 [VERIFICATION] Fetching verifications...")
        
#         # Use the database view for better performance
#         query = supabase_admin.table('v_admin_onboarding_queue').select('*')
        
#         if status_filter:
#             query = query.eq('admin_review_status', status_filter)
        
#         query = query.order('submitted_for_review_at', desc=True)
        
#         # Execute
#         result = query.execute()
#         all_verifications = result.data or []
        
#         print(f" [VERIFICATION] Found {len(all_verifications)} verifications")
        
#         # Enrich with landlord details
#         if all_verifications:
#             landlord_ids = [v['landlord_id'] for v in all_verifications]
            
#             users_result = supabase_admin.table('users')\
#                 .select('id, email, full_name, avatar_url, trust_score, phone_number')\
#                 .in_('id', landlord_ids)\
#                 .execute()
            
#             user_map = {u['id']: u for u in (users_result.data or [])}
            
#             for verification in all_verifications:
#                 landlord_id = verification['landlord_id']
#                 user = user_map.get(landlord_id, {})
                
#                 # Create nested landlord object as expected by frontend
#                 verification['landlord'] = {
#                     'id': landlord_id,
#                     'email': user.get('email'),
#                     'full_name': user.get('full_name'),
#                     'avatar_url': user.get('avatar_url'),
#                     'trust_score': user.get('trust_score', 50)
#                 }
                
#                 # Map backend fields to frontend expectations
#                 if 'phone_number' in verification or user.get('phone_number'):
#                     verification['phone_number'] = user.get('phone_number', verification.get('phone_number'))  # Use user phone first
                
#                 # Map landlord_type to account_type for frontend compatibility
#                 if 'landlord_type' in verification:
#                     verification['account_type'] = verification['landlord_type']
        
#         # Paginate
#         total = len(all_verifications)
#         start_idx = (page - 1) * limit
#         end_idx = start_idx + limit
#         paginated = all_verifications[start_idx:end_idx]
        
#         response = {
#             "success": True,
#             "verifications": paginated,
#             "pagination": {
#                 "total": total,
#                 "page": page,
#                 "limit": limit,
#                 "total_pages": (total + limit - 1) // limit
#             }
#         }
        
#         # Cache result
#         set_cached(cache_key, response, ttl_seconds=30)
        
#         elapsed = time.time() - start_time
#         print(f"✅ [VERIFICATION] Total time: {elapsed:.2f}s")
        
#         return response
        
#     except Exception as e:
#         print(f"❌ [VERIFICATION] Error: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to fetch verifications: {str(e)}"
#         )


# @router.get("/stats")
# async def get_verification_stats(
#     current_admin: UserResponse = Depends(get_current_admin)
# ) -> Dict[str, Any]:
#     """
#     Get verification statistics (cached for 60s)
    
#     ✅ UNCHANGED: This endpoint remains exactly the same
#     """
#     try:
#         cache_key = "verification_stats"
#         cached_result = get_cached(cache_key, ttl_seconds=60)
#         if cached_result:
#             return cached_result
        
#         print(f"📊 [VERIFICATION-STATS] Calculating stats...")
#         start_time = time.time()
        
#         # Get all onboarding records
#         result = supabase_admin.table('landlord_onboarding')\
#             .select('admin_review_status, submitted_for_review')\
#             .execute()
        
#         verifications = result.data or []
        
#         # Calculate stats
#         stats = {
#             "total": len(verifications),
#             "pending": len([v for v in verifications if v.get('admin_review_status') == 'pending']),
#             "in_review": len([v for v in verifications if v.get('admin_review_status') == 'in_review']),
#             "approved": len([v for v in verifications if v.get('admin_review_status') == 'approved']),
#             "rejected": len([v for v in verifications if v.get('admin_review_status') == 'rejected']),
#             "needs_correction": len([v for v in verifications if v.get('admin_review_status') == 'needs_correction']),
#             "not_submitted": len([v for v in verifications if not v.get('submitted_for_review')])
#         }
        
#         # Cache result
#         set_cached(cache_key, stats, ttl_seconds=60)
        
#         elapsed = time.time() - start_time
#         print(f"✅ [VERIFICATION-STATS] Stats: {stats} ({elapsed:.2f}s)")
        
#         return stats
        
#     except Exception as e:
#         print(f"❌ [VERIFICATION-STATS] Error: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to fetch stats: {str(e)}"
#         )


# @router.get("/recent")
# async def get_recent_verifications(
#     current_admin: UserResponse = Depends(get_current_admin),
#     days: int = Query(7, ge=1, le=90)
# ) -> Dict[str, Any]:
#     """
#     Get recent verification submissions
    
#     🆕 NEW ENDPOINT: Added to fix the 500 error
#     ⚠️ CRITICAL: This route MUST be defined BEFORE /{verification_id}
#     Otherwise FastAPI treats "recent" as a verification_id parameter!
#     """
#     try:
#         print(f"🔍 [VERIFICATION-RECENT] Fetching submissions from last {days} days")
#         start_time = time.time()
        
#         # Build cache key
#         cache_key = f"verification_recent_{days}"
#         cached_result = get_cached(cache_key, ttl_seconds=60)
#         if cached_result:
#             return cached_result
        
#         # Calculate cutoff date
#         cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
#         # Query recent submissions
#         result = supabase_admin.table('landlord_onboarding')\
#             .select('*')\
#             .gte('submitted_for_review_at', cutoff_date)\
#             .not_.is_('submitted_for_review_at', 'null')\
#             .order('submitted_for_review_at', desc=True)\
#             .limit(50)\
#             .execute()
        
#         submissions = result.data or []
        
#         # Enrich with landlord details
#         if submissions:
#             landlord_ids = [s['landlord_id'] for s in submissions if s.get('landlord_id')]
            
#             if landlord_ids:
#                 landlords_result = supabase_admin.table('users')\
#                     .select('id, email, full_name, avatar_url, trust_score')\
#                     .in_('id', landlord_ids)\
#                     .execute()
                
#                 landlords_map = {l['id']: l for l in (landlords_result.data or [])}
                
#                 # Enrich submissions with landlord info
#                 for submission in submissions:
#                     landlord_id = submission.get('landlord_id')
#                     if landlord_id and landlord_id in landlords_map:
#                         submission['landlord'] = landlords_map[landlord_id]
        
#         response = {
#             "success": True,
#             "submissions": submissions,
#             "period_days": days,
#             "count": len(submissions)
#         }
        
#         # Cache result
#         set_cached(cache_key, response, ttl_seconds=60)
        
#         elapsed = time.time() - start_time
#         print(f"✅ [VERIFICATION-RECENT] Found {len(submissions)} recent submissions ({elapsed:.2f}s)")
        
#         return response
        
#     except Exception as e:
#         print(f"❌ [VERIFICATION-RECENT] Error: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to fetch recent verifications: {str(e)}"
#         )


# @router.get("/{verification_id}")
# async def get_verification_detail(
#     verification_id: str,
#     current_admin: UserResponse = Depends(get_current_admin)
# ) -> Dict[str, Any]:
#     """
#     Get detailed verification information
    
#     ⚠️ CRITICAL: This route MUST be defined AFTER /stats and /recent
#     Otherwise it will intercept those routes!
    
#     ✅ UNCHANGED: This endpoint remains exactly the same
#     """
#     try:
#         print(f"🔍 [VERIFICATION-DETAIL] Fetching verification {verification_id}")
        
#         # Get onboarding record
#         onboarding_result = supabase_admin.table('landlord_onboarding')\
#             .select('*')\
#             .eq('id', verification_id)\
#             .single()\
#             .execute()
        
#         if not onboarding_result.data:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Verification not found"
#             )
        
#         onboarding = onboarding_result.data
#         landlord_id = onboarding['landlord_id']
        
#         # Get user info - select only needed fields to speed up query
#         user_result = supabase_admin.table('users')\
#             .select('id, email, full_name, avatar_url, trust_score, phone_number')\
#             .eq('id', landlord_id)\
#             .single()\
#             .execute()
        
#         user = user_result.data if user_result.data else {}
        
#         # Get document processing jobs - select only needed fields
#         jobs = []
#         try:
#             jobs_result = supabase_admin.table('document_processing_jobs')\
#                 .select('id, job_status, document_type')\
#                 .eq('onboarding_id', verification_id)\
#                 .execute()
#             jobs = jobs_result.data or []
#         except Exception as jobs_err:
#             print(f"⚠️ [VERIFICATION-DETAIL] Failed to fetch jobs: {str(jobs_err)}")
#             # Continue without jobs data - don't fail the whole request
#             jobs = []
        
#         # Get properties if first_property_id exists
#         property_info = None
#         if onboarding.get('first_property_id'):
#             try:
#                 property_result = supabase_admin.table('properties')\
#                     .select('id, title, rent_amount, location, status')\
#                     .eq('id', onboarding['first_property_id'])\
#                     .single()\
#                     .execute()
#                 property_info = property_result.data if property_result.data else None
#             except Exception as prop_err:
#                 print(f"⚠️ [VERIFICATION-DETAIL] Failed to fetch property: {str(prop_err)}")
#                 property_info = None
        
#         response = {
#             "success": True,
#             "verification": {
#                 **onboarding,
#                 # Create nested landlord object as expected by frontend
#                 "landlord": {
#                     "id": landlord_id,
#                     "email": user.get('email'),
#                     "full_name": user.get('full_name'),
#                     "avatar_url": user.get('avatar_url'),
#                     "trust_score": user.get('trust_score', 50)
#                 },
#                 # Map backend fields to frontend expectations
#                 "phone_number": user.get('phone_number', onboarding.get('phone_number')),  # Use user phone_number first, fallback to onboarding
#                 "admin_notes": onboarding.get('admin_feedback'),
#                 "document_jobs": jobs,
#                 "first_property": property_info,
#                 "documents_count": {
#                     "total": len(jobs),
#                     "completed": len([j for j in jobs if j.get('job_status') == 'completed']),
#                     "processing": len([j for j in jobs if j.get('job_status') == 'processing']),
#                     "failed": len([j for j in jobs if j.get('job_status') == 'failed'])
#                 }
#             }
#         }
        
#         print(f"✅ [VERIFICATION-DETAIL] Retrieved verification details")
        
#         return response
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         error_msg = str(e)
#         print(f"❌ [VERIFICATION-DETAIL] Error: {error_msg}")
        
#         # Handle SSL timeout specifically
#         if "SSL handshake" in error_msg or "timeout" in error_msg.lower():
#             raise HTTPException(
#                 status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
#                 detail="Service temporarily unavailable due to network issues. Please try again."
#             )
        
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to fetch verification details: {error_msg}"
#         )


# @router.post("/{verification_id}/review")
# async def review_verification(
#     verification_id: str,
#     review_data: Dict[str, Any],
#     background_tasks: BackgroundTasks,
#     current_admin: UserResponse = Depends(get_current_admin)
# ) -> Dict[str, Any]:
#     """
#     Approve or reject a landlord verification
    
#     IMPORTANT: This syncs status across all related tables
    
#     Request body:
#     {
#       "admin_review_status": "approved" | "rejected" | "needs_correction",
#       "admin_feedback": "Optional feedback message",
#       "nin_verified": true,
#       "bvn_verified": true,
#       "id_document_verified": true,
#       "selfie_verified": true,
#       "bank_verification_status": "verified"
#     }
    
#     ✅ UNCHANGED: This endpoint remains exactly the same
#     """
#     try:
#         print(f"✏️ [VERIFICATION-REVIEW] Reviewing verification {verification_id}")
        
#         # Get onboarding record
#         onboarding_result = supabase_admin.table('landlord_onboarding')\
#             .select('landlord_id, admin_review_status')\
#             .eq('id', verification_id)\
#             .single()\
#             .execute()
        
#         if not onboarding_result.data:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Verification not found"
#             )
        
#         landlord_id = onboarding_result.data['landlord_id']
#         new_status = review_data.get('admin_review_status')
        
#         if not new_status:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="admin_review_status is required"
#             )
        
#         # Get admin ID safely
#         admin_id = current_admin.get('id') if isinstance(current_admin, dict) else current_admin.id
        
#         # Prepare update
#         update_dict = {
#             "admin_review_status": new_status,
#             "admin_reviewer_id": admin_id,
#             "admin_reviewed_at": datetime.now(timezone.utc).isoformat(),
#             "last_updated_at": datetime.now(timezone.utc).isoformat()
#         }
        
#         # Add optional fields
#         if 'admin_feedback' in review_data:
#             update_dict['admin_feedback'] = review_data['admin_feedback']
        
#         if 'nin_verified' in review_data:
#             update_dict['nin_verified'] = review_data['nin_verified']
        
#         if 'bvn_verified' in review_data:
#             update_dict['bvn_verified'] = review_data['bvn_verified']
        
#         if 'id_document_verified' in review_data:
#             update_dict['id_document_verified'] = review_data['id_document_verified']
        
#         if 'selfie_verified' in review_data:
#             update_dict['selfie_verified'] = review_data['selfie_verified']
        
#         if 'bank_verification_status' in review_data:
#             update_dict['bank_verification_status'] = review_data['bank_verification_status']
        
#         # Update onboarding record
#         update_result = supabase_admin.table('landlord_onboarding')\
#             .update(update_dict)\
#             .eq('id', verification_id)\
#             .execute()
        
#         if not update_result.data:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Failed to update verification"
#             )
        
#         # Sync status across tables
#         await sync_verification_status(
#             landlord_id=landlord_id,
#             onboarding_id=verification_id,
#             new_status=new_status
#         )

#         # Fetch landlord details for notifications (email + full_name)
#         landlord_row = supabase_admin.table('users')\
#             .select('email, full_name')\
#             .eq('id', landlord_id)\
#             .execute()
#         landlord = landlord_row.data[0] if landlord_row.data else {}
#         landlord_email = landlord.get('email', '')
#         landlord_name  = landlord.get('full_name') or 'Landlord'

#         if new_status == 'approved':
#             background_tasks.add_task(
#                 notification_service.notify_verification_approved,
#                 user_id=landlord_id,
#                 user_email=landlord_email,
#                 user_name=landlord_name,
#                 trust_score=80,
#             )
#             print(f"✅ [VERIFICATION-REVIEW] Approval notification queued for {landlord_email}")

#         elif new_status == 'rejected':
#             background_tasks.add_task(
#                 notification_service.notify_verification_rejected,
#                 user_id=landlord_id,
#                 user_email=landlord_email,
#                 user_name=landlord_name,
#                 rejection_reason=review_data.get('admin_feedback') or 'Your documents could not be verified.',
#                 onboarding_id=verification_id,
#             )
#             print(f"✅ [VERIFICATION-REVIEW] Rejection notification queued for {landlord_email}")

#         elif new_status == 'needs_correction':
#             background_tasks.add_task(
#                 notification_service.notify_verification_needs_correction,
#                 user_id=landlord_id,
#                 user_email=landlord_email,
#                 user_name=landlord_name,
#                 admin_feedback=review_data.get('admin_feedback') or 'Please review and resubmit your documents.',
#                 onboarding_id=verification_id,
#             )
#             print(f"✅ [VERIFICATION-REVIEW] Needs-correction notification queued for {landlord_email}")

#         print(f"✅ [VERIFICATION-REVIEW] Review completed: {new_status}")
        
#         return {
#             "success": True,
#             "message": f"Verification {new_status}",
#             "verification": update_result.data[0]
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"❌ [VERIFICATION-REVIEW] Error: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to review verification: {str(e)}"
#         )


# @router.post("/{verification_id}/request-correction")
# async def request_correction(
#     verification_id: str,
#     correction_data: Dict[str, Any],
#     current_admin: UserResponse = Depends(get_current_admin)
# ) -> Dict[str, Any]:
#     """
#     Request corrections from landlord
    
#     ✅ UNCHANGED: This endpoint remains exactly the same
#     """
#     try:
#         print(f"📝 [CORRECTION] Requesting correction for {verification_id}")
        
#         feedback = correction_data.get('feedback', '')
#         corrections_needed = correction_data.get('corrections_needed', [])
        
#         # Get admin ID safely
#         admin_id = current_admin.get('id') if isinstance(current_admin, dict) else current_admin.id
        
#         # Update onboarding
#         update_dict = {
#             "admin_review_status": "needs_correction",
#             "admin_feedback": feedback,
#             "admin_reviewer_id": admin_id,
#             "admin_reviewed_at": datetime.now(timezone.utc).isoformat(),
#             "last_updated_at": datetime.now(timezone.utc).isoformat()
#         }
        
#         # Add corrections metadata
#         if corrections_needed:
#             update_dict['documents'] = {
#                 "corrections_needed": corrections_needed,
#                 "requested_at": datetime.now(timezone.utc).isoformat()
#             }
        
#         update_result = supabase_admin.table('landlord_onboarding')\
#             .update(update_dict)\
#             .eq('id', verification_id)\
#             .execute()
        
#         # Clear caches
#         _cache.clear()
#         _cache_ttl.clear()
        
#         print(f"✅ [CORRECTION] Correction requested")
        
#         return {
#             "success": True,
#             "message": "Correction requested successfully",
#             "verification": update_result.data[0] if update_result.data else None
#         }
        
#     except Exception as e:
#         print(f"❌ [CORRECTION] Error: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to request correction: {str(e)}"
#         )