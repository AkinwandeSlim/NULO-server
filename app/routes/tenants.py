"""
Tenant api routes
"""
from fastapi import APIRouter, HTTPException, Depends, status, File, UploadFile
from app.database import supabase_admin
from app.middleware.auth import get_current_tenant
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor

router = APIRouter(prefix="/tenants")
executor = ThreadPoolExecutor(max_workers=4)


async def upload_document_with_timeout(file_content: bytes, file_name: str, content_type: str, timeout: int = 30) -> Optional[str]:
    """
    Upload document to Supabase storage with timeout handling.
    Returns public URL on success, None on failure.
    """
    try:
        def do_upload():
            return supabase_admin.storage.from_("application-documents").upload(
                path=file_name,
                file=file_content,
                file_options={"content-type": content_type}
            )
        
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(executor, do_upload),
            timeout=timeout
        )
        
        def get_url():
            return supabase_admin.storage.from_("application-documents").get_public_url(file_name)
        
        public_url = await asyncio.wait_for(
            loop.run_in_executor(executor, get_url),
            timeout=10
        )
        
        print(f"✅ Document uploaded: {public_url}")
        return public_url
        
    except asyncio.TimeoutError:
        print(f"⚠️ Document upload timed out after {timeout}s: {file_name}")
        return None
    except Exception as e:
        print(f"⚠️ Document upload failed: {type(e).__name__}: {str(e)}")
        return None


class TenantProfileUpdate(BaseModel):
    budget: Optional[float] = None
    preferred_location: Optional[str] = None
    move_in_date: Optional[str] = None
    preferences: Optional[dict] = None


class PreferencesData(BaseModel):
    budget: float
    preferred_location: str
    bedrooms: int
    move_in_date: Optional[str] = None


class CompleteProfileData(BaseModel):
    # Step 1: Preferences
    budget: float
    preferred_location: str
    bedrooms: int
    move_in_date: Optional[str] = None
    
    # Step 2: Documents
    id_document_url: str
    proof_of_income_url: str
    reference1_email: Optional[str] = None
    reference2_email: Optional[str] = None
    
    # Step 3: Rent Credit
    join_rent_credit: bool = False


@router.get("/profile")
async def get_tenant_profile(current_user: dict = Depends(get_current_tenant)):
    """
    Get tenant profile with completion status
    """
    try:
        tenant_id = current_user["id"]
        
        # Fetch tenant profile
        response = supabase_admin.table("tenants").select("*").eq("id", tenant_id).single().execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant profile not found"
            )
        
        tenant_data = response.data
        
        # Calculate profile completion
        completion = calculate_profile_completion(tenant_data)
        
        return {
            "success": True,
            "profile": {
                **tenant_data,
                "profile_completion": completion
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch profile: {str(e)}"
        )


@router.get("/profile-status")
async def get_profile_status(current_user: dict = Depends(get_current_tenant)):
    """
    Get profile completion status and missing fields
    """
    try:
        tenant_id = current_user["id"]
        
        # Fetch tenant and user data
        tenant_response = supabase_admin.table("tenants").select("*").eq("id", tenant_id).single().execute()
        user_response = supabase_admin.table("users").select("trust_score, verification_status").eq("id", tenant_id).single().execute()
        
        if not tenant_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant profile not found"
            )
        
        tenant_data = tenant_response.data
        user_data = user_response.data if user_response.data else {}
        
        # Calculate completion
        completion = calculate_profile_completion(tenant_data)
        
        # Determine missing fields
        missing_fields = []
        if not tenant_data.get("budget"):
            missing_fields.append("budget")
        if not tenant_data.get("preferred_location"):
            missing_fields.append("preferred_location")
        
        documents = tenant_data.get("documents", {})
        if isinstance(documents, dict):
            if not documents.get("id_document"):
                missing_fields.append("id_document")
            if not documents.get("proof_of_income"):
                missing_fields.append("proof_of_income")
        else:
            missing_fields.extend(["id_document", "proof_of_income"])
        
        return {
            "profile_completion": completion,
            "onboarding_completed": tenant_data.get("onboarding_completed", False),
            "trust_score": user_data.get("trust_score", 50),
            "verification_status": user_data.get("verification_status", "partial"),
            "missing_fields": missing_fields,
            "can_apply": completion >= 100
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch profile status: {str(e)}"
        )


