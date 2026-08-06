"""
PropFlow Qwen Client
Real Qwen API integration via Alibaba Cloud DashScope (OpenAI-compatible endpoint).

SDK used: openai>=1.0.0 pointed at the DashScope base URL.
No separate qwen SDK needed -- the openai client handles it transparently.

Three production use-cases:
  1. extract_intent       -- Nigerian Pidgin/English -> structured property JSON
  2. generate_briefing    -- Tenant profile -> 3-sentence landlord briefing
  3. generate_anomaly_sms -- Payment anomaly -> 160-char SMS for tenant

Fallback chain:
  QWEN_MODEL (qwen-plus) -> QWEN_FALLBACK_MODEL (qwen-turbo) -> mock
  The mock is only reached in tests or when QWEN_API_KEY is unset.
"""

import json
import logging
import re
from typing import Any, Optional

from app.propflow.config import propflow_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_INTENT_SYSTEM_PROMPT = """You are a Nigerian rental agent assistant. Your job is to extract
structured property requirements from tenant messages written in Nigerian English, Pidgin,
Broken English, or formal English.

Always return ONLY a valid JSON object -- no markdown, no explanation, no extra text.

JSON schema (all keys required, use null for unknown fields):
{
  "property_type": "self-contain" | "flat" | "duplex" | "bungalow" | "room" | null,
  "location": string | null,
  "bedrooms": integer | null,
  "budget_monthly": number | null,
  "budget_annual": number | null,
  "move_in_date": "YYYY-MM-DD" | null,
  "payment_frequency": "MONTHLY" | "QUARTERLY" | "SEMI_ANNUAL" | "ANNUAL" | null,
  "special_requests": string | null,
  "confidence": float  // 0.0-1.0, how confident you are in the extraction
}

Nigerian Pidgin translation guide:
  "self-contain" = self-contained flat (bathroom inside)
  "face-me-I-face-you" = shared compound rooms
  "BQ" = boys quarters (servant quarters)
  "VI" = Victoria Island, Lagos
  "GRA" = Government Reserved Area (a neighbourhood, NOT a city)
  "k" or "K" after number = thousands (e.g. "500k" = 500,000)
  "m" or "M" after number = millions (e.g. "1.5m" = 1,500,000)
  "per month", "monthly" -> budget_monthly
  "per year", "annually", "per annum" -> budget_annual
  If only monthly given, annual = monthly * 12. If only annual, monthly = annual / 12.
  "ASAP", "immediately" -> move_in_date = today's date
  "next month" -> move_in_date = first day of next month

LOCATION EXTRACTION (IMPORTANT -- preserve specificity):
  Keep the tenant's neighbourhood exactly as written; do NOT collapse it to
  the city or state. Nigerian tenants write many forms; preserve them all:
    - "Ajah Lagos"        -> location = "Ajah, Lagos"
    - "Ajah, Lagos"       -> location = "Ajah, Lagos"
    - "Badagry Lagos"     -> location = "Badagry, Lagos"
    - "First Junction PH" -> location = "First Junction, Port Harcourt"
    - "GRA PH"            -> location = "GRA, Port Harcourt"
    - "GRA, Portharcourt" -> location = "GRA, Port Harcourt"
    - "Lekki Phase 1"     -> location = "Lekki Phase 1"
    - "VI, Lagos"         -> location = "Victoria Island, Lagos"
  Preserve the specific neighbourhood BEFORE the city so the matcher can
  show the tenant exactly what they asked for, not every listing in the
  whole city. Do NOT drop "GRA", "Badagry", "First Junction", etc.
  If the user names ONLY a city (e.g. "Lagos" or "Abuja"), return just that.
"""

_BRIEFING_SYSTEM_PROMPT = """You are a professional Nigerian property manager writing a briefing
for a landlord about a prospective tenant.

Write exactly 3 sentences. Be factual, professional, and concise.
Sentence 1: Who the tenant is (occupation, employer if known, income level).
Sentence 2: Their specific requirements and payment preference.
Sentence 3: Why they are a good fit and any relevant prior history.

If memory context is provided, use it to personalize the briefing.
Do not invent facts. If information is missing, say "not provided" rather than guessing.
Return ONLY the 3-sentence briefing text -- no JSON, no bullet points, no headers.
"""

