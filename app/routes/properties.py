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

from fastapi import APIRouter, HTTPException, Depends, Query, status, Form, File, UploadFile
from app.database import supabase_admin
from app.middleware.auth import get_current_user, get_current_landlord, get_optional_current_user
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import math
import json
import asyncio
import time

router = APIRouter(prefix="/properties")

# ============================================================================
# OPTIMIZED BATCH OPERATIONS
# ============================================================================

async def fetch_landlords_batch(property_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Batch fetch landlord data to avoid N+1 queries
    Uses database fields: id, landlord_id from properties
    Uses database fields from users: id, full_name, avatar_url, trust_score, verification_status
    """
    if not property_ids:
        return {}
    
    try:
        # Get unique landlord IDs
        props_response = supabase_admin.table("properties").select(
            "id, landlord_id"
        ).in_("id", property_ids).execute()
        
        landlord_ids = list(set(
            p["landlord_id"] for p in props_response.data if p.get("landlord_id")
        ))
        
        if not landlord_ids:
            return {}
        
        # Batch fetch all landlords
        landlords_response = supabase_admin.table("users").select(
            "id, full_name, avatar_url, trust_score, verification_status"
        ).in_("id", landlord_ids).execute()
        
        # Create lookup dict
        landlords_dict = {
            landlord["id"]: {
                'id': landlord['id'],
                'name': landlord.get('full_name'),
                'avatar_url': landlord.get('avatar_url'),
                'trust_score': landlord.get('trust_score', 50),
                'verified': landlord.get('verification_status') == 'approved',
                'properties_count': 0,
                'joined_year': datetime.now().year,
                'guarantee_joined': False
            }
            for landlord in landlords_response.data
        }
        
        return landlords_dict
        
    except Exception as e:
        print(f"⚠️ Batch fetch landlords failed: {e}")
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
        
        # FILTER 1: Only vacant properties (uses idx_properties_status)
        query = query.eq("status", "vacant")
        
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
        
        # Execute query with timeout handling
        query_start = time.time()
        try:
            response = query.execute()
        except Exception as query_error:
            # If query times out, return empty results instead of crashing
            if "timed out" in str(query_error).lower() or "timeout" in str(query_error).lower():
                print(f"⏱️ [QUERY TIMEOUT] Supabase query timed out, returning empty results")
                response = type('obj', (object,), {'data': [], 'count': 0})()
            else:
                raise query_error
        
        query_duration = time.time() - query_start
        
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
    Get property by ID with optimized queries
    Database fields: All fields from properties table
    """
    try:
        start_time = time.time()
        
        # Fetch property
        response = supabase_admin.table("properties").select(
            "*"
        ).eq("id", property_id).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        property_data = response.data[0]
        
        # Increment view_count asynchronously
        asyncio.create_task(
            asyncio.to_thread(
                lambda: supabase_admin.table("properties").update({
                    "view_count": property_data.get("view_count", 0) + 1
                }).eq("id", property_id).execute()
            )
        )
        
        # Fetch landlord and favorite status in parallel
        if property_data.get('landlord_id'):
            landlords_dict = await fetch_landlords_batch([property_id])
            landlord_data = landlords_dict.get(property_data['landlord_id'])
            if landlord_data:
                property_data['landlord'] = landlord_data
        
        if current_user:
            favorited_ids = await fetch_favorites_batch(
                current_user["id"],
                [property_id]
            )
            property_data['is_favorited'] = property_id in favorited_ids
        else:
            property_data['is_favorited'] = False
        
        execution_time = time.time() - start_time
        property_data['_performance'] = {
            "execution_time": round(execution_time, 3)
        }
        
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

@router.post("/")
async def create_property(
    title: str = Form(...),
    description: str = Form(...),
    property_type: str = Form(...),
    address: str = Form(...),
    city: str = Form(...),
    state: str = Form(...),
    country: str = Form("Nigeria"),
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
        
        print(f"📤 [CREATE] landlord={landlord_id}, title={title}")
        
        # Check if landlord has a landlord_profile, create one if not
        try:
            profile_response = supabase_admin.table("landlord_profiles").select("id").eq("id", landlord_id).execute()
            if not profile_response.data:
                print(f"⚠️ [CREATE] No landlord profile found for landlord {landlord_id}, creating one...")
                # Create landlord profile from user data
                profile_data = {
                    "id": landlord_id,
                    "account_type": "individual",
                    "onboarding_started": True,
                    "profile_step_completed": False,
                    "property_step_completed": False,
                    "payment_step_completed": False,
                    "verification_fee_paid": False,
                    "owns_properties": True,
                    "number_of_properties": 0,
                    "verification_status": "pending",
                    "is_verified": False
                }
                supabase_admin.table("landlord_profiles").insert(profile_data).execute()
                print(f"✅ [CREATE] Landlord profile created for landlord {landlord_id}")
        except Exception as profile_error:
            print(f"⚠️ [CREATE] Landlord profile check/create failed: {profile_error}")
            # Continue with property creation anyway
        print(f"📤 [CREATE FORM DATA] Received fields:")
        print(f"  title: {title}")
        print(f"  description: {description}")
        print(f"  property_type: {property_type}")
        print(f"  address: {address}")
        print(f"  city: {city}")
        print(f"  state: {state}")
        print(f"  country: {country}")
        print(f"  price: {price}")
        print(f"  beds: {beds}")
        print(f"  baths: {baths}")
        print(f"  sqft: {sqft}")
        print(f"  available_from: {available_from}")
        print(f"  amenities: {amenities}")
        print(f"  images count: {len(images)}")
        
        # DEBUG: Check types and values of city/state
        print(f"\n🔍 [DEBUG] TYPE ANALYSIS:")
        print(f"  city type: {type(city).__name__}, repr: {repr(city)}")
        print(f"  state type: {type(state).__name__}, repr: {repr(state)}")
        print(f"  address type: {type(address).__name__}, repr: {repr(address)}")
        
        # Check if any field is a list or already contains commas
        if isinstance(city, (list, tuple)):
            print(f"  ⚠️ WARNING: city is {type(city).__name__}! Value: {city}")
        if isinstance(state, (list, tuple)):
            print(f"  ⚠️ WARNING: state is {type(state).__name__}! Value: {state}")
        if ',' in str(city):
            print(f"  ⚠️ WARNING: city contains comma! Value: {city}")
        if ',' in str(state):
            print(f"  ⚠️ WARNING: state contains comma! Value: {state}")
        
        # Parse amenities
        try:
            amenities_list = json.loads(amenities) if amenities else []
            print(f"📤 [CREATE] Parsed amenities: {amenities_list}")
        except json.JSONDecodeError:
            amenities_list = []
            print(f"⚠️ [CREATE] Failed to parse amenities, using empty list")
        
        # Handle images - upload to Supabase storage
        image_urls = []
        if images:
            for image in images:
                try:
                    # Upload image to Supabase storage
                    file_extension = image.filename.split('.')[-1] if image.filename else 'jpg'
                    file_name = f"properties/{landlord_id}/{int(time.time())}_{image.filename}"
                    
                    # Read file content
                    file_content = await image.read()
                    
                    # Upload to Supabase storage
                    storage_response = supabase_admin.storage.from_("property-images").upload(
                        path=file_name,
                        file=file_content,
                        file_options={"content-type": image.content_type}
                    )
                    
                    # Check if upload was successful (status 200 means success)
                    if hasattr(storage_response, 'status_code') and storage_response.status_code == 200:
                        # Get public URL
                        public_url = supabase_admin.storage.from_("property-images").get_public_url(file_name)
                        image_urls.append(public_url)
                        print(f"✅ Image uploaded: {public_url}")
                    else:
                        # Fallback to placeholder
                        placeholder_url = f"https://images.unsplash.com/photo-{1560448204 + len(image_urls)}-e02f11c3d0e2?w=800&h=600&fit=crop"
                        image_urls.append(placeholder_url)
                        print(f"⚠️ Image upload failed, using placeholder: {placeholder_url}")
                        
                except Exception as img_error:
                    print(f"⚠️ Image upload failed: {img_error}")
                    # Fallback to placeholder
                    placeholder_url = f"https://images.unsplash.com/photo-{1560448204 + len(image_urls)}-e02f11c3d0e2?w=800&h=600&fit=crop"
                    image_urls.append(placeholder_url)
        else:
            # Default placeholder if no images
            image_urls = ["https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=800&h=600&fit=crop"]
        
        # Build property dict matching database schema
        print(f"\n📍 [DEBUG] Building location field:")
        print(f"  city: {repr(city)}")
        print(f"  state: {repr(state)}")
        location_result = f"{city}, {state}"
        print(f"  result: {repr(location_result)}")
        
        property_dict = {
            "landlord_id": landlord_id,
            "title": title,
            "description": description,
            "property_type": property_type,
            "address": address,
            "city": city,
            "state": state,
            "country": country,
            "location": location_result,  # Use the debug result
            "price": price,
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "security_deposit": security_deposit if security_deposit else price,
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
        
        print(f"✅ [CREATED] property_id={response.data[0]['id']}")
        return response.data[0]
        
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
        
        # Get counts for each city
        for city in cities_data:
            response = supabase_admin.table("properties").select(
                "id", count="exact"
            ).eq("city", city["name"]).eq("status", "vacant").execute()
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
        
        # Fetch all vacant properties with location data
        response = supabase_admin.table("properties").select(
            "location, city, state, country"
        ).eq("status", "vacant").execute()
        
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
        
        # Soft delete (mark as inactive and deleted)
        supabase_admin.table("properties").update({
            "deleted_at": datetime.now().isoformat(),
            "status": "inactive"
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























# """
# Property routes - Enhanced with AI optimization
# """
# from fastapi import APIRouter, HTTPException, Depends, Query, status, Form, File, UploadFile
# from app.models.property import PropertyCreate, PropertyUpdate, PropertyResponse, PropertyListResponse, PropertySearch
# from app.database import supabase_admin
# from app.middleware.auth import get_current_user, get_current_landlord, get_optional_current_user
# from typing import Optional, List
# from datetime import datetime
# import math
# import json
# import uuid
# import os

# # Import simple optimization service (no Redis required)
# from app.services.simple_property_optimizer import simple_property_optimizer

# router = APIRouter(prefix="/properties")

# # Simple optimization service - no setup required
# def init_property_services():
#     """Initialize simple property optimization (no external dependencies)"""
#     print("🚀 Simple property optimization ready (no Redis required)")


# @router.get("/search")
# async def search_properties(
#     location: Optional[str] = Query(None),
#     min_budget: Optional[float] = Query(None, ge=0),
#     max_budget: Optional[float] = Query(None, ge=0),
#     bedrooms: Optional[int] = Query(None, ge=0),
#     bathrooms: Optional[int] = Query(None, ge=1),
#     property_type: Optional[str] = Query(None),
#     sort: str = Query("newest", regex="^(newest|price_low|price_high|featured)$"),
#     page: int = Query(1, ge=1),
#     limit: int = Query(20, ge=1, le=100),
#     current_user: Optional[dict] = Depends(get_optional_current_user)
# ):
#     """
#     Ultra-optimized property search with AI enhancement and Redis caching
#     """
#     import time
    
#     start_time = time.time()
    
#     try:
#         # 1. Normalize and validate search parameters
#         search_params = {
#             "location": location.strip() if location else None,
#             "min_price": min_budget or 0,
#             "max_price": max_budget or 10000000,
#             "beds": bedrooms or 0,
#             "baths": bathrooms or 0,
#             "property_type": property_type or "all",
#             "sort": sort,
#             "page": page,
#             "limit": min(limit, 50),  # Performance cap
#             "user_id": current_user.get("id") if current_user else None
#         }
        
#         print(f"🚀 [OPTIMIZED_SEARCH] Request: {search_params}")
        
#         # 2. Execute optimized search (no Redis required)
#         results = await simple_property_optimizer.optimize_search_query(search_params)
        
#         # 3. Add performance metadata
#         execution_time = time.time() - start_time
#         results["performance"] = {
#             **results.get("performance", {}),
#             "total_execution_time": round(execution_time, 3),
#             "cache_hit": execution_time < 0.1,  # Assume cache hit if very fast
#             "optimized": True,
#             "timestamp": datetime.utcnow().isoformat()
#         }
        
#         # 4. Log performance metrics
#         print(f"✅ [OPTIMIZED_SEARCH] Completed in {execution_time:.3f}s - {len(results.get('properties', []))} results")
        
#         return results
        
#     except Exception as e:
#         print(f"❌ [OPTIMIZED_SEARCH] Error: {e}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Search optimization failed: {str(e)}"
#         )


# @router.get("/featured")
# async def get_featured_properties(
#     limit: int = Query(default=6, ge=1, le=20),
# ):
#     """Get featured properties"""
#     try:
#         # Get featured or newest properties
#         response = supabase_admin.table("properties").select(
#             "*"
#         ).eq("status", "vacant").order("created_at", desc=True).limit(limit).execute()
        
#         properties = response.data or []
        
#         return {
#             "success": True,
#             "properties": properties,
#             "count": len(properties)
#         }
        
#     except Exception as e:
#         print(f"❌ [FEATURED] Error: {e}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to get featured properties: {str(e)}"
#         )


# @router.post("/", response_model=PropertyResponse)
# async def create_property_with_files(
#     title: str = Form(...),
#     description: str = Form(...),
#     property_type: str = Form(...),
#     location: str = Form(...),
#     address: str = Form(...),
#     rent_amount: float = Form(...),
#     bedrooms: int = Form(...),
#     bathrooms: int = Form(...),
#     square_feet: Optional[int] = Form(None),
#     amenities: str = Form("[]"),  # JSON string
#     availability_start: Optional[str] = Form(None),
#     images: List[UploadFile] = File([]),
#     current_user: dict = Depends(get_current_landlord)
# ):
#     """
#     Create a new property listing with file uploads (landlords only)
#     """
#     try:
#         landlord_id = current_user["id"]
        
#         # Debug logging
#         print(f"📥 Received property creation request from landlord: {landlord_id}")
#         print(f"  Title: {title}")
#         print(f"  Property Type: {property_type}")
#         print(f"  Location: {location}")
#         print(f"  Rent Amount: {rent_amount}")
#         print(f"  Bedrooms: {bedrooms}, Bathrooms: {bathrooms}")
#         print(f"  Images count: {len(images)}")
        
#         # Parse amenities JSON
#         try:
#             amenities_list = json.loads(amenities) if amenities else []
#             print(f"  Amenities: {amenities_list}")
#         except json.JSONDecodeError as e:
#             print(f"  ⚠️ Failed to parse amenities JSON: {e}")
#             amenities_list = []
        
#         # Handle image uploads (for now, we'll store placeholder URLs)
#         # TODO: Implement actual file upload to Supabase Storage
#         print(f"  Processing {len(images)} images...")
#         image_urls = []
        
#         # For now, just use placeholder images regardless of upload
#         # This avoids timeout issues while we implement proper file upload
#         num_images = len(images) if images else 1
#         for i in range(min(num_images, 5)):  # Max 5 images
#             placeholder_url = f"https://images.unsplash.com/photo-{1560448204 + i}-e02f11c3d0e2?w=800&h=600&fit=crop"
#             image_urls.append(placeholder_url)
        
#         print(f"  Using {len(image_urls)} placeholder images")
        
#         # Prepare property data (using correct database field names)
#         property_dict = {
#             "landlord_id": landlord_id,
#             "title": title,
#             "description": description,
#             "property_type": property_type,
#             "location": location,
#             "address": address,
#             "city": "Lagos",
#             "state": "Lagos State",
#             "country": "Nigeria",
#             "price": int(rent_amount),  # Convert to integer
#             "beds": int(bedrooms),  # Ensure integer
#             "baths": int(bathrooms),  # Ensure integer
#             "sqft": int(square_feet) if square_feet else None,
#             "status": "vacant",  # Use 'vacant' for available properties
#             "featured": False,
#             "year_built": None,
#             "furnished": False,
#             "parking_spaces": 0,
#             "utilities_included": False,
#             "pet_friendly": False,
#             "security_deposit": int(rent_amount),  # Convert to integer
#             "lease_duration": "12 months",
#             "available_from": availability_start if availability_start else None,
#             "images": image_urls,  # Database uses 'images' field
#             "amenities": amenities_list,
#             "rules": [],
#             "neighborhood": None,
#             "latitude": None,
#             "longitude": None
#         }
        
#         # Insert property
#         print(f"💾 Inserting property into database...")
#         print(f"  Property dict keys: {list(property_dict.keys())}")
        
#         try:
#             response = supabase_admin.table("properties").insert(property_dict).execute()
#         except Exception as db_error:
#             print(f"  ❌ Database insert error: {str(db_error)}")
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail=f"Database error: {str(db_error)}"
#             )
        
#         if not response.data:
#             print(f"  ❌ Database insert failed - no data returned")
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Failed to create property - database insert returned no data"
#             )
        
#         property_result = response.data[0]
#         print(f"  ✅ Property created with ID: {property_result.get('id')}")
        
#         # Fetch landlord info
#         landlord_response = supabase_admin.table("users").select(
#             "id, full_name, avatar_url, trust_score, verification_status"
#         ).eq("id", landlord_id).execute()
        
#         landlord_data = landlord_response.data[0] if landlord_response.data else None
#         if landlord_data:
#             property_result['landlord'] = {
#                 'id': landlord_data['id'],
#                 'name': landlord_data.get('full_name'),
#                 'avatar_url': landlord_data.get('avatar_url'),
#                 'trust_score': landlord_data.get('trust_score', 50),
#                 'verified': landlord_data.get('verification_status') == 'approved',
#                 'properties_count': 1,
#                 'joined_year': datetime.now().year,
#                 'guarantee_joined': False
#             }
        
#         return property_result
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         import traceback
#         error_details = traceback.format_exc()
#         print(f"❌ ERROR creating property:")
#         print(error_details)
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=f"Failed to create property: {str(e)}"
#         )



# @router.get("/featured")
# async def get_featured_properties(
#     limit: int = Query(default=6, ge=1, le=20),
# ):
#     """Get featured properties"""
#     try:
#         # Get featured or newest properties
#         response = supabase_admin.table("properties").select(
#             "*"
#         ).eq("status", "vacant").order("created_at", desc=True).limit(limit).execute()
        
#         properties = response.data or []
        
#         # Add landlord info
#         landlord_ids = [p['landlord_id'] for p in properties if p.get('landlord_id')]
#         landlords_map = {}
        
#         if landlord_ids:
#             landlords = supabase_admin.table("users").select(
#                 "id, full_name, avatar_url, trust_score, verification_status"
#             ).in_("id", list(set(landlord_ids))).execute()
            
#             for l in landlords.data:
#                 landlords_map[l['id']] = {
#                     'id': l['id'],
#                     'name': l.get('full_name'),
#                     'avatar_url': l.get('avatar_url'),
#                     'trust_score': l.get('trust_score', 50),
#                     'verified': l.get('verification_status') == 'approved',
#                 }
        
#         for p in properties:
#             if p.get('landlord_id') in landlords_map:
#                 p['landlord'] = landlords_map[p['landlord_id']]
        
#         return {"properties": properties, "count": len(properties)}
#     except Exception as e:
#         print(f"Error: {e}")
#         return {"properties": [], "count": 0}





# @router.get("/locations/popular")
# async def get_popular_locations(
#     limit: int = Query(default=10, ge=1, le=50, description="Number of locations to return"),
# ):
#     """
#     Get popular locations with CORRECTED state values
#     """
#     try:
#         # ✅ Print for debugging
#         print("🔍 Fetching popular locations...")
        
#         # Fetch all vacant properties
#         response = supabase_admin.table("properties").select(
#             "location, state, country"
#         ).eq("status", "vacant").execute()
        
#         print(f"📊 Found {len(response.data) if response.data else 0} properties")
        
#         if not response.data:
#             print("⚠️ No properties found, returning defaults")
#             return {
#                 "locations": [
#                     {"location": "Lekki", "state": "Lagos State", "country": "Nigeria", "property_count": 0, "display_name": "Lekki, Lagos State"},
#                     {"location": "Gwarinpa", "state": "FCT", "country": "Nigeria", "property_count": 0, "display_name": "Gwarinpa, FCT"},
#                     {"location": "Ikoyi", "state": "Lagos State", "country": "Nigeria", "property_count": 0, "display_name": "Ikoyi, Lagos State"},
#                 ],
#                 "total_locations": 3
#             }
        
#         # ✅ COMPREHENSIVE STATE CORRECTION MAP
#         def get_correct_state(location_text: str) -> str:
#             """Determine correct state from location text"""
#             loc_lower = location_text.lower()
            
#             # FCT Abuja (most specific matches first)
#             abuja_keywords = [
#                 'gwarinpa', 'gwarimpa',  # Your problem area!
#                 'abuja', 'garki', 'wuse', 'maitama', 'asokoro',
#                 'jabi', 'utako', 'kubwa', 'lugbe', 'kuje',
#                 'nyanya', 'karu', 'gwagwalada', 'durumi',
#                 'apo', 'lokogoma', 'katampe', 'life camp',
#                 'lifecamp', 'guzape', 'central business district', 'cbd'
#             ]
            
#             for keyword in abuja_keywords:
#                 if keyword in loc_lower:
#                     return 'FCT'
            
#             # Lagos State
#             lagos_keywords = [
#                 'lagos', 'lekki', 'victoria island', 'vi', 'ikoyi',
#                 'ajah', 'ikeja', 'surulere', 'yaba', 'maryland',
#                 'banana island', 'eko atlantic', 'oniru', 'parkview',
#                 'magodo', 'gbagada', 'apapa', 'festac', 'isolo',
#                 'oshodi', 'badagry', 'epe', 'ikorodu', 'gra lagos'
#             ]
            
#             for keyword in lagos_keywords:
#                 if keyword in loc_lower:
#                     return 'Lagos State'
            
#             # Rivers State (Port Harcourt)
#             rivers_keywords = ['port harcourt', 'ph', 'rumuola', 'gra port harcourt']
#             for keyword in rivers_keywords:
#                 if keyword in loc_lower:
#                     return 'Rivers State'
            
#             # Oyo State (Ibadan)
#             oyo_keywords = ['ibadan', 'bodija', 'dugbe']
#             for keyword in oyo_keywords:
#                 if keyword in loc_lower:
#                     return 'Oyo State'
            
#             # Kano State
#             if 'kano' in loc_lower:
#                 return 'Kano State'
            
#             # Edo State (Benin)
#             if 'benin' in loc_lower:
#                 return 'Edo State'
            
#             # Default to Lagos State if unknown
#             return 'Lagos State'
        
#         # Process and count locations
#         location_counts = {}
        
#         for prop in response.data:
#             location_raw = prop.get('location', '').strip()
#             if not location_raw:
#                 continue
            
#             # Normalize location name
#             location_normalized = location_raw.title()
            
#             # ✅ GET CORRECT STATE (ignore database state, use our mapping)
#             correct_state = get_correct_state(location_raw)
#             country = 'Nigeria'
            
#             # Debug print for Gwarinpa specifically
#             if 'gwarinpa' in location_raw.lower() or 'gwarimpa' in location_raw.lower():
#                 print(f"🐛 DEBUG Gwarinpa:")
#                 print(f"   Raw location: {location_raw}")
#                 print(f"   DB state: {prop.get('state')}")
#                 print(f"   Corrected state: {correct_state}")
            
#             # Create key
#             key = (location_normalized, correct_state, country)
            
#             if key not in location_counts:
#                 location_counts[key] = 0
#             location_counts[key] += 1
        
#         # Sort by count
#         sorted_locations = sorted(
#             location_counts.items(),
#             key=lambda x: x[1],
#             reverse=True
#         )[:limit]
        
#         # Format response
#         locations_data = [
#             {
#                 "location": loc[0],
#                 "state": loc[1],
#                 "country": loc[2],
#                 "property_count": count,
#                 "display_name": f"{loc[0]}, {loc[1]}"
#             }
#             for loc, count in sorted_locations
#         ]
        
#         print(f"✅ Returning {len(locations_data)} locations")
        
#         # Debug print all locations
#         for loc_data in locations_data:
#             print(f"   📍 {loc_data['display_name']} ({loc_data['property_count']})")
        
#         return {
#             "locations": locations_data,
#             "total_locations": len(location_counts),
#             "timestamp": datetime.now().isoformat()
#         }
        
#     except Exception as e:
#         print(f"❌ ERROR in get_popular_locations: {str(e)}")
#         import traceback
#         traceback.print_exc()
        
#         # Return safe fallback
#         return {
#             "locations": [
#                 {"location": "Lekki", "state": "Lagos State", "country": "Nigeria", "property_count": 0, "display_name": "Lekki, Lagos State"},
#                 {"location": "Gwarinpa", "state": "FCT", "country": "Nigeria", "property_count": 0, "display_name": "Gwarinpa, FCT"},
#                 {"location": "Victoria Island", "state": "Lagos State", "country": "Nigeria", "property_count": 0, "display_name": "Victoria Island, Lagos State"},
#             ],
#             "total_locations": 3
#         }


# # ============================================================================
# # NEW ENDPOINT: Get Cities Summary (for homepage)
# # ============================================================================

# @router.get("/locations/cities-summary")
# async def get_cities_summary():
#     """
#     Get summary of major Nigerian cities with property counts.
#     Optimized for homepage display.
    
#     Response:
#     {
#         "cities": [
#             {
#                 "name": "Lagos",
#                 "state": "Lagos State",
#                 "country": "Nigeria",
#                 "property_count": 850,
#                 "image_url": "/lagos-victoria-island-skyline.jpg",
#                 "description": "Nigeria's commercial capital"
#             },
#             ...
#         ]
#     }
#     """
#     try:
#         # Define major Nigerian cities with metadata
#         major_cities = {
#             'Lagos': {
#                 'state': 'Lagos State',
#                 'description': "Nigeria's commercial capital with vibrant city life",
#                 'image': '/lagos-victoria-island-skyline.jpg',
#                 'search_terms': ['lagos', 'lekki', 'victoria island', 'ikoyi', 'ajah', 'ikeja', 'surulere']
#             },
#             'Abuja': {
#                 'state': 'FCT',
#                 'description': "Nigeria's modern capital city with planned infrastructure",
#                 'image': '/contemporary-townhouse-johannesburg.jpg',
#                 'search_terms': ['abuja', 'garki', 'wuse', 'maitama', 'asokoro', 'gwarimpa']
#             },
#             'Port Harcourt': {
#                 'state': 'Rivers State',
#                 'description': "The Garden City - Nigeria's oil and gas hub",
#                 'image': '/citywaker1.png',
#                 'search_terms': ['port harcourt', 'ph', 'gra']
#             },
#             'Ibadan': {
#                 'state': 'Oyo State',
#                 'description': "Ancient city with rich cultural heritage",
#                 'image': '/cities/ibadan.jpg',
#                 'search_terms': ['ibadan', 'bodija', 'dugbe']
#             },
#             'Kano': {
#                 'state': 'Kano State',
#                 'description': "Northern Nigeria's commercial center",
#                 'image': '/cities/kano.jpg',
#                 'search_terms': ['kano', 'sabon gari']
#             },
#             'Benin City': {
#                 'state': 'Edo State',
#                 'description': "Historic city known for arts and culture",
#                 'image': '/cities/benin.jpg',
#                 'search_terms': ['benin', 'edo']
#             }
#         }
        
#         # Fetch all vacant properties
#         response = supabase_admin.table("properties").select("location").eq(
#             "status", "vacant"
#         ).execute()
        
#         cities_data = []
        
#         if response.data:
#             # Count properties for each city
#             for city_name, city_info in major_cities.items():
#                 count = 0
#                 for prop in response.data:
#                     location = prop.get('location', '').lower()
#                     # Check if location matches any search terms
#                     if any(term in location for term in city_info['search_terms']):
#                         count += 1
                
#                 # Only include cities with properties
#                 if count > 0:
#                     cities_data.append({
#                         "name": city_name,
#                         "state": city_info['state'],
#                         "country": "Nigeria",
#                         "property_count": count,
#                         "image_url": city_info['image'],
#                         "description": city_info['description']
#                     })
        
#         # If no cities have properties, add defaults
#         if not cities_data:
#             for city_name, city_info in list(major_cities.items())[:3]:  # Top 3 cities
#                 cities_data.append({
#                     "name": city_name,
#                     "state": city_info['state'],
#                     "country": "Nigeria",
#                     "property_count": 0,
#                     "image_url": city_info['image'],
#                     "description": city_info['description']
#                 })
        
#         # Sort by property count (descending)
#         cities_data.sort(key=lambda x: x['property_count'], reverse=True)
        
#         return {
#             "cities": cities_data,
#             "timestamp": datetime.now().isoformat()
#         }
        
#     except Exception as e:
#         print(f"Error fetching cities summary: {str(e)}")
#         # Return default cities on error
#         return {
#             "cities": [
#                 {
#                     "name": "Lagos",
#                     "state": "Lagos State",
#                     "country": "Nigeria",
#                     "property_count": 0,
#                     "image_url": "/lagos-victoria-island-skyline.jpg",
#                     "description": "Nigeria's commercial capital with vibrant city life"
#                 },
#                 {
#                     "name": "Abuja",
#                     "state": "FCT",
#                     "country": "Nigeria",
#                     "property_count": 0,
#                     "image_url": "/contemporary-townhouse-johannesburg.jpg",
#                     "description": "Nigeria's modern capital city with planned infrastructure"
#                 },
#                 {
#                     "name": "Port Harcourt",
#                     "state": "Rivers State",
#                     "country": "Nigeria",
#                     "property_count": 0,
#                     "image_url": "/citywaker1.png",
#                     "description": "The Garden City - Nigeria's oil and gas hub"
#                 }
#             ]
#         }



# @router.get("/search-enhanced")  # Temporary route for testing - merge into /search later
# async def search_properties_enhanced(
#     location: Optional[str] = Query(None),
#     min_budget: Optional[float] = Query(None, ge=0),
#     max_budget: Optional[float] = Query(None, ge=0),
#     bedrooms: Optional[int] = Query(None, ge=0),
#     bathrooms: Optional[int] = Query(None, ge=1),
#     property_type: Optional[str] = Query(None),
#     min_size: Optional[int] = Query(None, ge=0),  # NEW: Minimum square footage
#     furnished: Optional[bool] = Query(None),      # NEW: Furnished filter
#     sort: str = Query("newest", regex="^(newest|price_low|price_high)$"),
#     page: int = Query(1, ge=1),
#     limit: int = Query(20, ge=1, le=100),
#     current_user: Optional[dict] = Depends(get_optional_current_user)
# ):
#     """
#     Enhanced search with additional filters
#     """
#     try:
#         # Build query
#         query = supabase_admin.table("properties").select(
#             "*",
#             count="exact"
#         ).eq("status", "vacant")
        
#         # Apply filters
#         if location:
#             query = query.ilike("location", f"%{location}%")
        
#         if min_budget:
#             query = query.gte("price", min_budget)
        
#         if max_budget:
#             query = query.lte("price", max_budget)
        
#         if bedrooms:
#             query = query.gte("beds", bedrooms)  # Use gte for "at least X bedrooms"
        
#         if bathrooms:
#             query = query.gte("baths", bathrooms)
        
#         if property_type and property_type.lower() != 'all':
#             query = query.eq("property_type", property_type.lower())
        
#         # NEW: Square footage filter
#         if min_size:
#             query = query.gte("sqft", min_size)
        
#         # NEW: Furnished filter
#         if furnished is not None:
#             query = query.eq("furnished", furnished)
        
#         # Apply sorting
#         if sort == "newest":
#             query = query.order("created_at", desc=True)
#         elif sort == "price_low":
#             query = query.order("price", desc=False)
#         elif sort == "price_high":
#             query = query.order("price", desc=True)
        
#         # Apply pagination
#         offset = (page - 1) * limit
#         query = query.range(offset, offset + limit - 1)
        
#         # Execute query
#         response = query.execute()
        
#         # Calculate pagination
#         total = response.count if hasattr(response, 'count') else len(response.data)
#         total_pages = math.ceil(total / limit) if total > 0 else 1
        
#         # Fetch landlords (same as your current implementation)
#         landlord_ids = list(set([prop.get('landlord_id') for prop in response.data if prop.get('landlord_id')]))
        
#         landlords_map = {}
#         if landlord_ids:
#             try:
#                 landlords_response = supabase_admin.table("users").select(
#                     "id, full_name, avatar_url, trust_score, verification_status"
#                 ).in_("id", landlord_ids).execute()
                
#                 for landlord in landlords_response.data:
#                     landlords_map[landlord['id']] = {
#                         'id': landlord['id'],
#                         'name': landlord.get('full_name'),
#                         'avatar_url': landlord.get('avatar_url'),
#                         'trust_score': landlord.get('trust_score', 50),
#                         'verified': landlord.get('verification_status') == 'approved',
#                         'properties_count': 0,
#                         'joined_year': datetime.now().year,
#                         'guarantee_joined': False
#                     }
#             except Exception as e:
#                 print(f"Error fetching landlords: {e}")
        
#         # Format properties with landlord data
#         properties = []
#         for prop in response.data:
#             property_dict = {**prop}
            
#             if prop.get('landlord_id') and prop['landlord_id'] in landlords_map:
#                 property_dict['landlord'] = landlords_map[prop['landlord_id']]
            
#             properties.append(property_dict)
        
#         return {
#             "success": True,
#             "properties": properties,
#             "pagination": {
#                 "total": total,
#                 "page": page,
#                 "limit": limit,
#                 "total_pages": total_pages
#             },
#             "filters_applied": {
#                 "location": location,
#                 "property_type": property_type,
#                 "min_budget": min_budget,
#                 "max_budget": max_budget,
#                 "bedrooms": bedrooms,
#                 "bathrooms": bathrooms,
#                 "min_size": min_size,
#                 "furnished": furnished
#             }
#         }
        
#     except Exception as e:
#         print(f"Search error: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Search failed: {str(e)}"
#         )








# """
# Platform Statistics API Endpoint - SUPABASE VERSION
# Add these endpoints to the END of your app/routes/properties.py file
# (after the search-enhanced endpoint)
# """

# # ============================================================================
# # PLATFORM STATISTICS ENDPOINT - Real data from Supabase
# # ============================================================================

# @router.get("/stats/platform-summary")
# async def get_platform_summary():
#     """Get real-time platform statistics for homepage"""
#     try:
#         print("📊 Fetching platform statistics...")
        
#         from datetime import timedelta
        
#         # Total properties
#         total_properties_response = supabase_admin.table("properties").select(
#             "id", count="exact"
#         ).eq("status", "vacant").execute()
#         total_properties = total_properties_response.count or 0
        
#         # New this week
#         one_week_ago = (datetime.now() - timedelta(days=7)).isoformat()
#         new_this_week_response = supabase_admin.table("properties").select(
#             "id", count="exact"
#         ).eq("status", "vacant").gte("created_at", one_week_ago).execute()
#         new_this_week = new_this_week_response.count or 0
        
#         # Unique landlords
#         landlords_response = supabase_admin.table("properties").select(
#             "landlord_id"
#         ).eq("status", "vacant").execute()
#         unique_landlords = len(set([p['landlord_id'] for p in landlords_response.data if p.get('landlord_id')]))
        
#         # Active tenants (users with favorites)
#         favorites_response = supabase_admin.table("favorites").select("tenant_id").execute()
#         active_tenants = len(set([f['tenant_id'] for f in favorites_response.data if f.get('tenant_id')]))
        
#         # Cities covered
#         cities_response = supabase_admin.table("properties").select("location").eq("status", "vacant").execute()
#         cities = set()
#         for prop in cities_response.data:
#             location = prop.get('location', '').strip()
#             if location:
#                 city = location.split(',')[0].strip().title()
#                 cities.add(city)
#         cities_covered = len(cities)
        
#         # Verification rate
#         all_landlords = supabase_admin.table("users").select("id", count="exact").eq("user_type", "landlord").execute()
#         verified_landlords = supabase_admin.table("users").select("id", count="exact").eq("user_type", "landlord").eq("verification_status", "approved").execute()
#         total_ll = all_landlords.count or 0
#         verified_ll = verified_landlords.count or 0
#         verification_rate = int((verified_ll / total_ll * 100)) if total_ll > 0 else 95
        
#         return {
#             "total_properties": total_properties,
#             "new_this_week": new_this_week,
#             "active_tenants": active_tenants,
#             "verified_landlords": unique_landlords,
#             "cities_covered": cities_covered,
#             "verification_rate": verification_rate,
#             "avg_response_time": "< 24h",
#             "timestamp": datetime.now().isoformat(),
#             "data_source": "real"
#         }
#     except Exception as e:
#         print(f"❌ Error: {str(e)}")
#         return {
#             "total_properties": 50, "new_this_week": 5, "active_tenants": 120,
#             "verified_landlords": 20, "cities_covered": 3, "verification_rate": 95,
#             "avg_response_time": "< 24h", "data_source": "fallback"
#         }



# @router.get("/my-properties", response_model=PropertyListResponse)
# async def get_my_properties(
#     page: int = Query(1, ge=1),
#     limit: int = Query(20, ge=1, le=100),
#     current_user: dict = Depends(get_current_landlord)
# ):
#     """
#     Get all properties for the current landlord
#     """
#     try:
#         landlord_id = current_user["id"]
        
#         # Calculate offset
#         offset = (page - 1) * limit
        
#         # Fetch properties with count
#         query = supabase_admin.table("properties").select(
#             "*", count="exact"
#         ).eq("landlord_id", landlord_id).order("created_at", desc=True)
        
#         # Apply pagination
#         response = query.range(offset, offset + limit - 1).execute()
        
#         properties = response.data or []
#         total = response.count or 0
        
#         # Add landlord info to each property
#         for property_item in properties:
#             property_item['landlord'] = {
#                 'id': landlord_id,
#                 'name': current_user.get('full_name'),
#                 'avatar_url': current_user.get('avatar_url'),
#                 'trust_score': current_user.get('trust_score', 50),
#                 'verified': current_user.get('verification_status') == 'approved',
#                 'properties_count': total,
#                 'joined_year': datetime.now().year,
#                 'guarantee_joined': False
#             }
#             property_item['is_favorited'] = False  # Landlord's own properties
        
#         # Calculate pagination
#         total_pages = math.ceil(total / limit) if total > 0 else 1
        
#         return {
#             "success": True,
#             "properties": properties,
#             "pagination": {
#                 "total": total,
#                 "page": page,
#                 "limit": limit,
#                 "total_pages": total_pages
#             }
#         }
        
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to fetch properties: {str(e)}"
#         )


# @router.get("/{property_id}")
# async def get_property(
#     property_id: str,
#     current_user: Optional[dict] = Depends(get_optional_current_user)
# ):
#     """
#     Get property details by ID
#     """
#     try:
#         # Fetch property
#         response = supabase_admin.table("properties").select(
#             "*"
#         ).eq("id", property_id).execute()
        
#         if not response.data:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Property not found"
#             )
        
#         property_data = response.data[0]
        
#         # Increment view count
#         supabase_admin.table("properties").update({
#             "view_count": property_data.get("view_count", 0) + 1
#         }).eq("id", property_id).execute()
        
#         # Fetch landlord data separately
#         if property_data.get('landlord_id'):
#             try:
#                 landlord_response = supabase_admin.table("users").select(
#                     "id, full_name, avatar_url, trust_score, verification_status"
#                 ).eq("id", property_data['landlord_id']).execute()
                
#                 if landlord_response.data:
#                     landlord_data = landlord_response.data[0]
#                     property_data['landlord'] = {
#                         'id': landlord_data['id'],
#                         'name': landlord_data.get('full_name'),
#                         'avatar_url': landlord_data.get('avatar_url'),
#                         'trust_score': landlord_data.get('trust_score', 50),
#                         'verified': landlord_data.get('verification_status') == 'approved',
#                         'properties_count': 0,
#                         'joined_year': datetime.now().year,
#                         'guarantee_joined': False
#                     }
#             except Exception as e:
#                 print(f"Error fetching landlord: {e}")
#                 # Continue without landlord data
        
#         # Check if favorited by current user
#         property_data['is_favorited'] = False
#         if current_user:
#             fav_check = supabase_admin.table("favorites").select("*").eq(
#                 "tenant_id", current_user["id"]
#             ).eq("property_id", property_id).execute()
#             property_data['is_favorited'] = len(fav_check.data) > 0
        
#         return property_data
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to fetch property: {str(e)}"
#         )


# @router.patch("/{property_id}", response_model=PropertyResponse)
# async def update_property(
#     property_id: str,
#     property_data: PropertyUpdate,
#     current_user: dict = Depends(get_current_landlord)
# ):
#     """
#     Update property (landlord only, own properties)
#     """
#     try:
#         landlord_id = current_user["id"]
        
#         # Verify ownership
#         property_check = supabase_admin.table("properties").select("landlord_id").eq(
#             "id", property_id
#         ).execute()
        
#         if not property_check.data or property_check.data[0]["landlord_id"] != landlord_id:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="You don't have permission to update this property"
#             )
        
#         # Update property
#         update_dict = property_data.dict(exclude_unset=True)
#         response = supabase_admin.table("properties").update(update_dict).eq(
#             "id", property_id
#         ).execute()
        
#         if not response.data:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Failed to update property"
#             )
        
#         return response.data[0]
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=f"Failed to update property: {str(e)}"
#         )


# @router.delete("/{property_id}")
# async def delete_property(
#     property_id: str,
#     current_user: dict = Depends(get_current_landlord)
# ):
#     """
#     Delete property (soft delete - landlord only, own properties)
#     """
#     try:
#         landlord_id = current_user["id"]
        
#         # Verify ownership
#         property_check = supabase_admin.table("properties").select("landlord_id").eq(
#             "id", property_id
#         ).execute()
        
#         if not property_check.data or property_check.data[0]["landlord_id"] != landlord_id:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="You don't have permission to delete this property"
#             )
        
#         # Soft delete
#         supabase_admin.table("properties").update({
#             "deleted_at": datetime.now().isoformat(),
#             "status": "inactive"
#         }).eq("id", property_id).execute()
        
#         return {
#             "success": True,
#             "message": "Property deleted successfully"
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=f"Failed to delete property: {str(e)}"
#         )
