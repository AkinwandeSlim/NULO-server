"""
Property Routes - Database-Aligned & Ultra-Optimized
All field names match the exact Supabase schema

Database Schema Reference (properties table):
- id (uuid, primary key)
- landlord_id (uuid, foreign key)
- title, description, property_type
- address, full_address, location, city, state, country, neighborhood
- latitude, longitude (numeric)
- price, security_deposit (integer)
- beds, baths, sqft, floor_number, total_floors, year_built (integer)
- amenities, rules, images (text arrays)
- furnished, pet_friendly, utilities_included, featured (boolean)
- parking_spaces, view_count, application_count (integer)
- status, verification_status, lease_duration (text)
- available_from (date)
- created_at, updated_at (timestamp)
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Query, status, Form, File, UploadFile
from app.database import supabase_admin
from app.middleware.auth import get_current_user, get_current_landlord, get_optional_current_user
from app.services.notification_service import notification_service
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import math
import json
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

router = APIRouter(prefix="/properties")
executor = ThreadPoolExecutor(max_workers=4)

# ============================================================================
# VALIDATION HELPERS
# ============================================================================

# Allowed payment_frequency values per the DB check constraint
# (properties_payment_frequency_check) in newupdateDB.csv line 1060.
# Must stay in sync with docs/sql/migrations/001_add_payment_frequency_to_properties.sql:
#   CHECK (payment_frequency IN ('MONTHLY', 'ANNUAL', 'SEMI_ANNUAL', 'QUARTERLY'))
_VALID_PAYMENT_FREQUENCIES = ("MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUAL")

# Legacy alias map: maps older / UI-friendly values to the canonical DB values.
# 'YEARLY' was used by the frontend before the DB values were aligned. We accept
# it as an input and normalize it to 'ANNUAL' so older clients keep working.
_LEGACY_FREQUENCY_ALIASES = {
    "YEARLY": "ANNUAL",
    "ANNUALLY": "ANNUAL",
    "EVERY_12_MONTHS": "ANNUAL",
    "SEMI-ANNUAL": "SEMI_ANNUAL",
    "SEMIANNUAL": "SEMI_ANNUAL",
    "EVERY_6_MONTHS": "SEMI_ANNUAL",
    "BIANNUAL": "SEMI_ANNUAL",
    "EVERY_3_MONTHS": "QUARTERLY",
    "QUARTER": "QUARTERLY",
}


def _normalize_payment_frequency(value) -> str:
    """
    Coerce a payment_frequency input to one of the valid DB-allowed values.

    Accepts:
      - Canonical DB values: MONTHLY, QUARTERLY, SEMI_ANNUAL, ANNUAL
      - Legacy aliases (mapped automatically): YEARLY -> ANNUAL, etc.

    Falls back to MONTHLY for missing/empty/unknown input so existing rows
    and partial submissions keep working. The DB will still reject any
    bad value that slips through (check constraint), but this avoids
    500-ing the entire create flow.
    """
    if value is None:
        return "MONTHLY"
    candidate = str(value).strip().upper()
    if not candidate:
        return "MONTHLY"
    # Legacy alias -> canonical
    if candidate in _LEGACY_FREQUENCY_ALIASES:
        return _LEGACY_FREQUENCY_ALIASES[candidate]
    if candidate in _VALID_PAYMENT_FREQUENCIES:
        return candidate
    return "MONTHLY"


# ============================================================================
# NUBAN AUTO-PROVISION HELPER (Stage 3 polish)
# ============================================================================

async def _auto_provision_nuban_for_property(property_id: str, landlord_id: str):
    """
    Background task placeholder for auto-provisioning NUBANs.

    NOTE: NUBANs are for AGREEMENTS (signed leases between landlord + tenant),
    not for properties themselves. This helper is kept for compatibility
    but currently only logs a message. To provision a NUBAN, use the
    /agreements/{agreement_id}/provision-nomba endpoint after creating
    a signed agreement.
    """
    print(
        f"🏦 [NUBAN-AUTO] Placeholder: Auto-provisioning NUBANs for properties "
        f"is not supported. NUBANs are for signed agreements only. | "
        f"property_id={property_id} | landlord_id={landlord_id}"
    )


# ============================================================================
# IMAGE UPLOAD HELPER WITH TIMEOUT
# ============================================================================

async def upload_image_with_timeout(file_content: bytes, file_name: str, content_type: str, timeout: int = 30) -> Optional[str]:
    """
    Upload image to Supabase storage with timeout handling.
    Returns public URL on success, None on failure.
    """
    try:
        # Run storage upload in thread executor with timeout
        def do_upload():
            return supabase_admin.storage.from_("property-images").upload(
                path=file_name,
                file=file_content,
                file_options={"content-type": content_type}
            )
        
        # Execute with timeout
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(executor, do_upload),
            timeout=timeout
        )
        
        # Get public URL
        def get_url():
            return supabase_admin.storage.from_("property-images").get_public_url(file_name)
        
        public_url = await asyncio.wait_for(
            loop.run_in_executor(executor, get_url),
            timeout=10
        )
        
        print(f"✅ Image uploaded: {public_url}")
        return public_url
        
    except asyncio.TimeoutError:
        print(f"⚠️ Image upload timed out after {timeout}s: {file_name}")
        return None
    except Exception as e:
        print(f"⚠️ Image upload failed: {type(e).__name__}: {str(e)}")
        return None

# ============================================================================
# OPTIMIZED BATCH OPERATIONS
# ============================================================================

async def fetch_landlords_batch(
    property_ids: List[str],
    landlord_ids_hint: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Batch fetch landlord data keyed by landlord_id.

    BEFORE: 3 sequential round trips per call
      1. SELECT id, landlord_id FROM properties WHERE id IN [...]   ← always a duplicate
      2. SELECT * FROM users WHERE id IN [landlord_ids]
      3. SELECT COUNT FROM properties WHERE landlord_id IN [...]

    AFTER: 2 parallel round trips
      1. SELECT * FROM users WHERE id IN [landlord_ids]       ┐ run with
      2. SELECT landlord_id FROM properties WHERE landlord_id  ┘ asyncio.gather

    The caller can pass landlord_ids_hint (already known from the property row)
    to skip the redundant first properties query entirely.
    """
    if not property_ids and not landlord_ids_hint:
        return {}

    try:
        # ── Resolve landlord IDs ───────────────────────────────────────────────
        # If the caller already has landlord_ids (e.g. from the property row),
        # skip the redundant property lookup entirely.
        if landlord_ids_hint:
            landlord_ids = [lid for lid in landlord_ids_hint if lid]
        else:
            props_response = supabase_admin.table("properties").select(
                "id, landlord_id"
            ).in_("id", property_ids).execute()
            landlord_ids = list(set(
                p["landlord_id"] for p in props_response.data if p.get("landlord_id")
            ))

        if not landlord_ids:
            return {}

        # ── Fetch users + property counts IN PARALLEL (not sequentially) ──────
        async def _fetch_users():
            return supabase_admin.table("users").select(
                "id, full_name, avatar_url, trust_score, verification_status"
            ).in_("id", landlord_ids).execute()

        async def _fetch_counts():
            try:
                r = supabase_admin.table("properties").select(
                    "landlord_id", count="exact"
                ).in_("landlord_id", landlord_ids).eq("status", "vacant").is_("deleted_at", "null").execute()
                # Count per landlord properly — don't divide total evenly
                counts: Dict[str, int] = {lid: 0 for lid in landlord_ids}
                for row in (r.data or []):
                    lid = row.get("landlord_id")
                    if lid:
                        counts[lid] = counts.get(lid, 0) + 1
                return counts
            except Exception as count_err:
                print(f"⚠️ [LANDLORD COUNTS] Failed, defaulting to 0: {count_err}")
                return {lid: 0 for lid in landlord_ids}

        users_response, properties_count_dict = await asyncio.gather(
            _fetch_users(),
            _fetch_counts(),
        )

        print(f"🏠 [LANDLORD COUNTS] Per landlord: {properties_count_dict}")

        landlords_dict = {
            landlord["id"]: {
                "id": landlord["id"],
                "name": landlord.get("full_name"),
                "avatar_url": landlord.get("avatar_url"),
                "trust_score": landlord.get("trust_score", 50),
                "verified": landlord.get("verification_status") == "approved",
                "properties_count": properties_count_dict.get(landlord["id"], 0),
                "joined_year": datetime.now().year,
                "guarantee_joined": False,
            }
            for landlord in users_response.data
        }

        print(f"🏠 [LANDLORD DATA] Resolved {len(landlords_dict)} landlord(s)")
        return landlords_dict

    except Exception as e:
        print(f"⚠️ fetch_landlords_batch failed: {e}")
        return {}


