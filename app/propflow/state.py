"""
PropFlow State Schema
Strict TypedDict mapping 1:1 with NuloAfrica Postgres schema
"""

from typing import TypedDict, Optional, Literal
import uuid


class PropFlowState(TypedDict):
    # ── Cognitive Extraction (Qwen Output) ──────────────────────────────────
    raw_inquiry_text: str
    extracted_intent: Optional[dict]       # Structured JSON from Qwen
    extraction_confidence: Optional[float] # Gate: < 0.7 routes to clarification

    # ── Property Matching ────────────────────────────────────────────────────
    # Top candidates returned by match_properties node (up to 3)
    # Each item: { id, title, location, price, bedrooms, property_type }
    property_matches: Optional[list]
    selected_property_id: Optional[uuid.UUID]
    # How closely the matches fit the tenant's request:
    #   'neighbourhood' — found in the exact area asked for (true matches)
    #   'city'          — only found via city/area fallback (recommendations)
    #   'none'          — nothing found
    match_quality: Optional[str]

    # ── Application State Machine ────────────────────────────────────────────
    application_id: Optional[uuid.UUID]
    # CHECK ('submitted','under_review','approved','rejected','withdrawn')
    application_status: Optional[Literal[
        "submitted", "under_review", "approved", "rejected", "withdrawn"
    ]]

    # ── Agreement State Machine ──────────────────────────────────────────────
    agreement_id: Optional[uuid.UUID]
    # CHECK ('PENDING_TENANT','PENDING_LANDLORD','SIGNED','ACTIVE')
    agreement_status: Optional[Literal[
        "PENDING_TENANT", "PENDING_LANDLORD", "SIGNED", "ACTIVE"
    ]]
    # OSS key for the generated agreement PDF (Alibaba Cloud OSS)
    agreement_pdf_oss_key: Optional[str]

    # ── Nomba Monetary Infrastructure ────────────────────────────────────────
    nomba_account_ref: Optional[str]           # {agreement_id}-SUB
    nomba_virtual_account_number: Optional[str] # NUBAN shown to tenant
    expected_payment_amount: Optional[float]    # Decimal Naira (NOT kobo)

    # ── Reconciliation & Disbursement ────────────────────────────────────────
    reconciliation_status: Optional[Literal[
        "PENDING", "FULL_PAYMENT", "UNDERPAYMENT",
        "OVERPAYMENT", "MISDIRECTED", "DUPLICATE"
    ]]
    disbursement_merchant_tx_ref: Optional[str]

    # ── Mem0 Persistent Memory ───────────────────────────────────────────────
    # Memories retrieved at the start of extract_intent (returning tenant context)
    prior_tenant_memories: Optional[list]
    # Memories retrieved at enrich_and_qualify (landlord preferences)
    prior_landlord_memories: Optional[list]
    # Qwen-generated landlord briefing stored here + written to applications table
    landlord_briefing: Optional[str]
    # Flag: was this tenant seen before in Mem0?
    is_returning_tenant: Optional[bool]

    # ── Disbursement ─────────────────────────────────────────────────────────
    disbursement_amount: Optional[float]       # net amount sent to landlord
    platform_fee: Optional[float]             # 2% NuloAfrica platform fee
    rejection_reason: Optional[str]           # landlord rejection reason

    # ── Trust Passport (collected before create_application) ─────────────────
    # Trust data is NEVER assumed — the tenant explicitly provides it on the
    # in-chat Trust Passport card after selecting a property. These fields are
    # injected by POST /complete-application and read by create_application_node
    # which forwards them to application_service.submit_application().
    trust_documents: Optional[list]               # storage paths (≥2: identity + income)
    trust_references: Optional[dict]              # {reference1:{name,phone,relationship}, ...}
    trust_consent: Optional[bool]                 # "share these details with this landlord"
    trust_profile_completion: Optional[bool]     # True once the minimum is satisfied
    trust_employment_status: Optional[str]
    trust_employer_name: Optional[str]
    trust_job_title: Optional[str]
    trust_employment_duration: Optional[str]
    trust_monthly_income: Optional[int]
    trust_emergency_contact_name: Optional[str]
    trust_emergency_contact_phone: Optional[str]
    trust_phone_number: Optional[str]           # tenant contact — Google OAuth users
                                                # arrive without a phone, so the card
                                                # collects it and we persist to users.
    trust_move_in_date: Optional[str]
    trust_lease_duration: Optional[str]
    trust_number_of_occupants: Optional[int]
    trust_has_pets: Optional[bool]
    trust_pet_details: Optional[str]
    trust_message: Optional[str]
    # Honest status labels — Provided (uploaded) / Verified (validated) /
    # Confirmed (reference responded). We never claim more than is evidenced.
    document_verification_status: Optional[dict]  # {path: "provided"|"verified"|"confirmed"}
    reference_verification_status: Optional[dict] # {reference1: "provided"|...}

    # ── Multi-turn conversation transcript ────────────────────────────────────
    # List of {"role": "user"|"agent", "text": ...} turns for this thread. Lets a
    # follow-up like "search within 500k-600k" resolve against earlier messages
    # ("4-bed in Ajah") instead of being parsed in a vacuum. Only REAL turns are
    # stored — never fabricated. Seeded on each follow-up /chat call.
    conversation_history: Optional[list]

    # ── Metadata ─────────────────────────────────────────────────────────────
    workflow_id: str
    tenant_id: uuid.UUID   # maps to users.id
    landlord_id: Optional[uuid.UUID]  # populated after property match
    current_stage: str
    error_log: list[str]
