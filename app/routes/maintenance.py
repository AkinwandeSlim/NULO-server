"""
Maintenance routes - Using Supabase (not SQLAlchemy)
Post Move-in Maintenance Management
"""
from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File
from app.database import supabase_admin
from app.middleware.auth import get_current_user
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date

router = APIRouter(prefix="/maintenance")


class MaintenanceCreate(BaseModel):
    """Model for creating new maintenance requests"""
    property_id: str
    category: str  # PLUMBING, ELECTRICAL, APPLIANCE, HVAC, PEST_CONTROL, SECURITY, STRUCTURAL, OTHER
    title: str = Field(..., min_length=5, max_length=255)
    description: str = Field(..., min_length=20)
    urgency: str = Field("MEDIUM", description="Issue urgency level")  # LOW, MEDIUM, HIGH, EMERGENCY
    preferred_date: Optional[str] = None  # YYYY-MM-DD format


class MaintenanceUpdate(BaseModel):
    """Model for updating maintenance requests"""
    status: Optional[str] = None  # PENDING, ACKNOWLEDGED, IN_PROGRESS, RESOLVED, CLOSED
    landlord_response: Optional[str] = Field(None, min_length=10)
    resolution_notes: Optional[str] = Field(None, min_length=10)
    estimated_cost: Optional[float] = Field(None, ge=0)
    actual_cost: Optional[float] = Field(None, ge=0)
    scheduled_date: Optional[str] = None  # YYYY-MM-DD format
    tenant_rating: Optional[int] = Field(None, ge=1, le=5)
    tenant_feedback: Optional[str] = Field(None, min_length=10)