async def fetch_favorites_batch(user_id: str, property_ids: List[str]) -> set:
    """
    Batch fetch favorites
    Uses database table: favorites (tenant_id, property_id)
    """
    if not user_id or not property_ids:
        return set()
    
    try:
        response = supabase_admin.table("favorites").select(
            "property_id"
        ).eq("tenant_id", user_id).in_("property_id", property_ids).execute()
        
        return set(fav["property_id"] for fav in response.data)
    except Exception as e:
        print(f"⚠️ Batch fetch favorites failed: {e}")
        return set()


# ============================================================================
# SEARCH ENDPOINT - Database-Aligned
# ============================================================================

@router.get("/search")
async def search_properties(
    location: Optional[str] = Query(None),
    min_price: Optional[int] = Query(None, ge=0),
    max_price: Optional[int] = Query(None, ge=0),
    bedrooms: Optional[int] = Query(None, ge=0),
    bathrooms: Optional[int] = Query(None, ge=0),
    property_type: Optional[str] = Query(None),
    furnished: Optional[bool] = Query(None),
    pet_friendly: Optional[bool] = Query(None),
    parking_required: Optional[bool] = Query(None),
    sort: str = Query("newest", pattern="^(newest|price_low|price_high|featured)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: Optional[dict] = Depends(get_optional_current_user)
):
    """
    Ultra-optimized property search
    
    Database Query Strategy:
    1. Filter by status = 'vacant' (indexed)
    2. Location search in: location, city, state (all indexed)
    3. Price range on price field (indexed)
    4. Beds/baths filters (beds is indexed)
    5. Property type filter
    6. Boolean filters: furnished, pet_friendly
    7. Sort by: created_at (newest), price, featured (all indexed)
    8. Pagination with range()
    """
    start_time = time.time()
    
    try:
        print(f"🔍 [SEARCH] location={location}, beds={bedrooms}, price={min_price}-{max_price}")
        
        # FILTER 1: Only vacant AND approved + non-deleted properties (uses idx_properties_status)
        # Filter out soft-deleted properties from public marketplace (REG-08 fix)
        query = supabase_admin.table("properties").select(
            "*"
        ).eq(
            "status", "vacant"
        ).eq(
            "verification_status", "approved"
        ).is_(
            "deleted_at", "null"
        )
        
        # FILTER 2: Location search - SMART BACKWARD COMPATIBLE SEARCH
        # Handles both new format (Maitama, FCT) and old corrupted data (Maitama, Abuja, Abuja)
        if location:
            location_clean = location.strip()
            print(f"🔍 [LOCATION SEARCH] User searched for: '{location_clean}'")
            
            # Strategy: Split location by comma and search in PRIMARY field first
            # Then fall back to searching in city, state, and address fields
            # This handles both new and old data formats
            
            location_parts = [part.strip() for part in location_clean.split(",") if part.strip()]
            print(f"📍 [LOCATION SEARCH] Split into {len(location_parts)} parts: {location_parts}")
            
            # Get the main search term (first part)
            # From "Maitama, FCT" we get "Maitama"
            search_term = location_parts[0] if location_parts else location_clean
            
            # Log what we're searching for
            print(f"🔎 [LOCATION SEARCH] Main search term: '{search_term}'")
            print(f"   Will match: location, city, state fields containing '{search_term}'")
            
            # Apply the filter - search in location field first (composite field)
            # This field contains "city, state" so it should match most queries
            query = query.ilike("location", f"%{search_term}%")
        
        # FILTER 3: Price range (uses idx_properties_price)
        if min_price is not None and min_price > 0:
            query = query.gte("price", min_price)
        
        if max_price is not None and max_price < 10000000:
            query = query.lte("price", max_price)
        
        # FILTER 4: Bedrooms (uses idx_properties_beds)
        if bedrooms is not None and bedrooms > 0:
            query = query.gte("beds", bedrooms)
        
        # FILTER 5: Bathrooms (baths field)
        if bathrooms is not None and bathrooms > 0:
            query = query.gte("baths", bathrooms)
        
        # FILTER 6: Property type (BUG-016 fix)
        #   The frontend filter dropdown sends Capitalised values
        #   ("Apartment", "Villa", "Penthouse"...) but the DB may hold
        #   the same word in any case ("apartment", "APARTMENT"...).
        #   `.eq()` is case-sensitive so "Apartment" would miss "apartment"
        #   rows and return 0 results. Use `.ilike()` (case-insensitive
        #   pattern match) without wildcards so we get a case-insensitive
        #   equality. We also strip + lowercase the value first to avoid
        #   accidentally injecting SQL LIKE wildcards from the query string.
        if property_type and property_type.strip().lower() != "all":
            safe = (
                property_type.strip()
                .replace("%", r"\%")
                .replace("_", r"\_")
            )
            query = query.ilike("property_type", safe)
        
        # FILTER 7: Furnished
        if furnished is not None:
            query = query.eq("furnished", furnished)
        
        # FILTER 8: Pet friendly
        if pet_friendly is not None:
            query = query.eq("pet_friendly", pet_friendly)
        
        # FILTER 9: Parking
        if parking_required is not None and parking_required:
            query = query.gt("parking_spaces", 0)
        
        # SORTING (all use indexes)
        if sort == "price_low":
            query = query.order("price", desc=False)
        elif sort == "price_high":
            query = query.order("price", desc=True)
        elif sort == "featured":
            query = query.order("featured", desc=True).order("created_at", desc=True)
        else:  # newest
            query = query.order("created_at", desc=True)
        
        # PAGINATION
        # Supabase/PostgREST `.range(start, end)` is INCLUSIVE on both ends
        # (the underlying Range header uses closed intervals). So for limit=20,
        # page=1: offset=0, range(0, 19) = 20 items. The previous comment was
        # wrong and the formula produced `limit + 1` items.
        offset = (page - 1) * limit
        range_start = offset
        range_end = offset + limit - 1
        
        print(f"📍 [PAGINATION] page={page}, limit={limit}, offset={offset}, range({range_start}, {range_end}) - expecting {limit} items")
        query = query.range(range_start, range_end)
        
        # Execute query with timeout handling and retry logic
        query_start = time.time()
        max_retries = 2
        retry_count = 0
        response = None
        last_error = None
        
        # Retry loop with exponential backoff
        while retry_count <= max_retries:
            try:
                response = query.execute()
                break  # Success, exit retry loop
            except Exception as query_error:
                last_error = query_error
                is_timeout = "timed out" in str(query_error).lower() or "timeout" in str(query_error).lower()
                
                if is_timeout and retry_count < max_retries:
                    # Retry on timeout with exponential backoff
                    wait_time = 0.5 * (2 ** retry_count)  # 0.5s, 1s, 2s
                    print(f"⏱️ [QUERY TIMEOUT] Retry {retry_count + 1}/{max_retries} after {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    retry_count += 1
                else:
                    # Final attempt failed or non-timeout error - calculate duration before raising
                    query_duration = time.time() - query_start
                    if is_timeout:
                        print(f"❌ [QUERY TIMEOUT] All retries exhausted after {query_duration:.1f}s")
                    raise query_error
        
        # Calculate query duration after successful query or all retries exhausted
        query_duration = time.time() - query_start
        
        # Safely access response data (should never be None if we reach here)
        if response is None:
            print("❌ [SEARCH] Query returned None despite no exception")
            properties = []
            total = 0
        else:
            properties = response.data or []
            total = response.count or 0
        
        print(f"📊 Query: {query_duration:.3f}s, Results: {len(properties)}/{total}")
        
        # BATCH OPERATIONS: Fetch related data in parallel
        if properties:
            property_ids = [p["id"] for p in properties]
            
            landlords_dict, favorited_ids = await asyncio.gather(
                fetch_landlords_batch(property_ids),
                fetch_favorites_batch(
                    current_user.get("id") if current_user else None,
                    property_ids
                )
            )
            
            # Attach related data
            for prop in properties:
                # Attach landlord info
                landlord_id = prop.get("landlord_id")
                if landlord_id and landlord_id in landlords_dict:
                    prop["landlord"] = landlords_dict[landlord_id]
                
                # Attach favorite status
                prop["is_favorited"] = prop["id"] in favorited_ids
        
        # Calculate pagination
        total_pages = math.ceil(total / limit) if total > 0 else 1
        execution_time = time.time() - start_time
        
        result = {
            "success": True,
            "properties": properties,
            "pagination": {
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages
            },
            "performance": {
                "total_execution_time": round(execution_time, 3),
                "query_time": round(query_duration, 3),
                "cache_hit": False,
                "optimized": True,
                "timestamp": datetime.utcnow().isoformat()
            },
            "optimization": {
                "client_cache_ttl": 300,
                "batch_operations": True,
                "query_optimized": True
            }
        }
        
        print(f"✅ [SEARCH COMPLETE] {execution_time:.3f}s")
        return result
        
    except Exception as e:
        print(f"❌ [SEARCH ERROR] {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


# ============================================================================
# FEATURED PROPERTIES
# ============================================================================

@router.get("/featured")
async def get_featured_properties(
    limit: int = Query(default=6, ge=1, le=20),
):
    """
    Get featured properties
    Uses: featured (indexed), status (indexed), created_at (indexed)
    """
    try:
        start_time = time.time()
        
        response = supabase_admin.table("properties").select(
            "*"
        ).eq(
            "status", "vacant"
        ).eq(
            "verification_status", "approved"
        ).is_(
            "deleted_at", "null"
        ).eq(
            "featured", True
        ).order(
            "created_at", desc=True
        ).limit(limit).execute()
        
        properties = response.data or []
        
        # Batch fetch landlords
        if properties:
            property_ids = [p["id"] for p in properties]
            landlords_dict = await fetch_landlords_batch(property_ids)
            
            for prop in properties:
                landlord_id = prop.get("landlord_id")
                if landlord_id and landlord_id in landlords_dict:
                    prop["landlord"] = landlords_dict[landlord_id]
        
        execution_time = time.time() - start_time
        
        return {
            "success": True,
            "properties": properties,
            "count": len(properties),
            "performance": {
                "execution_time": round(execution_time, 3)
            }
        }
        
    except Exception as e:
        print(f"❌ [FEATURED ERROR] {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get featured properties: {str(e)}"
        )


# ============================================================================
# LANDLORD PROPERTY MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/my-properties")
async def get_my_properties(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, description="Filter by status: vacant, rented, inactive"),
    include_deleted: bool = Query(False, description="REG-08 fix: include soft-deleted properties (landlord view)"),
    include_pending: bool = Query(False, description="Include properties still awaiting admin approval"),
    include_rejected: bool = Query(False, description="Include properties rejected by admin"),
    search: Optional[str] = Query(None, description="Search across title, address, city, state, location"),
    current_user: dict = Depends(get_current_landlord)
):
    """
    Get all properties for the current landlord with pagination and filtering.

    Default filtering (matches My Properties page UI):
      - Excludes soft-deleted (`deleted_at IS NULL`)
      - Excludes rejected (admin test data leak fix)
      - Excludes pending review (no action available until approved)
      - Only returns properties that are approved AND (vacant OR occupied)
    """
    try:
        landlord_id = current_user["id"]

        # Calculate offset
        # ── Off-by-one fix: Supabase/PostgREST `.range(start, end)` is INCLUSIVE
        # on both ends, so `range(0, 14)` returns 15 items, not 14.
        # The previous code used `range_end = offset + limit` which produced
        # `limit + 1` items (e.g. 16 instead of 15). Use `offset + limit - 1`.
        offset = (page - 1) * limit
        range_start = offset
        range_end = offset + limit - 1

        print(f"📍 [MY-PROPERTIES PAGINATION] page={page}, limit={limit}, offset={offset}, range({range_start}, {range_end}), include_deleted={include_deleted} - expecting {limit} items")

        # Build query
        query = supabase_admin.table("properties").select(
            "*", count="exact"
        ).eq("landlord_id", landlord_id)

        # REG-08 fix: exclude soft-deleted by default; landlord can opt-in to see them
        if not include_deleted:
            query = query.is_("deleted_at", "null")

        # Filter by admin verification status. Default is "approved" only so
        # admin test/rejected/pending records don't leak into the My Properties
        # list. The landlord can opt-in to see pending or rejected rows.
        if include_rejected and include_pending:
            query = query.in_("verification_status", ["approved", "pending", "rejected"])
        elif include_rejected:
            query = query.in_("verification_status", ["approved", "rejected"])
        elif include_pending:
            query = query.in_("verification_status", ["approved", "pending"])
        else:
            query = query.eq("verification_status", "approved")

        # Apply status (lifecycle) filter if provided.
        # Allowed values: vacant, occupied, maintenance. Anything else is ignored.
        if status_filter and status_filter in ("vacant", "occupied", "maintenance"):
            query = query.eq("status", status_filter)
        else:
            # No status filter supplied — restrict to active lifecycle states so
            # 'maintenance' or other transient states don't show by default.
            query = query.in_("status", ["vacant", "occupied"])

        # Apply search filter (case-insensitive) across multiple text fields.
        # Uses PostgREST `or=` with `ilike` for substring match.
        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.or_(
                f"title.ilike.{term},"
                f"address.ilike.{term},"
                f"city.ilike.{term},"
                f"state.ilike.{term},"
                f"location.ilike.{term},"
                f"full_address.ilike.{term}"
            )

        # Order by creation date (newest first)
        query = query.order("created_at", desc=True)

        # Apply pagination
        response = query.range(range_start, range_end).execute()
        
        properties = response.data or []
        total = response.count or 0
        
        # Add landlord info and statistics
        for property_item in properties:
            property_item['landlord'] = {
                'id': landlord_id,
                'name': current_user.get('full_name'),
                'avatar_url': current_user.get('avatar_url'),
                'trust_score': current_user.get('trust_score', 50),
                'verified': current_user.get('verification_status') == 'approved',
                'joined_year': datetime.now().year,
                'guarantee_joined': False
            }
            property_item['is_favorited'] = False  # Landlord's own properties
            
            # Add view and application counts
            property_item['view_count'] = property_item.get('view_count', 0)
            property_item['application_count'] = property_item.get('application_count', 0)
        
        # Calculate pagination
        total_pages = math.ceil(total / limit) if total > 0 else 1
        
        return {
            "success": True,
            "properties": properties,
            "pagination": {
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1
            },
            "filters": {
                "status": status_filter
            }
        }
        
    except Exception as e:
        print(f"❌ Error fetching landlord properties: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch properties: {str(e)}"
        )

# ============================================================================
# GET PROPERTY BY ID
# ============================================================================

@router.get("/{property_id}")
async def get_property(
    property_id: str,
    current_user: Optional[dict] = Depends(get_optional_current_user)
):
    """
    Get property by ID.

    Query plan (was 5 sequential, now 2 parallel):
      Round trip 1: SELECT * FROM properties WHERE id = ?
      Round trip 2 (parallel):
        a. SELECT users WHERE id = landlord_id
        b. SELECT COUNT properties WHERE landlord_id = ?  (for landlord card)
        c. SELECT favorites WHERE tenant_id = ?           (if logged in)
      Background: UPDATE view_count (fire-and-forget)
    """
    try:
        start_time = time.time()

        # ── Round trip 1: fetch the property ──────────────────────────────────
        response = supabase_admin.table("properties").select("*").eq(
            "id", property_id
        ).execute()

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )

        property_data = response.data[0]
        landlord_id = property_data.get("landlord_id")

        # ── Fire-and-forget view count increment ──────────────────────────────
        asyncio.create_task(
            asyncio.to_thread(
                lambda: supabase_admin.table("properties").update({
                    "view_count": property_data.get("view_count", 0) + 1
                }).eq("id", property_id).execute()
            )
        )

        # ── Round trip 2: landlord info + favorites IN PARALLEL ───────────────
        async def _empty_landlords():
            return {}

        async def _empty_favorites():
            return set()

        landlords_task = (
            fetch_landlords_batch(
                property_ids=[],
                landlord_ids_hint=[landlord_id],   # skip the redundant property query
            )
            if landlord_id else _empty_landlords()
        )

        favorites_task = (
            fetch_favorites_batch(current_user["id"], [property_id])
            if current_user else _empty_favorites()
        )

        landlords_dict, favorited_ids = await asyncio.gather(
            landlords_task,
            favorites_task,
        )

        # ── Attach results ────────────────────────────────────────────────────
        if landlord_id and landlord_id in landlords_dict:
            property_data["landlord"] = landlords_dict[landlord_id]
            print(f"✅ [GET PROPERTY] Landlord: {property_data['landlord'].get('name')}")
        else:
            print(f"⚠️ [GET PROPERTY] No landlord data for landlord_id={landlord_id}")

        property_data["is_favorited"] = property_id in favorited_ids

        execution_time = time.time() - start_time
        property_data["_performance"] = {"execution_time": round(execution_time, 3)}
        print(f"✅ [GET PROPERTY] {property_id} in {execution_time:.3f}s")

        return property_data

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [GET PROPERTY ERROR] {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch property: {str(e)}"
        )


# ============================================================================
# CREATE PROPERTY
# ============================================================================

@router.post("")
async def create_property(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    description: str = Form(...),
    property_type: str = Form(...),
    address: str = Form(...),
    city: str = Form(...),
    state: str = Form(...),
    country: str = Form("Nigeria"),
    neighborhood: Optional[str] = Form(None),
    full_address: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    price: int = Form(...),
    payment_frequency: str = Form("MONTHLY"),
    beds: int = Form(...),
    baths: int = Form(...),
    sqft: Optional[int] = Form(None),
    security_deposit: Optional[int] = Form(None),
    amenities: str = Form("[]"),
    furnished: Optional[bool] = Form(False),
    pet_friendly: Optional[bool] = Form(False),
    parking_spaces: Optional[int] = Form(0),
    utilities_included: Optional[bool] = Form(False),
    available_from: Optional[str] = Form(None),
    lease_duration: Optional[str] = Form("12 months"),
    # Stage 3 polish: opt-in to auto-provision a Nomba NUBAN for this property
    # right after creation. When "true", the route will call
    # /provision-nomba for the new property id (fire-and-forget so a Nomba
    # hiccup never blocks the property create flow).
    generate_nuban: Optional[str] = Form("false"),
    images: List[UploadFile] = File([]),
    current_user: dict = Depends(get_current_landlord)
):
    """
    Create property - All fields match database schema exactly
    """
    try:
        landlord_id = current_user["id"]

        print(f"📤 [CREATE] landlord={landlord_id}, title={title}, city={city}, state={state}, images={len(images)}")

        # ── ONBD-09 fix: Block rejected landlords from creating new properties ──
        # Admins reject landlords via /api/v1/onboarding/admin/review/{onboarding_id}
        # which sets users.verification_status = 'rejected'. A rejected landlord
        # must NOT be able to create new property listings. The landlord must
        # contact support / re-submit onboarding instead.
        landlord_status_check = supabase_admin.table("users").select(
            "verification_status"
        ).eq("id", landlord_id).single().execute()
        landlord_status = (
            (landlord_status_check.data or {}).get("verification_status", "pending")
        )

        if landlord_status == "rejected":
            print(f"❌ [CREATE] Blocked: landlord {landlord_id} is rejected")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Your landlord account was rejected and cannot create new "
                    "property listings. Please contact support or resubmit your "
                    "verification documents."
                ),
            )

        # ── BUG-014 fix: Block unverified (still-pending) landlords too ──
        # Previously, only "rejected" was blocked. An account still in the
        # verification queue (status == "pending") could still create
        # listings. Now we require an *approved* verification_status before
        # accepting new listings — anything else (pending / partial /
        # suspended) is rejected with an actionable error message.
        if landlord_status != "approved":
            print(
                f"❌ [CREATE] Blocked: landlord {landlord_id} is not verified "
                f"(verification_status={landlord_status})"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"You can only publish property listings once your landlord "
                    f"verification is approved. Your current status is "
                    f"'{landlord_status}'. Please complete the onboarding "
                    f"process and wait for admin approval before listing "
                    f"properties."
                ),
            )

        # Validate and set security deposit to 2 months rent if not provided
        if not security_deposit:
            security_deposit = price * 2  # Default to 2 months rent
            print(f"✅ [CREATE] Security deposit set to default: {security_deposit} (2 months rent)")
        elif security_deposit < price:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Security deposit must be at least 1 month rent (₦{price:,}). Current: ₦{security_deposit:,}"
            )
        else:
            print(f"✅ [CREATE] Security deposit provided: {security_deposit}")
        
        # Ensure landlord_profile row exists (created during onboarding, but guard anyway)
        try:
            profile_response = supabase_admin.table("landlord_profiles").select("id").eq("id", landlord_id).execute()
            if not profile_response.data:
                print(f"⚠️ [CREATE] No landlord profile found for {landlord_id}, creating placeholder")
                supabase_admin.table("landlord_profiles").insert({
                    "id": landlord_id,
                    "onboarding_started": True,
                    "verification_status": "pending",
                    "is_verified": False,
                }).execute()
        except Exception as profile_error:
            print(f"⚠️ [CREATE] Landlord profile check failed (non-fatal): {profile_error}")
        
        # Parse amenities
        try:
            amenities_list = json.loads(amenities) if amenities else []
        except json.JSONDecodeError:
            amenities_list = []
            print(f"⚠️ [CREATE] Failed to parse amenities JSON, defaulting to []")
        
        # Handle images - upload to Supabase storage with timeout protection
        image_urls = []
        if images:
            for image in images:
                try:
                    # Read file content
                    file_content = await image.read()
                    file_extension = image.filename.split('.')[-1] if image.filename else 'jpg'
                    file_name = f"properties/{landlord_id}/{int(time.time())}_{image.filename}"
                    
                    # Upload with timeout (30 seconds per image)
                    public_url = await upload_image_with_timeout(
                        file_content=file_content,
                        file_name=file_name,
                        content_type=image.content_type or "image/jpeg",
                        timeout=30
                    )
                    
                    if public_url:
                        image_urls.append(public_url)
                    else:
                        # Fallback to placeholder on timeout or failure
                        placeholder_url = f"https://images.unsplash.com/photo-{1560448204 + len(image_urls)}-e02f11c3d0e2?w=800&h=600&fit=crop"
                        image_urls.append(placeholder_url)
                        print(f"⚠️ Image upload failed, using placeholder: {placeholder_url}")
                        
                except Exception as img_error:
                    print(f"⚠️ Image processing error: {type(img_error).__name__}: {img_error}")
                    # Fallback to placeholder
                    placeholder_url = f"https://images.unsplash.com/photo-{1560448204 + len(image_urls)}-e02f11c3d0e2?w=800&h=600&fit=crop"
                    image_urls.append(placeholder_url)
        else:
            # Default placeholder if no images
            image_urls = ["https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=800&h=600&fit=crop"]
        
        location_result = location if location else f"{city}, {state}"
        
        property_dict = {
            "landlord_id": landlord_id,
            "title": title,
            "description": description,
            "property_type": property_type,
            "address": address,
            "city": city,
            "state": state,
            "country": country,
            "neighborhood": neighborhood or "",
            "full_address": full_address or f"{address}, {neighborhood or ''}, {city}, {state}, Nigeria".replace(", ,", ","),
            "location": location_result,
            "latitude": latitude,
            "longitude": longitude,
            "price": price,
            "payment_frequency": _normalize_payment_frequency(payment_frequency),
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "security_deposit": security_deposit,
            "amenities": amenities_list,
            "furnished": furnished,
            "pet_friendly": pet_friendly,
            "parking_spaces": parking_spaces,
            "utilities_included": utilities_included,
            "available_from": available_from,
            "lease_duration": lease_duration,
            "images": image_urls,
            "rules": [],
            "status": "vacant",
            "featured": False,
            "verification_status": "pending",
            "view_count": 0,
            "application_count": 0,
        }
        
        # Insert into database
        response = supabase_admin.table("properties").insert(property_dict).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create property"
            )
        
        created_property = response.data[0]
        print(f"✅ [CREATED] property_id={created_property['id']}")
        
        # Fire notification (non-blocking) — notifies landlord + admin
        landlord_name  = current_user.get("full_name") or current_user.get("email", "Landlord")
        landlord_email = current_user.get("email", "")
        background_tasks.add_task(
            notification_service.notify_property_listed,
            property_id=created_property["id"],
            landlord_id=landlord_id,
            landlord_name=landlord_name,
            landlord_email=landlord_email,
            property_title=title,
        )

        # Stage 3 polish: opt-in to auto-provision a Nomba NUBAN for this
        # property. Coerce the form value to a bool, then schedule a
        # background task so a Nomba hiccup never blocks the create flow.
        if isinstance(generate_nuban, str):
            wants_nuban = generate_nuban.strip().lower() in ("true", "1", "yes", "on")
        else:
            wants_nuban = bool(generate_nuban)
        if wants_nuban:
            background_tasks.add_task(
                _auto_provision_nuban_for_property,
                property_id=created_property["id"],
                landlord_id=landlord_id,
            )
            print(
                f"🏦 [CREATE] NUBAN auto-provision scheduled | property_id="
                f"{created_property['id']} | landlord_id={landlord_id}"
            )

        return created_property
        
    except HTTPException as he:
        print(f"❌ [CREATE HTTP ERROR] {he.status_code}: {he.detail}")
        raise he
    except Exception as e:
        print(f"❌ [CREATE ERROR] {str(e)}")
        print(f"❌ [CREATE ERROR TYPE] {type(e)}")
        import traceback
        print(f"❌ [CREATE TRACEBACK] {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create property: {str(e)}"
        )


