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

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
from app.database import supabase_admin, run_db_async

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Security-deposit policy
# ─────────────────────────────────────────────────────────────────────────────
# MVP default: deposit is WAIVED (₦0). For testing you can enable a deposit by
# setting AGREEMENT_SECURITY_DEPOSIT_PERCENT in the environment (e.g. "5" for
# 5% of the monthly rent). The deterministic template and the persisted
# `deposit_amount` both derive from this single helper, so the agreement text
# and the DB row can never disagree.
_DEPOSIT_PERCENT_ENV = "AGREEMENT_SECURITY_DEPOSIT_PERCENT"


# ─────────────────────────────────────────────────────────────────────────────
# Date formatting helpers (legal-document style)
# ─────────────────────────────────────────────────────────────────────────────

def _ordinal(day: int) -> str:
    """Return the English ordinal for a day-of-month (1 -> '1st', 22 -> '22nd')."""
    try:
        day = int(day)
    except (TypeError, ValueError):
        return ""
    if 10 <= (day % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _format_lease_date(value: Any) -> str:
    """
    Render a lease date as '17 August 2026' for the legal document.
    Accepts datetime/date objects or ISO date strings ('2026-08-17',
    '2026-08-17T00:00:00+00:00'). Falls back to the raw string, or a neutral
    phrase when empty, so the document never shows a raw ISO timestamp.
    """
    if value is None:
        return "a date to be agreed by the parties"
    if isinstance(value, datetime):
        return value.strftime("%d %B %Y")
    if hasattr(value, "strftime"):  # datetime.date
        try:
            return value.strftime("%d %B %Y")
        except Exception:
            return str(value)
    s = str(value).strip()
    if not s:
        return "a date to be agreed by the parties"
    # ISO 8601 (with/without time & offset)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%d %B %Y")
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%d %B %Y")
        except ValueError:
            continue
    return s


def _party_contact_lines(
    name: str,
    address: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> str:
    """
    Build a Markdown contact block for a party, OMITTING any field we do not
    have so the document never shows '[... to be provided]' placeholders.
    """
    lines = [f"**Full Name:** {name}"]
    if address and str(address).strip():
        lines.append(f"**Address:** {str(address).strip()}")
    if phone and str(phone).strip():
        lines.append(f"**Phone:** {str(phone).strip()}")
    if email and str(email).strip():
        lines.append(f"**Email:** {str(email).strip()}")
    return "\n".join(lines)


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
    def resolve_security_deposit(monthly_rent: Any) -> Tuple[int, Optional[float]]:
        """
        Resolve the security deposit for a tenancy from platform policy.

        Returns:
            (deposit_amount, deposit_percent)
            - deposit_amount: integer Naira to persist on the agreement row and
              render in the deterministic template.
            - deposit_percent: the percentage of monthly rent applied, or None
              when the deposit is waived (₦0).

        Policy:
            Default is WAIVED (₦0) per NuloAfrica MVP policy. To enable a
            deposit for testing, set AGREEMENT_SECURITY_DEPOSIT_PERCENT in the
            environment (e.g. "5" => 5% of monthly rent). Invalid values fall
            back to waived so a bad env var can never produce a bogus deposit.
        """
        try:
            rent = int(float(monthly_rent or 0))
        except (TypeError, ValueError):
            rent = 0

        raw = os.getenv(_DEPOSIT_PERCENT_ENV)
        if raw is None or str(raw).strip() == "":
            return 0, None

        try:
            percent = float(str(raw).strip())
        except (TypeError, ValueError):
            logger.warning(
                f"⚠️ [AGREEMENT SERVICE] Invalid {_DEPOSIT_PERCENT_ENV}={raw!r} — "
                "deposit treated as waived (₦0)"
            )
            return 0, None

        if percent <= 0:
            return 0, None

        deposit = int(round(rent * percent / 100.0))
        if deposit <= 0:
            return 0, None

        return deposit, percent

    @staticmethod
    async def generate_enhanced_agreement_terms(
        property_data: Dict[str, Any],
        tenant_data: Dict[str, Any],
        landlord_name: str,
        lease_dates: Dict[str, Any],
        application: Dict[str, Any] = None,
        landlord_email: Optional[str] = None,
        landlord_phone: Optional[str] = None,
        landlord_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Deterministic agreement generation — single source of truth.
        Returns: { terms, source, metadata }

        STRATEGY (post-AI-removal):
        - The tenancy agreement body is ALWAYS produced by the deterministic
          template (generate_enhanced_manual_terms), filled with the property,
          tenant and landlord data. No LLM is involved, so the financial terms
          can never be hallucinated.
        - The AI plain-English tenant brief is generated separately (Qwen) from
          these terms, so brief and agreement always share one source of truth.
        - Source is reported as "deterministic_template" for analytics.

        Landlord contact details (email/phone/address) are optional — when
        provided they are printed in the parties block; when absent the field
        is simply omitted (never a '[... to be provided]' placeholder).
        """
        logger.info(
            f"📋 [AGREEMENT SERVICE] Generating deterministic agreement for "
            f"{tenant_data.get('full_name', 'Tenant')}"
        )

        terms = AgreementService.generate_enhanced_manual_terms(
            application=application or {},
            property_data=property_data,
            lease_data=lease_dates,
            landlord_name=landlord_name,
            tenant_name=tenant_data.get("full_name", "Tenant"),
            tenant_email=tenant_data.get("email", ""),
            tenant_phone=tenant_data.get("phone_number", ""),
            tenant_address=tenant_data.get("address"),
            landlord_email=landlord_email,
            landlord_phone=landlord_phone,
            landlord_address=landlord_address,
        )

        deposit_amount, deposit_percent = AgreementService.resolve_security_deposit(
            property_data.get("price", 0)
        )

        metadata = {
            "generated_at": datetime.now().isoformat(),
            "template_version": "deterministic_v2_legal",
            "security_deposit_amount": deposit_amount,
            "security_deposit_percent": deposit_percent,
        }

        return {
            "terms": terms,                        # SINGLE agreement field
            "source": "deterministic_template",    # always deterministic now
            "metadata": metadata                   # generation metadata
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
        tenant_address: Optional[str] = None,
        landlord_email: Optional[str] = None,
        landlord_phone: Optional[str] = None,
        landlord_address: Optional[str] = None,
    ) -> str:
        """
        Deterministic legal template (deterministic_v2_legal) — the single
        source of truth for the tenancy agreement body.

        Produces a formally-worded Nigerian residential tenancy agreement in
        Markdown, filled exclusively with real data:
        - Financial figures come from the property row + platform policy
          (resolve_security_deposit) — never from an LLM, so they can never
          be hallucinated.
        - Contact fields that are missing are OMITTED, never rendered as
          '[... to be provided]' placeholders.
        """
        # Compute frequency-based period rent (matches nomba_helpers.FREQUENCY_MULTIPLIERS)
        _freq_mult = {"MONTHLY": 1, "QUARTERLY": 3, "SEMI_ANNUAL": 6, "ANNUAL": 12}
        _freq = str(property_data.get("payment_frequency") or "MONTHLY").upper()
        if _freq not in _freq_mult:
            _freq = "MONTHLY"
        try:
            _monthly = int(float(property_data.get("price", 0) or 0))
        except (TypeError, ValueError):
            _monthly = 0
        _period_rent = _monthly * _freq_mult[_freq]
        _freq_schedule = {
            "MONTHLY": "monthly in advance",
            "QUARTERLY": "quarterly (every 3 months) in advance",
            "SEMI_ANNUAL": "semi-annually (every 6 months) in advance",
            "ANNUAL": "annually (every 12 months) in advance",
        }[_freq]
        _freq_noun = {
            "MONTHLY": "Monthly",
            "QUARTERLY": "Quarterly",
            "SEMI_ANNUAL": "Semi-Annual",
            "ANNUAL": "Annual",
        }[_freq]

        # Security deposit — resolved from platform policy (waived by default,
        # configurable via AGREEMENT_SECURITY_DEPOSIT_PERCENT for testing).
        _deposit_amount, _deposit_percent = AgreementService.resolve_security_deposit(_monthly)
        if _deposit_amount > 0:
            _deposit_summary = f"₦{_deposit_amount:,} ({_deposit_percent:g}% of monthly rent, refundable)"
            _deposit_clause = (
                f"4.1 The Tenant shall pay a security deposit of **₦{_deposit_amount:,}** "
                f"(being {_deposit_percent:g}% of the monthly rent) upon execution of this Agreement.\n\n"
                f"4.2 The security deposit shall be held by the Landlord and refunded to the Tenant "
                f"within fourteen (14) days of the expiration or lawful termination of this tenancy, "
                f"subject to a final inspection of the Property and deduction of any sums reasonably "
                f"due for damage beyond fair wear and tear or outstanding charges lawfully owed by the Tenant."
            )
        else:
            _deposit_summary = "₦0 (waived under NuloAfrica platform policy)"
            _deposit_clause = (
                "4.1 The security deposit (caution fee) for this tenancy is **waived**; the Tenant shall "
                "pay **₦0** as security deposit, in accordance with the prevailing NuloAfrica platform "
                "policy at the date of this Agreement.\n\n"
                "4.2 No caution fee, key money or any other deposit of any kind shall be demanded from "
                "the Tenant in respect of this tenancy."
            )

        # Real contact blocks — missing fields are omitted, never placeholdered.
        _landlord_block = _party_contact_lines(
            landlord_name, address=landlord_address, phone=landlord_phone, email=landlord_email
        )
        _tenant_block = _party_contact_lines(
            tenant_name, address=tenant_address, phone=tenant_phone, email=tenant_email
        )

        _property_address = (
            property_data.get("full_address")
            or property_data.get("address")
            or property_data.get("location")
            or "the property described on the NuloAfrica platform"
        )
        _property_title = property_data.get("title") or "the Property"
        _property_type = str(property_data.get("property_type") or "residential property").strip()
        _property_id = property_data.get("id") or "N/A"

        _start = _format_lease_date(lease_data.get("lease_start_date"))
        _end = _format_lease_date(lease_data.get("lease_end_date"))
        try:
            _duration = int(lease_data.get("lease_duration") or 12)
        except (TypeError, ValueError):
            _duration = 12

        _now = datetime.now()
        _made_day = f"{_ordinal(_now.day)} day of {_now.strftime('%B')}, {_now.year}"

        terms = f"""# RESIDENTIAL TENANCY AGREEMENT

**THIS TENANCY AGREEMENT** (the "Agreement") is made this {_made_day}

**BETWEEN**

**{landlord_name}** (hereinafter referred to as the **"Landlord"**, which expression shall where the context so admits include his/her heirs, executors, administrators, legal representatives and assigns) of the one part:

{_landlord_block}

**AND**

**{tenant_name}** (hereinafter referred to as the **"Tenant"**, which expression shall where the context so admits include his/her heirs, executors, administrators, legal representatives and assigns) of the other part:

{_tenant_block}

The Landlord and the Tenant are individually referred to as a **"Party"** and collectively as the **"Parties"**.

## WHEREAS:

A. The Landlord is the owner of the residential property known as **{_property_title}**, situate at and known as **{_property_address}** (hereinafter referred to as the **"Property"**).

B. The Tenant has applied to the Landlord, through the NuloAfrica digital rental platform, for a tenancy of the Property, and the Landlord has agreed to grant the Tenant a residential tenancy of the Property upon the terms and conditions hereinafter set out.

**NOW THIS AGREEMENT WITNESSETH AS FOLLOWS:**

## 1. THE PROPERTY

1.1 The Landlord hereby lets, and the Tenant hereby takes, the Property described below for residential use only:

- **Property Address:** {_property_address}
- **Property Type:** {_property_type}
- **Platform Property Reference:** {_property_id}
- **Permitted Use:** Private residential occupation only

## 2. TERM OF TENANCY

2.1 This tenancy shall be for a fixed term of **{_duration} months**, commencing on **{_start}** and expiring on **{_end}** (the "Term"), unless sooner determined in accordance with this Agreement.

2.2 Upon the expiration of the Term, this tenancy shall not automatically renew. Any renewal shall be subject to a fresh written agreement between the Parties.

## 3. RENT AND PAYMENT TERMS

3.1 The rent for the Property is **₦{_monthly:,}** per calendar month (the "Monthly Rent").

3.2 Rent is payable **{_freq_schedule}** at the rate of **₦{_period_rent:,}** per payment period (the "Period Rent").

3.3 All rent payments shall be made exclusively through the NuloAfrica platform's designated payment channels, and shall be subject to the platform's escrow and payment-protection mechanisms. No payment made outside the NuloAfrica platform shall be recognised under this Agreement.

3.4 Each instalment of rent shall be paid on or before the first day of the period to which it relates.

3.5 In the event of late payment, the Tenant shall be liable to pay a late-payment charge of **5%** of the Period Rent then due, without prejudice to the Landlord's other rights under this Agreement.

## 4. SECURITY DEPOSIT

{_deposit_clause}

## 5. PLATFORM FEE

5.1 The NuloAfrica platform fee for this tenancy is **₦0 (waived)**. The Tenant shall not be required to pay any agency fee, platform fee or intermediary commission in respect of this tenancy.

## 6. TENANT'S COVENANTS

The Tenant hereby covenants with the Landlord as follows:

6.1 To pay the rent reserved by this Agreement in the manner and at the times prescribed in Clause 3.

6.2 To pay all charges for electricity, water, waste disposal and other utilities consumed at the Property during the Term, as and when due.

6.3 To keep the interior of the Property, including all fixtures and fittings, in good and tenantable repair and condition (fair wear and tear excepted), and to be responsible for minor day-to-day repairs and maintenance.

6.4 To use the Property for private residential purposes only, and not to use or permit the Property to be used for any commercial, industrial, illegal or immoral purpose.

6.5 Not to assign, sublet, part with or share possession of the Property or any part thereof without the prior written consent of the Landlord.

6.6 Not to make any structural alteration or addition to the Property without the prior written consent of the Landlord.

6.7 To permit the Landlord or the Landlord's authorised agent, upon not less than twenty-four (24) hours' prior notice (except in an emergency), to enter the Property at reasonable times to inspect its condition or to carry out repairs.

6.8 To comply with all applicable laws, regulations and estate rules governing the use and occupation of the Property.

6.9 To yield up the Property at the expiration or sooner determination of the Term in good and tenantable condition, fair wear and tear excepted.

## 7. LANDLORD'S COVENANTS

The Landlord hereby covenants with the Tenant as follows:

7.1 That the Tenant, paying the rent and performing the covenants on the Tenant's part herein contained, shall peaceably hold and enjoy the Property during the Term without any interruption by the Landlord or any person lawfully claiming through or in trust for the Landlord.

7.2 To be responsible for all major structural repairs to the Property, including the roof, main walls, main drains and external structures, and to keep the same in good and substantial repair.

7.3 To pay all property taxes, ground rent (where applicable) and building insurance premiums in respect of the Property during the Term.

7.4 To ensure that the Property is fit for residential habitation at the commencement of the Term.

## 8. TERMINATION

8.1 Either Party may terminate this Agreement before the expiration of the Term by giving not less than **thirty (30) days' written notice** to the other Party.

8.2 Where the Tenant terminates this Agreement before the expiration of the Term, any rent already paid in advance for the unexpired period shall be refunded to the Tenant, subject to reasonable and lawful deductions for any outstanding obligations of the Tenant.

8.3 Where the Landlord terminates this Agreement before the expiration of the Term otherwise than for the Tenant's default, the Landlord shall refund to the Tenant the rent paid in advance for the unexpired portion of the Term.

8.4 Upon the expiration or termination of this Agreement, the Tenant shall promptly yield up vacant possession of the Property to the Landlord.

## 9. DEFAULT AND REMEDIES

9.1 The Tenant shall be deemed to be in default if rent remains unpaid for more than **thirty (30) days** after the date on which it fell due.

9.2 Upon default by the Tenant, the Landlord may, without prejudice to any other right or remedy, terminate this Agreement and recover possession of the Property in accordance with applicable law.

9.3 Where the Landlord commits a material breach of this Agreement, the Tenant shall be entitled to the remedies available under applicable law, including, where appropriate, a lawful set-off against rent after written notice to the Landlord.

## 10. FORCE MAJEURE

10.1 Neither Party shall be liable for any failure or delay in performing its obligations under this Agreement to the extent that such failure or delay is caused by circumstances beyond its reasonable control, including acts of God, fire, flood, government action, civil disturbance or any other force majeure event.

10.2 Where a force majeure event materially affects the use or habitability of the Property, the Parties shall negotiate in good faith a fair adjustment of their respective obligations.

## 11. DISPUTE RESOLUTION AND GOVERNING LAW
11.1 This Agreement shall be governed by and construed in accordance with the laws of the Federal Republic of Nigeria, including the Tenancy Law of Lagos State, 2011 (and any corresponding legislation applicable to the location of the Property).

11.2 Any dispute arising out of or in connection with this Agreement shall first be referred to the NuloAfrica platform's dispute-resolution process. If the dispute is not resolved within thirty (30) days, it shall be referred to arbitration in accordance with the Arbitration and Mediation Act, 2023, or, at the election of either Party, to a court of competent jurisdiction.

## 12. GENERAL PROVISIONS

12.1 **Entire Agreement.** This Agreement constitutes the entire agreement between the Parties with respect to its subject matter and supersedes all prior negotiations, representations and agreements, whether written or oral.

12.2 **Amendment.** No amendment or variation of this Agreement shall be valid unless made in writing and signed by both Parties.

12.3 **Notices.** Any notice required under this Agreement shall be in writing and may be delivered through the NuloAfrica platform messaging system or to the contact details of the Parties set out above.

12.4 **Severability.** If any provision of this Agreement is held to be invalid or unenforceable, the remaining provisions shall continue in full force and effect.

12.5 **Electronic Execution.** This Agreement is generated electronically upon approval of the Tenant's application and shall be executed by the Parties by way of electronic signature through the NuloAfrica platform. The Parties agree that such electronic signatures, together with their recorded timestamps and IP addresses, shall have the same legal effect as handwritten signatures.

## EXECUTION

**IN WITNESS WHEREOF** the Parties have executed this Agreement on the date first written above.

**SIGNED by the LANDLORD:**

Name: {landlord_name}

Signature: ______________________________

Date: ______________________________

**SIGNED by the TENANT:**

Name: {tenant_name}

Signature: ______________________________

Date: ______________________________

**In the presence of (WITNESS):**

Name: ______________________________

Signature: ______________________________

Date: ______________________________

---

*This document was generated electronically by the NuloAfrica platform on {_now.strftime('%d %B %Y at %H:%M')}. It is a legally binding agreement — both Parties should read it carefully before signing. The financial terms set out in Clauses 3, 4 and 5 prevail over any other figure stated elsewhere in this document.*
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
            # Resolved from platform policy (waived ₦0 by default; configurable
            # via AGREEMENT_SECURITY_DEPOSIT_PERCENT). Same helper the template
            # uses, so the DB row and the agreement text always agree.
            "deposit_amount": AgreementService.resolve_security_deposit(
                property_data.get("price", 0)
            )[0],
            "platform_fee": 0,  # MVP: Platform fee set to 0% for transparency
            "service_charge": 0,
            "payment_frequency": property_data.get("payment_frequency", "MONTHLY"),
            "terms": terms,
            "agreement_source": "deterministic_template",  # Updated after generation
            "generation_metadata": {},             # Updated after generation
            # Note: created_at and updated_at are auto-managed by database
        }
    
    @staticmethod
    async def auto_generate_agreement(
        application_id: str,
        property_data: Dict[str, Any],
        tenant_data: Dict[str, Any],
        landlord_name: str,
        propflow_workflow_id: Optional[str] = None,
        landlord_email: Optional[str] = None,
        landlord_phone: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Auto-generate agreement for approved application
        Enhanced with seamless AI integration

        Args:
            application_id: The approved application ID
            property_data: Property details dict
            tenant_data: Tenant user data dict
            landlord_name: Landlord's full name
            propflow_workflow_id: Optional LangGraph thread ID for PropFlow
                                  context-aware resume. When provided, it is
                                  stored in generation_metadata on the
                                  agreement row and linked via the
                                  application's propflow_thread_id.
        """
        try:
            logger.info(f"🔥 [AGREEMENT SERVICE] Auto-generating enhanced agreement for application {application_id}")

            # Calculate standard lease dates
            lease_dates = AgreementService.calculate_standard_lease_dates()

            # Generate enhanced agreement terms (deterministic template)
            terms_result = await AgreementService.generate_enhanced_agreement_terms(
                property_data=property_data,
                tenant_data=tenant_data,
                landlord_name=landlord_name,
                lease_dates=lease_dates,
                application={"id": application_id},
                landlord_email=landlord_email,
                landlord_phone=landlord_phone,
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
            metadata = terms_result["metadata"]
            if propflow_workflow_id:
                metadata["propflow_workflow_id"] = propflow_workflow_id
                agreement_dict["propflow_thread_id"] = propflow_workflow_id
            agreement_dict["generation_metadata"] = metadata
            
            logger.info(f"🔥 [AGREEMENT SERVICE] Inserting enhanced agreement (source: {terms_result['source']})")

            # Insert agreement into database
            agreement_response = await run_db_async(
                lambda: supabase_admin.table("agreements").insert(agreement_dict).execute()
            )

            if agreement_response.data:
                agreement_id = agreement_response.data[0]['id']
                logger.info(f"✅ [AGREEMENT SERVICE] Enhanced agreement {agreement_id} created ({terms_result['source']})")

                # ── Notification side-effect ────────────────────────────────────
                # Fire agreement-created notification so both tenant and landlord
                # get in-app + email alerts. This runs for both manual route and
                # PropFlow paths since both call this service.
                try:
                    from app.services.notification_service import notification_service
                    landlord_id = property_data.get("landlord_id", "")
                    await notification_service.notify_agreement_created(
                        agreement_id=agreement_id,
                        application_id=application_id,
                        property_title=property_data.get("title", "Property"),
                        tenant_id=tenant_data.get("id", ""),
                        tenant_name=tenant_data.get("full_name", "Tenant"),
                        tenant_email=tenant_data.get("email"),
                        tenant_phone=tenant_data.get("phone_number"),
                        landlord_id=landlord_id,
                        landlord_name=landlord_name,
                        landlord_email=landlord_email,
                        landlord_phone=landlord_phone,
                    )
                    logger.info(f"✅ [AGREEMENT SERVICE] Agreement notification sent for {agreement_id}")
                except Exception as notif_err:
                    logger.warning(f"⚠️ [AGREEMENT SERVICE] Agreement notification failed (non-fatal): {notif_err}")

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
