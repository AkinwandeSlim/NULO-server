"""
Agreement Service - ENHANCED with Seamless AI Integration
=========================================================

INTEGRATION STRATEGY:
- Single agreement generation (not two different ones)
- AI enhances the existing template when available
- Graceful fallback to manual template when AI fails
- Consistent user experience regardless of AI availability
- Backward compatibility maintained

KEY CHANGE:
- "terms" field always contains the BEST available agreement
- No more confusion between "terms" and "ai_content"
- Frontend always shows one consistent agreement
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from app.database import supabase_admin

logger = logging.getLogger(__name__)

class AgreementService:
    """Centralized service for agreement generation and management"""

    @staticmethod
    def derive_effective_status(agreement: Optional[Dict[str, Any]]) -> str:
        """Normalize agreement state from signature timestamps when the DB status is stale."""
        if not agreement:
            return "PENDING_TENANT"

        raw_status = str(agreement.get("status") or "").upper()
        tenant_signed = bool(agreement.get("tenant_signed_at"))
        landlord_signed = bool(agreement.get("landlord_signed_at"))

        if raw_status in {"TERMINATED", "EXPIRED", "CANCELLED", "CANCELED"}:
            return raw_status

        if tenant_signed and landlord_signed:
            if raw_status in {"ACTIVE", "SIGNED"}:
                return raw_status
            return "SIGNED"

        if tenant_signed and not landlord_signed:
            return "PENDING_LANDLORD"

        if landlord_signed and not tenant_signed:
            return "PENDING_TENANT"

        if raw_status in {"ACTIVE", "SIGNED"}:
            return raw_status

        if raw_status in {"PENDING_LANDLORD", "PENDING_TENANT", "PENDING"}:
            return raw_status

        return raw_status or "PENDING_TENANT"
    
    @staticmethod
    async def generate_enhanced_agreement_terms(
        property_data: Dict[str, Any],
        tenant_data: Dict[str, Any],
        landlord_name: str,
        lease_dates: Dict[str, Any],
        application: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        ENHanced agreement generation - AI first, seamless fallback.
        Returns: { terms, source, metadata }
        
        STRATEGY:
        - Try AI generation first (rich, professional agreement)
        - If AI fails, use enhanced manual template
        - Always return ONE agreement in "terms" field
        - Track source for analytics and debugging
        """
        terms = None
        source = "manual_template"
        metadata = {}

        # Try AI generation first for the best agreement
        try:
            from app.services.ai.ai_service import ai_service
            
            logger.info(f"🤖 [AGREEMENT SERVICE] Attempting AI generation for {tenant_data.get('full_name', 'Tenant')}")
            
            ai_result = await ai_service.generate_agreement(
                tenant_name=tenant_data.get("full_name", "Tenant"),
                landlord_name=landlord_name,
                property_address=property_data.get(
                    "full_address", 
                    property_data.get("address", 
                    property_data.get("location", ""))
                ),
                monthly_rent=int(property_data.get("price", 0)),
                lease_duration=f"{lease_dates.get('lease_duration', 12)} months",
                property_type=property_data.get("property_type", "Apartment")
            )
            
            if ai_result["success"]:
                terms = ai_result["agreement"]
                source = "groq_llama"
                metadata = {
                    "model_used": ai_result.get("model_used"),
                    "tokens_used": ai_result.get("tokens_used"),
                    "compliance_score": ai_result.get("compliance_score"),
                    "generation_time_seconds": ai_result.get("generation_time_seconds"),
                    "cost_usd": ai_result.get("cost_usd"),
                    "generated_at": datetime.now().isoformat()
                }
                logger.info(f"✅ [AGREEMENT SERVICE] AI agreement generated "
                           f"({ai_result.get('tokens_used')} tokens, {ai_result.get('compliance_score', 0):.1f}% compliance)")
            else:
                logger.warning(f"⚠️ [AGREEMENT SERVICE] AI generation failed: {ai_result.get('error')}")
                
        except Exception as e:
            logger.warning(f"⚠️ [AGREEMENT SERVICE] AI unavailable: {e}")

        # If AI failed, generate enhanced manual template
        if not terms:
            logger.info(f"📋 [AGREEMENT SERVICE] Using enhanced manual template")
            terms = AgreementService.generate_enhanced_manual_terms(
                application=application or {},
                property_data=property_data,
                lease_data=lease_dates,
                landlord_name=landlord_name,
                tenant_name=tenant_data.get("full_name", "Tenant"),
                tenant_email=tenant_data.get("email", ""),
                tenant_phone=tenant_data.get("phone_number", ""),
                tenant_address=tenant_data.get("address", "Tenant Address to be provided")
            )
            source = "manual_template"
            metadata = {
                "generated_at": datetime.now().isoformat(),
                "template_version": "enhanced_v2"
            }

        return {
            "terms": terms,                    # SINGLE agreement field
            "source": source,                  # "groq_llama" or "manual_template"
            "metadata": metadata               # generation metadata
        }
    
    @staticmethod
    def generate_enhanced_manual_terms(
        application: Dict[str, Any], 
        property_data: Dict[str, Any], 
        lease_data: Dict[str, Any],
        landlord_name: str,
        tenant_name: str,
        tenant_email: str,
        tenant_phone: str,
        tenant_address: str = "Tenant Address to be provided"
    ) -> str:
        """
        Enhanced manual template - better than original, closer to AI quality
        This is the fallback when AI is not available
        """
        terms = f"""
TENANCY AGREEMENT

This Tenancy Agreement is made on this {datetime.now().strftime('%dth day of %B, %Y')}

BETWEEN:
LANDLORD
- Full Name: {landlord_name}
- Address: [Landlord Address to be provided]
- Phone: [Landlord Phone to be provided]
- Email: [Landlord Email to be provided]

AND:
TENANT
- Full Name: {tenant_name}
- Address: {tenant_address}
- Phone: {tenant_phone}
- Email: {tenant_email}

PROPERTY DETAILS:
- Property Address: {property_data.get('full_address', property_data.get('location', 'Property Address'))}
- Property Type: {property_data.get('property_type', 'Residential Property')}
- Property ID: {property_data.get('id', 'N/A')}
- Use: Residential purposes only

LEASE TERMS:
- Lease Duration: {lease_data.get('lease_duration', 12)} months
- Start Date: {lease_data.get('lease_start_date', '').strftime('%B %d, %Y') if isinstance(lease_data.get('lease_start_date'), datetime) else lease_data.get('lease_start_date', 'To be determined')}
- End Date: {lease_data.get('lease_end_date', '').strftime('%B %d, %Y') if isinstance(lease_data.get('lease_end_date'), datetime) else lease_data.get('lease_end_date', 'To be determined')}

FINANCIAL TERMS:
- Monthly Rent: ₦{property_data.get('price', 0):,}
- Annual Rent: ₦{property_data.get('price', 0) * 12:,}
- Security Deposit: ₦{property_data.get('price', 0) * 2:,} (equivalent to 2 months' rent)
- Payment Method: Via NuloAfrica platform
- Payment Schedule: Monthly in advance
- Payment Due: On or before the 1st day of each month

TERMS AND CONDITIONS:

1. RENT PAYMENT
   - Rent shall be paid monthly in advance through the NuloAfrica platform
   - Late payment shall attract a penalty of 5% of the monthly rent
   - All payments are subject to NuloAfrica's escrow protection

2. SECURITY DEPOSIT
   - Security deposit is refundable subject to property inspection at move-out
   - Deposit will be returned within 30 days of lease termination
   - Deductions may be made for damages beyond normal wear and tear

3. PROPERTY MAINTENANCE
   - Tenant shall maintain the property in good condition and repair
   - Tenant is responsible for minor repairs and maintenance
   - Landlord shall be responsible for major structural repairs

4. PROPERTY USE
   - Property shall be used for residential purposes only
   - No commercial activities shall be conducted on the premises
   - No illegal activities shall be permitted on the property

5. ACCESS AND INSPECTION
   - Landlord shall have reasonable access for repairs and inspections
   - 24-hour notice shall be given for non-emergency access
   - Emergency access is permitted without notice

6. TERMINATION CLAUSE
   - Either party may terminate with 30 days' written notice
   - Tenant terminating before lease end forfeits security deposit
   - Landlord terminating before lease end provides 30 days rent refund

7. ASSIGNMENT AND SUBLETTING
   - Tenant shall not sublet the property without landlord's written consent
   - Assignment of lease requires prior written approval from landlord

8. UTILITIES AND SERVICES
   - Tenant shall pay for electricity, water, and waste disposal
   - Landlord shall pay property tax and building insurance
   - Service charges (if applicable) shall be paid by tenant

9. COMPLIANCE WITH LAWS
   - This agreement is governed by the laws of the Federal Republic of Nigeria
   - Lagos Tenancy Law 2011 compliance is acknowledged by both parties
   - Any disputes shall be resolved through arbitration in accordance with Nigerian law

10. DEFAULT AND REMEDIES
    - Rent arrears exceeding 30 days constitute default
    - Landlord may terminate agreement for persistent default
    - Tenant may withhold rent for major breaches by landlord

11. FORCE MAJEURE
    - Neither party shall be liable for breaches due to force majeure events
    - Government actions affecting property use shall be considered force majeure

12. ENTIRE AGREEMENT
    - This agreement constitutes the entire understanding between parties
    - No verbal agreements or modifications shall be recognized
    - Changes must be in writing and signed by both parties

SIGNATURES:

This agreement is automatically generated upon application approval.
Both parties must digitally sign to activate the lease.

LANDLORD:
_________________________
{landlord_name}
Date: _________________

TENANT:
_________________________
{tenant_name}
Date: _________________

WITNESSED BY:
_________________________
Witness Name
Date: _________________

NOTICE: This is a legally binding agreement. Read carefully before signing.
Generated via NuloAfrica Platform - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return terms.strip()
    
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
        Legacy method - kept for backward compatibility
        DEPRECATED: Use generate_enhanced_agreement_terms() instead
        """
        logger.warning("⚠️ [AGREEMENT SERVICE] Using deprecated generate_nigerian_lease_terms() method")
        
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
        """Calculate standard Nigerian lease dates (1-year lease starting tomorrow)"""
        lease_start_date = datetime.now().date() + timedelta(days=1)
        lease_end_date = lease_start_date + timedelta(days=365)
        lease_duration = 12
        
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
        Enhanced with AI tracking fields
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
            "deposit_amount": 0,  # MVP: Caution fee set to 0 for transparency
            "platform_fee": 0,  # MVP: Platform fee set to 0% for transparency
            "service_charge": 0,
            "payment_frequency": property_data.get("payment_frequency", "MONTHLY"),
            "terms": terms,
            "agreement_source": "manual_template",  # Updated after generation
            "generation_metadata": {},             # Updated after generation
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
        Enhanced with seamless AI integration
        """
        try:
            logger.info(f"🔥 [AGREEMENT SERVICE] Auto-generating enhanced agreement for application {application_id}")
            
            # Calculate standard lease dates
            lease_dates = AgreementService.calculate_standard_lease_dates()
            
            # Generate enhanced agreement terms (AI first, fallback to template)
            terms_result = await AgreementService.generate_enhanced_agreement_terms(
                property_data=property_data,
                tenant_data=tenant_data,
                landlord_name=landlord_name,
                lease_dates=lease_dates,
                application={"id": application_id}
            )
            
            # Create agreement dictionary
            agreement_dict = AgreementService.create_agreement_dict(
                application_id=application_id,
                property_id=property_data.get("id"),
                tenant_id=tenant_data.get("id"),
                landlord_id=property_data.get("landlord_id"),
                property_data=property_data,
                lease_dates=lease_dates,
                terms=terms_result["terms"]
            )
            
            # Add generation metadata
            agreement_dict["agreement_source"] = terms_result["source"]
            agreement_dict["generation_metadata"] = terms_result["metadata"]
            
            logger.info(f"🔥 [AGREEMENT SERVICE] Inserting enhanced agreement (source: {terms_result['source']})")
            
            # Insert agreement into database
            agreement_response = supabase_admin.table("agreements").insert(agreement_dict).execute()
            
            if agreement_response.data:
                agreement_id = agreement_response.data[0]['id']
                logger.info(f"✅ [AGREEMENT SERVICE] Enhanced agreement {agreement_id} created ({terms_result['source']})")
                return agreement_response.data[0]
            else:
                logger.error(f"❌ [AGREEMENT SERVICE] Failed to insert agreement: {agreement_response}")
                return None
                
        except Exception as e:
            logger.error(f"❌ [AGREEMENT SERVICE] Error auto-generating enhanced agreement: {str(e)}")
            return None
    
    @staticmethod
    async def create_manual_agreement(
        agreement_data: Dict[str, Any],
        current_user: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Create agreement manually with enhanced AI integration
        """
        try:
            logger.info(f"🔥 [AGREEMENT SERVICE] Creating enhanced manual agreement")
            
            tenant_id = current_user["id"]
            
            # Verify application exists and belongs to current user
            app_response = supabase_admin.table("applications").select("*").eq(
                "id", agreement_data.get("application_id")
            ).eq("user_id", tenant_id).eq("status", "approved").single().execute()
            
            if not app_response.data:
                logger.warning(f"❌ [AGREEMENT SERVICE] Approved application not found: {agreement_data.get('application_id')}")
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
            
            # Generate enhanced agreement terms
            terms_result = await AgreementService.generate_enhanced_agreement_terms(
                property_data=property_data,
                tenant_data=current_user,
                landlord_name="Landlord",  # Will be fetched from property
                lease_dates=lease_dates,
                application=application
            )
            
            # Create agreement dictionary
            agreement_dict = AgreementService.create_agreement_dict(
                application_id=agreement_data.get("application_id"),
                property_id=property_data.get("id"),
                tenant_id=tenant_id,
                landlord_id=property_data.get("landlord_id"),
                property_data=property_data,
                lease_dates=lease_dates,
                terms=terms_result["terms"]
            )
            
            # Add generation metadata
            agreement_dict["agreement_source"] = terms_result["source"]
            agreement_dict["generation_metadata"] = terms_result["metadata"]
            
            # Insert agreement
            agreement_response = supabase_admin.table("agreements").insert(agreement_dict).execute()
            
            if agreement_response.data:
                logger.info(f"✅ [AGREEMENT SERVICE] Enhanced manual agreement created ({terms_result['source']})")
                return agreement_response.data[0]
            else:
                logger.error(f"❌ [AGREEMENT SERVICE] Failed to create manual agreement")
                return None
                
        except Exception as e:
            logger.error(f"❌ [AGREEMENT SERVICE] Error creating enhanced manual agreement: {str(e)}")
            return None
    
    @staticmethod
    async def sign_agreement(
        agreement_id: str,
        user_id: str,
        user_type: str,
        ip_address: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Sign agreement (tenant or landlord) - unchanged"""
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
            
            # Update signature and status based on signing flow
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

            merged_agreement = {**agreement, **update_data}
            update_data["status"] = AgreementService.derive_effective_status(merged_agreement)
            
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



















































# """
# Agreement Service - Centralized agreement generation and management
# Single source of truth for all agreement-related operations
# Enhanced with Groq AI integration and manual template fallback
# """

# import logging
# from datetime import datetime, timedelta
# from typing import Dict, Any, Optional
# from app.database import supabase_admin

# logger = logging.getLogger(__name__)

# class AgreementService:
#     """Centralized service for agreement generation and management"""
    
#     @staticmethod
#     async def generate_agreement_terms(
#         property_data: Dict[str, Any],
#         tenant_data: Dict[str, Any],
#         landlord_name: str,
#         lease_dates: Dict[str, Any],
#         application: Dict[str, Any] = None
#     ) -> Dict[str, Any]:
#         """
#         Smart agreement generation — tries AI first, falls back to template.
#         Returns: { terms, ai_content, ai_source, ai_metadata }
#         """
#         ai_content = None
#         ai_source = "manual_template"
#         ai_metadata = {}

#         # Try AI generation first
#         try:
#             from app.services.ai.ai_service import ai_service
            
#             ai_result = await ai_service.generate_agreement(
#                 tenant_name=tenant_data.get("full_name", "Tenant"),
#                 landlord_name=landlord_name,
#                 property_address=property_data.get(
#                     "full_address", 
#                     property_data.get("address", 
#                     property_data.get("location", ""))
#                 ),
#                 monthly_rent=int(property_data.get("price", 0)),
#                 lease_duration=f"{lease_dates.get('lease_duration', 12)} months",
#                 property_type=property_data.get("property_type", "Apartment")
#             )
            
#             if ai_result["success"]:
#                 ai_content = ai_result["agreement"]
#                 ai_source = "groq_llama"
#                 ai_metadata = {
#                     "model_used": ai_result.get("model_used"),
#                     "tokens_used": ai_result.get("tokens_used"),
#                     "compliance_score": ai_result.get("compliance_score"),
#                     "generated_at": datetime.now().isoformat()
#                 }
#                 logger.info(f"✅ [AGREEMENT SERVICE] AI terms generated "
#                            f"({ai_result.get('tokens_used')} tokens)")
#             else:
#                 logger.warning(f"⚠️ [AGREEMENT SERVICE] AI generation failed, "
#                               f"using template: {ai_result.get('error')}")
                
#         except Exception as e:
#             logger.warning(f"⚠️ [AGREEMENT SERVICE] AI unavailable, "
#                           f"using template: {e}")

#         # Always generate manual template as the base "terms" field
#         # (keeps backward compatibility with existing frontend + PDF generation)
#         manual_terms = AgreementService.generate_nigerian_lease_terms(
#             application=application or {},
#             property_data=property_data,
#             lease_data=lease_dates,
#             landlord_name=landlord_name,
#             tenant_name=tenant_data.get("full_name", "Tenant"),
#             tenant_email=tenant_data.get("email", ""),
#             tenant_phone=tenant_data.get("phone_number", "")
#         )

#         return {
#             "terms": manual_terms,           # existing field — always populated
#             "ai_content": ai_content,        # new field — None if AI failed
#             "ai_source": ai_source,          # "groq_llama" or "manual_template"
#             "ai_metadata": ai_metadata       # tokens, model, score etc.
#         }
    
#     @staticmethod
#     def generate_nigerian_lease_terms(
#         application: Dict[str, Any], 
#         property_data: Dict[str, Any], 
#         lease_data: Dict[str, Any],
#         landlord_name: str,
#         tenant_name: str,
#         tenant_email: str,
#         tenant_phone: str
#     ) -> str:
#         """
#         Generate standard Nigerian rental agreement terms
#         Single source of truth for agreement content
#         """
#         terms = f"""
# RENTAL AGREEMENT

# This Rental Agreement is made on {datetime.now().strftime('%B %d, %Y')}

# BETWEEN:
# Landlord: {landlord_name}
# Property: {property_data.get('title', 'Property')}
# Address: {property_data.get('location', 'Address')}

# AND:
# Tenant: {tenant_name}
# Email: {tenant_email}
# Phone: {tenant_phone}

# PROPERTY DETAILS:
# Property ID: {property_data.get('id')}
# Monthly Rent: ₦{property_data.get('price', 0):,}
# Security Deposit: ₦{property_data.get('price', 0) * 2:,} (2 months' rent)

# LEASE TERMS:
# Lease Duration: {lease_data.get('lease_duration', 12)} months
# Start Date: {lease_data.get('lease_start_date', '').strftime('%B %d, %Y') if isinstance(lease_data.get('lease_start_date'), datetime) else lease_data.get('lease_start_date')}
# End Date: {lease_data.get('lease_end_date', '').strftime('%B %d, %Y') if isinstance(lease_data.get('lease_end_date'), datetime) else lease_data.get('lease_end_date')}

# FINANCIAL TERMS:
# - Monthly Rent: ₦{property_data.get('price', 0):,}
# - Security Deposit: ₦{property_data.get('price', 0) * 2:,} (refundable)
# - Payment Method: Via NuloAfrica platform
# - Payment Schedule: Monthly in advance

# TERMS & CONDITIONS:
# 1. Rent is payable monthly in advance via the NuloAfrica platform
# 2. Security deposit is refundable subject to property inspection at move-out
# 3. Tenant shall maintain the property in good condition and repair
# 4. Landlord shall be responsible for major structural repairs
# 5. Either party may terminate with 30 days' written notice
# 6. All payments shall be processed through NuloAfrica escrow system
# 7. Tenant shall not sublet the property without landlord's written consent
# 8. Property shall be used for residential purposes only
# 9. No illegal activities shall be conducted on the premises
# 10. Tenant shall comply with all building rules and regulations

# NIGERIAN CLAUSES:
# 11. This agreement is governed by the laws of the Federal Republic of Nigeria
# 12. Any disputes shall be resolved through arbitration in accordance with Nigerian law
# 13. Utility bills (electricity, water, waste disposal) are tenant's responsibility
# 14. Property tax and building insurance are landlord's responsibility
# 15. Tenant shall allow reasonable access for repairs and inspections

# This agreement is automatically generated upon application approval.
# Both parties must digitally sign to activate the lease.

# Signatures below constitute acceptance of all terms and conditions.
# """
#         return terms.strip()
    
#     @staticmethod
#     def calculate_standard_lease_dates() -> Dict[str, Any]:
#         """
#         Calculate standard Nigerian lease dates (1-year lease starting tomorrow)
#         """
#         lease_start_date = datetime.now().date() + timedelta(days=1)  # Start tomorrow
#         lease_end_date = lease_start_date + timedelta(days=365)  # 1 year later
#         lease_duration = 12  # 12 months
        
#         return {
#             "lease_start_date": lease_start_date.isoformat(),
#             "lease_end_date": lease_end_date.isoformat(),
#             "lease_duration": lease_duration
#         }
    
#     @staticmethod
#     def create_agreement_dict(
#         application_id: str,
#         property_id: str,
#         tenant_id: str,
#         landlord_id: str,
#         property_data: Dict[str, Any],
#         lease_dates: Dict[str, Any],
#         terms: str
#     ) -> Dict[str, Any]:
#         """
#         Create agreement dictionary matching database schema
#         Reference: database/newupdatDB.csv - agreements table
#         """
#         return {
#             "application_id": application_id,
#             "property_id": property_id,
#             "tenant_id": tenant_id,
#             "landlord_id": landlord_id,
#             "status": "PENDING_TENANT",
#             "lease_start_date": lease_dates["lease_start_date"],
#             "lease_end_date": lease_dates["lease_end_date"],
#             "lease_duration": lease_dates["lease_duration"],
#             "rent_amount": property_data.get("price", 0),
#             "deposit_amount": property_data.get("price", 0) * 2,  # 2 months deposit (Nigerian standard)
#             "platform_fee": 0,  # Calculate based on platform fee structure
#             "service_charge": 0,  # Additional service charges
#             "terms": terms,
#             "ai_agreement_content": None,   # populated after AI generation
#             "ai_source": "manual_template", # updated after generation
#             "ai_metadata": {},              # updated after generation
#             # Note: created_at and updated_at are auto-managed by database
#         }
    
#     @staticmethod
#     async def auto_generate_agreement(
#         application_id: str,
#         property_data: Dict[str, Any],
#         tenant_data: Dict[str, Any],
#         landlord_name: str
#     ) -> Optional[Dict[str, Any]]:
#         """
#         Auto-generate agreement for approved application
#         Used by applications.py approval flow
#         """
#         try:
#             logger.info(f"🔥 [AGREEMENT SERVICE] Auto-generating agreement for application {application_id}")
            
#             # Calculate standard lease dates
#             lease_dates = AgreementService.calculate_standard_lease_dates()
#             logger.info(f"🔥 [AGREEMENT SERVICE] Lease dates: {lease_dates}")
            
#             # Generate agreement terms with AI integration
#             terms_result = await AgreementService.generate_agreement_terms(
#                 property_data=property_data,
#                 tenant_data=tenant_data,
#                 landlord_name=landlord_name,
#                 lease_dates=lease_dates,
#                 application={"id": application_id}
#             )
            
#             # Create agreement dictionary
#             agreement_dict = AgreementService.create_agreement_dict(
#                 application_id=application_id,
#                 property_id=property_data.get("id"),
#                 tenant_id=tenant_data.get("id"),
#                 landlord_id=property_data.get("landlord_id"),
#                 property_data=property_data,
#                 lease_dates=lease_dates,
#                 terms=terms_result["terms"]
#             )
            
#             # Add AI fields to agreement dict
#             agreement_dict["ai_agreement_content"] = terms_result["ai_content"]
#             agreement_dict["ai_source"] = terms_result["ai_source"]
#             agreement_dict["ai_metadata"] = terms_result["ai_metadata"]
            
#             logger.info(f"🔥 [AGREEMENT SERVICE] Agreement dict to insert: {agreement_dict}")
            
#             # Insert agreement into database
#             agreement_response = supabase_admin.table("agreements").insert(agreement_dict).execute()
            
#             logger.info(f"🔥 [AGREEMENT SERVICE] Agreement insert response: {agreement_response}")
            
#             if agreement_response.data:
#                 agreement_id = agreement_response.data[0]['id']
#                 ai_status = "AI" if terms_result["ai_content"] else "Template"
#                 logger.info(f"✅ [AGREEMENT SERVICE] Auto-generated agreement {agreement_id} for application {application_id} ({ai_status})")
#                 return agreement_response.data[0]
#             else:
#                 logger.error(f"❌ [AGREEMENT SERVICE] Failed to insert agreement: {agreement_response}")
#                 return None
                
#         except Exception as e:
#             logger.error(f"❌ [AGREEMENT SERVICE] Error auto-generating agreement: {str(e)}")
#             return None
    
#     @staticmethod
#     async def create_manual_agreement(
#         agreement_data: Dict[str, Any],
#         current_user: Dict[str, Any]
#     ) -> Optional[Dict[str, Any]]:
#         """
#         Create agreement manually (for direct API calls)
#         Used by agreements.py create endpoint
#         """
#         try:
#             logger.info(f"🔥 [AGREEMENT SERVICE] Creating manual agreement for application {agreement_data.get('application_id')}")
            
#             tenant_id = current_user["id"]
            
#             # Verify application exists and belongs to current user
#             app_response = supabase_admin.table("applications").select("*").eq(
#                 "id", agreement_data.get("application_id")
#             ).eq("user_id", tenant_id).eq("status", "approved").single().execute()
            
#             if not app_response.data:
#                 logger.warning(f"❌ [AGREEMENT SERVICE] Approved application not found: {agreement_data.get('application_id')} for tenant {tenant_id}")
#                 return None
            
#             application = app_response.data
            
#             # Get property details
#             property_response = supabase_admin.table("properties").select("*").eq(
#                 "id", application["property_id"]
#             ).single().execute()
            
#             if not property_response.data:
#                 logger.error(f"❌ [AGREEMENT SERVICE] Property not found: {application['property_id']}")
#                 return None
            
#             property_data = property_response.data
            
#             # Generate lease dates from provided data
#             lease_dates = {
#                 "lease_start_date": agreement_data.get("lease_start_date"),
#                 "lease_end_date": agreement_data.get("lease_end_date"),
#                 "lease_duration": agreement_data.get("lease_duration")
#             }
            
#             # Generate agreement terms with AI integration
#             terms_result = await AgreementService.generate_agreement_terms(
#                 property_data=property_data,
#                 tenant_data=current_user,
#                 landlord_name="Landlord",  # Will be fetched from property
#                 lease_dates=lease_dates,
#                 application=application
#             )
            
#             # Create agreement dictionary
#             agreement_dict = AgreementService.create_agreement_dict(
#                 application_id=agreement_data.get("application_id"),
#                 property_id=property_data.get("id"),
#                 tenant_id=tenant_id,
#                 landlord_id=property_data.get("landlord_id"),
#                 property_data=property_data,
#                 lease_dates=lease_dates,
#                 terms=terms_result["terms"]
#             )
            
#             # Add AI fields to agreement dict
#             agreement_dict["ai_agreement_content"] = terms_result["ai_content"]
#             agreement_dict["ai_source"] = terms_result["ai_source"]
#             agreement_dict["ai_metadata"] = terms_result["ai_metadata"]
            
#             # Insert agreement
#             agreement_response = supabase_admin.table("agreements").insert(agreement_dict).execute()
            
#             if agreement_response.data:
#                 ai_status = "AI" if terms_result["ai_content"] else "Template"
#                 logger.info(f"✅ [AGREEMENT SERVICE] Manual agreement created: {agreement_response.data[0]['id']} ({ai_status})")
#                 return agreement_response.data[0]
#             else:
#                 logger.error(f"❌ [AGREEMENT SERVICE] Failed to create manual agreement")
#                 return None
                
#         except Exception as e:
#             logger.error(f"❌ [AGREEMENT SERVICE] Error creating manual agreement: {str(e)}")
#             return None
    
#     @staticmethod
#     async def sign_agreement(
#         agreement_id: str,
#         user_id: str,
#         user_type: str,
#         ip_address: Optional[str] = None
#     ) -> Optional[Dict[str, Any]]:
#         """
#         Sign agreement (tenant or landlord)
#         """
#         try:
#             logger.info(f"🔥 [AGREEMENT SERVICE] Signing agreement {agreement_id} by {user_type} {user_id}")
            
#             # Get current agreement
#             agreement_response = supabase_admin.table("agreements").select("*").eq(
#                 "id", agreement_id
#             ).single().execute()
            
#             if not agreement_response.data:
#                 logger.error(f"❌ [AGREEMENT SERVICE] Agreement not found: {agreement_id}")
#                 return None
            
#             agreement = agreement_response.data
            
#             # Verify user owns this agreement
#             if user_type == "tenant" and agreement["tenant_id"] != user_id:
#                 logger.error(f"❌ [AGREEMENT SERVICE] Tenant {user_id} does not own agreement {agreement_id}")
#                 return None
            
#             if user_type == "landlord" and agreement["landlord_id"] != user_id:
#                 logger.error(f"❌ [AGREEMENT SERVICE] Landlord {user_id} does not own agreement {agreement_id}")
#                 return None
            
#             # Update signature
#             update_data = {}
#             if user_type == "tenant":
#                 update_data = {
#                     "tenant_signed_at": datetime.now().isoformat(),
#                     "tenant_signature_ip": ip_address
#                 }
#             else:  # landlord
#                 update_data = {
#                     "landlord_signed_at": datetime.now().isoformat(),
#                     "landlord_signature_ip": ip_address
#                 }
            
#             # Check if both parties have signed
#             if agreement.get("landlord_signed_at") and user_type == "tenant":
#                 update_data["status"] = "SIGNED"
#             elif agreement.get("tenant_signed_at") and user_type == "landlord":
#                 update_data["status"] = "SIGNED"
            
#             # Update agreement
#             update_response = supabase_admin.table("agreements").update(update_data).eq(
#                 "id", agreement_id
#             ).execute()
            
#             if update_response.data:
#                 logger.info(f"✅ [AGREEMENT SERVICE] Agreement {agreement_id} signed by {user_type}")
#                 return update_response.data[0]
#             else:
#                 logger.error(f"❌ [AGREEMENT SERVICE] Failed to sign agreement {agreement_id}")
#                 return None
                
#         except Exception as e:
#             logger.error(f"❌ [AGREEMENT SERVICE] Error signing agreement: {str(e)}")
#             return None

# # Create singleton instance
# agreement_service = AgreementService()
