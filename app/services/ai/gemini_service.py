# server/app/services/gemini_service.py
import google.generativeai as genai
import os
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GeminiAIService:
    def __init__(self):
        """Initialize Gemini AI service"""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro')  # Free tier model
        logger.info("✅ Gemini AI Service initialized successfully")
    
    async def test_connection(self) -> bool:
        """Test Gemini connection"""
        try:
            response = self.model.generate_content("Say 'Gemini connection successful!'")
            result = response.text
            logger.info(f"✅ Gemini Test Response: {result}")
            return True
        except Exception as e:
            logger.error(f"❌ Gemini Connection Failed: {e}")
            return False
    
    async def generate_nigerian_agreement(
        self,
        tenant_data: Dict[str, Any],
        landlord_data: Dict[str, Any],
        property_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate Nigerian tenancy agreement using Gemini"""
        
        prompt = self._build_agreement_prompt(tenant_data, landlord_data, property_data)
        
        try:
            logger.info(f"🤖 Generating agreement for tenant: {tenant_data.get('full_name', 'Unknown')}")
            
            response = self.model.generate_content(prompt)
            agreement_text = response.text
            
            # Extract metadata
            tokens_used = response.usage_metadata.total_token_count if hasattr(response, 'usage_metadata') else 0
            
            result = {
                "success": True,
                "agreement_content": agreement_text,
                "model_used": "gemini-pro",
                "tokens_used": tokens_used,
                "cost_estimate": self._calculate_cost(tokens_used),
                "clause_summary": self._extract_clauses(agreement_text),
                "compliance_check": self._check_compliance(agreement_text)
            }
            
            logger.info(f"✅ Agreement generated successfully, tokens: {tokens_used}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Agreement generation failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _build_agreement_prompt(
        self,
        tenant_data: Dict[str, Any],
        landlord_data: Dict[str, Any],
        property_data: Dict[str, Any]
    ) -> str:
        """Build comprehensive prompt for Nigerian tenancy agreement"""
        
        prompt = f"""
ROLE: You are an expert Nigerian real estate lawyer with 15+ years of experience in tenancy agreements across Lagos, Abuja, and Port Harcourt.

TASK: Generate a comprehensive, legally-binding Nigerian tenancy agreement that is 100% compliant with local laws.

PARTIES INVOLVED:
==================
LANDLORD:
- Name: {landlord_data.get('full_name', 'N/A')}
- Address: {landlord_data.get('address', 'N/A')}
- Phone: {landlord_data.get('phone_number', 'N/A')}
- Email: {landlord_data.get('email', 'N/A')}

TENANT:
- Name: {tenant_data.get('full_name', 'N/A')}
- Address: {tenant_data.get('address', 'N/A')}
- Phone: {tenant_data.get('phone_number', 'N/A')}
- Email: {tenant_data.get('email', 'N/A')}
- Employment: {tenant_data.get('employment_status', 'N/A')} at {tenant_data.get('employer', 'N/A')}
- Monthly Income: ₦{tenant_data.get('monthly_income', 'N/A'):,}

PROPERTY DETAILS:
=================
Address: {property_data.get('full_address', 'N/A')}, {property_data.get('city', 'Lagos')}
Type: {property_data.get('property_type', 'Apartment')}
Bedrooms: {property_data.get('bedrooms', 'N/A')}
Bathrooms: {property_data.get('bathrooms', 'N/A')}
Parking: {property_data.get('parking_spaces', 'N/A')} spaces
Amenities: {', '.join(property_data.get('amenities', []))}

FINANCIAL TERMS:
================
Monthly Rent: ₦{property_data.get('price', 'N/A'):,}
Security Deposit: ₦{property_data.get('security_deposit', 'N/A'):,} (2 months rent - Nigerian standard)
Lease Term: {tenant_data.get('preferred_lease_duration', '1 year')}
Payment Structure: Annual upfront payment (Nigerian market standard)
Payment Due Date: {tenant_data.get('move_in_date', 'N/A')}

LEGAL REQUIREMENTS:
==================
1. COMPLIANCE WITH NIGERIAN LAWS:
   - Lagos Tenancy Law 2011 (Sections 1, 2, 4, 6, 8, 11, 13, 14)
   - Abuja Residential Property Regulations (if applicable)
   - Nigerian Land Use Act 1978
   - Tenancy Laws of the relevant state

2. ESSENTIAL CLAUSES TO INCLUDE:
   - Parties identification with full contact details
   - Property description and address verification
   - Lease term and commencement date
   - Rent amount, payment schedule, and method
   - Security deposit terms and refund conditions
   - Utilities and service charge responsibilities
   - Maintenance and repair obligations
   - Permitted use and restrictions
   - Access and inspection rights
   - Assignment and subletting prohibitions
   - Default conditions and remedies
   - Termination notice periods (6 months tenant, 1 month landlord)
   - Dispute resolution mechanisms
   - Special conditions specific to the property

3. NIGERIAN MARKET SPECIFICS:
   - Annual rent payment norm clearly stated
   - 2-month security deposit standard
   - Proper notice periods as per Nigerian law
   - Rent review clauses (if applicable)
   - Utility payment responsibilities
   - Estate/gated community rules compliance
   - Local government charges and levies

FORMAT REQUIREMENTS:
===================
- Use professional legal document formatting
- Include clear clause numbering (1.0, 1.1, 1.2, etc.)
- Add proper headings and subheadings
- Include signature blocks with witness sections
- Add date and location placeholders
- Include schedule/annexure for inventory if applicable

EXAMPLE STRUCTURE:
==================
TENANCY AGREEMENT

THIS AGREEMENT is made on this [day] of [month], [year]

BETWEEN:
[Landlord Full Details] (hereinafter called "the Landlord")

AND
[Tenant Full Details] (hereinafter called "the Tenant")

PROPERTY:
[Full property description]

TERM AND RENT:
[Lease term details]

[Continue with all required sections...]

SIGNATURES:
[Signature blocks with witnesses]

Generate the complete, legally-binding Nigerian tenancy agreement now. Ensure it is comprehensive, professional, and ready for immediate use.
"""
        return prompt
    
    def _extract_clauses(self, agreement_text: str) -> Dict[str, str]:
        """Extract key clauses from generated agreement"""
        clauses = {}
        
        # Simple keyword-based extraction
        if 'RENT' in agreement_text.upper():
            # Extract rent section
            lines = agreement_text.split('\n')
            rent_section = []
            capturing = False
            for line in lines:
                if 'RENT' in line.upper() and ('TERM' in line.upper() or 'PAYMENT' in line.upper()):
                    capturing = True
                elif capturing and (line.strip().startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.')) or 'SIGNATURE' in line.upper()):
                    break
                elif capturing:
                    rent_section.append(line.strip())
            
            if rent_section:
                clauses['rent_terms'] = '\n'.join(rent_section)
        
        # Extract other key sections similarly
        for section_name in ['DEPOSIT', 'TERMINATION', 'MAINTENANCE']:
            if section_name in agreement_text.upper():
                lines = agreement_text.split('\n')
                section_content = []
                capturing = False
                
                for line in lines:
                    if section_name in line.upper():
                        capturing = True
                    elif capturing and line.strip().startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.')) and section_name not in line.upper():
                        break
                    elif capturing and line.strip():
                        section_content.append(line.strip())
                
                if section_content:
                    clauses[section_name.lower()] = '\n'.join(section_content[:5])  # First 5 lines
        
        return clauses
    
    def _check_compliance(self, agreement_text: str) -> Dict[str, bool]:
        """Check if agreement includes required compliance elements"""
        compliance_checks = {
            'rent_amount_specified': '₦' in agreement_text or 'NGN' in agreement_text,
            'security_deposit_included': 'deposit' in agreement_text.lower(),
            'termination_notice': 'notice' in agreement_text.lower() and ('month' in agreement_text.lower()),
            'signature_blocks': 'signature' in agreement_text.lower(),
            'nigerian_context': any(word in agreement_text.upper() for word in ['NIGERIAN', 'LAGOS', 'ABUJA', 'PORT HARCOURT']),
            'legal_references': any(word in agreement_text.upper() for word in ['LAW', 'ACT', 'SECTION', 'TENANCY']),
            'annual_payment': 'annual' in agreement_text.lower() or 'year' in agreement_text.lower(),
            'landlord_tenant_roles': 'landlord' in agreement_text.lower() and 'tenant' in agreement_text.lower()
        }
        return compliance_checks
    
    def _calculate_cost(self, tokens_used: int) -> float:
        """Calculate estimated cost for this request"""
        # Gemini Pro: $0.00025 per 1K tokens
        cost_per_1k_tokens = 0.00025
        return (tokens_used / 1000) * cost_per_1k_tokens

# Create global instance
gemini_service = GeminiAIService()