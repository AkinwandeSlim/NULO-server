"""
Agreement Service - Centralized agreement generation and management
Single source of truth for all agreement-related operations
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from app.database import supabase_admin

logger = logging.getLogger(__name__)

class AgreementService:
    """Centralized service for agreement generation and management"""
    
    @staticmethod
    def generate_nigerian_lease_terms(
        application: Dict[str, Any], 
        property_data: Dict[str, Any], 
        lease_data: Dict[str, Any],
        landlord_name: str,
        tenant_name: str,
        tenant_email: str,
        tenant_phone: str
    ) -> str:
        """
        Generate standard Nigerian rental agreement terms
        Single source of truth for agreement content
        """
        terms = f"""
RENTAL AGREEMENT

This Rental Agreement is made on {datetime.now().strftime('%B %d, %Y')}

BETWEEN:
Landlord: {landlord_name}
Property: {property_data.get('title', 'Property')}
Address: {property_data.get('location', 'Address')}

AND:
Tenant: {tenant_name}
Email: {tenant_email}
Phone: {tenant_phone}

PROPERTY DETAILS:
Property ID: {property_data.get('id')}
Monthly Rent: ₦{property_data.get('price', 0):,}
Security Deposit: ₦{property_data.get('price', 0) * 2:,} (2 months' rent)

LEASE TERMS:
Lease Duration: {lease_data.get('lease_duration', 12)} months
Start Date: {lease_data.get('lease_start_date', '').strftime('%B %d, %Y') if isinstance(lease_data.get('lease_start_date'), datetime) else lease_data.get('lease_start_date')}
End Date: {lease_data.get('lease_end_date', '').strftime('%B %d, %Y') if isinstance(lease_data.get('lease_end_date'), datetime) else lease_data.get('lease_end_date')}

FINANCIAL TERMS:
- Monthly Rent: ₦{property_data.get('price', 0):,}
- Security Deposit: ₦{property_data.get('price', 0) * 2:,} (refundable)
- Payment Method: Via NuloAfrica platform
- Payment Schedule: Monthly in advance

TERMS & CONDITIONS:
1. Rent is payable monthly in advance via the NuloAfrica platform
2. Security deposit is refundable subject to property inspection at move-out
3. Tenant shall maintain the property in good condition and repair
4. Landlord shall be responsible for major structural repairs
5. Either party may terminate with 30 days' written notice
6. All payments shall be processed through NuloAfrica escrow system
7. Tenant shall not sublet the property without landlord's written consent
8. Property shall be used for residential purposes only
9. No illegal activities shall be conducted on the premises
10. Tenant shall comply with all building rules and regulations

NIGERIAN CLAUSES:
11. This agreement is governed by the laws of the Federal Republic of Nigeria
12. Any disputes shall be resolved through arbitration in accordance with Nigerian law
13. Utility bills (electricity, water, waste disposal) are tenant's responsibility
14. Property tax and building insurance are landlord's responsibility
15. Tenant shall allow reasonable access for repairs and inspections

This agreement is automatically generated upon application approval.
Both parties must digitally sign to activate the lease.

Signatures below constitute acceptance of all terms and conditions.
"""
        return terms.strip()
    
    @staticmethod
    def calculate_standard_lease_dates() -> Dict[str, Any]:
        """
        Calculate standard Nigerian lease dates (1-year lease starting tomorrow)
        """
        lease_start_date = datetime.now().date() + timedelta(days=1)  # Start tomorrow
        lease_end_date = lease_start_date + timedelta(days=365)  # 1 year later
        lease_duration = 12  # 12 months
        
        return {
            "lease_start_date": lease_start_date.isoformat(),
            "lease_end_date": lease_end_date.isoformat(),
            "lease_duration": lease_duration
        }
    
    @staticmethod
    def create_agreement_dict(
        application_id: str,
        property_id: str,
        tenant_id: str,
        landlord_id: str,
        property_data: Dict[str, Any],
        lease_dates: Dict[str, Any],
        terms: str
    ) -> Dict[str, Any]:
        """
        Create agreement dictionary matching database schema
        Reference: database/newupdatDB.csv - agreements table
        """
        return {
            "application_id": application_id,
            "property_id": property_id,
            "tenant_id": tenant_id,
            "landlord_id": landlord_id,
            "status": "PENDING_TENANT",
            "lease_start_date": lease_dates["lease_start_date"],
            "lease_end_date": lease_dates["lease_end_date"],
            "lease_duration": lease_dates["lease_duration"],
            "rent_amount": property_data.get("price", 0),
            "deposit_amount": property_data.get("price", 0) * 2,  # 2 months deposit (Nigerian standard)
            "platform_fee": 0,  # Calculate based on platform fee structure
            "service_charge": 0,  # Additional service charges
            "terms": terms,
            # Note: created_at and updated_at are auto-managed by database
        }
    
    @staticmethod
    async def auto_generate_agreement(
        application_id: str,
        property_data: Dict[str, Any],
        tenant_data: Dict[str, Any],
        landlord_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Auto-generate agreement for approved application
        Used by applications.py approval flow
        """
        try:
            logger.info(f"🔥 [AGREEMENT SERVICE] Auto-generating agreement for application {application_id}")
            
            # Calculate standard lease dates
            lease_dates = AgreementService.calculate_standard_lease_dates()
            logger.info(f"🔥 [AGREEMENT SERVICE] Lease dates: {lease_dates}")
            
            # Generate agreement terms
            terms = AgreementService.generate_nigerian_lease_terms(
                application={"id": application_id},
                property_data=property_data,
                lease_data=lease_dates,
                landlord_name=landlord_name,
                tenant_name=tenant_data.get('full_name', 'Tenant'),
                tenant_email=tenant_data.get('email', ''),
                tenant_phone=tenant_data.get('phone_number', '')
            )
            
            # Create agreement dictionary
            agreement_dict = AgreementService.create_agreement_dict(
                application_id=application_id,
                property_id=property_data.get("id"),
                tenant_id=tenant_data.get("id"),
                landlord_id=property_data.get("landlord_id"),
                property_data=property_data,
                lease_dates=lease_dates,
                terms=terms
            )
            
            logger.info(f"🔥 [AGREEMENT SERVICE] Agreement dict to insert: {agreement_dict}")
            
            # Insert agreement into database
            agreement_response = supabase_admin.table("agreements").insert(agreement_dict).execute()
            
            logger.info(f"🔥 [AGREEMENT SERVICE] Agreement insert response: {agreement_response}")
            
            if agreement_response.data:
                agreement_id = agreement_response.data[0]['id']
                logger.info(f"✅ [AGREEMENT SERVICE] Auto-generated agreement {agreement_id} for application {application_id}")
                return agreement_response.data[0]
            else:
                logger.error(f"❌ [AGREEMENT SERVICE] Failed to insert agreement: {agreement_response}")
                return None
                
        except Exception as e:
            logger.error(f"❌ [AGREEMENT SERVICE] Error auto-generating agreement: {str(e)}")
            return None
    
    @staticmethod
    async def create_manual_agreement(
        agreement_data: Dict[str, Any],
        current_user: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Create agreement manually (for direct API calls)
        Used by agreements.py create endpoint
        """
        try:
            logger.info(f"🔥 [AGREEMENT SERVICE] Creating manual agreement for application {agreement_data.get('application_id')}")
            
            tenant_id = current_user["id"]
            
            # Verify application exists and belongs to current user
            app_response = supabase_admin.table("applications").select("*").eq(
                "id", agreement_data.get("application_id")
            ).eq("user_id", tenant_id).eq("status", "approved").single().execute()
            
            if not app_response.data:
                logger.warning(f"❌ [AGREEMENT SERVICE] Approved application not found: {agreement_data.get('application_id')} for tenant {tenant_id}")
                return None
            
            application = app_response.data
            
            # Get property details
            property_response = supabase_admin.table("properties").select("*").eq(
                "id", application["property_id"]
            ).single().execute()
            
            if not property_response.data:
                logger.error(f"❌ [AGREEMENT SERVICE] Property not found: {application['property_id']}")
                return None
            
            property_data = property_response.data
            
            # Generate lease dates from provided data
            lease_dates = {
                "lease_start_date": agreement_data.get("lease_start_date"),
                "lease_end_date": agreement_data.get("lease_end_date"),
                "lease_duration": agreement_data.get("lease_duration")
            }
            
            # Generate agreement terms
            terms = AgreementService.generate_nigerian_lease_terms(
                application=application,
                property_data=property_data,
                lease_data=lease_dates,
                landlord_name="Landlord",  # Will be fetched from property
                tenant_name=current_user.get("full_name", "Tenant"),
                tenant_email=current_user.get("email", ""),
                tenant_phone=current_user.get("phone_number", "")
            )
            
            # Create agreement dictionary
            agreement_dict = AgreementService.create_agreement_dict(
                application_id=agreement_data.get("application_id"),
                property_id=property_data.get("id"),
                tenant_id=tenant_id,
                landlord_id=property_data.get("landlord_id"),
                property_data=property_data,
                lease_dates=lease_dates,
                terms=terms
            )
            
            # Insert agreement
            agreement_response = supabase_admin.table("agreements").insert(agreement_dict).execute()
            
            if agreement_response.data:
                logger.info(f"✅ [AGREEMENT SERVICE] Manual agreement created: {agreement_response.data[0]['id']}")
                return agreement_response.data[0]
            else:
                logger.error(f"❌ [AGREEMENT SERVICE] Failed to create manual agreement")
                return None
                
        except Exception as e:
            logger.error(f"❌ [AGREEMENT SERVICE] Error creating manual agreement: {str(e)}")
            return None
    
    @staticmethod
    async def sign_agreement(
        agreement_id: str,
        user_id: str,
        user_type: str,
        ip_address: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Sign agreement (tenant or landlord)
        """
        try:
            logger.info(f"🔥 [AGREEMENT SERVICE] Signing agreement {agreement_id} by {user_type} {user_id}")
            
            # Get current agreement
            agreement_response = supabase_admin.table("agreements").select("*").eq(
                "id", agreement_id
            ).single().execute()
            
            if not agreement_response.data:
                logger.error(f"❌ [AGREEMENT SERVICE] Agreement not found: {agreement_id}")
                return None
            
            agreement = agreement_response.data
            
            # Verify user owns this agreement
            if user_type == "tenant" and agreement["tenant_id"] != user_id:
                logger.error(f"❌ [AGREEMENT SERVICE] Tenant {user_id} does not own agreement {agreement_id}")
                return None
            
            if user_type == "landlord" and agreement["landlord_id"] != user_id:
                logger.error(f"❌ [AGREEMENT SERVICE] Landlord {user_id} does not own agreement {agreement_id}")
                return None
            
            # Update signature
            update_data = {}
            if user_type == "tenant":
                update_data = {
                    "tenant_signed_at": datetime.now().isoformat(),
                    "tenant_signature_ip": ip_address
                }
            else:  # landlord
                update_data = {
                    "landlord_signed_at": datetime.now().isoformat(),
                    "landlord_signature_ip": ip_address
                }
            
            # Check if both parties have signed
            if agreement.get("landlord_signed_at") and user_type == "tenant":
                update_data["status"] = "SIGNED"
            elif agreement.get("tenant_signed_at") and user_type == "landlord":
                update_data["status"] = "SIGNED"
            
            # Update agreement
            update_response = supabase_admin.table("agreements").update(update_data).eq(
                "id", agreement_id
            ).execute()
            
            if update_response.data:
                logger.info(f"✅ [AGREEMENT SERVICE] Agreement {agreement_id} signed by {user_type}")
                return update_response.data[0]
            else:
                logger.error(f"❌ [AGREEMENT SERVICE] Failed to sign agreement {agreement_id}")
                return None
                
        except Exception as e:
            logger.error(f"❌ [AGREEMENT SERVICE] Error signing agreement: {str(e)}")
            return None

# Create singleton instance
agreement_service = AgreementService()
