"""
Viewing Requests routes
"""
from fastapi import APIRouter, HTTPException, Depends, status
from app.database import supabase_admin
from app.middleware.auth import get_current_tenant
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime

router = APIRouter(prefix="/viewing-requests")


class ViewingRequestCreate(BaseModel):
    property_id: str
    preferred_date: str  # YYYY-MM-DD format
    time_slot: Literal['morning', 'afternoon', 'evening']
    contact_number: str
    message: Optional[str] = None
    tenant_name: str


class ViewingRequestUpdate(BaseModel):
    status: Literal['pending', 'confirmed', 'cancelled', 'completed']
    landlord_notes: Optional[str] = None
    confirmed_date: Optional[str] = None
    confirmed_time: Optional[str] = None


@router.get("/")
async def get_viewing_requests(
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Get tenant's viewing requests
    """
    try:
        tenant_id = current_user["id"]
        
        # Build query (simplified without complex joins)
        query = supabase_admin.table("viewing_requests").select("*").eq("tenant_id", tenant_id)
        
        # Apply status filter if provided
        if status_filter:
            query = query.eq("status", status_filter)
        
        response = query.order("created_at", desc=True).execute()
        
        # Format response
        viewing_requests = []
        for req in response.data:
            try:
                # Fetch property details separately
                property_response = supabase_admin.table("properties").select("*").eq(
                    "id", req["property_id"]
                ).execute()
                
                property_data = property_response.data[0] if property_response.data else None
                
                # Fetch landlord details separately
                landlord_data = None
                if property_data and property_data.get("landlord_id"):
                    landlord_response = supabase_admin.table("users").select(
                        "id, full_name, avatar_url, phone_number, email"
                    ).eq("id", property_data["landlord_id"]).execute()
                    landlord_data = landlord_response.data[0] if landlord_response.data else None
                
                viewing_requests.append({
                    "id": req["id"],
                    "property": property_data,
                    "landlord": landlord_data,
                    "preferred_date": req["preferred_date"],
                    "time_slot": req["time_slot"],
                    "contact_number": req["contact_number"],
                    "message": req.get("message"),
                    "status": req["status"],
                    "landlord_notes": req.get("landlord_notes"),
                    "confirmed_date": req.get("confirmed_date"),
                    "confirmed_time": req.get("confirmed_time"),
                    "created_at": req["created_at"],
                    "updated_at": req.get("updated_at")
                })
            except Exception as req_error:
                print(f"Error processing viewing request {req.get('id')}: {str(req_error)}")
                continue
        
        return {
            "success": True,
            "viewing_requests": viewing_requests,
            "count": len(viewing_requests)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch viewing requests: {str(e)}"
        )


@router.get("/{request_id}")
async def get_viewing_request(
    request_id: str,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Get specific viewing request details
    """
    try:
        tenant_id = current_user["id"]
        
        # Fetch viewing request (simplified)
        response = supabase_admin.table("viewing_requests").select("*").eq(
            "id", request_id
        ).eq("tenant_id", tenant_id).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Viewing request not found"
            )
        
        req = response.data[0]
        
        # Fetch property details separately
        property_response = supabase_admin.table("properties").select("*").eq(
            "id", req["property_id"]
        ).execute()
        property_data = property_response.data[0] if property_response.data else None
        
        # Fetch landlord details separately
        landlord_data = None
        if property_data and property_data.get("landlord_id"):
            landlord_response = supabase_admin.table("users").select(
                "id, full_name, avatar_url, phone_number, email"
            ).eq("id", property_data["landlord_id"]).execute()
            landlord_data = landlord_response.data[0] if landlord_response.data else None
        
        # Combine data
        viewing_request = {
            **req,
            "property": property_data,
            "landlord": landlord_data
        }
        
        return {
            "success": True,
            "viewing_request": viewing_request
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch viewing request: {str(e)}"
        )


@router.post("/")
async def create_viewing_request(
    request_data: ViewingRequestCreate,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Create a new viewing request
    """
    try:
        tenant_id = current_user["id"]
        
        # Verify property exists
        property_check = supabase_admin.table("properties").select(
            "id, landlord_id, title"
        ).eq("id", request_data.property_id).execute()
        
        if not property_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        landlord_id = property_check.data[0]["landlord_id"]
        
        # Check for duplicate pending requests
        existing_request = supabase_admin.table("viewing_requests").select("id").eq(
            "tenant_id", tenant_id
        ).eq("property_id", request_data.property_id).eq(
            "status", "pending"
        ).execute()
        
        if existing_request.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have a pending viewing request for this property"
            )
        
        # Create viewing request
        request_dict = {
            "tenant_id": tenant_id,
            "landlord_id": landlord_id,
            "property_id": request_data.property_id,
            "preferred_date": request_data.preferred_date,
            "time_slot": request_data.time_slot,
            "contact_number": request_data.contact_number,
            "message": request_data.message,
            "tenant_name": request_data.tenant_name,
            "status": "pending"
        }
        
        response = supabase_admin.table("viewing_requests").insert(request_dict).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create viewing request"
            )
        
        # TODO: Send notification to landlord (email/SMS)
        # TODO: Create notification record
        
        return {
            "success": True,
            "message": "Viewing request sent successfully",
            "viewing_request": response.data[0]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create viewing request: {str(e)}"
        )


@router.patch("/{request_id}")
async def update_viewing_request(
    request_id: str,
    update_data: ViewingRequestUpdate,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Update viewing request (tenant can cancel)
    """
    try:
        tenant_id = current_user["id"]
        
        # Verify request exists and belongs to tenant
        existing_request = supabase_admin.table("viewing_requests").select("*").eq(
            "id", request_id
        ).eq("tenant_id", tenant_id).execute()
        
        if not existing_request.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Viewing request not found"
            )
        
        # Tenant can only cancel their own requests
        if update_data.status != "cancelled":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenants can only cancel viewing requests"
            )
        
        # Update request
        update_dict = {
            "status": update_data.status,
            "updated_at": datetime.now().isoformat()
        }
        
        response = supabase_admin.table("viewing_requests").update(
            update_dict
        ).eq("id", request_id).execute()
        
        return {
            "success": True,
            "message": "Viewing request updated successfully",
            "viewing_request": response.data[0]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update viewing request: {str(e)}"
        )


@router.delete("/{request_id}")
async def delete_viewing_request(
    request_id: str,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Delete viewing request (soft delete by setting status to cancelled)
    """
    try:
        tenant_id = current_user["id"]
        
        # Verify request exists and belongs to tenant
        existing_request = supabase_admin.table("viewing_requests").select("*").eq(
            "id", request_id
        ).eq("tenant_id", tenant_id).execute()
        
        if not existing_request.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Viewing request not found"
            )
        
        # Soft delete by setting status to cancelled
        supabase_admin.table("viewing_requests").update({
            "status": "cancelled",
            "updated_at": datetime.now().isoformat()
        }).eq("id", request_id).execute()
        
        return {
            "success": True,
            "message": "Viewing request cancelled successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to delete viewing request: {str(e)}"
        )