# ============================================================================
# PLATFORM STATS
# ============================================================================

@router.get("/stats/platform-summary")
async def get_platform_stats():
    """
    Get platform statistics with optimized parallel queries
    """
    try:
        # Parallel queries
        properties_task = asyncio.create_task(
            asyncio.to_thread(
                lambda: supabase_admin.table("properties").select(
                    "id", count="exact"
                ).eq("status", "vacant").is_("deleted_at", "null").execute()
            )
        )
        
        tenants_task = asyncio.create_task(
            asyncio.to_thread(
                lambda: supabase_admin.table("users").select(
                    "id", count="exact"
                ).eq("user_type", "tenant").execute()
            )
        )
        
        landlords_task = asyncio.create_task(
            asyncio.to_thread(
                lambda: supabase_admin.table("users").select(
                    "id", count="exact"
                ).eq("user_type", "landlord").eq(
                    "verification_status", "approved"
                ).execute()
            )
        )
        
        props_res, tenants_res, landlords_res = await asyncio.gather(
            properties_task,
            tenants_task,
            landlords_task
        )
        
        return {
            "total_properties": props_res.count or 0,
            "active_tenants": tenants_res.count or 0,
            "verified_landlords": landlords_res.count or 0,
            "cities_covered": 3,
            "new_this_week": 0,
            "verification_rate": 95,
            "avg_response_time": "< 24h"
        }
        
    except Exception as e:
        print(f"❌ [STATS ERROR] {e}")
        return {
            "total_properties": 0,
            "active_tenants": 0,
            "verified_landlords": 0,
            "cities_covered": 3,
            "new_this_week": 0,
            "verification_rate": 95,
            "avg_response_time": "< 24h"
        }


