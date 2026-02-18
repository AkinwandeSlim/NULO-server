"""
Maintenance API - Post Move-in Maintenance Management
Handles maintenance requests from tenants to landlords
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from datetime import date, datetime

from ..database import get_db
from ..models.maintenance import (
    MaintenanceRequest, MaintenanceCreate, MaintenanceResponse,
    MaintenanceUpdate, MaintenanceStatus, MaintenanceCategory
)
from ..dependencies.auth import get_current_user
from ..models.user import User

router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])

@router.post("/", response_model=MaintenanceResponse)
async def create_maintenance_request(
    maintenance_data: MaintenanceCreate,
    photos: Optional[List[UploadFile]] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new maintenance request
    Only tenants can create maintenance requests for properties they're renting
    """
    try:
        # Verify user is a tenant
        if current_user.user_type != "tenant":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only tenants can create maintenance requests"
            )
        
        # Verify property exists and tenant has access
        from ..models.property import Property
        property = db.query(Property).filter(Property.id == maintenance_data.property_id).first()
        
        if not property:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        # TODO: Verify tenant is actively renting this property
        # This would require checking active agreements/leases
        
        # Handle photo uploads
        photo_urls = []
        if photos:
            for photo in photos:
                # TODO: Upload to cloud storage (Supabase Storage)
                photo_url = await upload_maintenance_photo(photo, maintenance_data.property_id)
                photo_urls.append(photo_url)
        
        # Create maintenance request
        maintenance_request = MaintenanceRequest(
            property_id=maintenance_data.property_id,
            tenant_id=current_user.id,
            landlord_id=property.landlord_id,
            category=maintenance_data.category,
            title=maintenance_data.title,
            description=maintenance_data.description,
            urgency=maintenance_data.urgency,
            photos=photo_urls,
            preferred_date=maintenance_data.preferred_date,
            status="PENDING"
        )
        
        db.add(maintenance_request)
        db.commit()
        db.refresh(maintenance_request)
        
        # Send notification to landlord
        await send_maintenance_notification(maintenance_request, "landlord")
        
        return maintenance_request
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create maintenance request: {str(e)}"
        )

@router.get("/", response_model=List[MaintenanceResponse])
async def get_maintenance_requests(
    status: Optional[str] = None,
    urgency: Optional[str] = None,
    property_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get maintenance requests for the current user
    Tenants see their requests, landlords see requests for their properties
    """
    query = db.query(MaintenanceRequest)
    
    # Filter based on user type
    if current_user.user_type == "tenant":
        query = query.filter(MaintenanceRequest.tenant_id == current_user.id)
    else:  # landlord
        query = query.filter(MaintenanceRequest.landlord_id == current_user.id)
    
    # Apply filters
    if status:
        query = query.filter(MaintenanceRequest.status == status)
    
    if urgency:
        query = query.filter(MaintenanceRequest.urgency == urgency)
    
    if property_id:
        query = query.filter(MaintenanceRequest.property_id == property_id)
    
    # Order by creation date (newest first)
    requests = query.order_by(MaintenanceRequest.created_at.desc()).all()
    
    return requests

@router.get("/{request_id}", response_model=MaintenanceResponse)
async def get_maintenance_request(
    request_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific maintenance request by ID
    Users can only view requests they are involved in
    """
    maintenance_request = db.query(MaintenanceRequest).filter(
        MaintenanceRequest.id == request_id
    ).first()
    
    if not maintenance_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance request not found"
        )
    
    # Check authorization
    if (maintenance_request.tenant_id != current_user.id and 
        maintenance_request.landlord_id != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this maintenance request"
        )
    
    return maintenance_request

