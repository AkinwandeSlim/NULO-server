"""
Agreements routes - Using Supabase (not SQLAlchemy)
Rental Agreement Management with electronic signatures
"""
from fastapi import APIRouter, HTTPException, Depends, status
from app.database import supabase_admin
from app.middleware.auth import get_current_user
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
import uuid

router = APIRouter(prefix="/agreements")


class AgreementCreate(BaseModel):
    """Model for creating new agreements"""
    application_id: str
    lease_start_date: str  # YYYY-MM-DD format
    lease_end_date: str    # YYYY-MM-DD format
    lease_duration: int    # in months


class AgreementSignRequest(BaseModel):
    """Model for signing agreements"""
    ip_address: Optional[str] = Field(None, description="Client IP address for signature verification")


class AgreementUpdate(BaseModel):
    """Model for updating agreements"""
    status: Optional[str] = Field(None, description="Agreement status")


@router.post("/")
async def create_agreement(
    agreement_data: AgreementCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new rental agreement from an approved application
    Only tenants can create agreements for their approved applications
    """
    try:
        tenant_id = current_user["id"]
        
        # Verify application exists and belongs to current user
        app_response = supabase_admin.table("applications").select("*").eq(
            "id", agreement_data.application_id
        ).eq("tenant_id", tenant_id).eq("status", "ACCEPTED").execute()
        
        if not app_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approved application not found"
            )
        
        application = app_response.data[0]
        
        # Check if agreement already exists
        existing_response = supabase_admin.table("agreements").select("*").eq(
            "application_id", agreement_data.application_id
        ).execute()
        
        if existing_response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agreement already exists for this application"
            )
        
        # Get property details
        property_response = supabase_admin.table("properties").select("*").eq(
            "id", application["property_id"]
        ).execute()
        
        if not property_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        property = property_response.data[0]
        
        # Create agreement
        agreement_dict = {
            "application_id": agreement_data.application_id,
            "property_id": application["property_id"],
            "tenant_id": tenant_id,
            "landlord_id": property["landlord_id"],
            "rent_amount": property["price"],
            "deposit_amount": property.get("security_deposit", property["price"] * 0.5),
            "service_charge": 0,
            "platform_fee": property["price"] * 0.05,  # 5% platform fee
            "lease_start_date": agreement_data.lease_start_date,
            "lease_end_date": agreement_data.lease_end_date,
            "lease_duration": agreement_data.lease_duration,
            "terms": generate_agreement_terms(property, agreement_data),
            "status": "PENDING_TENANT"
        }
        
        response = supabase_admin.table("agreements").insert(agreement_dict).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create agreement"
            )
        
        return response.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create agreement: {str(e)}"
        )


@router.get("/{agreement_id}")
async def get_agreement(
    agreement_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a specific agreement by ID
    Users can only view agreements they are party to
    """
    try:
        response = supabase_admin.table("agreements").select("*").eq(
            "id", agreement_id
        ).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agreement not found"
            )
        
        agreement = response.data[0]
        
        # Check if user is authorized to view this agreement
        if (agreement["tenant_id"] != current_user["id"] and 
            agreement["landlord_id"] != current_user["id"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this agreement"
            )
        
        return agreement
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agreement: {str(e)}"
        )


@router.get("/property/{property_id}")
async def get_property_agreements(
    property_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get all agreements for a specific property
    Only property owner/landlord can view all agreements
    """
    try:
        # Verify user owns the property
        property_response = supabase_admin.table("properties").select("*").eq(
            "id", property_id
        ).eq("landlord_id", current_user["id"]).execute()
        
        if not property_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found or access denied"
            )
        
        response = supabase_admin.table("agreements").select("*").eq(
            "property_id", property_id
        ).order("created_at", desc=True).execute()
        
        return response.data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get property agreements: {str(e)}"
        )


@router.patch("/{agreement_id}/sign")
async def sign_agreement(
    agreement_id: str,
    sign_request: AgreementSignRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Sign a rental agreement
    Both tenant and landlord must sign for agreement to be active
    """
    try:
        # Get agreement
        response = supabase_admin.table("agreements").select("*").eq(
            "id", agreement_id
        ).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agreement not found"
            )
        
        agreement = response.data[0]
        
        # Check if user is authorized to sign this agreement
        if (agreement["tenant_id"] != current_user["id"] and 
            agreement["landlord_id"] != current_user["id"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to sign this agreement"
            )
        
        # Check if already signed
        if current_user["id"] == agreement["tenant_id"] and agreement.get("tenant_signed_at"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already signed this agreement"
            )
        
        if current_user["id"] == agreement["landlord_id"] and agreement.get("landlord_signed_at"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already signed this agreement"
            )
        
        # Update signature
        client_ip = sign_request.ip_address or "unknown"
        update_data = {}
        
        if current_user["id"] == agreement["tenant_id"]:
            update_data["tenant_signed_at"] = datetime.utcnow().isoformat()
            update_data["tenant_signature_ip"] = client_ip
            update_data["status"] = "PENDING_LANDLORD" if not agreement.get("landlord_signed_at") else "SIGNED"
        else:
            update_data["landlord_signed_at"] = datetime.utcnow().isoformat()
            update_data["landlord_signature_ip"] = client_ip
            update_data["status"] = "SIGNED" if agreement.get("tenant_signed_at") else "PENDING_TENANT"
        
        # Update agreement
        update_response = supabase_admin.table("agreements").update(update_data).eq(
            "id", agreement_id
        ).execute()
        
        if not update_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to sign agreement"
            )
        
        updated_agreement = update_response.data[0]
        
        # If both signed, generate PDF document
        if updated_agreement["status"] == "SIGNED":
            generate_agreement_pdf(updated_agreement)
        
        return updated_agreement
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sign agreement: {str(e)}"
        )


