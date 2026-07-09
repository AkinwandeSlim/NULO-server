"""
Application routes
"""
import asyncio
import logging
from pydantic import ValidationError
from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File
from app.database import supabase_admin
from app.middleware.auth import get_current_user, get_current_tenant, get_current_landlord
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import re
import uuid

router = APIRouter(prefix="/applications")
logger = logging.getLogger(__name__)


class ApplicationCreate(BaseModel):
    property_id: str
    viewing_id: Optional[str] = None
    # Personal Info (will be extracted from user profile)
    message: Optional[str] = None
    
    # Employment Info
    employment_status: Optional[str] = None
    employer_name: Optional[str] = None
    monthly_income: Optional[int] = None
    
    # Additional Info
    move_in_date: Optional[str] = None
    lease_duration: Optional[str] = None
    number_of_occupants: Optional[int] = None
    has_pets: Optional[bool] = False
    pet_details: Optional[str] = None
    
    # References (JSONB)
    references: Optional[dict] = None
    
    # Documents (text array)
    documents: Optional[list] = None
    
    # Emergency contact
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class ApplicationApprove(BaseModel):
    pass


class ApplicationReject(BaseModel):
    reason: str
    reason_code: str


@router.post("/", response_model=dict)
async def create_application(
    application_data: ApplicationCreate,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Submit rental application (tenants only)
    Requires 100% profile completion (deferred KYC gate)
    """
    logger.info(f"📋 [APP] Received application request")
    logger.info(f"📋 [APP] Property ID: {application_data.property_id}")
    logger.info(f"📋 [APP] Viewing ID: {application_data.viewing_id}")
    logger.info(f"📋 [APP] References type: {type(application_data.references)}, value: {application_data.references}")
    logger.info(f"📋 [APP] Documents type: {type(application_data.documents)}, count: {len(application_data.documents) if application_data.documents else 0}")
    
    try:
        tenant_id = current_user["id"]
        
        # Verify user exists in users table
        user_check = supabase_admin.table("users").select("id, user_type").eq(
            "id", tenant_id
        ).single().execute()
        
        if not user_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        if user_check.data["user_type"] != "tenant":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only tenants can submit applications"
            )
        
        # Check tenant profile completion - skip for now (deferred KYC gate)
        # TODO: Re-enable when profile completion is implemented
        
        # Check if property exists and get landlord info
        property_check = supabase_admin.table("properties").select("id, landlord_id, title, price").eq(
            "id", application_data.property_id
        ).single().execute()
        
        if not property_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        property_data = property_check.data
        
        # Check for existing application
        existing_app = supabase_admin.table("applications").select("id").eq(
            "user_id", tenant_id
        ).eq("property_id", application_data.property_id).execute()
        
        if existing_app.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already applied for this property"
            )
        
        # Create application with correct schema
        # NB: applications_status_check constraint allows
        #     ('submitted', 'under_review', 'approved', 'rejected', 'withdrawn')
        # We use 'submitted' here so the row stores a value that matches the
        # CHECK constraint. (Previously the code wrote 'pending', which the DB
        # silently coerced — then the reject endpoint would refuse because
        # 'pending' was not in its allowlist, surfacing as "Cannot be
        # rejected". See LAPP-05 in QA checklist.)
        app_dict = {
            "user_id": tenant_id,  # Correct field name from database schema
            "property_id": application_data.property_id,
            "viewing_id": application_data.viewing_id,
            "status": "submitted",
            "message": application_data.message,
            "move_in_date": application_data.move_in_date,
            "lease_duration": application_data.lease_duration,
            "employment_status": application_data.employment_status,
            "employer_name": application_data.employer_name,
            "monthly_income": application_data.monthly_income,
            "number_of_occupants": application_data.number_of_occupants,
            "has_pets": application_data.has_pets,
            "pet_details": application_data.pet_details,
            "references": application_data.references or {},
            "documents": application_data.documents or [],
            "emergency_contact_name": application_data.emergency_contact_name,
            "emergency_contact_phone": application_data.emergency_contact_phone,
            "viewed_by_landlord": False
        }
        
        app_response = supabase_admin.table("applications").insert(app_dict).execute()
        
        if not app_response.data:
            logger.error(f"❌ [APP] Failed to create application - insert returned no data")
            logger.error(f"❌ [APP] Insert dict: {app_dict}")
            if hasattr(app_response, 'error') and app_response.error:
                logger.error(f"❌ [APP] Supabase error: {app_response.error}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create application: check server logs"
            )
        
        application = app_response.data[0]
        
        # Create mock escrow transaction (skip for now - implement in payment phase)
        # TODO: Implement in Priority 8 (Paystack integration)
        
        # FIX #2 — single atomic increment instead of read-then-write (N+1)
        # Fallback to the old pattern if the RPC doesn't exist yet in the DB.
        try:
            supabase_admin.rpc(
                "increment_application_count",
                {"property_id_input": application_data.property_id},
            ).execute()
        except Exception as rpc_err:
            logger.warning(f"⚠️ [APP] increment_application_count RPC unavailable, falling back: {rpc_err}")
            # Fallback: read current count then write (safe enough for low traffic)
            count_resp = supabase_admin.table("properties").select("application_count").eq(
                "id", application_data.property_id
            ).single().execute()
            current_count = (count_resp.data or {}).get("application_count", 0) or 0
            supabase_admin.table("properties").update(
                {"application_count": current_count + 1}
            ).eq("id", application_data.property_id).execute()

        # FIX #4 — fetch landlord + tenant details in parallel so both
        # round-trips happen concurrently instead of sequentially.
        from app.services.notification_service import notification_service

        loop = asyncio.get_event_loop()

        def _fetch_landlord():
            return supabase_admin.table("users").select(
                "full_name, email, phone_number"
            ).eq("id", property_data["landlord_id"]).single().execute()

        def _fetch_tenant():
            return supabase_admin.table("users").select(
                "full_name, email, phone_number"
            ).eq("id", tenant_id).single().execute()

        landlord_response, tenant_response = await asyncio.gather(
            loop.run_in_executor(None, _fetch_landlord),
            loop.run_in_executor(None, _fetch_tenant),
        )

        landlord_details = landlord_response.data or {}
        tenant_details   = tenant_response.data or {}

        logger.info(f"📧 [APP] Queuing fire-and-forget notification for application {application['id']}")

        # FIX #3 — fire-and-forget: schedule notifications without awaiting
        # them, so the tenant receives an HTTP 200 immediately after the
        # application row is committed rather than waiting for email + SMS.
        async def _send_notifications():
            try:
                await notification_service.notify_application_submitted(
                    application_id=application["id"],
                    property_id=application_data.property_id,
                    property_title=property_data["title"],
                    tenant_id=tenant_id,
                    tenant_name=tenant_details.get("full_name", "Unknown"),
                    tenant_email=tenant_details.get("email"),
                    tenant_phone=tenant_details.get("phone_number"),
                    landlord_id=property_data["landlord_id"],
                    landlord_name=landlord_details.get("full_name", "Landlord"),
                    landlord_email=landlord_details.get("email"),
                    landlord_phone=landlord_details.get("phone_number"),
                    monthly_income=application_data.monthly_income,
                    employment_status=application_data.employment_status,
                    message=application_data.message or "No additional message provided",
                )
            except Exception as notif_err:
                # Notification failures must never roll back a successful submission
                logger.error(f"❌ [APP] Background notification failed: {notif_err}")

        asyncio.create_task(_send_notifications())
        
        return {
            "success": True,
            "application": application,
            "message": "Application submitted successfully"
        }
        
    except ValidationError as e:
        logger.error(f"❌ [APP] Validation error: {e.errors()}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation failed: {e.errors()}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to submit application: {str(e)}"
        )


@router.get("/my-applications")
async def get_my_applications(
    current_user: dict = Depends(get_current_tenant)
):
    """
    Get tenant's own applications
    """
    try:
        user_id = current_user["id"]
        
        response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, location, price, landlord_id, payment_frequency)"
        ).eq("user_id", user_id).order("created_at", desc=True).execute()
        
        return {
            "success": True,
            "applications": response.data
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch applications: {str(e)}"
        )


@router.get("/received")
async def get_received_applications(
    current_user: dict = Depends(get_current_landlord)
):
    """
    Get applications received by landlord
    """
    try:
        user_id = current_user["id"]
        
        response = supabase_admin.table("applications").select(
            "*, property:properties!inner(id, title, location, price, landlord_id, payment_frequency), user:users!user_id(id, full_name, email, phone_number, trust_score)"
        ).eq("property.landlord_id", user_id).order("created_at", desc=True).execute()
        
        return {
            "success": True,
            "applications": response.data
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch applications: {str(e)}"
        )


@router.get("/stats")
async def get_applications_stats(
    current_user: dict = Depends(get_current_user)
):
    """
    Get application statistics
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]
        
        if user_type == "tenant":
            # Tenant stats: total, pending, approved, rejected
            response = supabase_admin.table("applications").select(
                "status"
            ).eq("user_id", user_id).execute()
            
        elif user_type == "landlord":
            # Landlord stats: total received, pending, approved, rejected
            response = supabase_admin.table("applications").select(
                "status"
            ).eq("property.landlord_id", user_id).execute()
            
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid user type"
            )
        
        applications = response.data or []
        stats = {
            "total": len(applications),
            "submitted": len([a for a in applications if a["status"] in ("submitted", "pending")]),
            "pending": len([a for a in applications if a["status"] in ("submitted", "pending")]),
            "approved": len([a for a in applications if a["status"] == "approved"]),
            "rejected": len([a for a in applications if a["status"] == "rejected"])
        }
        
        return {
            "success": True,
            "stats": stats
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch stats: {str(e)}"
        )