# ============================================================================
# CITIES SUMMARY
# ============================================================================

@router.get("/locations/cities-summary")
async def get_cities_summary():
    """
    Get property counts by city
    Uses: city field (indexed)
    """
    try:
        # Get distinct cities with counts
        # This is a simplified version - you may want to pre-compute this
        cities_data = [
            {
                "name": "Lagos",
                "state": "Lagos State",
                "country": "Nigeria",
                "image_url": "/lagos-victoria-island-skyline.jpg",
                "description": "Nigeria's commercial capital",
                "property_count": 0
            },
            {
                "name": "Abuja",
                "state": "FCT",
                "country": "Nigeria",
                "image_url": "/contemporary-townhouse-johannesburg.jpg",
                "description": "Nigeria's modern capital",
                "property_count": 0
            },
            {
                "name": "Port Harcourt",
                "state": "Rivers State",
                "country": "Nigeria",
                "image_url": "/citywaker1.png",
                "description": "The Garden City",
                "property_count": 0
            }
        ]
        
        # Get counts for each city — only approved listings visible on marketplace
        for city in cities_data:
            response = supabase_admin.table("properties").select(
                "id", count="exact"
            ).eq("city", city["name"]).eq("status", "vacant").eq("verification_status", "approved").is_("deleted_at", "null").execute()
            city["property_count"] = response.count or 0
        
        return {
            "success": True,
            "cities": cities_data
        }
        
    except Exception as e:
        print(f"❌ [CITIES ERROR] {e}")
        return {
            "success": False,
            "cities": []
        }




