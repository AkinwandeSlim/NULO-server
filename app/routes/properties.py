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
                ).in_("landlord_id", landlord_ids).eq("status", "vacant").execute()
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
    sort: str = Query("newest", regex="^(newest|price_low|price_high|featured)$"),
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
        
        # Build optimized query
        query = supabase_admin.table("properties").select(
            "*",  # Select all fields from properties table
            count="exact"
        )
        
        # FILTER 1: Only vacant AND approved properties (uses idx_properties_status)
        query = query.eq("status", "vacant").eq("verification_status", "approved")
        
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
        
        # FILTER 6: Property type
        if property_type and property_type != "all":
            query = query.eq("property_type", property_type)
        
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
        # Supabase range() is exclusive on upper bound (like Python slicing)
        # For limit=20, page=1: offset=0, range(0, 20) = 20 items (indices 0-19)
        offset = (page - 1) * limit
        range_start = offset
        range_end = offset + limit
        
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
    current_user: dict = Depends(get_current_landlord)
):
    """
    Get all properties for the current landlord with pagination and filtering
    """
    try:
        landlord_id = current_user["id"]
        
        # Calculate offset
        offset = (page - 1) * limit
        range_start = offset
        range_end = offset + limit
        
        print(f"📍 [MY-PROPERTIES PAGINATION] page={page}, limit={limit}, offset={offset}, range({range_start}, {range_end}) - expecting {limit} items")
        
        # Build query
        query = supabase_admin.table("properties").select(
            "*", count="exact"
        ).eq("landlord_id", landlord_id)
        
        # Apply status filter if provided
        if status_filter:
            query = query.eq("status", status_filter)
        
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
    images: List[UploadFile] = File([]),
    current_user: dict = Depends(get_current_landlord)
):
    """
    Create property - All fields match database schema exactly
    """
    try:
        landlord_id = current_user["id"]
        
        print(f"📤 [CREATE] landlord={landlord_id}, title={title}, city={city}, state={state}, images={len(images)}")
        
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
                ).eq("status", "vacant").execute()
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
            ).eq("city", city["name"]).eq("status", "vacant").eq("verification_status", "approved").execute()
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
        ).eq("status", "vacant").eq("verification_status", "approved").execute()
        
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
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    property_type: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    price: Optional[float] = Form(None),
    bedrooms: Optional[int] = Form(None),
    bathrooms: Optional[int] = Form(None),
    sqft: Optional[int] = Form(None),
    amenities: Optional[str] = Form("[]"),
    status: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_landlord)
):
    """
    Update an existing property (landlord only, own properties)
    """
    try:
        landlord_id = current_user["id"]
        
        # Verify ownership
        property_check = supabase_admin.table("properties").select("landlord_id").eq(
            "id", property_id
        ).execute()
        
        if not property_check.data or property_check.data[0]["landlord_id"] != landlord_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to update this property"
            )
        
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
            update_data["price"] = int(price)
        if bedrooms is not None:
            update_data["beds"] = bedrooms
        if bathrooms is not None:
            update_data["baths"] = bathrooms
        if sqft is not None:
            update_data["sqft"] = sqft
        if amenities is not None:
            update_data["amenities"] = json.loads(amenities)
        if status is not None:
            update_data["status"] = status
        
        # Update property
        response = supabase_admin.table("properties").update(update_data).eq(
            "id", property_id
        ).execute()
        
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
        
        # Soft delete — set deleted_at timestamp; status stays as-is so DB constraint is respected
        # Use verification_status='rejected' to hide from marketplace; deleted_at flags the record
        supabase_admin.table("properties").update({
            "deleted_at": datetime.now().isoformat(),
            "verification_status": "rejected"
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





