@router.get("/")
async def get_applications(current_user: dict = Depends(get_current_user)):
    """
    Get user's applications
    Tenants see their own applications
    Landlords see applications for their properties
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]
        
        if user_type == "tenant":
            # Fetch tenant's applications
            response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, location, price, landlord_id, payment_frequency)"
        ).eq("user_id", user_id).order("created_at", desc=True).execute()
            
        elif user_type == "landlord":
            # Fetch applications for landlord's properties
            response = supabase_admin.table("applications").select(
                "*, property:properties!inner(id, title, location, price), user:users!user_id(id, full_name, email, phone_number, trust_score)"
            ).eq("property.landlord_id", user_id).order("created_at", desc=True).execute()
            
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid user type"
            )
        
        return {
            "success": True,
            "applications": response.data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch applications: {str(e)}"
        )


@router.post("/upload-document")
async def upload_application_document(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_tenant),
):
    """
    BUG-025 FIX (RLS bypass): Upload an application document to Supabase
    Storage using the service-role admin client. Doing this on the server
    side means we don't have to write per-bucket RLS policies that give
    every authenticated user INSERT permission — the client only sends
    the file as multipart/form-data and we hand back the storage path.

    The path is namespaced by user id so that the signed-URL endpoint
    can verify ownership later if needed.
    """
    try:
        user_id = current_user["id"]

        # Validate file type — allow common document & image MIME types
        allowed_types = {
            "application/pdf",
            "image/jpeg", "image/jpg", "image/png", "image/webp",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        if file.content_type and file.content_type not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type: {file.content_type}",
            )

        # Sanitize filename and build a unique storage path
        original_name = file.filename or "document"
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", original_name)
        unique_id = uuid.uuid4().hex[:12]
        file_path = f"applications/{user_id}/{int(datetime.now().timestamp())}-{unique_id}-{safe_name}"

        # Read the file bytes
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty file upload",
            )

        # Upload via the service-role admin client (bypasses RLS)
        try:
            import inspect
            logger.info(f"🔍 [APP-DOCS] Using supabase_admin for upload")
            logger.info(f"🔍 [APP-DOCS] Upload path: {file_path}")
            logger.info(f"🔍 [APP-DOCS] File size: {len(file_bytes)}")
            # Check if we can get the client info
            logger.info(f"🔍 [APP-DOCS] Supabase admin client exists: {type(supabase_admin)}")
            
            supabase_admin.storage.from_("application-documents").upload(
                path=file_path,
                file=file_bytes,
                file_options={
                    "content-type": file.content_type or "application/octet-stream",
                    "cache-control": "3600",
                    "upsert": "false",
                },
            )
        except Exception as upload_error:
            # supabase-py sometimes raises a StorageException with the
            # underlying message attached — surface it for easier debugging
            import traceback
            logger.error(f"❌ [APP-DOCS] Full traceback of upload error:\n{traceback.format_exc()}")
            err_msg = str(upload_error)
            if hasattr(upload_error, "message"):
                err_msg = upload_error.message
            logger.error(f"❌ [APP-DOCS] Storage upload failed: {err_msg}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Storage upload failed: {err_msg}",
            )

        logger.info(f"✅ [APP-DOCS] Uploaded {file_path} ({len(file_bytes)} bytes) for user {user_id}")

        return {
            "success": True,
            "path": file_path,
            "filename": safe_name,
            "size": len(file_bytes),
            "content_type": file.content_type,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [APP-DOCS] Unexpected upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload application document: {str(e)}",
        )


@router.get("/{application_id}")
async def get_application(
    application_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get application by ID
    - Tenants can view their own applications
    - Landlords can view applications for their properties
    - Marks as viewed by landlord if accessed by landlord
    - BUG-025 FIX: Generates signed URLs for any document storage paths so
      the landlord can actually open the tenant's uploaded PDFs/images.
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]

        # Fetch application with full property and user details
        app_response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, description, property_type, address, full_address, location, city, state, price, beds, baths, sqft, images, amenities, furnished, pet_friendly, landlord_id, payment_frequency), user:users!user_id(id, full_name, email, phone_number, trust_score, avatar_url, user_type)"
        ).eq("id", application_id).single().execute()

        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found"
            )

        application = app_response.data

        # Verify access
        if user_type == "tenant":
            # Tenants can only view their own applications
            if application["user_id"] != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have permission to view this application"
                )
        elif user_type == "landlord":
            # Landlords can only view applications for their properties
            property_data = application.get("property")
            if not property_data or property_data.get("landlord_id") != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have permission to view this application"
                )

            # Mark as viewed by landlord (if not already)
            if not application.get("viewed_by_landlord"):
                try:
                    supabase_admin.table("applications").update({
                        "viewed_by_landlord": True,
                        "viewed_at": datetime.now().isoformat()
                    }).eq("id", application_id).execute()
                except Exception as e:
                    logger.warning(f"⚠️ [APP] Failed to mark application as viewed: {e}")
                    # Don't raise — still return the application even if marking fails
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid user type"
            )

        # BUG-025 FIX: Convert any document storage paths into signed URLs so
        # the landlord's <a href={url}> actually resolves to a downloadable
        # file. We treat each entry as either an absolute URL (already signed
        # or external) or a relative storage path inside the
        # 'application-documents' bucket.
        raw_documents = application.get("documents") or []
        signed_documents: list[dict] = []
        for path in raw_documents:
            if not path:
                continue
            # Already an absolute URL — pass through
            if isinstance(path, str) and path.startswith(("http://", "https://")):
                signed_documents.append({"path": path, "url": path, "filename": path.split("/")[-1]})
                continue

            try:
                signed = supabase_admin.storage.from_("application-documents").create_signed_url(
                    path,
                    3600,  # 1 hour expiry
                )
                # supabase-py v2 returns dict with `signedURL` key
                signed_url = signed.get("signedURL") if isinstance(signed, dict) else None
                if signed_url:
                    signed_documents.append({
                        "path": path,
                        "url": signed_url,
                        "filename": path.split("/")[-1],
                    })
                else:
                    logger.warning(f"⚠️ [APP] No signedURL returned for {path}")
            except Exception as storage_err:
                logger.warning(f"⚠️ [APP] Failed to sign document {path}: {storage_err}")
                # Fall back to the raw path so the UI can still display a label
                signed_documents.append({"path": path, "url": None, "filename": path.split("/")[-1]})

        # Replace the raw text[] field with the enriched list
        application["documents"] = signed_documents

        return {
            "success": True,
            "application": application
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch application: {str(e)}"
        )


@router.get("/{application_id}/documents/signed-url")
async def get_application_document_signed_url(
    application_id: str,
    path: str,
    current_user: dict = Depends(get_current_user),
):
    """
    BUG-025 FIX: Return a short-lived signed URL for a single application
    document. Used by the landlord view when it needs to lazy-load
    individual files without re-fetching the entire application.
    """
    try:
        user_id = current_user["id"]
        user_type = current_user["user_type"]

        # Fetch minimal app fields to verify access
        app_resp = supabase_admin.table("applications").select(
            "id, user_id, property:properties(id, landlord_id)"
        ).eq("id", application_id).single().execute()

        if not app_resp.data:
            raise HTTPException(status_code=404, detail="Application not found")

        app_row = app_resp.data
        if user_type == "tenant" and app_row["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Forbidden")
        if user_type == "landlord":
            prop = app_row.get("property") or {}
            if prop.get("landlord_id") != user_id:
                raise HTTPException(status_code=403, detail="Forbidden")

        if not path:
            raise HTTPException(status_code=400, detail="path query param is required")

        signed = supabase_admin.storage.from_("application-documents").create_signed_url(
            path, 3600
        )
        signed_url = signed.get("signedURL") if isinstance(signed, dict) else None
        if not signed_url:
            raise HTTPException(status_code=500, detail="Failed to generate signed URL")

        return {"success": True, "url": signed_url, "expires_in": 3600}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [APP] Signed-URL endpoint failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate signed URL: {str(e)}",
        )


@router.delete("/{application_id}")
async def withdraw_application(
    application_id: str,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Withdraw application (tenants only)
    """
    try:
        tenant_id = current_user["id"]
        
        # Fetch application
        app_response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, landlord_id)"
        ).eq("id", application_id).single().execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found"
            )
        
        application = app_response.data
        
        # Verify tenant owns the application
        if application["user_id"] != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to withdraw this application"
            )
        
        # Check if already withdrawn
        if application["status"] == "withdrawn":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Application is already withdrawn"
            )
        
        # Update status to withdrawn
        supabase_admin.table("applications").update({
            "status": "withdrawn"
        }).eq("id", application_id).execute()
        
        return {
            "success": True,
            "message": "Application withdrawn successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to withdraw application: {str(e)}"
        )