# IMPROVED MISSING ENDPOINTS for properties.py
# Add these endpoints to your existing properties.py file

# ============================================================================
# POPULAR LOCATIONS ENDPOINT
# ============================================================================

@router.get("/locations/popular")
async def get_popular_locations(
    limit: int = Query(default=10, ge=1, le=50, description="Number of locations to return"),
):
    """
    Get popular locations with property counts and coordinates
    """
    try:
        print("🔍 Fetching popular locations...")
        
        # Fetch all vacant + approved properties with location data (marketplace-visible only)
        response = supabase_admin.table("properties").select(
            "location, city, state, country"
        ).eq("status", "vacant").eq("verification_status", "approved").is_("deleted_at", "null").execute()
        
        if not response.data:
            return {
                "success": True,
                "locations": [
                    {"location": "Lekki", "city": "Lagos", "state": "Lagos State", "country": "Nigeria", "property_count": 0, "coordinates": {"lat": 6.4611, "lng": 3.5764}},
                    {"location": "Gwarinpa", "city": "Abuja", "state": "FCT", "country": "Nigeria", "property_count": 0, "coordinates": {"lat": 9.0833, "lng": 7.5167}},
                    {"location": "GRA", "city": "Port Harcourt", "state": "Rivers State", "country": "Nigeria", "property_count": 0, "coordinates": {"lat": 4.8167, "lng": 7.0500}},
                ],
                "total_locations": 3
            }
        
        # Group by location and count properties
        location_counts = {}
        for prop in response.data:
            location_key = prop.get('location', 'Unknown')
            if location_key not in location_counts:
                location_counts[location_key] = {
                    "location": location_key,
                    "city": prop.get('city', ''),
                    "state": prop.get('state', ''),
                    "country": prop.get('country', 'Nigeria'),
                    "property_count": 0,
                    "coordinates": get_coordinates_for_location(location_key, prop.get('city', ''))
                }
            location_counts[location_key]["property_count"] += 1
        
        # Sort by property count and limit
        sorted_locations = sorted(location_counts.values(), key=lambda x: x["property_count"], reverse=True)[:limit]
        
        return {
            "success": True,
            "locations": sorted_locations,
            "total_locations": len(sorted_locations)
        }
        
    except Exception as e:
        print(f"❌ Error fetching popular locations: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch popular locations: {str(e)}"
        )

