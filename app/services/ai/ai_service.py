import os
import json
from datetime import datetime
from typing import Dict, Any, Optional
from groq import Groq
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment variables")
        
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"  # Best for legal documents
        
        # Cost tracking (Groq: $0.05 per 1M tokens)
        self.cost_per_million_tokens = 0.05
        self.usage_stats = {
            "total_requests": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "successful_generations": 0,
            "failed_generations": 0
        }
        
        logger.info(f"✅ Groq AI Service initialized with model: {self.model}")

    async def test_connection(self) -> bool:
        """Test Groq AI connection"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Say hello!"}],
                max_tokens=20
            )
            logger.info(f"✅ Groq Connected: {response.choices[0].message.content}")
            return True
        except Exception as e:
            logger.error(f"❌ Connection Failed: {e}")
            return False

    async def generate_agreement(
        self,
        tenant_name: str,
        landlord_name: str,
        property_address: str,
        monthly_rent: int,
        lease_duration: str = "1 year",
        property_type: str = "Apartment"
    ) -> dict:
        """Generate Nigerian tenancy agreement with enhanced tracking"""
        
        # Update usage stats
        self.usage_stats["total_requests"] += 1
        
        # Enhanced prompt with more legal details
        prompt = f"""
        You are an expert Nigerian real estate lawyer with 15+ years experience in Lagos, Abuja, and Port Harcourt tenancy laws.
        Generate a comprehensive, legally-binding Nigerian tenancy agreement using the SPECIFIC DATA provided.

        CRITICAL INSTRUCTION: USE THE ACTUAL DATA PROVIDED BELOW. DO NOT USE PLACEHOLDERS LIKE [Insert Address] or [Insert Name]. 
        All information is real and should be used exactly as given.

        AGREEMENT DETAILS:
        ==================
        DATE: {datetime.now().strftime("%dth day of %B, %Y")}
        
        PARTIES:
        --------
        LANDLORD:
        - Full Name: {landlord_name}
        - Status: Property Owner/Landlord
        - Address: [To be provided by landlord]
        - Phone: [To be provided by landlord]
        - Email: [To be provided by landlord]
        
        TENANT:
        - Full Name: {tenant_name}
        - Status: Proposed Tenant
        - Address: [To be provided by tenant]
        - Phone: [To be provided by tenant]
        - Email: [To be provided by tenant]
        
        PROPERTY:
        --------
        - Address: {property_address}
        - Type: {property_type}
        - Use: Residential purposes only
        
        FINANCIAL TERMS:
        ================
        - Monthly Rent: ₦{monthly_rent:,}
        - Annual Rent: ₦{monthly_rent * 12:,}
        - Security Deposit: ₦0 (MVP: No caution fee for transparency)
        - Platform Fee: ₦0 (MVP: No platform fee for transparency)
        - Lease Duration: {lease_duration}
        - Payment Structure: Annual upfront payment (Nigerian market standard)
        - Payment Due: Commencement date
        - Payment Method: Via NuloAfrica platform or bank transfer
        
        LEGAL REQUIREMENTS:
        ===================
        1. COMPLIANCE WITH NIGERIAN LAWS:
           - Lagos Tenancy Law 2011 (Sections 1, 2, 4, 6, 8, 11, 13, 14)
           - Nigerian Land Use Act 1978
           - Recovery of Premises Act (applicable state)
           - Nigerian Arbitration Act 2011 (for dispute resolution)

        2. ESSENTIAL CLAUSES:
           - Parties identification with the ACTUAL NAMES provided above
           - Property description with the ACTUAL ADDRESS provided above
           - Lease term for exactly {lease_duration} months
           - Rent amount exactly ₦{monthly_rent:,} per month, ₦{monthly_rent * 12:,} annually
           - Security deposit exactly ₦{monthly_rent * 2:,}
           - Utilities and service charge responsibilities
           - Maintenance and repair obligations (both parties)
           - Permitted use and specific restrictions
           - Access rights and inspection protocols
           - Assignment and subletting prohibitions
           - Default conditions and remedial procedures
           - Termination notice periods (6 months tenant, 1 month landlord)
           - Dispute resolution via arbitration or court
           - Force majeure and government compliance clauses

        3. NIGERIAN MARKET SPECIFICS:
           - Annual rent payment of ₦{monthly_rent * 12:,} clearly stated
           - 2-month security deposit of ₦{monthly_rent * 2:,} (refundable) standard
           - Proper notice periods as per state laws
           - Rent review mechanisms (if applicable)
           - Utility payment responsibilities
           - Estate/gated community rules compliance
           - Local government charges and levies allocation

        FORMAT REQUIREMENTS:
        ====================
        - Professional legal document formatting
        - Clear clause numbering (1.0, 1.1, 1.2, etc.)
        - Proper headings and subheadings
        - Signature blocks with the ACTUAL NAMES: {landlord_name} and {tenant_name}
        - Current date: {datetime.now().strftime("%dth day of %B, %Y")}
        - Include "SCHEDULE/ANNEXURE" section for inventory

        GENERATION INSTRUCTIONS:
        ========================
        - Generate ONLY the tenancy agreement document
        - No preamble, explanation, or meta-commentary
        - Start directly with "TENANCY AGREEMENT"
        - Use the ACTUAL DATA provided - NO PLACEHOLDERS
        - Use formal legal language throughout
        - Ensure all clauses are legally enforceable
        - Include practical examples where helpful

        IMPORTANT: Use the real names "{landlord_name}" and "{tenant_name}" and real address "{property_address}" and real amounts ₦{monthly_rent:,} throughout the document. Do NOT use [Insert] placeholders.

        Generate the complete, professional tenancy agreement now.
        """

        try:
            logger.info(f"📝 Generating agreement for: {tenant_name} → {landlord_name}")
            start_time = datetime.now()
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a senior Nigerian real estate lawyer. CRITICAL: Use ONLY the actual data provided in the prompt. NEVER use placeholders like [Insert Address] or [Insert Name]. All names, addresses, and amounts are real and must be used exactly as given. Generate ONLY the tenancy agreement document with no explanations or preambles. Start directly with 'TENANCY AGREEMENT'."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2500,  # Increased for comprehensive agreements
                temperature=0.1,  # Very low for maximum consistency
                top_p=0.9,
                stream=False
            )

            agreement_text = response.choices[0].message.content
            tokens_used = response.usage.total_tokens
            generation_time = (datetime.now() - start_time).total_seconds()
            
            # Calculate cost
            cost_usd = (tokens_used / 1_000_000) * self.cost_per_million_tokens
            
            # Update usage stats
            self.usage_stats["total_tokens"] += tokens_used
            self.usage_stats["total_cost_usd"] += cost_usd
            self.usage_stats["successful_generations"] += 1

            # Enhanced compliance checking
            compliance = self._check_compliance(agreement_text)
            compliance_score = sum(compliance.values()) / len(compliance) * 100
            
            logger.info(f"✅ Agreement generated in {generation_time:.2f}s | Tokens: {tokens_used} | Cost: ${cost_usd:.6f} | Compliance: {compliance_score:.1f}%")

            return {
                "success": True,
                "agreement": agreement_text,
                "model_used": self.model,
                "tokens_used": tokens_used,
                "generation_time_seconds": generation_time,
                "cost_usd": cost_usd,
                "compliance": compliance,
                "compliance_score": compliance_score,
                "summary": self._extract_summary(agreement_text, monthly_rent),
                "usage_stats": self.get_usage_stats()
            }

        except Exception as e:
            self.usage_stats["failed_generations"] += 1
            logger.error(f"❌ Generation failed for {tenant_name}: {str(e)}")
            return {
                "success": False, 
                "error": str(e),
                "usage_stats": self.get_usage_stats()
            }

    async def generate_advanced_agreement(
        self,
        tenant_data: Dict[str, Any],
        landlord_data: Dict[str, Any],
        property_data: Dict[str, Any]
    ) -> dict:
        """Generate agreement with full data structures (for production use)"""
        
        # Update usage stats
        self.usage_stats["total_requests"] += 1
        
        # Build comprehensive prompt with full data
        prompt = f"""
        You are an expert Nigerian real estate lawyer with 15+ years experience.
        Generate a comprehensive, legally-binding Nigerian tenancy agreement.

        AGREEMENT DETAILS:
        ==================
        DATE: {datetime.now().strftime("%dth day of %B, %Y")}
        
        LANDLORD DETAILS:
        =================
        - Full Name: {landlord_data.get('full_name', 'N/A')}
        - Address: {landlord_data.get('address', 'N/A')}
        - Phone: {landlord_data.get('phone_number', 'N/A')}
        - Email: {landlord_data.get('email', 'N/A')}
        
        TENANT DETAILS:
        ================
        - Full Name: {tenant_data.get('full_name', 'N/A')}
        - Address: {tenant_data.get('address', 'N/A')}
        - Phone: {tenant_data.get('phone_number', 'N/A')}
        - Email: {tenant_data.get('email', 'N/A')}
        - Employment: {tenant_data.get('employment_status', 'N/A')} at {tenant_data.get('employer', 'N/A')}
        - Monthly Income: ₦{tenant_data.get('monthly_income', 0):,}
        
        PROPERTY DETAILS:
        ==================
        - Address: {property_data.get('full_address', 'N/A')}, {property_data.get('city', 'Lagos')}
        - Type: {property_data.get('property_type', 'Apartment')}
        - Bedrooms: {property_data.get('bedrooms', 'N/A')}
        - Bathrooms: {property_data.get('bathrooms', 'N/A')}
        - Parking: {property_data.get('parking_spaces', 'N/A')} spaces
        - Amenities: {', '.join(property_data.get('amenities', []))}
        
        FINANCIAL TERMS:
        ================
        - Monthly Rent: ₦{property_data.get('price', 0):,}
        - Annual Rent: ₦{property_data.get('price', 0) * 12:,}
        - Security Deposit: ₦{property_data.get('security_deposit', property_data.get('price', 0) * 2):,}
        - Lease Duration: {tenant_data.get('preferred_lease_duration', '1 year')}
        - Move-in Date: {tenant_data.get('move_in_date', 'N/A')}
        - Payment Structure: Annual upfront payment
        
        LEGAL & COMPLIANCE:
        ===================
        Include all Nigerian tenancy law requirements:
        - Lagos Tenancy Law 2011 compliance
        - Nigerian Land Use Act 1978
        - Proper notice periods (6 months tenant, 1 month landlord)
        - Dispute resolution mechanisms
        - Maintenance responsibilities
        - Default and termination clauses
        
        Generate the complete professional tenancy agreement now.
        """

        try:
            logger.info(f"📝 Generating advanced agreement for: {tenant_data.get('full_name', 'Unknown')}")
            start_time = datetime.now()
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a senior Nigerian real estate lawyer. Generate ONLY the tenancy agreement document with no explanations."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=3000,  # Increased for comprehensive agreements
                temperature=0.1,
                top_p=0.9
            )

            agreement_text = response.choices[0].message.content
            tokens_used = response.usage.total_tokens
            generation_time = (datetime.now() - start_time).total_seconds()
            
            # Calculate cost
            cost_usd = (tokens_used / 1_000_000) * self.cost_per_million_tokens
            
            # Update usage stats
            self.usage_stats["total_tokens"] += tokens_used
            self.usage_stats["total_cost_usd"] += cost_usd
            self.usage_stats["successful_generations"] += 1

            # Enhanced compliance checking
            compliance = self._check_compliance(agreement_text)
            compliance_score = sum(compliance.values()) / len(compliance) * 100
            
            logger.info(f"✅ Advanced agreement generated in {generation_time:.2f}s | Tokens: {tokens_used} | Cost: ${cost_usd:.6f}")

            return {
                "success": True,
                "agreement": agreement_text,
                "model_used": self.model,
                "tokens_used": tokens_used,
                "generation_time_seconds": generation_time,
                "cost_usd": cost_usd,
                "compliance": compliance,
                "compliance_score": compliance_score,
                "summary": self._extract_summary(agreement_text, property_data.get('price', 0)),
                "usage_stats": self.get_usage_stats(),
                "metadata": {
                    "tenant_name": tenant_data.get('full_name'),
                    "landlord_name": landlord_data.get('full_name'),
                    "property_address": property_data.get('full_address'),
                    "generated_at": datetime.now().isoformat(),
                    "agreement_type": "advanced_nigerian_tenancy"
                }
            }

        except Exception as e:
            self.usage_stats["failed_generations"] += 1
            logger.error(f"❌ Advanced agreement generation failed: {str(e)}")
            return {
                "success": False, 
                "error": str(e),
                "usage_stats": self.get_usage_stats()
            }

    def _check_compliance(self, text: str) -> dict:
        """Check if agreement includes required compliance elements"""
        t = text.upper()
        return {
            "lagos_law_referenced":    "LAGOS TENANCY LAW" in t or "TENANCY LAW 2011" in t,
            "rent_specified":          "₦" in text or "NGN" in t,
            "security_deposit":        "DEPOSIT" in t,
            "termination_notice":      "NOTICE" in t and "MONTH" in t,
            "signature_blocks":        "SIGNATURE" in t,
            "dispute_resolution":      "ARBITRATION" in t or "DISPUTE" in t,
            "maintenance_clauses":     "MAINTENANCE" in t,
            "landlord_tenant_defined": "LANDLORD" in t and "TENANT" in t,
        }

    def _extract_summary(self, text: str, monthly_rent: int) -> dict:
        """Extract key summary information from agreement"""
        return {
            "monthly_rent":    f"₦{monthly_rent:,}",
            "annual_rent":     f"₦{monthly_rent * 12:,}",
            "security_deposit": f"₦{monthly_rent * 2:,}",
            "word_count":      len(text.split()),
            "character_count": len(text),
            "estimated_reading_time": f"{len(text.split()) // 200} minutes"  # Avg 200 words/min
        }

    def get_usage_stats(self) -> dict:
        """Get current usage statistics"""
        return {
            **self.usage_stats,
            "average_tokens_per_request": (
                self.usage_stats["total_tokens"] / self.usage_stats["total_requests"]
                if self.usage_stats["total_requests"] > 0 else 0
            ),
            "success_rate": (
                (self.usage_stats["successful_generations"] / self.usage_stats["total_requests"]) * 100
                if self.usage_stats["total_requests"] > 0 else 0
            ),
            "cost_per_agreement": (
                self.usage_stats["total_cost_usd"] / self.usage_stats["successful_generations"]
                if self.usage_stats["successful_generations"] > 0 else 0
            )
        }

    def reset_usage_stats(self):
        """Reset usage statistics (for testing or new billing period)"""
        self.usage_stats = {
            "total_requests": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "successful_generations": 0,
            "failed_generations": 0
        }
        logger.info("📊 Usage statistics reset")

# Create global instance
ai_service = AIService()