@router.patch("/profile")
async def update_tenant_profile(
    profile_data: TenantProfileUpdate,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Update tenant profile
    """
    try:
        tenant_id = current_user["id"]
        
        # Update profile
        update_dict = profile_data.dict(exclude_unset=True)
        
        response = supabase_admin.table("tenants").update(update_dict).eq("id", tenant_id).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update profile"
            )
        
        # Recalculate completion
        tenant_data = response.data[0]
        completion = calculate_profile_completion(tenant_data)
        
        # Update completion percentage
        supabase_admin.table("tenants").update({
            "profile_completion": completion
        }).eq("id", tenant_id).execute()
        
        return {
            "success": True,
            "profile": {
                **tenant_data,
                "profile_completion": completion
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update profile: {str(e)}"
        )


@router.post("/complete-profile")
async def complete_profile(
    profile_data: CompleteProfileData,
    current_user: dict = Depends(get_current_tenant)
):
    """
    Complete tenant profile (deferred KYC)
    This unlocks the ability to apply for properties
    """
    try:
        tenant_id = current_user["id"]
        
        # Prepare documents
        documents = {
            "id_document": profile_data.id_document_url,
            "proof_of_income": profile_data.proof_of_income_url
        }
        
        # Add references if provided
        references = []
        if profile_data.reference1_email:
            references.append(profile_data.reference1_email)
        if profile_data.reference2_email:
            references.append(profile_data.reference2_email)
        
        if references:
            documents["references"] = references
        
        # Prepare preferences
        preferences = {
            "bedrooms": profile_data.bedrooms,
            "move_in_date": profile_data.move_in_date,
            "join_rent_credit": profile_data.join_rent_credit
        }
        
        # Update tenant profile
        update_dict = {
            "budget": profile_data.budget,
            "preferred_location": profile_data.preferred_location,
            "preferences": preferences,
            "documents": documents,
            "profile_completion": 100,
            "onboarding_completed": True,
            "profile_completed_at": datetime.now().isoformat()
        }
        
        response = supabase_admin.table("tenants").update(update_dict).eq("id", tenant_id).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to complete profile"
            )
        
        # Update trust score
        new_trust_score = 70  # Base 50 + Profile completion 20
        if profile_data.join_rent_credit:
            new_trust_score += 10  # Bonus for rent credit program
        
        supabase_admin.table("users").update({
            "trust_score": new_trust_score,
            "verification_status": "approved"
        }).eq("id", tenant_id).execute()
        
        return {
            "success": True,
            "message": "Profile completed! You can now apply for properties.",
            "profile": response.data[0],
            "trust_score": new_trust_score
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to complete profile: {str(e)}"
        )


def calculate_profile_completion(tenant_data: dict) -> int:
    """
    Calculate profile completion percentage based on 3-step wizard
    Step 1 (Preferences): 33%
    Step 2 (Documents): 67% (33% + 34%)
    Step 3 (Review): 100% (67% + 33%)
    """
    completion = 0
    
    # Step 1: Preferences (33%)
    has_preferences = (
        tenant_data.get("budget") and 
        tenant_data.get("preferred_location")
    )
    if has_preferences:
        completion = 33
    
    # Step 2: Documents (34% more = 67% total)
    documents = tenant_data.get("documents", {})
    if isinstance(documents, dict):
        has_documents = (
            documents.get("id_document") and 
            documents.get("proof_of_income")
        )
        if has_documents:
            completion = 67
    
    # Step 3: Completed (33% more = 100% total)
    if tenant_data.get("onboarding_completed"):
        completion = 100
    
    return completion


@router.post("/upload-document")
async def upload_document(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_tenant)
):
    """
    Upload tenant document to Supabase storage
    """
    try:
        # Read file content
        file_content = await file.read()
        
        # Generate unique file name with tenant ID prefix
        import uuid
        file_extension = file.filename.split(".")[-1] if "." in file.filename else "pdf"
        unique_file_name = f"tenant-docs/{current_user['id']}/{uuid.uuid4()}.{file_extension}"
        
        # Upload to storage
        document_url = await upload_document_with_timeout(
            file_content=file_content,
            file_name=unique_file_name,
            content_type=file.content_type or "application/pdf"
        )
        
        if not document_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload document"
            )
        
        return {
            "success": True,
            "url": document_url
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload document: {str(e)}"
        )