def get_coordinates_for_location(location: str, city: str) -> dict:
    """Get coordinates for Nigerian locations"""
    location_lower = location.lower()
    city_lower = city.lower()
    
    # Major Nigerian location coordinates
    coordinates = {
        # Lagos
        "lekki": {"lat": 6.4611, "lng": 3.5764},
        "victoria island": {"lat": 6.4281, "lng": 3.4219},
        "ikeja": {"lat": 6.6018, "lng": 3.3515},
        "ikoyi": {"lat": 6.4500, "lng": 3.4333},
        "surulere": {"lat": 6.4934, "lng": 3.3515},
        "ajah": {"lat": 6.4651, "lng": 3.5405},
        "yaba": {"lat": 6.5179, "lng": 3.3892},
        
        # Abuja
        "gwarinpa": {"lat": 9.0833, "lng": 7.5167},
        "maitama": {"lat": 9.0833, "lng": 7.4833},
        "asokoro": {"lat": 9.0833, "lng": 7.5000},
        "wuse": {"lat": 9.0667, "lng": 7.4667},
        "garki": {"lat": 9.0500, "lng": 7.4833},
        
        # Port Harcourt
        "gra": {"lat": 4.8167, "lng": 7.0500},
        "rumuola": {"lat": 4.8167, "lng": 7.0333},
        "rumuokwuta": {"lat": 4.8000, "lng": 7.0500},
    }
    
    # Try exact location match first
    if location_lower in coordinates:
        return coordinates[location_lower]
    
    # Try city match
    if city_lower in coordinates:
        return coordinates[city_lower]
    
    # Default coordinates (Nigeria center)
    return {"lat": 9.0765, "lng": 7.3986}

