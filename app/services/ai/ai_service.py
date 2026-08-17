from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import logging

from app.services.ai.agreement_validator import enforce_financial_terms

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Approximate blended USD cost per 1M tokens, per provider. Used only for the
# usage-stats/cost-tracking figures returned by the /api/v1/groq routes --
# never for billing. Tune freely; unknown providers report $0.
_COST_PER_MILLION_TOKENS: Dict[str, float] = {
    "groq": 0.05,     # llama family (historical default)
    "qwen": 0.40,     # qwen-plus blended in/out pricing
    "openai": 0.60,   # gpt-4o-mini blended pricing
    "mock": 0.0,
}


class AIService:
    """
    Tenancy-agreement generation service (Phase B -- configurable LLM layer).

    No longer hard-wired to Groq: every LLM call is routed through the
    provider plugin registry (``app.propflow.services.llm_provider``), so the
    backing model is chosen by ``LLM_PROVIDER`` in server/.env
    (qwen | groq | openai | mock). Switching models is a one-line .env change.

    The provider is resolved lazily (never at import time), so importing this
    module -- e.g. when FastAPI wires the /api/v1/groq routes -- can no longer
    crash the app because an API key is missing. When the active provider is
    unavailable, generation calls return ``{"success": False, ...}`` exactly
    like a failed API call did before.
    """

    def __init__(self):
        self._provider = None  # resolved lazily via _get_provider()
        self.usage_stats = {
            "total_requests": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "successful_generations": 0,
            "failed_generations": 0
        }
        logger.info(
            "✅ AI Service initialized (provider resolved lazily via LLM_PROVIDER)"
        )

    # -- provider plumbing ----------------------------------------------------

    def _get_provider(self):
        """Return the active LLM provider from the plugin registry (lazy)."""
        from app.propflow.services.llm_provider import get_llm_provider
        self._provider = get_llm_provider()
        return self._provider

    @property
    def provider_name(self) -> str:
        """Name of the active provider (qwen | groq | openai | mock)."""
        return self._get_provider().name

    @property
    def model(self) -> str:
        """Primary model identifier of the active provider."""
        return self._get_provider().model

    @property
    def cost_per_million_tokens(self) -> float:
        """USD per 1M tokens for the active provider (stats only)."""
        return _COST_PER_MILLION_TOKENS.get(self.provider_name, 0.0)

    async def _complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        temperature: float = 0.1,
        top_p: float = 0.9,
    ):
        """
        Run one chat completion through the active provider.

        Returns ``(text, tokens_used)`` or raises ``RuntimeError`` when the
        provider is unavailable or every model in its fallback chain failed --
        callers already wrap this in try/except and report
        ``{"success": False}``, matching the historical Groq error path.
        """
        provider = self._get_provider()
        if not provider.available:
            raise RuntimeError(
                f"LLM provider '{provider.name}' is not configured "
                f"(missing API key). Set the matching *_API_KEY in server/.env "
                f"or switch LLM_PROVIDER."
            )
        result = await provider.chat(
            system_prompt,
            user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )
        if result.text is None:
            raise RuntimeError(
                f"LLM provider '{provider.name}' returned no completion "
                f"(model={provider.model})"
            )
        return result.text, result.tokens_used

    async def test_connection(self) -> bool:
        """Test the active LLM provider connection"""
        try:
            text, _ = await self._complete(
                "You are a helpful assistant.",
                "Say hello!",
                max_tokens=20,
            )
            logger.info(f"✅ LLM Connected ({self.provider_name}): {text}")
            return True
        except Exception as e:
            logger.error(f"❌ Connection Failed: {e}")
            return False

    def _enforce_financial_terms(self, text: str, monthly_rent: int, frequency: str) -> dict:
        """
        Run the deterministic post-generation validation/repair layer on the
        LLM output. Never raises: if the validator itself fails, the raw text
        is kept and the error is recorded in the validation payload.
        """
        try:
            result = enforce_financial_terms(text, monthly_rent, frequency)
            if result["repaired"]:
                logger.warning(
                    "🔧 [VALIDATOR] Repaired hallucinated financial terms: "
                    f"{'; '.join(result['repairs'])} | issues_before: "
                    f"{[i['type'] for i in result['issues_before']]}"
                )
            return result
        except Exception as e:
            logger.error(f"❌ [VALIDATOR] Enforcement failed, keeping raw text: {e}")
            return {
                "text": text or "",
                "valid_before": None,
                "valid_after": None,
                "repaired": False,
                "issues_before": [],
                "issues_after": [],
                "repairs": [],
                "expected": {},
                "error": str(e),
            }

    # Frequency multipliers — must stay in sync with nomba_helpers.FREQUENCY_MULTIPLIERS
    _FREQ_MULTIPLIERS = {"MONTHLY": 1, "QUARTERLY": 3, "SEMI_ANNUAL": 6, "ANNUAL": 12}
    _FREQ_LABELS = {
        "MONTHLY": "monthly in advance",
        "QUARTERLY": "quarterly (every 3 months) in advance",
        "SEMI_ANNUAL": "semi-annually (every 6 months) in advance",
        "ANNUAL": "annually (every 12 months) in advance",
    }

    async def generate_agreement(
        self,
        tenant_name: str,
        landlord_name: str,
        property_address: str,
        monthly_rent: int,
        lease_duration: str = "1 year",
        property_type: str = "Apartment",
        payment_frequency: str = "MONTHLY"
    ) -> dict:
        """Generate Nigerian tenancy agreement with enhanced tracking"""
        
        # Update usage stats
        self.usage_stats["total_requests"] += 1
        
        # Compute frequency-based period rent (matches payment_service / nomba_helpers)
        freq = (payment_frequency or "MONTHLY").upper()
        multiplier = self._FREQ_MULTIPLIERS.get(freq, 1)
        period_rent = monthly_rent * multiplier
        freq_label = self._FREQ_LABELS.get(freq, "monthly in advance")
        
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
        - Period Rent ({freq}): ₦{period_rent:,} — payable {freq_label}
        - Security Deposit: ₦0 (waived — NuloAfrica MVP policy, no caution fee)
        - Platform Fee: ₦0 (waived — NuloAfrica MVP policy)
        - Service Charge: ₦0
        - Lease Duration: {lease_duration}
        - Payment Structure: Rent is paid {freq_label} via the NuloAfrica platform
        - Payment Due: On or before the commencement date of each payment period
        - Payment Method: Via NuloAfrica platform (virtual account transfer)
        
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
           - Rent amount exactly ₦{monthly_rent:,} per month, ₦{period_rent:,} per payment period ({freq})
           - Security deposit: ₦0 (waived for this tenancy — do NOT include any deposit amount)
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
           - Rent of ₦{period_rent:,} payable {freq_label}
           - No security deposit / caution fee required (waived by platform policy)
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

        IMPORTANT: Use the real names "{landlord_name}" and "{tenant_name}" and real address "{property_address}" and real amounts ₦{monthly_rent:,} per month (₦{period_rent:,} per payment period) throughout the document. Do NOT use [Insert] placeholders. Do NOT include any security deposit or caution fee clause — the deposit is waived (₦0) for this tenancy.

        Generate the complete, professional tenancy agreement now.
        """

        try:
            logger.info(f"📝 Generating agreement for: {tenant_name} → {landlord_name}")
            start_time = datetime.now()
            
            agreement_text, tokens_used = await self._complete(
                "You are a senior Nigerian real estate lawyer. CRITICAL: Use ONLY the actual data provided in the prompt. NEVER use placeholders like [Insert Address] or [Insert Name]. All names, addresses, and amounts are real and must be used exactly as given. Generate ONLY the tenancy agreement document with no explanations or preambles. Start directly with 'TENANCY AGREEMENT'.",
                prompt,
                max_tokens=2500,  # Increased for comprehensive agreements
                temperature=0.1,  # Very low for maximum consistency
                top_p=0.9,
            )

            generation_time = (datetime.now() - start_time).total_seconds()
            
            # Calculate cost
            cost_usd = (tokens_used / 1_000_000) * self.cost_per_million_tokens
            
            # Update usage stats
            self.usage_stats["total_tokens"] += tokens_used
            self.usage_stats["total_cost_usd"] += cost_usd
            self.usage_stats["successful_generations"] += 1

            # Deterministic post-generation validation/repair of the financial
            # terms (hallucinated deposits, wrong frequency wording, missing
            # figures). The enforced text is what gets persisted downstream.
            validation = self._enforce_financial_terms(agreement_text, monthly_rent, freq)
            agreement_text = validation["text"]

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
                "validation": {
                    "valid_before": validation["valid_before"],
                    "valid_after": validation["valid_after"],
                    "repaired": validation["repaired"],
                    "issues_before": validation["issues_before"],
                    "issues_after": validation["issues_after"],
                    "repairs": validation["repairs"],
                },
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

        # Frequency-based figures used by both the prompt and the validator
        freq = str(property_data.get("payment_frequency") or "MONTHLY").upper()
        if freq not in self._FREQ_MULTIPLIERS:
            freq = "MONTHLY"
        try:
            monthly_rent = int(property_data.get("price", 0) or 0)
        except (TypeError, ValueError):
            monthly_rent = 0
        
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
        - Period Rent ({(property_data.get('payment_frequency') or 'MONTHLY').upper()}): ₦{property_data.get('price', 0) * self._FREQ_MULTIPLIERS.get((property_data.get('payment_frequency') or 'MONTHLY').upper(), 1):,}
        - Security Deposit: ₦0 (waived — NuloAfrica MVP policy, no caution fee)
        - Platform Fee: ₦0 (waived)
        - Lease Duration: {tenant_data.get('preferred_lease_duration', '1 year')}
        - Move-in Date: {tenant_data.get('move_in_date', 'N/A')}
        - Payment Structure: Rent paid {(property_data.get('payment_frequency') or 'MONTHLY').lower()} in advance via NuloAfrica platform
        
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
            
            agreement_text, tokens_used = await self._complete(
                "You are a senior Nigerian real estate lawyer. Generate ONLY the tenancy agreement document with no explanations.",
                prompt,
                max_tokens=3000,  # Increased for comprehensive agreements
                temperature=0.1,
                top_p=0.9,
            )

            generation_time = (datetime.now() - start_time).total_seconds()
            
            # Calculate cost
            cost_usd = (tokens_used / 1_000_000) * self.cost_per_million_tokens
            
            # Update usage stats
            self.usage_stats["total_tokens"] += tokens_used
            self.usage_stats["total_cost_usd"] += cost_usd
            self.usage_stats["successful_generations"] += 1

            # Deterministic post-generation validation/repair of the financial
            # terms (hallucinated deposits, wrong frequency wording, missing
            # figures). The enforced text is what gets persisted downstream.
            validation = self._enforce_financial_terms(agreement_text, monthly_rent, freq)
            agreement_text = validation["text"]

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
                "summary": self._extract_summary(agreement_text, monthly_rent),
                "validation": {
                    "valid_before": validation["valid_before"],
                    "valid_after": validation["valid_after"],
                    "repaired": validation["repaired"],
                    "issues_before": validation["issues_before"],
                    "issues_after": validation["issues_after"],
                    "repairs": validation["repairs"],
                },
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
            "security_deposit": "₦0 (waived)",
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
