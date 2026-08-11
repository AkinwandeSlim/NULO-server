"""
Viewing Requests routes
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, status
from app.database import supabase_admin, run_db_async
from app.middleware.auth import get_current_tenant, get_current_landlord
from app.services.notification_service import notification_service
from app.services.notification_helpers import create_notification
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import date, datetime
import logging
import re
import time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/viewing-requests")


def _run_with_retry(fn, *, attempts: int = 3, delay: float = 0.4, label: str = "query"):
    """Run a Supabase query with retry on transient connection errors.

    The shared supabase-py client occasionally raises ConnectionTerminated /
    ConnectionReset on this host. Those failures are transient — retrying the
    same read shortly after almost always succeeds. We never retry writes.
    """
    last_err = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            msg = str(e)
            is_transient = any(k in msg for k in (
                "ConnectionTerminated", "ConnectionReset", "Connection broken",
                "connection reset", "RemoteProtocolError",
            ))
            if not is_transient or i == attempts - 1:
                break
            logger.warning(f"[viewing_requests] {label} transient failure (attempt {i+1}/{attempts}): {msg}")
            time.sleep(delay * (i + 1))
    raise last_err


class ViewingRequestCreate(BaseModel):
    property_id: str
    preferred_date: str  # YYYY-MM-DD format
    time_slot: Literal['morning', 'afternoon', 'evening']
    contact_number: str
    message: Optional[str] = None
    tenant_name: str
    viewing_type: Literal['PHYSICAL', 'VIRTUAL', 'LIVE_VIDEO'] = 'PHYSICAL'


class ViewingRequestUpdate(BaseModel):
    status: Literal['pending', 'confirmed', 'reschedule_proposed', 'cancelled', 'completed', 'no_show']
    landlord_notes: Optional[str] = None
    confirmed_date: Optional[str] = None
    confirmed_time: Optional[str] = None


class LandlordViewingReview(BaseModel):
    status: Literal['confirmed', 'reschedule_proposed', 'cancelled', 'completed', 'no_show']
    landlord_notes: Optional[str] = None
    confirmed_date: Optional[str] = None   # YYYY-MM-DD
    confirmed_time: Optional[str] = None   # e.g. "10:00 AM"
    safety_instructions: Optional[str] = None
    caretaker_name: Optional[str] = None
    caretaker_phone: Optional[str] = None
    meeting_url: Optional[str] = None
    no_show_reason: Optional[str] = None


class TenantRescheduleDecision(BaseModel):
    decision: Literal['accept', 'decline']


_EXACT_TIME = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$|^(?:0?[1-9]|1[0-2]):[0-5]\d\s?(?:AM|PM)$", re.I)
_PHONE = re.compile(r"^[\d\s+()\-]{9,20}$")


def _validate_future_date(value: str, label: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must use YYYY-MM-DD")
    if parsed < date.today():
        raise HTTPException(status_code=422, detail=f"{label} cannot be in the past")
    return parsed


def _validate_exact_time(value: Optional[str]) -> str:
    normalized = (value or "").strip().upper()
    if not _EXACT_TIME.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Choose an exact appointment time, for example 10:00 AM")
    return normalized


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_viewing_participants(viewing: dict) -> tuple:
    """
    Given a viewing row, return (tenant_data, landlord_data, property_data).
    Any of them can be None if the lookup fails — callers must handle that.
    """
    tenant_data = None
    landlord_data = None
    property_data = None

    try:
        r = supabase_admin.table("users").select(
            "id, full_name, email, phone_number"
        ).eq("id", viewing["tenant_id"]).execute()
        tenant_data = r.data[0] if r.data else None
    except Exception as e:
        logger.warning(f"Could not fetch tenant: {e}")

    try:
        r = supabase_admin.table("users").select(
            "id, full_name, email, phone_number"
        ).eq("id", viewing["landlord_id"]).execute()
        landlord_data = r.data[0] if r.data else None
    except Exception as e:
        logger.warning(f"Could not fetch landlord: {e}")

    try:
        r = supabase_admin.table("properties").select(
            "id, title"
        ).eq("id", viewing["property_id"]).execute()
        property_data = r.data[0] if r.data else None
    except Exception as e:
        logger.warning(f"Could not fetch property: {e}")

    return tenant_data, landlord_data, property_data


# ─────────────────────────────────────────────────────────────────────────────
# GET endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/landlord")
async def get_landlord_viewing_requests(
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_landlord)
):
    """Get all viewing requests for the current landlord's properties"""
    try:
        landlord_id = current_user["id"]

        def _base_query():
            return supabase_admin.table("viewing_requests").select("*").eq("landlord_id", landlord_id)

        def _run_query():
            query = _base_query()
            if status_filter:
                query = query.eq("status", status_filter)
            return query.order("created_at", desc=True).execute()

        response = await run_db_async(_run_query)

        # Batch fetch all unique property IDs and tenant IDs to avoid N+1 queries
        property_ids = list({req["property_id"] for req in response.data if req.get("property_id")})
        tenant_ids = list({req["tenant_id"] for req in response.data if req.get("tenant_id")})

        # Fetch all properties in one query
        properties_map = {}
        if property_ids:
            try:
                props_response = await run_db_async(
                    lambda: supabase_admin.table("properties").select("*").in_("id", property_ids).execute(),
                )
                properties_map = {p["id"]: p for p in (props_response.data or [])}
            except Exception as props_error:
                logger.warning(f"Could not fetch properties: {props_error}")

        # Fetch all tenants in one query
        tenants_map = {}
        if tenant_ids:
            try:
                tenants_response = await run_db_async(
                    lambda: supabase_admin.table("users").select(
                        "id, full_name, email, phone_number, avatar_url"
                    ).in_("id", tenant_ids).execute(),
                )
                tenants_map = {t["id"]: t for t in (tenants_response.data or [])}
            except Exception as tenants_error:
                logger.warning(f"Could not fetch tenants: {tenants_error}")

        viewing_requests = []
        for req in response.data:
            try:
                viewing_requests.append({
                    "id": req["id"],
                    "property": properties_map.get(req["property_id"]),
                    "tenant": tenants_map.get(req["tenant_id"]),
                    "tenant_name": req.get("tenant_name"),
                    "preferred_date": req["preferred_date"],
                    "time_slot": req["time_slot"],
                    "viewing_type": req.get("viewing_type", "PHYSICAL"),
                    "contact_number": req.get("contact_number"),
                    "message": req.get("message"),
                    "status": req["status"],
                    "landlord_notes": req.get("landlord_notes"),
                    "confirmed_date": req.get("confirmed_date"),
                    "confirmed_time": req.get("confirmed_time"),
                    "safety_instructions": req.get("safety_instructions") if req.get("status") == "confirmed" else None,
                    "caretaker_name": req.get("caretaker_name") if req.get("status") == "confirmed" else None,
                    "caretaker_phone": req.get("caretaker_phone") if req.get("status") == "confirmed" else None,
                    "meeting_url": req.get("meeting_url") if req.get("status") == "confirmed" else None,
                    "created_at": req["created_at"],
                    "updated_at": req.get("updated_at"),
                })
            except Exception as req_error:
                logger.warning(f"Error processing viewing request {req.get('id')}: {req_error}")
                continue

        return {"success": True, "viewing_requests": viewing_requests, "count": len(viewing_requests)}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch landlord viewing requests: {str(e)}"
        )


