"""
Property routes
"""
from fastapi import APIRouter, HTTPException, Depends, Query, status, Form, File, UploadFile
from app.models.property import PropertyCreate, PropertyUpdate, PropertyResponse, PropertyListResponse, PropertySearch
from app.database import supabase_admin
from app.middleware.auth import get_current_user, get_current_landlord, get_optional_current_user
from typing import Optional, List
from datetime import datetime
import math
import json
import uuid
import os

router = APIRouter(prefix="/properties")


@router.get("/search")
async def search_properties(
    location: Optional[str] = Query(None),
    min_budget: Optional[float] = Query(None, ge=0),
    max_budget: Optional[float] = Query(None, ge=0),
    bedrooms: Optional[int] = Query(None, ge=0),
    bathrooms: Optional[int] = Query(None, ge=1),
    property_type: Optional[str] = Query(None),
    sort: str = Query("newest", regex="^(newest|price_low|price_high)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: Optional[dict] = Depends(get_optional_current_user)
):
    """
    Search properties with filters and pagination
    """
    try:
        # Build query - fetch properties only (no join)
        query = supabase_admin.table("properties").select(
            "*",
            count="exact"
        ).eq("status", "vacant")
        
        # Apply filters
        if location:
            query = query.ilike("location", f"%{location}%")
        
        if min_budget:
            query = query.gte("price", min_budget)
        
        if max_budget:
            query = query.lte("price", max_budget)
        
        if bedrooms:
            query = query.eq("beds", bedrooms)
        
        if bathrooms:
            query = query.gte("baths", bathrooms)
        
        if property_type:
            query = query.eq("property_type", property_type)
        
        # Apply sorting
        if sort == "newest":
            query = query.order("created_at", desc=True)
        elif sort == "price_low":
            query = query.order("price", desc=False)
        elif sort == "price_high":
            query = query.order("price", desc=True)
        
        # Apply pagination
        offset = (page - 1) * limit
        query = query.range(offset, offset + limit - 1)
        
        # Execute query
        response = query.execute()
        
        # Calculate pagination
        total = response.count if hasattr(response, 'count') else len(response.data)
        total_pages = math.ceil(total / limit) if total > 0 else 1
        
        # Fetch all unique landlord IDs
        landlord_ids = list(set([prop.get('landlord_id') for prop in response.data if prop.get('landlord_id')]))
        
        # Fetch all landlords in a single query (MUCH FASTER!)
        landlords_map = {}
        if landlord_ids:
            try:
                landlords_response = supabase_admin.table("users").select(
                    "id, full_name, avatar_url, trust_score, verification_status"
                ).in_("id", landlord_ids).execute()
                
                # Create a map of landlord_id -> landlord_data
                for landlord in landlords_response.data:
                    landlords_map[landlord['id']] = {
                        'id': landlord['id'],
                        'name': landlord.get('full_name'),
                        'avatar_url': landlord.get('avatar_url'),
                        'trust_score': landlord.get('trust_score', 50),
                        'verified': landlord.get('verification_status') == 'approved',
                        'properties_count': 0,
                        'joined_year': datetime.now().year,
                        'guarantee_joined': False
                    }
            except Exception as e:
                print(f"Error fetching landlords: {e}")
        
        # Format properties with landlord data
        properties = []
        for prop in response.data:
            property_dict = {**prop}
            
            # Add landlord data if available
            if prop.get('landlord_id') and prop['landlord_id'] in landlords_map:
                property_dict['landlord'] = landlords_map[prop['landlord_id']]
            
            properties.append(property_dict)
        
        return {
            "success": True,
            "properties": properties,
            "pagination": {
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


@router.post("/", response_model=PropertyResponse)
async def create_property_with_files(
    title: str = Form(...),
    description: str = Form(...),
    property_type: str = Form(...),
    location: str = Form(...),
    address: str = Form(...),
    rent_amount: float = Form(...),
    bedrooms: int = Form(...),
    bathrooms: int = Form(...),
    square_feet: Optional[int] = Form(None),
    amenities: str = Form("[]"),  # JSON string
    availability_start: Optional[str] = Form(None),
    images: List[UploadFile] = File([]),
    current_user: dict = Depends(get_current_landlord)
):
    """
    Create a new property listing with file uploads (landlords only)
    """
    try:
        landlord_id = current_user["id"]
        
        # Debug logging
        print(f"📥 Received property creation request from landlord: {landlord_id}")
        print(f"  Title: {title}")
        print(f"  Property Type: {property_type}")
        print(f"  Location: {location}")
        print(f"  Rent Amount: {rent_amount}")
        print(f"  Bedrooms: {bedrooms}, Bathrooms: {bathrooms}")
        print(f"  Images count: {len(images)}")
        
        # Parse amenities JSON
        try:
            amenities_list = json.loads(amenities) if amenities else []
            print(f"  Amenities: {amenities_list}")
        except json.JSONDecodeError as e:
            print(f"  ⚠️ Failed to parse amenities JSON: {e}")
            amenities_list = []
        
        # Handle image uploads (for now, we'll store placeholder URLs)
        # TODO: Implement actual file upload to Supabase Storage
        print(f"  Processing {len(images)} images...")
        image_urls = []
        
        # For now, just use placeholder images regardless of upload
        # This avoids timeout issues while we implement proper file upload
        num_images = len(images) if images else 1
        for i in range(min(num_images, 5)):  # Max 5 images
            placeholder_url = f"https://images.unsplash.com/photo-{1560448204 + i}-e02f11c3d0e2?w=800&h=600&fit=crop"
            image_urls.append(placeholder_url)
        
        print(f"  Using {len(image_urls)} placeholder images")
        
        # Prepare property data (using correct database field names)
        property_dict = {
            "landlord_id": landlord_id,
            "title": title,
            "description": description,
            "property_type": property_type,
            "location": location,
            "address": address,
            "city": "Lagos",
            "state": "Lagos State",
            "country": "Nigeria",
            "price": int(rent_amount),  # Convert to integer
            "beds": int(bedrooms),  # Ensure integer
            "baths": int(bathrooms),  # Ensure integer
            "sqft": int(square_feet) if square_feet else None,
            "status": "vacant",  # Use 'vacant' for available properties
            "featured": False,
            "year_built": None,
            "furnished": False,
            "parking_spaces": 0,
            "utilities_included": False,
            "pet_friendly": False,
            "security_deposit": int(rent_amount),  # Convert to integer
            "lease_duration": "12 months",
            "available_from": availability_start if availability_start else None,
            "images": image_urls,  # Database uses 'images' field
            "amenities": amenities_list,
            "rules": [],
            "neighborhood": None,
            "latitude": None,
            "longitude": None
        }
        
        # Insert property
        print(f"💾 Inserting property into database...")
        print(f"  Property dict keys: {list(property_dict.keys())}")
        
        try:
            response = supabase_admin.table("properties").insert(property_dict).execute()
        except Exception as db_error:
            print(f"  ❌ Database insert error: {str(db_error)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Database error: {str(db_error)}"
            )
        
        if not response.data:
            print(f"  ❌ Database insert failed - no data returned")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create property - database insert returned no data"
            )
        
        property_result = response.data[0]
        print(f"  ✅ Property created with ID: {property_result.get('id')}")
        
        # Fetch landlord info
        landlord_response = supabase_admin.table("users").select(
            "id, full_name, avatar_url, trust_score, verification_status"
        ).eq("id", landlord_id).execute()
        
        landlord_data = landlord_response.data[0] if landlord_response.data else None
        if landlord_data:
            property_result['landlord'] = {
                'id': landlord_data['id'],
                'name': landlord_data.get('full_name'),
                'avatar_url': landlord_data.get('avatar_url'),
                'trust_score': landlord_data.get('trust_score', 50),
                'verified': landlord_data.get('verification_status') == 'approved',
                'properties_count': 1,
                'joined_year': datetime.now().year,
                'guarantee_joined': False
            }
        
        return property_result
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ ERROR creating property:")
        print(error_details)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create property: {str(e)}"
        )


@router.get("/my-properties", response_model=PropertyListResponse)
async def get_my_properties(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_landlord)
):
    """
    Get all properties for the current landlord
    """
    try:
        landlord_id = current_user["id"]
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Fetch properties with count
        query = supabase_admin.table("properties").select(
            "*", count="exact"
        ).eq("landlord_id", landlord_id).order("created_at", desc=True)
        
        # Apply pagination
        response = query.range(offset, offset + limit - 1).execute()
        
        properties = response.data or []
        total = response.count or 0
        
        # Add landlord info to each property
        for property_item in properties:
            property_item['landlord'] = {
                'id': landlord_id,
                'name': current_user.get('full_name'),
                'avatar_url': current_user.get('avatar_url'),
                'trust_score': current_user.get('trust_score', 50),
                'verified': current_user.get('verification_status') == 'approved',
                'properties_count': total,
                'joined_year': datetime.now().year,
                'guarantee_joined': False
            }
            property_item['is_favorited'] = False  # Landlord's own properties
        
        # Calculate pagination
        total_pages = math.ceil(total / limit) if total > 0 else 1
        
        return {
            "success": True,
            "properties": properties,
            "pagination": {
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch properties: {str(e)}"
        )


@router.get("/{property_id}")
async def get_property(
    property_id: str,
    current_user: Optional[dict] = Depends(get_optional_current_user)
):
    """
    Get property details by ID
    """
    try:
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
        
        # Increment view count
        supabase_admin.table("properties").update({
            "view_count": property_data.get("view_count", 0) + 1
        }).eq("id", property_id).execute()
        
        # Fetch landlord data separately
        if property_data.get('landlord_id'):
            try:
                landlord_response = supabase_admin.table("users").select(
                    "id, full_name, avatar_url, trust_score, verification_status"
                ).eq("id", property_data['landlord_id']).execute()
                
                if landlord_response.data:
                    landlord_data = landlord_response.data[0]
                    property_data['landlord'] = {
                        'id': landlord_data['id'],
                        'name': landlord_data.get('full_name'),
                        'avatar_url': landlord_data.get('avatar_url'),
                        'trust_score': landlord_data.get('trust_score', 50),
                        'verified': landlord_data.get('verification_status') == 'approved',
                        'properties_count': 0,
                        'joined_year': datetime.now().year,
                        'guarantee_joined': False
                    }
            except Exception as e:
                print(f"Error fetching landlord: {e}")
                # Continue without landlord data
        
        # Check if favorited by current user
        property_data['is_favorited'] = False
        if current_user:
            fav_check = supabase_admin.table("favorites").select("*").eq(
                "tenant_id", current_user["id"]
            ).eq("property_id", property_id).execute()
            property_data['is_favorited'] = len(fav_check.data) > 0
        
        return property_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch property: {str(e)}"
        )


@router.patch("/{property_id}", response_model=PropertyResponse)
async def update_property(
    property_id: str,
    property_data: PropertyUpdate,
    current_user: dict = Depends(get_current_landlord)
):
    """
    Update property (landlord only, own properties)
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
        
        # Update property
        update_dict = property_data.dict(exclude_unset=True)
        response = supabase_admin.table("properties").update(update_dict).eq(
            "id", property_id
        ).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update property"
            )
        
        return response.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update property: {str(e)}"
        )


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
        property_check = supabase_admin.table("properties").select("landlord_id").eq(
            "id", property_id
        ).execute()
        
        if not property_check.data or property_check.data[0]["landlord_id"] != landlord_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete this property"
            )
        
        # Soft delete
        supabase_admin.table("properties").update({
            "deleted_at": datetime.now().isoformat(),
            "status": "inactive"
        }).eq("id", property_id).execute()
        
        return {
            "success": True,
            "message": "Property deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to delete property: {str(e)}"
        )