@router.patch("/{application_id}/approve")
async def approve_application(
    application_id: str,
    current_user: dict = Depends(get_current_landlord)
):
    """
    Approve application (landlords only, own properties)
    """
    try:
        landlord_id = current_user["id"]
        
        # Fetch application with property and tenant
        app_response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, landlord_id, price, payment_frequency), user:users!user_id(id, full_name, email, phone_number)"
        ).eq("id", application_id).single().execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found"
            )
        
        application = app_response.data
        property_data = application.get("property")
        tenant_data = application.get("user")
        
        # Verify landlord owns the property
        if not property_data or property_data.get("landlord_id") != landlord_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to approve this application"
            )
        
        # Check if already approved/rejected
        # NOTE: include both 'submitted' and 'pending' here so we handle legacy
        # rows that may have been inserted before the status vocabulary was
        # aligned with the DB CHECK constraint. New rows are inserted as
        # 'submitted' (see create_application); legacy rows may still say
        # 'pending'.
        if application["status"] not in ["submitted", "pending", "under_review"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Application is already {application['status']}"
            )
        
        # Update application status
        update_response = supabase_admin.table("applications").update({
            "status": "approved",
            "viewed_by_landlord": True,
            "viewed_at": datetime.now().isoformat()
        }).eq("id", application_id).execute()
        
        # Fetch the updated application with full details
        updated_app_response = supabase_admin.table("applications").select(
            "*, property:properties!inner(id, title, location, price, landlord_id, payment_frequency), user:users!user_id(id, full_name, email, phone_number, trust_score)"
        ).eq("id", application_id).single().execute()
        
        if not updated_app_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch updated application"
            )
        
        # Send notification to tenant
        from app.services.notification_service import notification_service
        
        landlord_name = current_user.get("full_name", "Landlord")
        landlord_email = current_user.get("email")
        landlord_phone = current_user.get("phone_number")
        
        await notification_service.notify_application_approved(
            application_id=application_id,
            property_id=property_data.get("id"),
            property_title=property_data.get("title", "Property"),
            tenant_id=tenant_data.get("id"),
            tenant_name=tenant_data.get("full_name", "Tenant"),
            tenant_email=tenant_data.get("email"),
            tenant_phone=tenant_data.get("phone_number"),
            landlord_name=landlord_name,
        )
        
        # Auto-generate rental agreement (NuloGuide Stage 5)
        logger.info(f"🔥 [APP] Auto-generating agreement for approved application {application_id}")
        logger.info(f"🔥 [APP] Property data: {property_data}")
        logger.info(f"🔥 [APP] Tenant data: {tenant_data}")
        
        # Use centralized agreement service
        from app.services.agreement_service import agreement_service
        
        agreement = await agreement_service.auto_generate_agreement(
            application_id=application_id,
            property_data=property_data,
            tenant_data=tenant_data,
            landlord_name=landlord_name
        )
        
        if agreement:
            agreement_id = agreement['id']
            logger.info(f"✅ [APP] Auto-generated agreement {agreement_id} for application {application_id}")
            
            # Send notification about agreement creation
            try:
                await notification_service.notify_agreement_created(
                    agreement_id=agreement_id,
                    application_id=application_id,
                    property_title=property_data.get("title", "Property"),
                    tenant_id=tenant_data.get("id"),
                    tenant_name=tenant_data.get("full_name", "Tenant"),
                    tenant_email=tenant_data.get("email"),
                    tenant_phone=tenant_data.get("phone_number"),
                    landlord_id=landlord_id,
                    landlord_name=landlord_name,
                    landlord_email=landlord_email,
                    landlord_phone=landlord_phone,
                )
                logger.info(f"✅ [APP] Agreement notification sent for {agreement_id}")
            except Exception as e:
                logger.error(f"❌ [APP] Failed to send agreement notification: {e}")
        else:
            logger.error(f"❌ [APP] Failed to auto-generate agreement for application {application_id}")
        
        # TODO: Update property status to rented (implement in agreement phase)
        # TODO: Update trust scores (+5 bonus for both)
        
        return {
            "success": True,
            "application": updated_app_response.data,
            "agreement": agreement,
            "message": "Application approved and rental agreement generated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [APP] Failed to approve application: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to approve application: {str(e)}"
        )