@router.get("/")
async def get_viewing_requests(
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_tenant)
):
    """Get tenant's viewing requests"""
    try:
        tenant_id = current_user["id"]

        query = supabase_admin.table("viewing_requests").select("*").eq("tenant_id", tenant_id)
        if status_filter:
            query = query.eq("status", status_filter)
        response = query.order("created_at", desc=True).execute()

        viewing_requests = []
        for req in response.data:
            try:
                property_response = supabase_admin.table("properties").select("*").eq(
                    "id", req["property_id"]
                ).execute()
                property_data = property_response.data[0] if property_response.data else None

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
                    "safety_instructions": req.get("safety_instructions") if req.get("status") == "confirmed" else None,
                    "caretaker_name": req.get("caretaker_name") if req.get("status") == "confirmed" else None,
                    "caretaker_phone": req.get("caretaker_phone") if req.get("status") == "confirmed" else None,
                    "meeting_url": req.get("meeting_url") if req.get("status") == "confirmed" else None,
                    "created_at": req["created_at"],
                    "updated_at": req.get("updated_at"),
                })
            except Exception as req_error:
                logger.warning(f"Error processing viewing request {req.get('id')}: {req_error}")
                continue

        return {"success": True, "viewing_requests": viewing_requests, "count": len(viewing_requests)}

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
    """Get specific viewing request details"""
    try:
        tenant_id = current_user["id"]

        response = supabase_admin.table("viewing_requests").select("*").eq(
            "id", request_id
        ).eq("tenant_id", tenant_id).execute()

        if not response.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Viewing request not found")

        req = response.data[0]

        property_response = supabase_admin.table("properties").select("*").eq(
            "id", req["property_id"]
        ).execute()
        property_data = property_response.data[0] if property_response.data else None

        landlord_data = None
        if property_data and property_data.get("landlord_id"):
            landlord_response = supabase_admin.table("users").select(
                "id, full_name, avatar_url, phone_number, email"
            ).eq("id", property_data["landlord_id"]).execute()
            landlord_data = landlord_response.data[0] if landlord_response.data else None

        return {
            "success": True,
            "viewing_request": {**req, "property": property_data, "landlord": landlord_data},
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch viewing request: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# CREATE
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/")
async def create_viewing_request(
    request_data: ViewingRequestCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_tenant)
):
    """Create a new viewing request"""
    try:
        tenant_id = current_user["id"]
        preferred_date = _validate_future_date(request_data.preferred_date, "Preferred date")
        if not _PHONE.fullmatch(request_data.contact_number.strip()):
            raise HTTPException(status_code=422, detail="Enter a valid contact number")

        # Verify property exists
        property_check = supabase_admin.table("properties").select(
            "id, landlord_id, title"
        ).eq("id", request_data.property_id).execute()

        if not property_check.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

        landlord_id = property_check.data[0]["landlord_id"]
        property_title = property_check.data[0].get("title", "Property")

        # One active appointment journey per tenant/property. This is enforced
        # server-side so a stale browser cannot create duplicates.
        existing = supabase_admin.table("viewing_requests").select("id").eq(
            "tenant_id", tenant_id
        ).eq("property_id", request_data.property_id).in_("status", ["pending", "confirmed", "reschedule_proposed"]).execute()

        if existing.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have an active viewing request for this property"
            )

        # Insert viewing request
        response = supabase_admin.table("viewing_requests").insert({
            "tenant_id": tenant_id,
            "landlord_id": landlord_id,
            "property_id": request_data.property_id,
            "preferred_date": preferred_date.isoformat(),
            "time_slot": request_data.time_slot,
            "contact_number": request_data.contact_number,
            "message": request_data.message,
            "tenant_name": request_data.tenant_name,
            "viewing_type": request_data.viewing_type,
            "status": "pending",
        }).execute()

        if not response.data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create viewing request")

        viewing_request = response.data[0]
        viewing_id = viewing_request["id"]

        # Fetch user data for notifications
        tenant_r = supabase_admin.table("users").select(
            "id, full_name, email, phone_number"
        ).eq("id", tenant_id).execute()
        tenant_data = tenant_r.data[0] if tenant_r.data else None

        landlord_r = supabase_admin.table("users").select(
            "id, full_name, email, phone_number"
        ).eq("id", landlord_id).execute()
        landlord_data = landlord_r.data[0] if landlord_r.data else None

        tenant_name  = tenant_data.get("full_name", request_data.tenant_name) if tenant_data else request_data.tenant_name
        landlord_name = landlord_data.get("full_name", "Landlord") if landlord_data else "Landlord"

        # ── ONE call fires email + SMS + in-app for both parties ──────────────
        background_tasks.add_task(
            notification_service.notify_viewing_created,
            viewing_id=viewing_id,
            property_title=property_title,
            date=preferred_date.isoformat(),
            time_slot=request_data.time_slot,
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            tenant_email=tenant_data.get("email") if tenant_data else None,
            tenant_phone=request_data.contact_number,
            landlord_id=landlord_id,
            landlord_name=landlord_name,
            landlord_email=landlord_data.get("email") if landlord_data else None,
            landlord_phone=landlord_data.get("phone_number") if landlord_data else None,
        )

        return {
            "success": True,
            "message": "Viewing request sent successfully",
            "viewing_request": viewing_request,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create viewing request: {str(e)}"
        )