@router.post("/")
async def create_maintenance_request(
    maintenance_data: MaintenanceCreate,
    photos: Optional[List[UploadFile]] = File(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new maintenance request
    Only tenants can create maintenance requests for properties they're renting
    """
    try:
        # Verify user is a tenant
        if current_user["user_type"] != "tenant":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only tenants can create maintenance requests"
            )
        
        # Verify property exists
        property_response = supabase_admin.table("properties").select("*").eq(
            "id", maintenance_data.property_id
        ).execute()
        
        if not property_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        property = property_response.data[0]
        
        # TODO: Verify tenant is actively renting this property
        # This would require checking active agreements/leases
        
        # Handle photo uploads
        photo_urls = []
        if photos:
            for photo in photos:
                photo_url = await upload_maintenance_photo(photo, maintenance_data.property_id)
                photo_urls.append(photo_url)
        
        # Create maintenance request
        maintenance_dict = {
            "property_id": maintenance_data.property_id,
            "tenant_id": current_user["id"],
            "landlord_id": property["landlord_id"],
            "category": maintenance_data.category,
            "title": maintenance_data.title,
            "description": maintenance_data.description,
            "urgency": maintenance_data.urgency,
            "photos": photo_urls,
            "preferred_date": maintenance_data.preferred_date,
            "status": "PENDING"
        }
        
        response = supabase_admin.table("maintenance_requests").insert(maintenance_dict).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create maintenance request"
            )
        
        maintenance_request = response.data[0]
        
        # Send notification to landlord
        await send_maintenance_notification(maintenance_request, "landlord")
        
        return maintenance_request
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create maintenance request: {str(e)}"
        )


@router.get("/")
async def get_maintenance_requests(
    status: Optional[str] = None,
    urgency: Optional[str] = None,
    property_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Get maintenance requests for the current user
    Tenants see their requests, landlords see requests for their properties
    """
    try:
        # Build query based on user type
        if current_user["user_type"] == "tenant":
            query = supabase_admin.table("maintenance_requests").select("*").eq("tenant_id", current_user["id"])
        else:  # landlord
            query = supabase_admin.table("maintenance_requests").select("*").eq("landlord_id", current_user["id"])
        
        # Apply filters
        if status:
            query = query.eq("status", status)
        
        if urgency:
            query = query.eq("urgency", urgency)
        
        if property_id:
            query = query.eq("property_id", property_id)
        
        response = query.order("created_at", desc=True).execute()
        
        return response.data
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get maintenance requests: {str(e)}"
        )


@router.get("/{request_id}")
async def get_maintenance_request(
    request_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a specific maintenance request by ID
    Users can only view requests they are involved in
    """
    try:
        response = supabase_admin.table("maintenance_requests").select("*").eq(
            "id", request_id
        ).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Maintenance request not found"
            )
        
        maintenance_request = response.data[0]
        
        # Check authorization
        if (maintenance_request["tenant_id"] != current_user["id"] and 
            maintenance_request["landlord_id"] != current_user["id"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this maintenance request"
            )
        
        return maintenance_request
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get maintenance request: {str(e)}"
        )


@router.patch("/{request_id}")
async def update_maintenance_request(
    request_id: str,
    update_data: MaintenanceUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Update a maintenance request
    Landlords can update status, add response, schedule date
    Tenants can add feedback, rating
    """
    try:
        # Get maintenance request
        response = supabase_admin.table("maintenance_requests").select("*").eq(
            "id", request_id
        ).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Maintenance request not found"
            )
        
        maintenance_request = response.data[0]
        
        # Check authorization
        if (maintenance_request["tenant_id"] != current_user["id"] and 
            maintenance_request["landlord_id"] != current_user["id"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this maintenance request"
            )
        
        # Prepare update data
        update_dict = {}
        
        # Landlord updates
        if current_user["user_type"] == "landlord":
            if update_data.status:
                # Validate status transitions
                current_status = maintenance_request["status"]
                new_status = update_data.status
                
                valid_transitions = {
                    "PENDING": ["ACKNOWLEDGED", "IN_PROGRESS"],
                    "ACKNOWLEDGED": ["IN_PROGRESS", "RESOLVED"],
                    "IN_PROGRESS": ["RESOLVED"]
                }
                
                if new_status not in valid_transitions.get(current_status, []):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid status transition from {current_status} to {new_status}"
                    )
                
                update_dict["status"] = new_status
            
            if update_data.landlord_response:
                update_dict["landlord_response"] = update_data.landlord_response
            
            if update_data.scheduled_date:
                update_dict["scheduled_date"] = update_data.scheduled_date
            
            if update_data.estimated_cost:
                update_dict["estimated_cost"] = update_data.estimated_cost
            
            if update_data.actual_cost:
                update_dict["actual_cost"] = update_data.actual_cost
            
            if update_data.resolution_notes:
                update_dict["resolution_notes"] = update_data.resolution_notes
            
            if update_data.status == "RESOLVED":
                update_dict["completed_at"] = datetime.utcnow().isoformat()
                # Send notification to tenant
                await send_maintenance_notification(maintenance_request, "tenant")
        
        # Tenant updates
        else:  # tenant
            if update_data.tenant_rating:
                if not (1 <= update_data.tenant_rating <= 5):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Rating must be between 1 and 5"
                    )
                update_dict["tenant_rating"] = update_data.tenant_rating
            
            if update_data.tenant_feedback:
                update_dict["tenant_feedback"] = update_data.tenant_feedback
        
        # Update maintenance request
        update_response = supabase_admin.table("maintenance_requests").update(update_dict).eq(
            "id", request_id
        ).execute()
        
        if not update_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update maintenance request"
            )
        
        return update_response.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update maintenance request: {str(e)}"
        )