@router.patch("/{request_id}", response_model=MaintenanceResponse)
async def update_maintenance_request(
    request_id: uuid.UUID,
    update_data: MaintenanceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a maintenance request
    Landlords can update status, add response, schedule date
    Tenants can add feedback, rating
    """
    maintenance_request = db.query(MaintenanceRequest).filter(
        MaintenanceRequest.id == request_id
    ).first()
    
    if not maintenance_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance request not found"
        )
    
    # Check authorization
    if (maintenance_request.tenant_id != current_user.id and 
        maintenance_request.landlord_id != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this maintenance request"
        )
    
    try:
        # Landlord updates
        if current_user.user_type == "landlord":
            if update_data.status:
                # Validate status transitions
                valid_transitions = {
                    "PENDING": ["ACKNOWLEDGED", "IN_PROGRESS"],
                    "ACKNOWLEDGED": ["IN_PROGRESS", "RESOLVED"],
                    "IN_PROGRESS": ["RESOLVED"]
                }
                
                current_status = maintenance_request.status
                new_status = update_data.status
                
                if new_status not in valid_transitions.get(current_status, []):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid status transition from {current_status} to {new_status}"
                    )
                
                maintenance_request.status = new_status
            
            if update_data.landlord_response:
                maintenance_request.landlord_response = update_data.landlord_response
            
            if update_data.scheduled_date:
                maintenance_request.scheduled_date = update_data.scheduled_date
            
            if update_data.estimated_cost:
                maintenance_request.estimated_cost = update_data.estimated_cost
            
            if update_data.actual_cost:
                maintenance_request.actual_cost = update_data.actual_cost
            
            if update_data.resolution_notes:
                maintenance_request.resolution_notes = update_data.resolution_notes
            
            if update_data.status == "RESOLVED":
                maintenance_request.completed_at = datetime.utcnow()
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
                maintenance_request.tenant_rating = update_data.tenant_rating
            
            if update_data.tenant_feedback:
                maintenance_request.tenant_feedback = update_data.tenant_feedback
        
        db.commit()
        db.refresh(maintenance_request)
        
        return maintenance_request
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update maintenance request: {str(e)}"
        )

@router.get("/property/{property_id}", response_model=List[MaintenanceResponse])
async def get_property_maintenance_requests(
    property_id: uuid.UUID,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all maintenance requests for a specific property
    Only property owner/landlord can view all requests for their property
    """
    # Verify user owns the property
    from ..models.property import Property
    property = db.query(Property).filter(
        Property.id == property_id,
        Property.landlord_id == current_user.id
    ).first()
    
    if not property:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found or access denied"
        )
    
    query = db.query(MaintenanceRequest).filter(
        MaintenanceRequest.property_id == property_id
    )
    
    if status:
        query = query.filter(MaintenanceRequest.status == status)
    
    requests = query.order_by(MaintenanceRequest.created_at.desc()).all()
    
    return requests

@router.post("/{request_id}/photos")
async def upload_maintenance_photos(
    request_id: uuid.UUID,
    photos: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload additional photos for a maintenance request
    """
    maintenance_request = db.query(MaintenanceRequest).filter(
        MaintenanceRequest.id == request_id
    ).first()
    
    if not maintenance_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance request not found"
        )
    
    # Check authorization
    if (maintenance_request.tenant_id != current_user.id and 
        maintenance_request.landlord_id != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to upload photos for this request"
        )
    
    try:
        photo_urls = []
        for photo in photos:
            photo_url = await upload_maintenance_photo(photo, request_id)
            photo_urls.append(photo_url)
        
        # Add new photos to existing ones
        existing_photos = maintenance_request.photos or []
        maintenance_request.photos = existing_photos + photo_urls
        
        db.commit()
        
        return {"message": f"Uploaded {len(photo_urls)} photos successfully", "photo_urls": photo_urls}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload photos: {str(e)}"
        )

@router.get("/stats/summary")
async def get_maintenance_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get maintenance statistics for the current user
    """
    if current_user.user_type == "landlord":
        # Landlord stats
        from sqlalchemy import func
        
        stats = db.query(
            func.count(MaintenanceRequest.id).label('total_requests'),
            func.sum(func.case([(MaintenanceRequest.status == 'PENDING', 1), else_])).label('pending'),
            func.sum(func.case([(MaintenanceRequest.status == 'IN_PROGRESS', 1), else_])).label('in_progress'),
            func.sum(func.case([(MaintenanceRequest.status == 'RESOLVED', 1), else_])).label('resolved'),
            func.avg(MaintenanceRequest.tenant_rating).label('avg_rating')
        ).filter(
            MaintenanceRequest.landlord_id == current_user.id
        ).first()
        
        return {
            "total_requests": stats.total_requests or 0,
            "pending": stats.pending or 0,
            "in_progress": stats.in_progress or 0,
            "resolved": stats.resolved or 0,
            "average_rating": float(stats.avg_rating) if stats.avg_rating else None
        }
    
    else:
        # Tenant stats
        from sqlalchemy import func
        
        stats = db.query(
            func.count(MaintenanceRequest.id).label('total_requests'),
            func.sum(func.case([(MaintenanceRequest.urgency == 'EMERGENCY', 1), else_])).label('emergency'),
            func.sum(func.case([(MaintenanceRequest.urgency == 'HIGH', 1), else_])).label('high'),
            func.avg(MaintenanceRequest.tenant_rating).label('avg_rating')
        ).filter(
            MaintenanceRequest.tenant_id == current_user.id
        ).first()
        
        return {
            "total_requests": stats.total_requests or 0,
            "emergency": stats.emergency or 0,
            "high": stats.high or 0,
            "average_rating": float(stats.avg_rating) if stats.avg_rating else None
        }

# Helper Functions

async def upload_maintenance_photo(photo: UploadFile, property_id: uuid.UUID):
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
            message = f"New maintenance request: {maintenance_request.title}"
            # Send to landlord
        else:
            message = f"Your maintenance request has been {maintenance_request.status.lower()}"
            # Send to tenant
        
        print(f"Notification sent: {message}")
        
    except Exception as e:
        print(f"Failed to send notification: {str(e)}")