# ─────────────────────────────────────────────────────────────────────────────
# LANDLORD endpoints
# ─────────────────────────────────────────────────────────────────────────────



@router.patch("/{request_id}/review")
async def review_viewing_request(
    request_id: str,
    review_data: LandlordViewingReview,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_landlord)
):
    """Landlord confirms or cancels a viewing request, then fires notification"""
    try:
        logger.info(f"🔍 [REVIEW] Received review request for ID: {request_id}")
        logger.info(f"🔍 [REVIEW] Review data: {review_data}")
        logger.info(f"🔍 [REVIEW] Current user: {current_user['id']}")
        
        landlord_id = current_user["id"]

        existing = supabase_admin.table("viewing_requests").select("*").eq(
            "id", request_id
        ).eq("landlord_id", landlord_id).execute()

        if not existing.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Viewing request not found")

        viewing = existing.data[0]

        if viewing["status"] not in ("pending", "confirmed"):
            raise HTTPException(status_code=409, detail="This viewing is already closed and cannot be reviewed")
        if review_data.status in ("completed", "no_show") and viewing["status"] != "confirmed":
            raise HTTPException(status_code=409, detail="Only a confirmed viewing can be completed")

        update_payload = {"status": review_data.status, "landlord_notes": review_data.landlord_notes,
                          "updated_at": datetime.now().isoformat()}
        confirmed_date = None
        confirmed_time = None
        if review_data.status in ("confirmed", "reschedule_proposed"):
            confirmed_date = _validate_future_date(review_data.confirmed_date or "", "Confirmed date")
            confirmed_time = _validate_exact_time(review_data.confirmed_time)
            # A landlord cannot have two confirmed appointments at the same exact time.
            clash = supabase_admin.table("viewing_requests").select("id").eq(
                "landlord_id", landlord_id
            ).eq("status", "confirmed").eq("confirmed_date", confirmed_date.isoformat()).eq(
                "confirmed_time", confirmed_time
            ).neq("id", request_id).execute()
            if clash.data:
                raise HTTPException(status_code=409, detail="You already have a confirmed viewing at this time")
            update_payload.update({"confirmed_date": confirmed_date.isoformat(), "confirmed_time": confirmed_time})
            if review_data.status == "reschedule_proposed":
                update_payload["reschedule_proposed_at"] = datetime.now().isoformat()
        if review_data.status == "confirmed":
            update_payload.update({
                "safety_instructions": review_data.safety_instructions,
                "caretaker_name": review_data.caretaker_name,
                "caretaker_phone": review_data.caretaker_phone,
                "meeting_url": review_data.meeting_url,
            })
        elif review_data.status == "completed":
            update_payload["viewing_completed_at"] = datetime.now().isoformat()
        elif review_data.status == "no_show":
            update_payload["no_show_reason"] = review_data.no_show_reason

        response = supabase_admin.table("viewing_requests").update(update_payload).eq(
            "id", request_id
        ).execute()

        # Confirmation uses the shared email/SMS/in-app service below. Other
        # lifecycle changes still create an actionable in-app record.
        tenant_data, _, property_data = _fetch_viewing_participants(viewing)
        property_title = property_data.get("title", "this property") if property_data else "this property"
        if review_data.status == "reschedule_proposed":
            background_tasks.add_task(notification_service.notify_viewing_status_update, viewing_id=request_id, tenant_id=viewing["tenant_id"], tenant_email=tenant_data.get("email") if tenant_data else None, tenant_phone=viewing.get("contact_number"), property_title=property_title, title="Viewing time changed", message=f"A new viewing time was proposed for {property_title}: {confirmed_date.isoformat()} at {confirmed_time}. Accept or decline it in Nulo.")
        elif review_data.status == "cancelled":
            background_tasks.add_task(notification_service.notify_viewing_status_update, viewing_id=request_id, tenant_id=viewing["tenant_id"], tenant_email=tenant_data.get("email") if tenant_data else None, tenant_phone=viewing.get("contact_number"), property_title=property_title, title="Viewing request declined", message=f"The landlord could not confirm your viewing for {property_title}. See the note in Nulo.")

        # Fire confirmation notification when landlord confirms
        if review_data.status == "confirmed":
            tenant_data, landlord_data, property_data = _fetch_viewing_participants(viewing)
            background_tasks.add_task(
                notification_service.notify_viewing_confirmed,
                viewing_id=request_id,
                property_title=property_data.get("title", "Property") if property_data else "Property",
                date=confirmed_date.isoformat(),
                time_slot=confirmed_time,
                tenant_id=viewing["tenant_id"],
                tenant_name=tenant_data.get("full_name", viewing.get("tenant_name", "Tenant")) if tenant_data else viewing.get("tenant_name", "Tenant"),
                tenant_email=tenant_data.get("email") if tenant_data else None,
                tenant_phone=viewing.get("contact_number"),
                landlord_id=landlord_id,
                landlord_name=landlord_data.get("full_name", "Landlord") if landlord_data else "Landlord",
                landlord_email=landlord_data.get("email") if landlord_data else None,
                landlord_phone=landlord_data.get("phone_number") if landlord_data else None,
            )
            supabase_admin.table("viewing_requests").update({
                "sms_sent_confirmation": True,
                "last_notification_at": datetime.now().isoformat(),
            }).eq("id", request_id).execute()

        return {
            "success": True,
            "message": f"Viewing request {review_data.status}",
            "viewing_request": response.data[0],
        }

    except HTTPException as he:
        logger.error(f"❌ [REVIEW] HTTP Exception: {he.status_code} - {he.detail}")
        raise
    except Exception as e:
        logger.error(f"❌ [REVIEW] Failed to review viewing request: {str(e)}")
        logger.error(f"❌ [REVIEW] Exception type: {type(e).__name__}")
        import traceback
        logger.error(f"❌ [REVIEW] Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to review viewing request: {str(e)}"
        )

