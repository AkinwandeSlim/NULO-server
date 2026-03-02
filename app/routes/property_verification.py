"""
Property Verification Admin Routes
Handles admin approval/rejection of property listings
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from app.database import supabase_admin
from app.middleware.auth import get_current_admin
from app.models.user import UserResponse
from app.services.notification_service import notification_service
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import logging

router = APIRouter(prefix="/properties", tags=["admin-properties"])
logger = logging.getLogger(__name__)


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class PropertyVerificationAction(BaseModel):
    """Request model for approving/rejecting properties"""
    action: str = Field(..., pattern="^(approve|reject)$")
    rejection_reason: Optional[str] = None

class BulkPropertyAction(BaseModel):
    """Request model for bulk actions on properties"""
    property_ids: List[str]
    action: str = Field(..., pattern="^(approve|reject)$")
    rejection_reason: Optional[str] = None


# ============================================================================
# GET ENDPOINTS
# ============================================================================

@router.get("/pending")
async def get_pending_properties(
    current_user: UserResponse = Depends(get_current_admin),
    page: int = 1,
    limit: int = 20
) -> Dict[str, Any]:
    """
    Get all properties pending verification
    """
    try:
        user_email = current_user.get('email') if isinstance(current_user, dict) else getattr(current_user, 'email', 'Unknown')
        logger.info(f"🏠 [PROPERTIES] Admin {user_email} fetching pending properties (page {page})")
        
        offset = (page - 1) * limit
        
        # Get pending properties with landlord info
        # Note: Supabase range includes both start and end, so we use offset + limit (not offset + limit - 1)
        result = supabase_admin.table('properties')\
            .select('''
                *,
                landlord:users!landlord_id(
                    id,
                    email,
                    full_name,
                    verification_status
                )
            ''')\
            .eq('verification_status', 'pending')\
            .order('created_at', desc=True)\
            .range(offset, offset + limit)\
            .execute()
        
        logger.info(f"✅ [PROPERTIES] Found {len(result.data or [])} pending properties")
        
        # If landlord join didn't work, manually fetch and join
        if result.data and len(result.data) > 0:
            if not result.data[0].get('landlord'):
                logger.warning("⚠️ [PROPERTIES/PENDING] Nested select didn't work, doing manual join...")
                
                # Collect unique landlord IDs
                landlord_ids = list(set(p.get('landlord_id') for p in (result.data or []) if p.get('landlord_id')))
                
                if landlord_ids:
                    # Fetch landlord data
                    landlords_result = supabase_admin.table('users')\
                        .select('id, email, full_name, verification_status')\
                        .in_('id', landlord_ids)\
                        .execute()
                    
                    # Create lookup dict
                    landlords = {l['id']: l for l in (landlords_result.data or [])}
                    
                    # Add landlord data to properties
                    for prop in (result.data or []):
                        if prop.get('landlord_id') in landlords:
                            prop['landlord'] = landlords[prop['landlord_id']]
                        else:
                            prop['landlord'] = None
                    
                    logger.info(f"✅ [PROPERTIES/PENDING] Manual join completed")
        
        # Get total count
        count_result = supabase_admin.table('properties')\
            .select('id', count='exact')\
            .eq('verification_status', 'pending')\
            .execute()
        
        logger.info(f"✅ [PROPERTIES] Found {len(result.data or [])} pending properties")
        
        return {
            'properties': result.data or [],
            'total': count_result.count or 0,
            'page': page,
            'limit': limit,
            'total_pages': ((count_result.count or 0) + limit - 1) // limit
        }
        
    except Exception as e:
        logger.error(f"❌ [PROPERTIES] Failed to fetch pending: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch pending properties: {str(e)}"
        )


@router.get("/all")
async def get_all_properties(
    current_user: UserResponse = Depends(get_current_admin),
    verification_status: Optional[str] = None,
    page: int = 1,
    limit: int = 20
) -> Dict[str, Any]:
    """
    Get all properties with optional filtering by verification status
    """
    try:
        user_email = current_user.get('email') if isinstance(current_user, dict) else getattr(current_user, 'email', 'Unknown')
        logger.info(f"🏠 [PROPERTIES] Admin {user_email} fetching properties (status: {verification_status})")
        
        offset = (page - 1) * limit
        
        # Build query - Try the nested select first
        query = supabase_admin.table('properties')\
            .select('''
                *,
                landlord:users!landlord_id(
                    id,
                    email,
                    full_name,
                    verification_status
                )
            ''', count='exact')
        
        # Add filter if specified
        if verification_status:
            query = query.eq('verification_status', verification_status)
        
        # Note: Supabase range includes both start and end, so we use offset + limit (not offset + limit - 1)
        result = query\
            .order('created_at', desc=True)\
            .range(offset, offset + limit)\
            .execute()
        
        logger.info(f"✅ [PROPERTIES] Found {len(result.data or [])} properties")
        
        # Debug: Log first property structure
        if result.data and len(result.data) > 0:
            logger.info(f"🔍 [PROPERTIES] First property keys: {list(result.data[0].keys())}")
            logger.info(f"🔍 [PROPERTIES] First property landlord field: {result.data[0].get('landlord', 'MISSING')}")
            
            # If landlord join didn't work, manually fetch and join
            if not result.data[0].get('landlord'):
                logger.warning("⚠️ [PROPERTIES] Nested select didn't work, doing manual join...")
                
                # Collect unique landlord IDs
                landlord_ids = list(set(p.get('landlord_id') for p in (result.data or []) if p.get('landlord_id')))
                
                if landlord_ids:
                    # Fetch landlord data
                    landlords_result = supabase_admin.table('users')\
                        .select('id, email, full_name, verification_status')\
                        .in_('id', landlord_ids)\
                        .execute()
                    
                    # Create lookup dict
                    landlords = {l['id']: l for l in (landlords_result.data or [])}
                    
                    # Add landlord data to properties
                    for prop in (result.data or []):
                        if prop.get('landlord_id') in landlords:
                            prop['landlord'] = landlords[prop['landlord_id']]
                        else:
                            prop['landlord'] = None
                    
                    logger.info(f"✅ [PROPERTIES] Manual join completed, added landlord data to {len(result.data or [])} properties")
        
        return {
            'properties': result.data or [],
            'total': result.count or 0,
            'page': page,
            'limit': limit,
            'total_pages': ((result.count or 0) + limit - 1) // limit
        }
        
    except Exception as e:
        logger.error(f"❌ [PROPERTIES] Failed to fetch all: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch properties: {str(e)}"
        )


# ============================================================================
# STATS ENDPOINT
# ============================================================================

@router.get("/stats")
async def get_property_stats(
    current_user: UserResponse = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Get property verification statistics
    """
    try:
        user_email = current_user.get('email') if isinstance(current_user, dict) else getattr(current_user, 'email', 'Unknown')
        logger.info(f"🏠 [PROPERTIES] Admin {user_email} fetching property stats")
        
        # Get all properties
        result = supabase_admin.table('properties')\
            .select('id, verification_status, created_at')\
            .execute()
        
        properties = result.data or []
        
        # Count by status
        stats = {
            'total': len(properties),
            'pending': sum(1 for p in properties if p.get('verification_status') == 'pending'),
            'approved': sum(1 for p in properties if p.get('verification_status') == 'approved'),
            'rejected': sum(1 for p in properties if p.get('verification_status') == 'rejected'),
            'under_review': sum(1 for p in properties if p.get('verification_status') == 'under_review')
        }
        
        logger.info(f"✅ [PROPERTIES] Stats - Total: {stats['total']}, Pending: {stats['pending']}")
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ [PROPERTIES] Failed to fetch stats: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch property stats: {str(e)}"
        )









