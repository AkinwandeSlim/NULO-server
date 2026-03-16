"""
Favorites routes
"""
from fastapi import APIRouter, HTTPException, Depends, status
from app.database import supabase_admin
from app.middleware.auth import get_current_tenant, get_current_user
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/favorites")


class FavoriteCreate(BaseModel):
    property_id: str


@router.get("/")
async def get_favorites(current_user: dict = Depends(get_current_user)):
    """
    Get user's favorite properties.
    Returns empty list for non-tenants (admins/landlords browsing the marketplace).
    """
    # Admins and landlords don't have favorites — return empty gracefully
    if current_user.get("user_type") != "tenant":
        return {"success": True, "favorites": [], "total": 0, "count": 0}

    try:
        tenant_id = current_user["id"]
        
        # Fetch favorites (simplified query without complex joins)
        favorites_response = supabase_admin.table("favorites").select(
            "*"
        ).eq("tenant_id", tenant_id).order("created_at", desc=True).execute()
        
        # Format response
        favorites = []
        for fav in favorites_response.data:
            try:
                # Fetch property details separately
                property_response = supabase_admin.table("properties").select("*").eq(
                    "id", fav["property_id"]
                ).execute()
                
                if property_response.data and len(property_response.data) > 0:
                    property_data = property_response.data[0]
                    
                    # Fetch landlord details separately
                    landlord_response = supabase_admin.table("users").select(
                        "id, full_name, avatar_url, trust_score, verification_status"
                    ).eq("id", property_data["landlord_id"]).execute()
                    
                    if landlord_response.data and len(landlord_response.data) > 0:
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
                    
                    property_data['is_favorited'] = True
                    favorites.append(property_data)
            except Exception as fav_error:
                # Log error but continue processing other favorites
                print(f"Error processing favorite {fav.get('id')}: {str(fav_error)}")
                continue
        
        return {
            "success": True,
            "favorites": favorites,
            "total": len(favorites),
            "count": len(favorites)  # Keep for backward compatibility
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch favorites: {str(e)}"
        )


@router.post("/")
async def add_favorite(
    favorite_data: FavoriteCreate,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Add property to favorites (tenants only)
    """
    try:
        tenant_id = current_user["id"]
        property_id = favorite_data.property_id
        
        print(f"\n{'='*60}")
        print(f"📝 [ADD FAVORITE] Request from tenant: {tenant_id}")
        print(f"📝 [ADD FAVORITE] Property ID: {property_id}")
        print(f"📝 [ADD FAVORITE] Current user data: {current_user}")
        print(f"{'='*60}\n")
        
        # Check if property exists
        property_check = supabase_admin.table("properties").select("id").eq(
            "id", property_id
        ).execute()
        
        if not property_check.data:
            print(f"❌ [ADD FAVORITE] Property not found: {property_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        print(f"✅ [ADD FAVORITE] Property exists: {property_id}")
        
        # Check if already favorited
        existing_fav = supabase_admin.table("favorites").select("*").eq(
            "tenant_id", tenant_id
        ).eq("property_id", property_id).execute()
        
        if existing_fav.data:
            print(f"⚠️ [ADD FAVORITE] Property already favorited: {property_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Property already in favorites"
            )
        
        # Add to favorites
        fav_dict = {
            "tenant_id": tenant_id,
            "property_id": property_id
        }
        
        print(f"💾 [ADD FAVORITE] Inserting favorite record: {fav_dict}")
        response = supabase_admin.table("favorites").insert(fav_dict).execute()
        
        if not response.data:
            print(f"❌ [ADD FAVORITE] Failed to insert favorite")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to add favorite"
            )
        
        print(f"✅ [ADD FAVORITE] Successfully added favorite: {property_id}")
        return {
            "success": True,
            "message": "Property added to favorites",
            "favorite": response.data[0]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [ADD FAVORITE] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to add favorite: {str(e)}"
        )


@router.delete("/{property_id}")
async def remove_favorite(
    property_id: str,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Remove property from favorites (tenants only)
    """
    try:
        tenant_id = current_user["id"]
        
        print(f"🗑️ [REMOVE FAVORITE] Request from tenant: {tenant_id}")
        print(f"🗑️ [REMOVE FAVORITE] Property ID: {property_id}")
        
        # Check if favorited
        existing_fav = supabase_admin.table("favorites").select("*").eq(
            "tenant_id", tenant_id
        ).eq("property_id", property_id).execute()
        
        if not existing_fav.data:
            print(f"❌ [REMOVE FAVORITE] Not found for tenant {tenant_id}, property {property_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Favorite not found"
            )
        
        print(f"✅ [REMOVE FAVORITE] Found favorite, deleting...")
        # Remove from favorites
        supabase_admin.table("favorites").delete().eq(
            "tenant_id", tenant_id
        ).eq("property_id", property_id).execute()
        
        print(f"✅ [REMOVE FAVORITE] Successfully removed favorite: {property_id}")
        return {
            "success": True,
            "message": "Property removed from favorites"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [REMOVE FAVORITE] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to remove favorite: {str(e)}"
        )


@router.get("/check/{property_id}")
async def check_favorite(
    property_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Check if a property is in user's favorites.
    Always returns false for non-tenants.
    """
    # Non-tenants never have favorites
    if current_user.get("user_type") != "tenant":
        return {"is_favorite": False}

    try:
        tenant_id = current_user["id"]
        
        # Check if favorited
        existing_fav = supabase_admin.table("favorites").select("*").eq(
            "tenant_id", tenant_id
        ).eq("property_id", property_id).execute()
        
        is_favorite = bool(existing_fav.data and len(existing_fav.data) > 0)
        
        return {
            "is_favorite": is_favorite
        }
        
    except Exception as e:
        print(f"❌ [CHECK FAVORITE] Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to check favorite: {str(e)}"
        )