# ─────────────────────────────────────────────────────────────────────────────
# UPDATE / DELETE (tenant-side only)
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/{request_id}")
async def update_viewing_request(
    request_id: str,
    update_data: ViewingRequestUpdate,
    current_user: dict = Depends(get_current_tenant)
):
    """Update viewing request — tenants can only cancel"""
    try:
        tenant_id = current_user["id"]

        existing = supabase_admin.table("viewing_requests").select("*").eq(
            "id", request_id
        ).eq("tenant_id", tenant_id).execute()

        if not existing.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Viewing request not found")

        if update_data.status != "cancelled":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenants can only cancel viewing requests")
        if existing.data[0].get("status") not in ("pending", "confirmed"):
            raise HTTPException(status_code=409, detail="This viewing can no longer be cancelled")

        response = supabase_admin.table("viewing_requests").update({
            "status": update_data.status,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", request_id).execute()

        return {
            "success": True,
            "message": "Viewing request updated successfully",
            "viewing_request": response.data[0],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update viewing request: {str(e)}"
        )


@router.post("/{request_id}/reschedule-decision")
async def decide_reschedule(
    request_id: str,
    decision_data: TenantRescheduleDecision,
    current_user: dict = Depends(get_current_tenant),
):
    """Tenant accepts or declines a landlord-proposed exact appointment."""
    viewing_r = supabase_admin.table("viewing_requests").select("*").eq(
        "id", request_id
    ).eq("tenant_id", current_user["id"]).execute()
    if not viewing_r.data:
        raise HTTPException(status_code=404, detail="Viewing request not found")
    viewing = viewing_r.data[0]
    if viewing.get("status") != "reschedule_proposed":
        raise HTTPException(status_code=409, detail="There is no reschedule proposal awaiting your response")
    next_status = "confirmed" if decision_data.decision == "accept" else "cancelled"
    result = supabase_admin.table("viewing_requests").update({
        "status": next_status,
        "tenant_decision": decision_data.decision,
        "updated_at": datetime.now().isoformat(),
    }).eq("id", request_id).execute()
    create_notification(user_id=viewing["landlord_id"], notif_type="visit", title="Tenant responded to reschedule", message=f"The tenant {decision_data.decision}ed the proposed viewing time.", link=f"/landlord/viewings?request={request_id}", data={"viewing_id": request_id})
    return {"success": True, "message": f"Reschedule {decision_data.decision}ed", "viewing_request": result.data[0]}


@router.delete("/{request_id}")
async def delete_viewing_request(
    request_id: str,
    current_user: dict = Depends(get_current_tenant)
):
    """Soft-delete a viewing request (sets status to cancelled)"""
    try:
        tenant_id = current_user["id"]

        existing = supabase_admin.table("viewing_requests").select("*").eq(
            "id", request_id
        ).eq("tenant_id", tenant_id).execute()

        if not existing.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Viewing request not found")

        supabase_admin.table("viewing_requests").update({
            "status": "cancelled",
            "updated_at": datetime.now().isoformat(),
        }).eq("id", request_id).execute()

        return {"success": True, "message": "Viewing request cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to delete viewing request: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# SEND-SMS  (handles confirmation, reminders, interest)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{request_id}/send-sms")
async def send_viewing_sms(
    request_id: str,
    notification_type: Literal['confirmation', 'reminder_24h', 'reminder_1h', 'interest'],
    current_user: dict = Depends(get_current_landlord)
):
    """
    Trigger a notification batch for an existing viewing.

    notification_type:
      confirmation  — email + SMS + in-app to both parties (landlord confirmed)
      reminder_24h  — email + SMS + in-app to tenant only  (24h before)
      reminder_1h   — email + SMS + in-app to tenant only  (1h before)
      interest      — SMS + in-app to landlord only        (tenant interested)
    """
    try:
        viewing_r = supabase_admin.table("viewing_requests").select("*").eq(
            "id", request_id
        ).eq("landlord_id", current_user["id"]).execute()

        if not viewing_r.data:
            raise HTTPException(status_code=404, detail="Viewing not found")

        viewing = viewing_r.data[0]
        tenant_data, landlord_data, property_data = _fetch_viewing_participants(viewing)

        date_str      = viewing.get("confirmed_date") or viewing.get("preferred_date", "TBD")
        time_slot     = viewing.get("confirmed_time") or viewing.get("time_slot", "TBD")
        property_title = property_data.get("title", "Property") if property_data else "Property"
        tenant_name   = tenant_data.get("full_name", viewing.get("tenant_name", "Tenant")) if tenant_data else viewing.get("tenant_name", "Tenant")
        landlord_name = landlord_data.get("full_name", "Landlord") if landlord_data else "Landlord"

        # ── CONFIRMATION ──────────────────────────────────────────────────────
        if notification_type == "confirmation":
            if viewing.get("status") != "confirmed":
                raise HTTPException(status_code=409, detail="Only confirmed viewings can send confirmation")
            await notification_service.notify_viewing_confirmed(
                viewing_id=request_id,
                property_title=property_title,
                date=date_str,
                time_slot=time_slot,
                tenant_id=viewing["tenant_id"],
                tenant_name=tenant_name,
                tenant_email=tenant_data.get("email") if tenant_data else None,
                tenant_phone=viewing.get("contact_number"),
                landlord_id=viewing["landlord_id"],
                landlord_name=landlord_name,
                landlord_email=landlord_data.get("email") if landlord_data else None,
                landlord_phone=landlord_data.get("phone_number") if landlord_data else None,
            )
            supabase_admin.table("viewing_requests").update({
                "sms_sent_confirmation": True,
                "last_notification_at": datetime.now().isoformat(),
            }).eq("id", request_id).execute()

        # ── REMINDERS ─────────────────────────────────────────────────────────
        elif notification_type in ("reminder_24h", "reminder_1h"):
            if viewing.get("status") != "confirmed":
                raise HTTPException(status_code=409, detail="Only confirmed viewings can send reminders")
            hours = 24 if notification_type == "reminder_24h" else 1
            await notification_service.notify_viewing_reminder(
                viewing_id=request_id,
                property_title=property_title,
                date=date_str,
                time_slot=time_slot,
                hours=hours,
                tenant_id=viewing["tenant_id"],
                tenant_name=tenant_name,
                tenant_email=tenant_data.get("email") if tenant_data else None,
                tenant_phone=viewing.get("contact_number"),
            )
            flag_key = "sms_sent_reminder_24h" if hours == 24 else "sms_sent_reminder_1h"
            supabase_admin.table("viewing_requests").update({
                flag_key: True,
                "last_notification_at": datetime.now().isoformat(),
            }).eq("id", request_id).execute()

        # ── INTEREST ──────────────────────────────────────────────────────────
        elif notification_type == "interest":
            await notification_service.notify_viewing_interest(
                viewing_id=request_id,
                property_title=property_title,
                tenant_name=tenant_name,
                landlord_id=viewing["landlord_id"],
                landlord_name=landlord_name,
                landlord_phone=landlord_data.get("phone_number") if landlord_data else None,
            )

        return {"status": "sent", "type": notification_type}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in send_viewing_sms: {e}")
        raise HTTPException(status_code=500, detail=str(e))