@router.get("/{property_id}")
async def get_property_details(
    property_id: str,
    current_user: UserResponse = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Get detailed property information for review
    """
    try:
        user_email = current_user.get('email') if isinstance(current_user, dict) else getattr(current_user, 'email', 'Unknown')
        logger.info(f"🏠 [PROPERTIES] Admin {user_email} fetching property {property_id}")
        
        # Get property with landlord info
        result = supabase_admin.table('properties')\
            .select('''
                *,
                landlord:users!landlord_id(
                    id,
                    email,
                    full_name,
                    phone_number,
                    verification_status,
                    created_at
                )
            ''')\
            .eq('id', property_id)\
            .single()\
            .execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Property {property_id} not found"
            )
        
        logger.info(f"✅ [PROPERTIES] Found property: {result.data.get('title', 'Unknown')}")
        
        return result.data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [PROPERTIES] Failed to fetch property {property_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch property details: {str(e)}"
        )


# ============================================================================
# ACTION ENDPOINTS
# ============================================================================

@router.post("/{property_id}/verify")
async def verify_property(
    property_id: str,
    action: PropertyVerificationAction,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Approve or reject a property listing
    """
    try:
        user_id = current_user.get('id') if isinstance(current_user, dict) else getattr(current_user, 'id', None)
        user_email = current_user.get('email') if isinstance(current_user, dict) else getattr(current_user, 'email', 'Unknown')
        
        logger.info(f"🏠 [PROPERTIES] Admin {user_email} {action.action}ing property {property_id}")
        
        # Prepare update data
        now = datetime.now(timezone.utc).isoformat()
        update_data = {
            'verification_status': 'approved' if action.action == 'approve' else 'rejected',
            'reviewed_by': user_id,
            'reviewed_at': now
        }
        
        # Add rejection reason if rejecting
        if action.action == 'reject' and action.rejection_reason:
            update_data['rejection_reason'] = action.rejection_reason
        
        # Update property
        result = supabase_admin.table('properties')\
            .update(update_data)\
            .eq('id', property_id)\
            .execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Property {property_id} not found"
            )
        
        logger.info(f"✅ [PROPERTIES] Property {property_id} {action.action}ed successfully")
        
        # Fetch landlord info and fire notification (non-blocking)
        try:
            property_data = result.data[0]
            landlord_id = property_data.get('landlord_id')
            property_title = property_data.get('title', 'Your property')
            
            if landlord_id:
                landlord_resp = supabase_admin.table('users')\
                    .select('full_name, email')\
                    .eq('id', landlord_id)\
                    .single()\
                    .execute()
                
                if landlord_resp.data:
                    landlord_name  = landlord_resp.data.get('full_name') or landlord_resp.data.get('email', 'Landlord')
                    landlord_email = landlord_resp.data.get('email', '')
                    
                    # Convert 'approve'/'reject' → 'approved'/'rejected'
                    # notify_property_reviewed checks action == "approved"
                    notif_action = "approved" if action.action == "approve" else "rejected"
                    background_tasks.add_task(
                        notification_service.notify_property_reviewed,
                        property_id=property_id,
                        landlord_id=landlord_id,
                        landlord_name=landlord_name,
                        landlord_email=landlord_email,
                        property_title=property_title,
                        action=notif_action,
                        rejection_reason=action.rejection_reason,
                    )
        except Exception as notify_err:
            # Notification failure must never break the approval response
            logger.warning(f"⚠️ [PROPERTIES] Notification setup failed (non-fatal): {notify_err}")
        
        return {
            'success': True,
            'property_id': property_id,
            'action': action.action,
            'verification_status': update_data['verification_status'],
            'reviewed_at': now
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [PROPERTIES] Failed to {action.action} property {property_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to {action.action} property: {str(e)}"
        )


@router.post("/bulk-action")
async def bulk_property_action(
    action: BulkPropertyAction,
    current_user: UserResponse = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Perform bulk approve/reject on multiple properties
    """
    try:
        user_id = current_user.get('id') if isinstance(current_user, dict) else getattr(current_user, 'id', None)
        user_email = current_user.get('email') if isinstance(current_user, dict) else getattr(current_user, 'email', 'Unknown')
        
        logger.info(f"🏠 [PROPERTIES] Admin {user_email} performing bulk {action.action} on {len(action.property_ids)} properties")
        
        # Prepare update data
        now = datetime.now(timezone.utc).isoformat()
        update_data = {
            'verification_status': 'approved' if action.action == 'approve' else 'rejected',
            'reviewed_by': user_id,
            'reviewed_at': now
        }
        
        if action.action == 'reject' and action.rejection_reason:
            update_data['rejection_reason'] = action.rejection_reason
        
        # Update all properties in bulk
        success_count = 0
        failed_ids = []
        
        for property_id in action.property_ids:
            try:
                result = supabase_admin.table('properties')\
                    .update(update_data)\
                    .eq('id', property_id)\
                    .execute()
                
                if result.data:
                    success_count += 1
                else:
                    failed_ids.append(property_id)
                    
            except Exception as e:
                logger.warning(f"⚠️ [PROPERTIES] Failed to update {property_id}: {str(e)}")
                failed_ids.append(property_id)
        
        logger.info(f"✅ [PROPERTIES] Bulk action complete - {success_count} succeeded, {len(failed_ids)} failed")
        
        return {
            'success': True,
            'total_processed': len(action.property_ids),
            'successful': success_count,
            'failed': len(failed_ids),
            'failed_ids': failed_ids,
            'action': action.action
        }
        
    except Exception as e:
        logger.error(f"❌ [PROPERTIES] Bulk action failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk action failed: {str(e)}"
        )