# ============================================================================
# UPDATE PROPERTY ENDPOINT
# ============================================================================

@router.put("/{property_id}")
async def update_property(
    property_id: str,
    property_data: dict,
    current_user: dict = Depends(get_current_landlord)
):
    """
    Update an existing property (landlord only, own properties)

    BUG-012 fix: Switched from Form() to JSON body to fix FastAPI PUT request
    parsing issue where all fields were received as NULL when sent as
    multipart/form-data. JSON is more reliable for PUT operations.

    Accepts a JSON body with optional fields:
    - title, description, property_type
    - location, address
    - price, beds, baths, sqft
    - amenities (array), status
    - security_deposit, pet_friendly, parking_spaces
    - furnished, lease_duration, rules, available_from
    """
    try:
        landlord_id = current_user["id"]

        # Extract fields from JSON body with None defaults
        title = property_data.get("title")
        description = property_data.get("description")
        property_type = property_data.get("property_type")
        location = property_data.get("location")
        address = property_data.get("address")
        price = property_data.get("price")
        bedrooms = property_data.get("bedrooms") or property_data.get("beds")
        bathrooms = property_data.get("bathrooms") or property_data.get("baths")
        sqft = property_data.get("sqft") or property_data.get("square_feet")
        amenities = property_data.get("amenities", [])
        status = property_data.get("status")

        #region debug-point H4-backend-receives
        # Debug: Log what the backend receives
        print(f"🔍 [BACKEND-UPDATE] property_id={property_id}, landlord_id={landlord_id}")
        print(f"🔍 [BACKEND-UPDATE] Received fields: title={title}, price={price}, bedrooms={bedrooms}, bathrooms={bathrooms}")

        # Report to debug server (fire-and-forget)
        try:
            import urllib.request
            import json
            debug_data = {
                "hypothesisId": "H4",
                "stage": "backend-receives",
                "property_id": property_id,
                "landlord_id": landlord_id,
                "received_fields": {
                    "title": title,
                    "price": price,
                    "bedrooms": bedrooms,
                    "bathrooms": bathrooms,
                    "sqft": sqft,
                    "amenities": amenities,
                    "status": status
                }
            }
            urllib.request.urlopen(
                urllib.request.Request(
                    "http://127.0.0.1:7778/event",
                    data=json.dumps(debug_data).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                ),
                timeout=1
            )
        except Exception as e:
            print(f"⚠️ [BACKEND-UPDATE] Failed to report to debug server: {e}")
        #endregion debug-point H4-backend-receives

        # Verify ownership
        property_check = supabase_admin.table("properties").select("landlord_id").eq(
            "id", property_id
        ).execute()

        if not property_check.data or property_check.data[0]["landlord_id"] != landlord_id:
            print(f"❌ [BACKEND-UPDATE] Ownership check failed for property_id={property_id}, landlord_id={landlord_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to update this property"
            )

        print(f"✅ [BACKEND-UPDATE] Ownership verified for property_id={property_id}")

        # Build update data with only provided fields
        update_data = {
            "updated_at": datetime.now().isoformat()
        }

        # Add fields only if they are provided
        if title is not None:
            update_data["title"] = title
        if description is not None:
            update_data["description"] = description
        if property_type is not None:
            update_data["property_type"] = property_type
        if location is not None:
            update_data["location"] = location
        if address is not None:
            update_data["address"] = address
        if price is not None:
            update_data["price"] = int(price) if isinstance(price, (int, float, str)) else None
        if bedrooms is not None:
            update_data["beds"] = int(bedrooms) if isinstance(bedrooms, (int, float, str)) else None
        if bathrooms is not None:
            update_data["baths"] = int(bathrooms) if isinstance(bathrooms, (int, float, str)) else None
        if sqft is not None:
            update_data["sqft"] = int(sqft) if isinstance(sqft, (int, float, str)) else None
        if amenities is not None:
            # Handle both array and JSON string
            if isinstance(amenities, str):
                try:
                    update_data["amenities"] = json.loads(amenities)
                except (ValueError, TypeError):
                    update_data["amenities"] = []
            elif isinstance(amenities, list):
                update_data["amenities"] = amenities
            else:
                update_data["amenities"] = []

        # Handle additional fields that might be in the JSON
        security_deposit = property_data.get("security_deposit")
        if security_deposit is not None:
            update_data["security_deposit"] = int(security_deposit) if isinstance(security_deposit, (int, float, str)) else None

        pet_friendly = property_data.get("pet_friendly")
        if pet_friendly is not None:
            if isinstance(pet_friendly, bool):
                update_data["pet_friendly"] = pet_friendly
            elif isinstance(pet_friendly, str):
                update_data["pet_friendly"] = pet_friendly.lower() in ("true", "1", "yes", "on")

        parking_spaces = property_data.get("parking_spaces")
        if parking_spaces is not None:
            update_data["parking_spaces"] = int(parking_spaces) if isinstance(parking_spaces, (int, float, str)) else None

        furnished = property_data.get("furnished")
        if furnished is not None:
            if isinstance(furnished, bool):
                update_data["furnished"] = furnished
            elif isinstance(furnished, str):
                update_data["furnished"] = furnished.lower() in ("true", "1", "yes", "on")

        lease_duration = property_data.get("lease_duration")
        if lease_duration is not None:
            update_data["lease_duration"] = lease_duration

        payment_frequency = property_data.get("payment_frequency")
        if payment_frequency is not None:
            update_data["payment_frequency"] = _normalize_payment_frequency(payment_frequency)

        rules = property_data.get("rules")
        if rules is not None:
            if isinstance(rules, str):
                try:
                    update_data["rules"] = json.loads(rules)
                except (ValueError, TypeError):
                    update_data["rules"] = []
            elif isinstance(rules, list):
                update_data["rules"] = rules

        available_from = property_data.get("available_from") or property_data.get("availability_start")
        if available_from is not None:
            update_data["available_from"] = available_from

        if status is not None:
            update_data["status"] = status
        
        # Update property
        print(f"📝 [BACKEND-UPDATE] Sending update to Supabase: {update_data}")
        response = supabase_admin.table("properties").update(update_data).eq(
            "id", property_id
        ).execute()

        print(f"📊 [BACKEND-UPDATE] Supabase response: data={response.data}, count={response.count}")

        #region debug-point H5-database-saved
        # Debug: Verify what was actually saved to the database
        if response.data:
            saved_data = response.data[0]
            print(f"✅ [BACKEND-UPDATE] Saved to DB: title={saved_data.get('title')}, price={saved_data.get('price')}")

            try:
                import urllib.request
                import json
                debug_data = {
                    "hypothesisId": "H5",
                    "stage": "database-saved",
                    "property_id": property_id,
                    "saved_fields": {
                        "title": saved_data.get("title"),
                        "price": saved_data.get("price"),
                        "beds": saved_data.get("beds"),
                        "baths": saved_data.get("baths"),
                        "status": saved_data.get("status")
                    },
                    "update_data_sent": update_data
                }
                urllib.request.urlopen(
                    urllib.request.Request(
                        "http://127.0.0.1:7778/event",
                        data=json.dumps(debug_data).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    ),
                    timeout=1
                )
            except Exception as e:
                print(f"⚠️ [BACKEND-UPDATE] Failed to report to debug server: {e}")
        else:
            print(f"⚠️ [BACKEND-UPDATE] Supabase returned no data! Response: {response}")
            try:
                import urllib.request
                import json
                debug_data = {
                    "hypothesisId": "H5",
                    "stage": "database-saved-empty",
                    "property_id": property_id,
                    "message": "Supabase returned empty data",
                    "update_data_sent": update_data
                }
                urllib.request.urlopen(
                    urllib.request.Request(
                        "http://127.0.0.1:7778/event",
                        data=json.dumps(debug_data).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    ),
                    timeout=1
                )
            except Exception:
                pass
        #endregion debug-point H5-database-saved

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        return {
            "success": True,
            "message": "Property updated successfully",
            "property": response.data[0]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error updating property: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update property: {str(e)}"
        )