@router.get("/property/{property_id}")
async def get_property_maintenance_requests(
    property_id: str,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Get all maintenance requests for a specific property
    - Landlords: Can view all requests for their properties
    - Tenants: Can view requests only for properties they're actively renting
    """
    try:
        # Verify property exists
        property_response = supabase_admin.table("properties").select("*").eq(
            "id", property_id
        ).execute()
        
        if not property_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        property_data = property_response.data[0]
        
        # Check access permissions based on user type
        if current_user["user_type"] == "landlord":
            # Landlords can only view maintenance for their own properties
            if property_data.get("landlord_id") != current_user["id"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: This property is not yours"
                )
        elif current_user["user_type"] == "tenant":
            # Tenants can only view maintenance for properties they're actively renting
            agreement_response = supabase_admin.table("agreements").select("id").eq(
                "property_id", property_id
            ).eq("tenant_id", current_user["id"]).eq(
                "status", "ACTIVE"
            ).execute()
            
            if not agreement_response.data:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: You must have an active agreement for this property to view maintenance"
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Only landlords and tenants can view maintenance"
            )
        
        # Get maintenance requests
        query = supabase_admin.table("maintenance_requests").select("*").eq(
            "property_id", property_id
        )
        
        if status:
            query = query.eq("status", status)
        
        response = query.order("created_at", desc=True).execute()
        
        return response.data if response.data else []
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get property maintenance requests: {str(e)}"
        )


@router.post("/{request_id}/photos")
async def upload_maintenance_photos(
    request_id: str,
    photos: List[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload additional photos for a maintenance request
    """
    try:
        # Get maintenance request
        response = supabase_admin.table("maintenance_requests").select("*").eq(
            "id", request_id
        ).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Maintenance request not found"
            )
        
        maintenance_request = response.data[0]
        
        # Check authorization
        if (maintenance_request["tenant_id"] != current_user["id"] and 
            maintenance_request["landlord_id"] != current_user["id"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to upload photos for this request"
            )
        
        photo_urls = []
        for photo in photos:
            photo_url = await upload_maintenance_photo(photo, request_id)
            photo_urls.append(photo_url)
        
        # Add new photos to existing ones
        existing_photos = maintenance_request.get("photos", [])
        updated_photos = existing_photos + photo_urls
        
        # Update maintenance request
        update_response = supabase_admin.table("maintenance_requests").update({
            "photos": updated_photos
        }).eq("id", request_id).execute()
        
        return {"message": f"Uploaded {len(photo_urls)} photos successfully", "photo_urls": photo_urls}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload photos: {str(e)}"
        )


@router.get("/stats/summary")
async def get_maintenance_stats(
    current_user: dict = Depends(get_current_user)
):
    """
    Get maintenance statistics for the current user
    """
    try:
        if current_user["user_type"] == "landlord":
            # Landlord stats
            response = supabase_admin.table("maintenance_requests").select("*").eq(
                "landlord_id", current_user["id"]
            ).execute()
            
            requests = response.data
            
            stats = {
                "total_requests": len(requests),
                "pending": len([r for r in requests if r["status"] == "PENDING"]),
                "in_progress": len([r for r in requests if r["status"] == "IN_PROGRESS"]),
                "resolved": len([r for r in requests if r["status"] == "RESOLVED"]),
                "average_rating": None
            }
            
            # Calculate average rating
            ratings = [r["tenant_rating"] for r in requests if r.get("tenant_rating")]
            if ratings:
                stats["average_rating"] = sum(ratings) / len(ratings)
            
            return stats
        
        else:
            # Tenant stats
            response = supabase_admin.table("maintenance_requests").select("*").eq(
                "tenant_id", current_user["id"]
            ).execute()
            
            requests = response.data
            
            stats = {
                "total_requests": len(requests),
                "emergency": len([r for r in requests if r["urgency"] == "EMERGENCY"]),
                "high": len([r for r in requests if r["urgency"] == "HIGH"]),
                "average_rating": None
            }
            
            # Calculate average rating
            ratings = [r["tenant_rating"] for r in requests if r.get("tenant_rating")]
            if ratings:
                stats["average_rating"] = sum(ratings) / len(ratings)
            
            return stats
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get maintenance stats: {str(e)}"
        )


# Helper Functions

async def upload_maintenance_photo(photo: UploadFile, property_id: str):
    """
    Upload maintenance photo to cloud storage
    This is a placeholder - integrate with Supabase Storage
    """
    try:
        # TODO: Upload to Supabase Storage
        # For now, return a mock URL
        filename = f"maintenance/{property_id}/{photo.filename}"
        file_url = f"https://storage.nuloafrica.com/{filename}"
        
        return file_url
        
    except Exception as e:
        print(f"Failed to upload photo {photo.filename}: {str(e)}")
        return None


async def send_maintenance_notification(maintenance_request, recipient_type):
    """
    Send notification for maintenance request
    """
    try:
        # TODO: Integrate with notification system
        if recipient_type == "landlord":
            message = f"New maintenance request: {maintenance_request['title']}"
            # Send to landlord
        else:
            message = f"Your maintenance request has been {maintenance_request['status'].lower()}"
            # Send to tenant
        
        print(f"Notification sent: {message}")
        
    except Exception as e:
        print(f"Failed to send notification: {str(e)}")
