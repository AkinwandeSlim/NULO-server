"""
Viewing Requests routes
"""
from fastapi import APIRouter, HTTPException, Depends, status
from app.database import supabase_admin
from app.middleware.auth import get_current_tenant
from app.services.sms_service import sms_service
from app.services.email_service import email_service
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

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
        
        viewing_request = response.data[0]
        viewing_id = viewing_request["id"]
        
        logger.info(f"📧 [EMAIL] Sending confirmation emails for viewing {viewing_id}")
        
        # Get tenant data for notifications
        tenant_response = supabase_admin.table("users").select(
            "id, full_name, email, phone_number"
        ).eq("id", tenant_id).execute()
        tenant_data = tenant_response.data[0] if tenant_response.data else None
        
        # Get landlord data for notifications
        landlord_response = supabase_admin.table("users").select(
            "id, full_name, email, phone_number"
        ).eq("id", landlord_id).execute()
        landlord_data = landlord_response.data[0] if landlord_response.data else None
        
        # Get property data for notifications
        property_response = supabase_admin.table("properties").select(
            "id, title"
        ).eq("id", request_data.property_id).execute()
        property_data = property_response.data[0] if property_response.data else None
        
        # Send emails
        tenant_msgid = None
        landlord_msgid = None
        
        # Email to tenant
        if tenant_data and tenant_data.get("email"):
            tenant_email_result = email_service.send_viewing_confirmation_email(
                tenant_email=tenant_data["email"],
                tenant_name=tenant_data.get("full_name", "Tenant"),
                property_title=property_data.get("title", "Property") if property_data else "Property",
                date=request_data.preferred_date,
                time=request_data.time_slot,
                viewing_id=viewing_id
            )
            tenant_msgid = tenant_email_result.get("message_id") if isinstance(tenant_email_result, dict) else None
            tenant_sent = bool(tenant_email_result and tenant_email_result.get("success")) if isinstance(tenant_email_result, dict) else bool(tenant_email_result)
            logger.info(f"✉️ [EMAIL] Tenant email: {tenant_data['email']} - {'sent' if tenant_sent else 'failed'} (msgid={tenant_msgid})")
        
        # Email to landlord
        if landlord_data and landlord_data.get("email"):
            landlord_email_result = email_service.send_landlord_viewing_notification_email(
                landlord_email=landlord_data["email"],
                landlord_name=landlord_data.get("full_name", "Landlord"),
                tenant_name=tenant_data.get("full_name", "Tenant") if tenant_data else request_data.tenant_name,
                property_title=property_data.get("title", "Property") if property_data else "Property",
                date=request_data.preferred_date,
                time=request_data.time_slot,
                viewing_id=viewing_id
            )
            landlord_msgid = landlord_email_result.get("message_id") if isinstance(landlord_email_result, dict) else None
            landlord_sent = bool(landlord_email_result and landlord_email_result.get("success")) if isinstance(landlord_email_result, dict) else bool(landlord_email_result)
            logger.info(f"✉️ [EMAIL] Landlord email: {landlord_data['email']} - {'sent' if landlord_sent else 'failed'} (msgid={landlord_msgid})")
        
        # Send SMS (if configured)
        tenant_phone = request_data.contact_number
        if tenant_phone:
            msg = sms_service.get_viewing_confirmation_message(
                tenant_name=tenant_data.get("full_name", "Tenant") if tenant_data else request_data.tenant_name,
                property_title=property_data.get("title", "Property") if property_data else "Property",
                date_str=request_data.preferred_date,
                time_slot=request_data.time_slot
            )
            sms_service.send_sms(tenant_phone, msg)
            logger.info(f"📱 Sending SMS to {tenant_phone}")
        
        if landlord_data and landlord_data.get("phone_number"):
            msg = sms_service.get_landlord_notification_message(
                landlord_name=landlord_data.get("full_name", "Landlord"),
                property_title=property_data.get("title", "Property") if property_data else "Property",
                tenant_name=tenant_data.get("full_name", "Tenant") if tenant_data else request_data.tenant_name,
                date_str=request_data.preferred_date,
                time_slot=request_data.time_slot
            )
            sms_service.send_sms(landlord_data["phone_number"], msg)
            logger.info(f"📱 Sending SMS to landlord at {landlord_data['phone_number']}")
        
        # Create in-app notifications
        try:
            # Notification to tenant
            if tenant_data:
                try:
                    res = supabase_admin.table("notifications").insert({
                        "user_id": tenant_data["id"],
                        "type": "visit",
                        "title": "Viewing Confirmed! ✓",
                        "message": f"Your viewing for {property_data.get('title', 'Property') if property_data else 'Property'} on {request_data.preferred_date} at {request_data.time_slot} has been confirmed.",
                        "data": {
                            "viewing_id": viewing_id,
                            "property_id": request_data.property_id,
                            "date": request_data.preferred_date,
                            "time": request_data.time_slot
                        },
                        "link": f"/tenant/viewings/{viewing_id}",
                        "read": False,
                        "message_id": tenant_msgid,
                        "metadata": {"source": "system", "sent_via": "email", "message_id": tenant_msgid}
                    }).execute()
                    logger.info(f"📲 [NOTIF] Tenant notification created: {getattr(res, 'status_code', 'unknown')}")
                except Exception as e_tn:
                    logger.warning(f"📲 [NOTIF] Tenant notification insert failed (retrying without metadata): {str(e_tn)}")
                    try:
                        res = supabase_admin.table("notifications").insert({
                            "user_id": tenant_data["id"],
                            "type": "visit",
                            "title": "Viewing Confirmed! ✓",
                            "message": f"Your viewing for {property_data.get('title', 'Property') if property_data else 'Property'} on {request_data.preferred_date} at {request_data.time_slot} has been confirmed.",
                            "data": {
                                "viewing_id": viewing_id,
                                "property_id": request_data.property_id,
                                "date": request_data.preferred_date,
                                "time": request_data.time_slot
                            },
                            "link": f"/tenant/viewings/{viewing_id}",
                            "read": False,
                            "message_id": tenant_msgid
                        }).execute()
                        logger.info(f"📲 [NOTIF] Tenant notification created (no metadata): {getattr(res, 'status_code', 'unknown')}")
                    except Exception as e_tn2:
                        logger.error(f"📲 [NOTIF] Tenant notification retry failed: {str(e_tn2)}")
            
            # Notification to landlord
            if landlord_data:
                try:
                    res2 = supabase_admin.table("notifications").insert({
                        "user_id": landlord_data["id"],
                        "type": "visit",
                        "title": "Viewing Scheduled",
                        "message": f"{tenant_data.get('full_name', 'A tenant') if tenant_data else 'A tenant'} has a viewing for {property_data.get('title', 'Property') if property_data else 'Property'} on {request_data.preferred_date}.",
                        "data": {
                            "viewing_id": viewing_id,
                            "property_id": request_data.property_id,
                            "tenant_id": tenant_id
                        },
                        "link": f"/landlord/viewings/{viewing_id}",
                        "read": False,
                        "message_id": landlord_msgid,
                        "metadata": {"source": "system", "sent_via": "email/sms", "message_id": landlord_msgid}
                    }).execute()
                    logger.info(f"📲 [NOTIF] Landlord notification created: {getattr(res2, 'status_code', 'unknown')}")
                except Exception as e_inner:
                    # Retry without metadata if column doesn't exist in notifications table
                    err_text = str(e_inner)
                    logger.warning(f"📲 [NOTIF] Failed to create landlord notification with metadata: {err_text}")
                    if 'metadata' in err_text or "Could not find the 'metadata' column" in err_text:
                        try:
                            res2 = supabase_admin.table("notifications").insert({
                                "user_id": landlord_data["id"],
                                "type": "visit",
                                "title": "Viewing Scheduled",
                                "message": f"{tenant_data.get('full_name', 'A tenant') if tenant_data else 'A tenant'} has a viewing for {property_data.get('title', 'Property') if property_data else 'Property'} on {request_data.preferred_date}.",
                                "data": {
                                    "viewing_id": viewing_id,
                                    "property_id": request_data.property_id,
                                    "tenant_id": tenant_id
                                },
                                "link": f"/landlord/viewings/{viewing_id}",
                                "read": False,
                                "message_id": landlord_msgid
                            }).execute()
                            logger.info(f"📲 [NOTIF] Landlord notification created (no metadata): {getattr(res2, 'status_code', 'unknown')}")
                        except Exception as e_retry:
                            logger.error(f"📲 [NOTIF] Retry without metadata failed: {str(e_retry)}")
                    else:
                        logger.error(f"📲 [NOTIF] Could not create landlord notification: {err_text}")
        except Exception as notif_error:
            logger.error(f"Error creating in-app notification: {str(notif_error)}")
            # Don't fail the whole request if notification creation fails
        
        # Update viewing request with notification flags
        supabase_admin.table("viewing_requests").update({
            "sms_sent_confirmation": True,
            "last_notification_at": datetime.now().isoformat()
        }).eq("id", viewing_id).execute()
        
        return {
            "success": True,
            "message": "Viewing request sent successfully",
            "viewing_request": viewing_request
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


# ===== SMS NOTIFICATION ENDPOINTS =====

@router.post("/{request_id}/send-sms")
async def send_viewing_sms(
    request_id: str,
    notification_type: Literal['confirmation', 'reminder_24h', 'reminder_1h', 'interest'],
    current_user: dict = Depends(get_current_tenant)
):
    """
    Send SMS notification for a viewing
    
    notification_type options:
    - "confirmation": Confirm viewing to tenant and landlord
    - "reminder_24h": Remind tenant 24 hours before
    - "reminder_1h": Remind tenant 1 hour before
    - "interest": Notify landlord when tenant interested
    """
    
    try:
        # Get viewing request
        viewing_response = supabase_admin.table("viewing_requests").select("*").eq(
            "id", request_id
        ).execute()
        
        if not viewing_response.data:
            raise HTTPException(status_code=404, detail="Viewing not found")
        
        viewing = viewing_response.data[0]
        
        # Get tenant data
        tenant_response = supabase_admin.table("users").select(
            "id, full_name, email, phone_number"
        ).eq("id", viewing["tenant_id"]).execute()
        tenant_data = tenant_response.data[0] if tenant_response.data else None
        
        # Get landlord data
        landlord_response = supabase_admin.table("users").select(
            "id, full_name, email, phone_number"
        ).eq("id", viewing["landlord_id"]).execute()
        landlord_data = landlord_response.data[0] if landlord_response.data else None
        
        # Get property data
        property_response = supabase_admin.table("properties").select(
            "id, title"
        ).eq("id", viewing["property_id"]).execute()
        property_data = property_response.data[0] if property_response.data else None
        
        # Initialize tracking variables
        results = []
        sent_count = 0
        date_str = viewing.get("preferred_date", "TBD")
        tenant_msgid = None
        landlord_msgid = None
        
        # SEND CONFIRMATION SMS & EMAILS
        if notification_type == "confirmation":
            logger.info(f"📧 [EMAIL] Sending confirmation emails for viewing {request_id}")
            
            # Email to tenant
            if tenant_data and tenant_data.get("email"):
                tenant_email_result = email_service.send_viewing_confirmation_email(
                    tenant_email=tenant_data["email"],
                    tenant_name=tenant_data.get("full_name", "Tenant"),
                    property_title=property_data.get("title", "Property"),
                    date=date_str,
                    time=viewing.get("time_slot", "TBD"),
                    viewing_id=request_id
                )
                tenant_msgid = tenant_email_result.get("message_id") if isinstance(tenant_email_result, dict) else None
                tenant_sent = bool(tenant_email_result and tenant_email_result.get("success")) if isinstance(tenant_email_result, dict) else bool(tenant_email_result)
                logger.info(f"✉️ [EMAIL] Tenant email: {tenant_data['email']} - {'sent' if tenant_sent else 'failed'} (msgid={tenant_msgid})")
            
            # Email to landlord
            if landlord_data and landlord_data.get("email"):
                landlord_email_result = email_service.send_landlord_viewing_notification_email(
                    landlord_email=landlord_data["email"],
                    landlord_name=landlord_data.get("full_name", "Landlord"),
                    tenant_name=tenant_data.get("full_name", "Tenant") if tenant_data else viewing.get("tenant_name", "Tenant"),
                    property_title=property_data.get("title", "Property"),
                    date=date_str,
                    time=viewing.get("time_slot", "TBD"),
                    viewing_id=request_id
                )
                landlord_msgid = landlord_email_result.get("message_id") if isinstance(landlord_email_result, dict) else None
                landlord_sent = bool(landlord_email_result and landlord_email_result.get("success")) if isinstance(landlord_email_result, dict) else bool(landlord_email_result)
                logger.info(f"✉️ [EMAIL] Landlord email: {landlord_data['email']} - {'sent' if landlord_sent else 'failed'} (msgid={landlord_msgid})")
            
            # SMS to tenant - use contact_number from viewing request
            tenant_phone = viewing.get("contact_number")
            if tenant_phone:
                msg = sms_service.get_viewing_confirmation_message(
                    tenant_name=tenant_data.get("full_name", "Tenant") if tenant_data else viewing.get("tenant_name", "Tenant"),
                    property_title=property_data.get("title", "Property"),
                    date_str=date_str,
                    time_slot=viewing.get("time_slot", "TBD")
                )
                success = sms_service.send_sms(tenant_phone, msg)
                results.append({
                    "to": "tenant",
                    "phone": tenant_phone,
                    "success": success
                })
                if success:
                    sent_count += 1
            else:
                results.append({
                    "to": "tenant",
                    "phone": "NOT PROVIDED",
                    "success": False,
                    "reason": "No contact number provided"
                })
            
            # SMS to landlord - use landlord phone if available
            if landlord_data and landlord_data.get("phone_number"):
                msg = sms_service.get_landlord_notification_message(
                    landlord_name=landlord_data.get("full_name", "Landlord"),
                    property_title=property_data.get("title", "Property"),
                    tenant_name=tenant_data.get("full_name", "Tenant") if tenant_data else viewing.get("tenant_name", "Tenant"),
                    date_str=date_str,
                    time_slot=viewing.get("time_slot", "TBD")
                )
                success = sms_service.send_sms(landlord_data["phone_number"], msg)
                results.append({
                    "to": "landlord",
                    "phone": landlord_data["phone_number"],
                    "success": success
                })
                if success:
                    sent_count += 1
            else:
                results.append({
                    "to": "landlord",
                    "phone": "NO PHONE ON FILE",
                    "success": False,
                    "reason": "Landlord has no phone number"
                })
            
            # Update database flag
            supabase_admin.table("viewing_requests").update({
                "sms_sent_confirmation": True,
                "last_notification_at": datetime.now().isoformat()
            }).eq("id", request_id).execute()
        
        # SEND REMINDER SMS & EMAIL
        elif notification_type in ["reminder_24h", "reminder_1h"]:
            hours = 24 if notification_type == "reminder_24h" else 1
            
            # SMS to tenant - use contact_number from viewing request
            tenant_phone = viewing.get("contact_number")
            if tenant_phone:
                msg = sms_service.get_reminder_message(
                    tenant_name=tenant_data.get("full_name", "Guest") if tenant_data else "Guest",
                    property_title=property_data.get("title", "Property"),
                    hours_before=hours
                )
                success = sms_service.send_sms(tenant_phone, msg)
                results.append({
                    "to": "tenant",
                    "phone": tenant_phone,
                    "success": success
                })
                if success:
                    sent_count += 1
            else:
                results.append({
                    "to": "tenant",
                    "phone": "NOT PROVIDED",
                    "success": False,
                    "reason": "No contact number provided"
                })
            
            # Email reminder to tenant
            if tenant_data and tenant_data.get("email"):
                reminder_result = email_service.send_viewing_reminder_email(
                    tenant_email=tenant_data["email"],
                    tenant_name=tenant_data.get("full_name", "Tenant"),
                    property_title=property_data.get("title", "Property"),
                    date=date_str,
                    time=viewing.get("time_slot", "TBD"),
                    hours_until=hours,
                    viewing_id=request_id
                )
                reminder_sent = bool(reminder_result and reminder_result.get("success")) if isinstance(reminder_result, dict) else bool(reminder_result)
                logger.info(f"✉️ [EMAIL] Reminder email to {tenant_data['email']} - {'sent' if reminder_sent else 'failed'}")
            
            # Update database flag
            update_data = {"last_notification_at": datetime.now().isoformat()}
            if notification_type == "reminder_24h":
                update_data["sms_sent_reminder_24h"] = True
            else:
                update_data["sms_sent_reminder_1h"] = True
            
            supabase_admin.table("viewing_requests").update(update_data).eq("id", request_id).execute()
        
        # SEND INTEREST NOTIFICATION SMS
        elif notification_type == "interest":
            if landlord_data and landlord_data.get("phone_number"):
                msg = sms_service.get_interest_notification_message(
                    landlord_name=landlord_data.get("full_name", "Landlord"),
                    tenant_name=tenant_data.get("full_name", "Tenant") if tenant_data else viewing.get("tenant_name", "Tenant"),
                    property_title=property_data.get("title", "Property")
                )
                success = sms_service.send_sms(landlord_data["phone_number"], msg)
                results.append({
                    "to": "landlord",
                    "phone": landlord_data["phone_number"],
                    "success": success
                })
                if success:
                    sent_count += 1
            else:
                results.append({
                    "to": "landlord",
                    "phone": "NO PHONE ON FILE",
                    "success": False,
                    "reason": "Landlord has no phone number"
                })
        
        # Create in-app notifications (via Supabase) for confirmation only
        if notification_type == "confirmation":
            try:
                # Notification to tenant
                if tenant_data:
                    try:
                        res = supabase_admin.table("notifications").insert({
                            "user_id": tenant_data["id"],
                            "type": "visit",
                            "title": "Viewing Confirmed! ✓",
                            "message": f"Your viewing for {property_data.get('title', 'Property')} on {date_str} at {viewing.get('time_slot', 'TBD')} has been confirmed.",
                            "data": {
                                "viewing_id": request_id,
                                "property_id": viewing["property_id"],
                                "date": date_str,
                                "time": viewing.get("time_slot", "TBD")
                            },
                            "link": f"/dashboard/tenant/viewings/{request_id}",
                            "read": False,
                            "message_id": tenant_msgid,
                            "metadata": {"source": "system", "sent_via": "email", "message_id": tenant_msgid}
                        }).execute()
                        logger.info(f"📲 [NOTIF] Tenant notification created: {getattr(res, 'status_code', 'unknown')}")
                    except Exception as e_tn:
                        logger.warning(f"📲 [NOTIF] Tenant notification insert failed (retrying without metadata): {str(e_tn)}")
                        try:
                            res = supabase_admin.table("notifications").insert({
                                "user_id": tenant_data["id"],
                                "type": "visit",
                                "title": "Viewing Confirmed! ✓",
                                "message": f"Your viewing for {property_data.get('title', 'Property')} on {date_str} at {viewing.get('time_slot', 'TBD')} has been confirmed.",
                                "data": {
                                    "viewing_id": request_id,
                                    "property_id": viewing["property_id"],
                                    "date": date_str,
                                    "time": viewing.get("time_slot", "TBD")
                                },
                                "link": f"/dashboard/tenant/viewings/{request_id}",
                                "read": False,
                                "message_id": tenant_msgid
                            }).execute()
                            logger.info(f"📲 [NOTIF] Tenant notification created (no metadata): {getattr(res, 'status_code', 'unknown')}")
                        except Exception as e_tn2:
                            logger.error(f"📲 [NOTIF] Tenant notification retry failed: {str(e_tn2)}")
                
                # Notification to landlord
                if landlord_data:
                    try:
                        res2 = supabase_admin.table("notifications").insert({
                            "user_id": landlord_data["id"],
                            "type": "visit",
                            "title": "Viewing Scheduled",
                            "message": f"{tenant_data.get('full_name', 'A tenant') if tenant_data else 'A tenant'} has a viewing for {property_data.get('title', 'Property')} on {date_str}.",
                            "data": {
                                "viewing_id": request_id,
                                "property_id": viewing["property_id"],
                                "tenant_id": viewing["tenant_id"]
                            },
                            "link": f"/dashboard/landlord/viewings/{request_id}",
                            "read": False,
                            "message_id": landlord_msgid,
                            "metadata": {"source": "system", "sent_via": "email/sms", "message_id": landlord_msgid}
                        }).execute()
                        logger.info(f"📲 [NOTIF] Landlord notification created: {getattr(res2, 'status_code', 'unknown')}")
                    except Exception as e_inner:
                        # Retry without metadata if column doesn't exist in notifications table
                        err_text = str(e_inner)
                        logger.warning(f"📲 [NOTIF] Failed to create landlord notification with metadata: {err_text}")
                        if 'metadata' in err_text or "Could not find the 'metadata' column" in err_text:
                            try:
                                res2 = supabase_admin.table("notifications").insert({
                                    "user_id": landlord_data["id"],
                                    "type": "visit",
                                    "title": "Viewing Scheduled",
                                    "message": f"{tenant_data.get('full_name', 'A tenant') if tenant_data else 'A tenant'} has a viewing for {property_data.get('title', 'Property')} on {date_str}.",
                                    "data": {
                                        "viewing_id": request_id,
                                        "property_id": viewing["property_id"],
                                        "tenant_id": viewing["tenant_id"]
                                    },
                                    "link": f"/dashboard/landlord/viewings/{request_id}",
                                    "read": False,
                                    "message_id": landlord_msgid
                                }).execute()
                                logger.info(f"📲 [NOTIF] Landlord notification created (no metadata): {getattr(res2, 'status_code', 'unknown')}")
                            except Exception as e_retry:
                                logger.error(f"📲 [NOTIF] Retry without metadata failed: {str(e_retry)}")
                        else:
                            logger.error(f"📲 [NOTIF] Could not create landlord notification: {err_text}")
            except Exception as notif_error:
                logger.error(f"Error creating in-app notification: {str(notif_error)}")
                # Don't fail the whole request if notification creation fails
        
        return {
            "status": "sms_sent",
            "type": notification_type,
            "sent_count": sent_count,
            "details": results
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending SMS: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
