"""
Agreements API - Rental Agreement Management
Handles creation, signing, and management of rental agreements
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from datetime import date, datetime

from ..database import get_db
from ..models.agreement import (
    Agreement, AgreementCreate, AgreementResponse, 
    AgreementSignRequest, AgreementStatus
)
from ..dependencies.auth import get_current_user
from ..models.user import User

router = APIRouter(prefix="/api/v1/agreements", tags=["agreements"])

@router.post("/", response_model=AgreementResponse)
async def create_agreement(
    agreement_data: AgreementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new rental agreement from an approved application
    Only tenants can create agreements for their approved applications
    """
    try:
        # Verify application exists and belongs to current user
        from ..models.application import Application
        application = db.query(Application).filter(
            Application.id == agreement_data.application_id,
            Application.tenant_id == current_user.id,
            Application.status == "ACCEPTED"
        ).first()
        
        if not application:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approved application not found"
            )
        
        # Check if agreement already exists
        existing_agreement = db.query(Agreement).filter(
            Agreement.application_id == agreement_data.application_id
        ).first()
        
        if existing_agreement:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agreement already exists for this application"
            )
        
        # Get property details
        from ..models.property import Property
        property = db.query(Property).filter(Property.id == application.property_id).first()
        if not property:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        # Create agreement
        agreement = Agreement(
            application_id=agreement_data.application_id,
            property_id=application.property_id,
            tenant_id=current_user.id,
            landlord_id=property.landlord_id,
            rent_amount=property.price,
            deposit_amount=property.security_deposit or (property.price * 0.5),
            service_charge=0,  # Can be configured per property
            platform_fee=property.price * 0.05,  # 5% platform fee
            lease_start_date=agreement_data.lease_start_date,
            lease_end_date=agreement_data.lease_end_date,
            lease_duration=agreement_data.lease_duration,
            terms=generate_agreement_terms(property, agreement_data),
            status="PENDING_TENANT"
        )
        
        db.add(agreement)
        db.commit()
        db.refresh(agreement)
        
        return agreement
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create agreement: {str(e)}"
        )

@router.get("/{agreement_id}", response_model=AgreementResponse)
async def get_agreement(
    agreement_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific agreement by ID
    Users can only view agreements they are party to
    """
    agreement = db.query(Agreement).filter(
        Agreement.id == agreement_id
    ).first()
    
    if not agreement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agreement not found"
        )
    
    # Check if user is authorized to view this agreement
    if (agreement.tenant_id != current_user.id and 
        agreement.landlord_id != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this agreement"
        )
    
    return agreement

@router.get("/property/{property_id}", response_model=List[AgreementResponse])
async def get_property_agreements(
    property_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all agreements for a specific property
    Only property owner/landlord can view all agreements
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
    
    agreements = db.query(Agreement).filter(
        Agreement.property_id == property_id
    ).order_by(Agreement.created_at.desc()).all()
    
    return agreements

@router.patch("/{agreement_id}/sign", response_model=AgreementResponse)
async def sign_agreement(
    agreement_id: uuid.UUID,
    sign_request: AgreementSignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Sign a rental agreement
    Both tenant and landlord must sign for agreement to be active
    """
    agreement = db.query(Agreement).filter(
        Agreement.id == agreement_id
    ).first()
    
    if not agreement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agreement not found"
        )
    
    # Check if user is authorized to sign this agreement
    if (agreement.tenant_id != current_user.id and 
        agreement.landlord_id != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to sign this agreement"
        )
    
    # Check if already signed
    if current_user.id == agreement.tenant_id and agreement.tenant_signed_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already signed this agreement"
        )
    
    if current_user.id == agreement.landlord_id and agreement.landlord_signed_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already signed this agreement"
        )
    
    # Update signature
    client_ip = sign_request.ip_address or "unknown"
    
    if current_user.id == agreement.tenant_id:
        agreement.tenant_signed_at = datetime.utcnow()
        agreement.tenant_signature_ip = client_ip
        agreement.status = "PENDING_LANDLORD" if not agreement.landlord_signed_at else "SIGNED"
    else:
        agreement.landlord_signed_at = datetime.utcnow()
        agreement.landlord_signature_ip = client_ip
        agreement.status = "SIGNED" if agreement.tenant_signed_at else "PENDING_TENANT"
    
    db.commit()
    db.refresh(agreement)
    
    # If both signed, generate PDF document
    if agreement.status == "SIGNED":
        generate_agreement_pdf(agreement, db)
    
    return agreement

@router.get("/my-agreements", response_model=List[AgreementResponse])
async def get_my_agreements(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all agreements for the current user (as tenant or landlord)
    """
    query = db.query(Agreement)
    
    # Filter by user role
    if current_user.user_type == "tenant":
        query = query.filter(Agreement.tenant_id == current_user.id)
    else:
        query = query.filter(Agreement.landlord_id == current_user.id)
    
    # Filter by status if provided
    if status:
        query = query.filter(Agreement.status == status)
    
    agreements = query.order_by(Agreement.created_at.desc()).all()
    
    return agreements

@router.post("/{agreement_id}/generate-pdf")
async def generate_pdf(
    agreement_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Generate PDF version of signed agreement
    """
    agreement = db.query(Agreement).filter(
        Agreement.id == agreement_id
    ).first()
    
    if not agreement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agreement not found"
        )
    
    # Check authorization
    if (agreement.tenant_id != current_user.id and 
        agreement.landlord_id != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this agreement"
        )
    
    # Check if agreement is signed
    if agreement.status != "SIGNED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agreement must be fully signed before generating PDF"
        )
    
    # Generate PDF
    pdf_url = generate_agreement_pdf(agreement, db)
    
    return {"document_url": pdf_url, "message": "PDF generated successfully"}

# Helper Functions

def generate_agreement_terms(property, agreement_data):
    """
    Generate standard rental agreement terms
    """
    terms = f"""
    RESIDENTIAL LEASE AGREEMENT
    
    PROPERTY DETAILS:
    Address: {property.full_address or property.address}
    City: {property.city}
    State: {property.state}
    Monthly Rent: ₦{property.price:,.2f}
    Security Deposit: ₦{(property.security_deposit or property.price * 0.5):,.2f}
    Platform Fee: ₦{property.price * 0.05:,.2f}
    
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

def generate_agreement_pdf(agreement, db):
    """
    Generate PDF document for signed agreement
    This is a placeholder - integrate with PDF generation service
    """
    try:
        # TODO: Integrate with PDF generation service like ReportLab or similar
        pdf_url = f"https://storage.nuloafrica.com/agreements/{agreement.id}.pdf"
        
        # Update agreement with PDF URL
        agreement.document_url = pdf_url
        db.commit()
        
        return pdf_url
        
    except Exception as e:
        print(f"Failed to generate PDF: {str(e)}")
        return None