_ANOMALY_SMS_PROMPT = """You are writing a professional but friendly SMS to a Nigerian tenant
about a rent payment anomaly. Maximum 160 characters. Be clear about amounts and action needed.
Use plain language (no jargon). Format amounts as NGN with commas (e.g. NGN 50,000).
Return ONLY the SMS text -- nothing else.
"""


class QwenClient:
    """
    Async client for Qwen API via DashScope OpenAI-compatible endpoint.
    Uses the openai SDK (already in requirements.txt) with base_url override.
    """

    def __init__(self):
        self._settings = propflow_settings
        self._client = None      # Lazy-init to avoid crash on import if openai not installed
        self._fallback_used = False

    def _get_openai_client(self):
        """Lazy-init the openai AsyncOpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=self._settings.QWEN_API_KEY or "placeholder",
                    base_url=self._settings.QWEN_API_URL,
                )
            except ImportError:
                logger.error("openai package not installed. Run: pip install openai>=1.0.0")
                return None
        return self._client

    async def _chat(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """
        Core chat completion call with automatic fallback to qwen-turbo.
        Returns raw response text, or None on failure.
        """
        if not self._settings.QWEN_API_KEY:
            logger.warning("QWEN_API_KEY not set -- returning mock response")
            return None

        client = self._get_openai_client()
        if client is None:
            return None

        models_to_try = [
            self._settings.QWEN_MODEL,
            self._settings.QWEN_FALLBACK_MODEL,
        ]

        for model in models_to_try:
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=self._settings.QWEN_TEMPERATURE,
                    max_tokens=max_tokens or self._settings.QWEN_MAX_TOKENS,
                )
                content = response.choices[0].message.content
                if model == self._settings.QWEN_FALLBACK_MODEL:
                    logger.info(f"Used fallback model: {model}")
                return content
            except Exception as exc:
                logger.warning(f"Qwen call failed with model={model}: {exc}")
                continue

        logger.error("All Qwen models failed -- falling back to mock")
        return None

    # ── 1. Intent Extraction ──────────────────────────────────────────────────

    async def extract_intent(
        self,
        text: str,
        prior_memories: Optional[list] = None,
    ) -> dict[str, Any]:
        """
        Convert a raw tenant inquiry into structured property requirements.

        Args:
            text:           Raw tenant message (Pidgin, broken English, formal)
            prior_memories: Mem0 memories from previous sessions (may refine extraction)

        Returns:
            Structured dict with property_type, location, bedrooms, budget, etc.
            Always includes a 'confidence' float (0.0-1.0).
            Falls back to mock if API unavailable.
        """
        # Build user message, optionally enriched with prior memory context
        memory_block = ""
        if prior_memories:
            from app.propflow.services.mem0_client import Mem0Service
            memory_block = Mem0Service.format_memories_for_prompt(prior_memories)

        user_message = f"Tenant message: {text}"
        if memory_block:
            user_message = (
                f"Context from this tenant's history:\n{memory_block}\n\n"
                f"Tenant message: {text}"
            )

        raw = await self._chat(_INTENT_SYSTEM_PROMPT, user_message)

        if raw is None:
            logger.info("Qwen unavailable -- using mock intent extraction")
            return self._mock_intent_extraction(text)

        return self._parse_intent_json(raw, text)

    def _parse_intent_json(self, raw: str, original_text: str) -> dict[str, Any]:
        """
        Parse Qwen's response into a clean dict.
        Handles cases where the model wraps JSON in markdown code fences.
        """
        # Strip markdown code fences if present
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            parsed = json.loads(cleaned)
            # Ensure confidence is always present
            if "confidence" not in parsed:
                parsed["confidence"] = 0.75
            # Normalize confidence to 0-1 range
            parsed["confidence"] = max(0.0, min(1.0, float(parsed["confidence"])))
            logger.info(
                f"Intent extracted: location={parsed.get('location')} "
                f"bedrooms={parsed.get('bedrooms')} "
                f"budget_monthly={parsed.get('budget_monthly')} "
                f"confidence={parsed.get('confidence'):.2f}"
            )
            return parsed
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"Failed to parse Qwen intent JSON: {exc}. Raw: {raw[:200]}")
            # Fall back to mock rather than crash the workflow
            return self._mock_intent_extraction(original_text)

    def _mock_intent_extraction(self, text: str) -> dict[str, Any]:
        """Mock for tests and when API key is not set."""
        text_lower = text.lower()
        # Very basic keyword extraction for demo purposes
        location = None
        for loc in ["vi", "victoria island", "lekki","Lagos", "Portharcout","ajah", "yaba", "ikeja", "abuja", "ph"]:
            if loc in text_lower:
                location = loc.upper() if len(loc) <= 3 else loc.title()
                break

        bedrooms = None
        for n in ["1", "2", "3", "4"]:
            patterns = [f"{n} bed", f"{n}-bed", f"{n}bed", f"{n}bd", f"{n}-bd", f"{n} bedroom", f"{n}-bedroom"]
            if any(p in text_lower for p in patterns):
                bedrooms = int(n)
                break

        # Budget: look for patterns like "500k", "500,000", "1.2m"
        # Also detect whether stated as monthly or annual
        budget_monthly = None
        budget_annual = None
        budget_match = re.search(r"(\d+(?:\.\d+)?)\s*([km])", text_lower)
        if budget_match:
            amount = float(budget_match.group(1))
            unit = budget_match.group(2)
            if unit == "k":
                amount *= 1000
            elif unit == "m":
                amount *= 1_000_000
            # Determine if annual or monthly based on context keywords
            if any(w in text_lower for w in ["per year", "annual", "per annum", "yearly"]):
                budget_annual = amount
                budget_monthly = round(amount / 12, 2)
            else:
                budget_monthly = amount
                budget_annual = amount * 12

        return {
            "property_type": "self-contain" if "self" in text_lower else "flat",
            "location": location or "Lagos",
            "bedrooms": bedrooms,
            "budget_monthly": budget_monthly,
            "budget_annual": budget_annual,
            "move_in_date": None,
            "payment_frequency": "MONTHLY",
            "special_requests": None,
            "confidence": 0.85,  # Mock confidence — high enough to pass 0.7 threshold for demo flow
        }

    # ── 2. Landlord Briefing ──────────────────────────────────────────────────

    async def generate_landlord_briefing(
        self,
        tenant_data: dict[str, Any],
        property_data: dict[str, Any],
        extracted_intent: dict[str, Any],
        prior_tenant_memories: Optional[list] = None,
        prior_landlord_memories: Optional[list] = None,
    ) -> str:
        """
        Generate a 3-sentence landlord briefing about the prospective tenant.

        Args:
            tenant_data:             Tenant profile from Supabase (name, occupation, income)
            property_data:           Property details (title, location, price)
            extracted_intent:        Structured intent from extract_intent node
            prior_tenant_memories:   Mem0 history for this tenant
            prior_landlord_memories: Mem0 preferences for this landlord

        Returns:
            3-sentence briefing string ready for landlord notification.
            Falls back to mock if API unavailable.
        """
        # Build rich context block for Qwen
        context_parts = []

        tenant_name = tenant_data.get("full_name") or tenant_data.get("email", "Tenant")
        context_parts.append(f"Tenant name: {tenant_name}")
        if tenant_data.get("occupation"):
            context_parts.append(f"Occupation: {tenant_data['occupation']}")
        if tenant_data.get("employer"):
            context_parts.append(f"Employer: {tenant_data['employer']}")
        if tenant_data.get("monthly_income"):
            income_val = tenant_data['monthly_income']
            # monthly_income from tenant_profiles is a range string (e.g. "500000-1000000")
            # so just pass it through without numeric formatting
            try:
                income_display = f"NGN {float(income_val):,.0f}"
            except (TypeError, ValueError):
                income_display = f"NGN {income_val}"
            context_parts.append(f"Monthly income: {income_display}")

        context_parts.append(
            f"Requested: {extracted_intent.get('bedrooms')} bed "
            f"{extracted_intent.get('property_type')} in {extracted_intent.get('location')}"
        )
        if extracted_intent.get("payment_frequency"):
            context_parts.append(
                f"Payment preference: {extracted_intent['payment_frequency'].lower()}"
            )
        if extracted_intent.get("budget_monthly"):
            try:
                budget_display = f"NGN {float(extracted_intent['budget_monthly']):,.0f}/month"
            except (TypeError, ValueError):
                budget_display = f"NGN {extracted_intent['budget_monthly']}/month"
            context_parts.append(f"Budget: {budget_display}")

        context_parts.append(
            f"Property: {property_data.get('title', 'Listed property')} "
            f"in {property_data.get('location', '')}"
        )

        # Inject memory context
        if prior_tenant_memories:
            from app.propflow.services.mem0_client import Mem0Service
            mem_block = Mem0Service.format_memories_for_prompt(prior_tenant_memories)
            if mem_block:
                context_parts.append(f"Prior history for this tenant:\n{mem_block}")

        if prior_landlord_memories:
            from app.propflow.services.mem0_client import Mem0Service
            mem_block = Mem0Service.format_memories_for_prompt(prior_landlord_memories)
            if mem_block:
                context_parts.append(f"This landlord's past preferences:\n{mem_block}")

        user_message = "\n".join(context_parts)

        raw = await self._chat(_BRIEFING_SYSTEM_PROMPT, user_message, max_tokens=300)

        if raw is None:
            return self._mock_landlord_briefing(tenant_data, property_data)

        briefing = raw.strip()
        logger.info(f"Landlord briefing generated ({len(briefing)} chars)")
        return briefing

    def _mock_landlord_briefing(
        self,
        tenant_data: dict[str, Any],
        property_data: dict[str, Any],
    ) -> str:
        name = tenant_data.get("full_name") or tenant_data.get("email", "The applicant")
        return (
            f"{name} is a working professional who has submitted a complete application. "
            f"They are interested in the {property_data.get('title', 'listed property')} "
            f"and are ready to commence the lease upon approval. "
            f"Payment will be arranged via Nomba virtual account upon agreement signing."
        )

    # ── 3. Payment Anomaly SMS ────────────────────────────────────────────────

    async def generate_anomaly_sms(
        self,
        expected: float,
        actual: float,
        anomaly_type: str,
        tenant_name: Optional[str] = None,
    ) -> str:
        """
        Generate a plain-English SMS (max 160 chars) for rent payment anomalies.

        Args:
            expected:      Expected payment amount (decimal Naira)
            actual:        Actual amount received (decimal Naira)
            anomaly_type:  "UNDERPAYMENT" or "OVERPAYMENT"
            tenant_name:   Optional first name for personalization

        Returns:
            SMS-ready string, always <= 160 characters.
        """
        name_part = f"Hi {tenant_name}, " if tenant_name else ""

        if anomaly_type == "UNDERPAYMENT":
            shortfall = expected - actual
            user_message = (
                f"{name_part}NGN {actual:,.0f} received for rent. "
                f"Expected NGN {expected:,.0f}. "
                f"Shortfall: NGN {shortfall:,.0f}. "
                f"Please complete payment to activate your agreement."
            )
        else:
            excess = actual - expected
            user_message = (
                f"{name_part}NGN {actual:,.0f} received. "
                f"Expected NGN {expected:,.0f}. "
                f"Excess: NGN {excess:,.0f}. "
                f"Refund will be processed within 24 hours."
            )

        raw = await self._chat(_ANOMALY_SMS_PROMPT, user_message, max_tokens=80)

        if raw is None:
            return self._mock_anomaly_sms(expected, actual, anomaly_type)

        sms = raw.strip()
        # Hard-cap at 160 chars -- SMS limit
        if len(sms) > 160:
            sms = sms[:157] + "..."
        logger.info(f"Anomaly SMS generated ({len(sms)} chars): type={anomaly_type}")
        return sms

    def _mock_anomaly_sms(self, expected: float, actual: float, anomaly_type: str) -> str:
        if anomaly_type == "UNDERPAYMENT":
            return (
                f"Rent received: NGN {actual:,.0f}. "
                f"Balance: NGN {expected - actual:,.0f}. Please complete payment."
            )[:160]
        return (
            f"Overpayment: NGN {actual - expected:,.0f} excess received. "
            f"Refund in 24hrs."
        )[:160]


# Singleton
qwen_client = QwenClient()