@router.patch("/{application_id}/reject")
async def reject_application(
    application_id: str,
    rejection_data: ApplicationReject,
    current_user: dict = Depends(get_current_landlord)
):
    """
    Reject application (landlords only, own properties)
    """
    try:
        landlord_id = current_user["id"]
        
        # Fetch application with property and tenant
        app_response = supabase_admin.table("applications").select(
            "*, property:properties(id, title, landlord_id, price, payment_frequency), user:users!user_id(id, full_name, email, phone_number)"
        ).eq("id", application_id).single().execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found"
            )
        
        application = app_response.data
        property_data = application.get("property")
        tenant_data = application.get("user")

        # Verify landlord owns the property
        if not property_data or property_data.get("landlord_id") != landlord_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to reject this application"
            )

        # Idempotency: if the application is already rejected, treat this as a
        # success so the landlord's UI doesn't spin forever on a re-submit that
        # was caused by a previous transient failure (e.g. notification side-
        # effect). We still return the existing row.
        if application["status"] == "rejected":
            logger.info(
                f"♻️  [APP] Application {application_id} already rejected; "
                f"returning existing row"
            )
            return {
                "success": True,
                "application": application,
                "message": "Application was already rejected",
                "already_rejected": True,
            }

        # Check if already approved/rejected (or otherwise terminal)
        # NOTE: include both 'submitted' and 'pending' here so we handle legacy
        # rows that may have been inserted before the status vocabulary was
        # aligned with the DB CHECK constraint. New rows are inserted as
        # 'submitted' (see create_application); legacy rows may still say
        # 'pending'.
        if application["status"] not in ["submitted", "pending", "under_review"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Application is already {application['status']} and "
                    f"cannot be rejected. Only submitted or under_review "
                    f"applications can be rejected."
                ),
            )

        # Update application status
        update_response = supabase_admin.table("applications").update({
            "status": "rejected",
            "rejection_reason": rejection_data.reason,  # Store reason in rejection_reason field
            "viewed_by_landlord": True,
            "viewed_at": datetime.now().isoformat()
        }).eq("id", application_id).execute()

        if not update_response.data:
            # Log full debug context so we can see why the update failed
            logger.error(
                f"❌ [APP] Reject update returned no data. "
                f"app_id={application_id} current_status={application['status']} "
                f"reason={rejection_data.reason!r}"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database update returned no data; the application could not be rejected.",
            )

        # Fetch the updated application with full details
        updated_app_response = supabase_admin.table("applications").select(
            "*, property:properties!inner(id, title, location, price, landlord_id, payment_frequency), user:users!user_id(id, full_name, email, phone_number, trust_score)"
        ).eq("id", application_id).single().execute()

        if not updated_app_response.data:
            # Don't fail the whole request — the DB row is already updated.
            logger.warning(
                f"⚠️  [APP] Could not re-fetch updated application {application_id} "
                f"after rejection (DB row is updated though)."
            )
            updated_app_response_data = application
        else:
            updated_app_response_data = updated_app_response.data

        # Send notification to tenant — wrapped in its own try/except so a
        # notification-side failure (e.g. SMS gateway down) cannot roll back
        # the rejection. The DB is already updated; the rejection stands.
        try:
            from app.services.notification_service import notification_service

            await notification_service.notify_application_rejected(
                application_id=application_id,
                property_id=property_data.get("id"),
                property_title=property_data.get("title", "Property"),
                tenant_id=tenant_data.get("id"),
                tenant_name=tenant_data.get("full_name", "Tenant"),
                tenant_email=tenant_data.get("email"),
                tenant_phone=tenant_data.get("phone_number"),
                rejection_reason=rejection_data.reason,
            )
        except Exception as notify_err:
            # Log but do NOT fail the whole request — the rejection itself
            # succeeded and the tenant can still see it in their dashboard.
            logger.error(
                f"⚠️  [APP] Failed to send rejection notification for "
                f"application {application_id}: {notify_err}. "
                f"Rejection itself succeeded — tenant can view it in their "
                f"dashboard regardless."
            )

        return {
            "success": True,
            "application": updated_app_response_data,
            "message": "Application rejected",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [APP] Failed to reject application: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to reject application: {str(e)}",
        )