@router.get("/my-agreements")
async def get_my_agreements(
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Get all agreements for the current user (as tenant or landlord)
    """
    try:
        # Build query based on user type
        if current_user["user_type"] == "tenant":
            query = supabase_admin.table("agreements").select("*").eq("tenant_id", current_user["id"])
        else:
            query = supabase_admin.table("agreements").select("*").eq("landlord_id", current_user["id"])
        
        # Apply status filter if provided
        if status:
            query = query.eq("status", status)
        
        response = query.order("created_at", desc=True).execute()
        
        return response.data
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agreements: {str(e)}"
        )


@router.post("/{agreement_id}/generate-pdf")
async def generate_pdf(
    agreement_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Generate PDF version of signed agreement
    """
    try:
        # Get agreement
        response = supabase_admin.table("agreements").select("*").eq(
            "id", agreement_id
        ).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agreement not found"
            )
        
        agreement = response.data[0]
        
        # Check authorization
        if (agreement["tenant_id"] != current_user["id"] and 
            agreement["landlord_id"] != current_user["id"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this agreement"
            )
        
        # Check if agreement is signed
        if agreement["status"] != "SIGNED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agreement must be fully signed before generating PDF"
            )
        
        # Generate PDF
        pdf_url = generate_agreement_pdf(agreement)
        
        return {"document_url": pdf_url, "message": "PDF generated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PDF: {str(e)}"
        )


# Helper Functions

def generate_agreement_terms(property, agreement_data):
    """
    Generate standard rental agreement terms
    """
    terms = f"""
    RESIDENTIAL LEASE AGREEMENT
    
    PROPERTY DETAILS:
    Address: {property.get('full_address', property.get('address', 'N/A'))}
    City: {property.get('city', 'N/A')}
    State: {property.get('state', 'N/A')}
    Monthly Rent: ₦{property.get('price', 0):,.2f}
    Security Deposit: ₦{property.get('security_deposit', property.get('price', 0) * 0.5):,.2f}
    Platform Fee: ₦{property.get('price', 0) * 0.05:,.2f}
    
    LEASE TERMS:
    Lease Duration: {agreement_data.lease_duration} months
    Start Date: {agreement_data.lease_start_date}
    End Date: {agreement_data.lease_end_date}
    
    TERMS AND CONDITIONS:
    1. Tenant agrees to pay monthly rent on or before the 1st day of each month
    2. Security deposit will be returned within 30 days of lease termination, minus any damages
    3. Platform fee is non-refundable and covers transaction processing and platform services
    4. All payments will be processed through NuloAfrica platform
    5. Property must be maintained in good condition throughout the lease period
    6. No subletting allowed without written consent from landlord
    7. 30-day notice required for lease termination
    
    This agreement is governed by the laws of Nigeria and any disputes will be resolved
    through NuloAfrica's dispute resolution process.
    
    Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    Agreement ID: {uuid.uuid4()}
    """
    return terms.strip()


def generate_agreement_pdf(agreement):
    """
    Generate PDF document for signed agreement
    This is a placeholder - integrate with PDF generation service
    """
    try:
        # TODO: Integrate with PDF generation service like ReportLab or similar
        pdf_url = f"https://storage.nuloafrica.com/agreements/{agreement['id']}.pdf"
        
        # Update agreement with PDF URL
        supabase_admin.table("agreements").update({
            "document_url": pdf_url
        }).eq("id", agreement["id"]).execute()
        
        return pdf_url
        
    except Exception as e:
        print(f"Failed to generate PDF: {str(e)}")
        return None