# ============================================================================
# DELETE PROPERTY ENDPOINT
# ============================================================================

@router.delete("/{property_id}")
async def delete_property(
    property_id: str,
    current_user: dict = Depends(get_current_landlord)
):
    """
    Delete property (soft delete - landlord only, own properties)
    """
    try:
        landlord_id = current_user["id"]
        
        # Verify ownership
        property_check = supabase_admin.table("properties").select("landlord_id, title").eq(
            "id", property_id
        ).execute()
        
        if not property_check.data or property_check.data[0]["landlord_id"] != landlord_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete this property"
            )
        
        property_title = property_check.data[0]["title"]
        

        # REG-08 + UX fix: only set deleted_at — do NOT touch verification_status.
        # Setting verification_status='rejected' on landlord-delete was a semantic bug:
        # it conflated admin-rejection (property_verification.py) with self-deletion,
        # causing the UI to label deleted properties as "Rejected". Now:
        #   • deleted_at IS NOT NULL         → landlord has deleted the property
        #   • verification_status='rejected' → admin has rejected the property
        # Marketplace queries already filter by deleted_at IS NULL, so this change
        # preserves all filtering behavior while restoring semantic accuracy.
        supabase_admin.table("properties").update({
            "deleted_at": datetime.now().isoformat()
        }).eq("id", property_id).execute()
        
        return {
            "success": True,
            "message": f"Property '{property_title}' deleted successfully",
            "property_id": property_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error deleting property: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to delete property: {str(e)}"
        )





















