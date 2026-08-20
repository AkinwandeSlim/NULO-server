"""
PropFlow API Routes
===================
FastAPI endpoints for the PropFlow AI agent system.

Endpoints:
  POST /api/v1/propflow/chat          - Start new PropFlow conversation
  POST /api/v1/propflow/select/{id}   - Tenant selects a property from matches
  POST /api/v1/propflow/resume/{id}   - Resume workflow (landlord approval)
  GET  /api/v1/propflow/status/{id}   - Check workflow status
  GET  /api/v1/propflow/threads       - List threads (tenant/landlord multi-tenant)
  GET  /api/v1/propflow/health        - PropFlow health check
"""

import asyncio
import logging
import re
import traceback
import uuid
from typing import Dict, Any, Optional, List, ClassVar
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from app.middleware.auth import get_current_user
from app.database import get_supabase_admin
from app.propflow.graph import propflow_graph
from app.propflow.state import PropFlowState
from app.propflow.config import propflow_settings
from app.services.nomba_helpers import calculate_expected_amount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/propflow", tags=["PropFlow AI Agent"])

# Stages where an application/lease/payment is already in flight.
# /select must NEVER overwrite these — doing so would destroy an active
# lease, payment, or disbursement. Instead /select returns the existing
# stage so the client can render the correct next-step UI.
PROTECTED_SELECT_STAGES: frozenset[str] = frozenset({
    "application_created",
    "awaiting_landlord_approval",
    "agreement_drafted",
    "awaiting_landlord_signature",
    "nomba_provisioned",
    "payment_confirmed",
    "awaiting_full_payment",
    "disbursement_complete",
    "rejected",
})

# Sentinel tenant used for guest (unauthenticated) search-only runs. Search
# nodes (extract_intent / match_properties) never read tenant_id, and the
# graph pauses at INTERRUPT #1 before create_application, so a guest workflow
# never reaches any node that needs a real tenant. Guests are never resumed.
GUEST_TENANT_UUID = uuid.UUID(int=0)

# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    """Start new PropFlow conversation."""
    message: str = Field(..., description="User's rental inquiry message")
    use_memory: bool = Field(default=True, description="Whether to use persistent memory")
    mock_mode: bool = Field(default=False, description="Use mock responses (testing)")
    # Optional — pass the current thread's workflow_id on FOLLOW-UP messages so
    # the server loads the prior conversation transcript and resolves the new
    # message in context (e.g. "within 500k-600k" adjusts the earlier budget).
    workflow_id: Optional[str] = Field(
        default=None,
        description="Prior search thread to continue conversationally",
    )

class ChatResponse(BaseModel):
    """PropFlow chat response."""
    success: bool
    workflow_id: str
    current_stage: str
    response_message: str
    extracted_intent: Optional[Dict[str, Any]] = None
    matched_properties: Optional[list] = None
    application_id: Optional[str] = None
    error_message: Optional[str] = None

class ResumeRequest(BaseModel):
    """Resume PropFlow workflow — landlord decision OR tenant lease signing."""
    decision: str = Field(
        ...,
        description="'approved' or 'rejected' (landlord) | 'signed' (tenant)"
    )
    rejection_reason: Optional[str] = Field(None, description="Reason if rejected")

class ResumeResponse(BaseModel):
    """PropFlow resume response."""
    success: bool
    workflow_id: str
    current_stage: str
    response_message: str
    agreement_id: Optional[str] = None
    virtual_account_number: Optional[str] = None
    # Public URL of the draft agreement PDF (Supabase Storage, ownership-docs
    # bucket) — populated once create_agreement has uploaded the PDF so the
    # frontend can offer a download link without a page refresh.
    agreement_pdf_url: Optional[str] = None
    error_message: Optional[str] = None

class StatusResponse(BaseModel):
    """PropFlow workflow status."""
    success: bool
    workflow_id: str
    current_stage: str
    tenant_id: str
    created_at: datetime
    last_updated: datetime
    extracted_intent: Optional[Dict[str, Any]] = None
    selected_property_id: Optional[str] = None
    application_id: Optional[str] = None
    agreement_id: Optional[str] = None
    landlord_briefing: Optional[str] = None
    # Payment account info — populated once provision_nomba_dva has run so the
    # tenant's PropFlow chat can display the NUBAN + amount without a page refresh.
    virtual_account_number: Optional[str] = None
    expected_payment_amount: Optional[float] = None
    # Draft agreement PDF public URL (Supabase Storage) — populated once
    # create_agreement has uploaded the PDF.
    agreement_pdf_url: Optional[str] = None
    error_log: list[str] = []


class SelectRequest(BaseModel):
    """Tenant selects a property from matched results."""
    property_index: Optional[int] = Field(
        default=None, ge=0, description="Index of the selected property in the matches list (mutually exclusive with property_id)"
    )
    property_id: Optional[str] = Field(
        default=None, description="ID of the selected property (mutually exclusive with property_index)"
    )

    @model_validator(mode='after')
    def validate_mutually_exclusive(self) -> 'SelectRequest':
        """Ensure exactly one of property_index or property_id is provided."""
        has_index = self.property_index is not None
        has_id = self.property_id is not None
        if has_index and has_id:
            raise ValueError('Exactly one of property_index or property_id must be provided, not both')
        if not has_index and not has_id:
            raise ValueError('Either property_index or property_id must be provided')
        return self


class SelectResponse(BaseModel):
    """PropFlow property selection response."""
    success: bool
    workflow_id: str
    current_stage: str
    response_message: str
    application_id: Optional[str] = None
    error_message: Optional[str] = None


class CompleteApplicationRequest(BaseModel):
    """
    Trust Passport payload — the tenant's documents, references and consent,
    collected on the in-chat card BEFORE the application is created.

    Mirrors the Phase-2 ApplicationCreate validation so a submitted application
    means the same thing everywhere: ID + income proof + one reference + consent.
    """
    documents: list[str] = Field(..., description="Storage paths (≥2: identity + income evidence)")
    references: dict = Field(..., description="{reference1: {name, phone, relationship}, ...}")
    consent: bool = Field(..., description="Tenant authorises sharing details with this property's landlord")
    # Employment / emergency fields (optional — profile + intent fill gaps)
    employment_status: Optional[str] = None
    employer_name: Optional[str] = None
    job_title: Optional[str] = None
    employment_duration: Optional[str] = None
    monthly_income: Optional[int] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    # Tenant contact number — collected on the card because Google OAuth users
    # sign up with only name + email (no phone). We persist it to users.phone_number
    # so the landlord always has a reachable number. Basic sanity check only;
    # full validation (e.g. SMS OTP) is a later version.
    phone_number: Optional[str] = None
    move_in_date: Optional[str] = None
    lease_duration: Optional[str] = None
    number_of_occupants: Optional[int] = None
    has_pets: Optional[bool] = None
    pet_details: Optional[str] = None
    message: Optional[str] = None

    EMPLOYMENT_STATUSES: ClassVar[set[str]] = {'employed', 'self-employed', 'student', 'retired', 'unemployed'}

    @field_validator('documents')
    @classmethod
    def _validate_documents(cls, v: list) -> list:
        if not v or len(v) < 2:
            raise ValueError('Identity and proof-of-income documents are required (at least 2)')
        return v

    @field_validator('references')
    @classmethod
    def _validate_references(cls, v: dict) -> dict:
        if not v or 'reference1' not in v:
            raise ValueError('At least one reference (reference1) is required')
        ref1 = v.get('reference1') or {}
        if not ref1.get('name') or not ref1.get('phone'):
            raise ValueError('reference1 must have name and phone')
        return v

    @field_validator('consent')
    @classmethod
    def _validate_consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError('Tenant consent is required to share details with the landlord')
        return v

    @field_validator('employment_status')
    @classmethod
    def _validate_employment_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in cls.EMPLOYMENT_STATUSES:
            raise ValueError(f'employment_status must be one of {sorted(cls.EMPLOYMENT_STATUSES)}')
        return v

    @field_validator('number_of_occupants')
    @classmethod
    def _validate_occupants(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError('number_of_occupants must be at least 1')
        return v

    @field_validator('phone_number')
    @classmethod
    def _validate_phone_number(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        digits = re.sub(r'\D', '', v)
        if len(digits) < 7 or len(digits) > 15:
            raise ValueError('phone_number must be a valid phone number (7–15 digits)')
        return v


class ThreadInfoResponse(BaseModel):
    """Summary info for a PropFlow thread in multi-tenant listing."""
    thread_id: str
    tenant_id: str
    tenant_name: Optional[str] = None
    tenant_phone: Optional[str] = None
    landlord_id: Optional[str] = None
    property_title: Optional[str] = None
    current_stage: str = ""
    status: str = "active"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ThreadListResponse(BaseModel):
    """PropFlow thread list response."""
    success: bool
    threads: List[ThreadInfoResponse] = []
    total: int = 0
    error_message: Optional[str] = None

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

async def _load_conversation_history(
    graph, workflow_id: str, expected_tenant_id: str
) -> list:
    """
    Load a prior search thread's conversation transcript for a follow-up.

    Returns the stored conversation_history (or [] when the thread is unknown,
    so a stale client thread simply starts fresh). Verifies the thread belongs
    to the caller and NEVER returns another account's conversation.

    Args:
        graph: the compiled PropFlow graph (for its checkpointer).
        workflow_id: the thread to continue, or "" for a brand-new chat.
        expected_tenant_id: the caller's tenant id; "" disables the check
                            (guest threads share a sentinel tenant).
    """
    if not workflow_id:
        return []
    try:
        thread_config = {"configurable": {"thread_id": workflow_id}}
        saved = await graph.checkpointer.aget_tuple(thread_config)
        if not saved:
            logger.info(
                f"[PROPFLOW] Follow-up referenced unknown thread "
                f"{workflow_id[:16]}... — starting fresh"
            )
            return []
        prev = saved.checkpoint.get("channel_values", {})
        owner = str(prev.get("tenant_id", "") or "")
        if owner and expected_tenant_id and owner != expected_tenant_id:
            logger.warning(
                f"[PROPFLOW] Cross-tenant follow-up blocked: "
                f"caller={expected_tenant_id[:8]}... "
                f"thread_owner={owner[:8]}..."
            )
            return []  # never leak another account's transcript
        return list(prev.get("conversation_history") or [])
    except Exception as exc:
        logger.warning(f"[PROPFLOW] Failed to load conversation history: {exc}")
        return []


@router.post("/chat", response_model=ChatResponse)
async def start_propflow_chat(
    request: ChatRequest,
    current_user = Depends(get_current_user),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Start new PropFlow conversation.
    
    Process user's rental inquiry through the AI agent workflow:
    1. Extract intent (Qwen + Nigerian Pidgin support)
    2. Match properties (database search)
    3. Create application (if property found)
    4. Generate landlord briefing (Qwen AI)
    """
    try:
        # Validate user is tenant
        if current_user.get("user_type") != "tenant":
            raise HTTPException(
                status_code=403,
                detail="PropFlow is only available to tenants"
            )

        graph = propflow_graph()

        # ── Conversational follow-up ──────────────────────────────────────────
        # On follow-ups the client passes the current workflow_id. Load that
        # thread's transcript so Qwen can resolve the new message in context
        # (e.g. "within 500k-600k" adjusts the earlier 4-bed/Ajah budget).
        conversation_history = await _load_conversation_history(
            graph, request.workflow_id or "", current_user["id"]
        )
        conversation_history = (
            conversation_history + [{"role": "user", "text": request.message}]
        )[-20:]  # keep the last ~10 exchanges; transcript must never grow unbounded

        # Create initial PropFlow state
        workflow_id = f"propflow-{uuid.uuid4().hex[:12]}"

        initial_state = PropFlowState(
            workflow_id=workflow_id,
            tenant_id=uuid.UUID(current_user["id"]),
            raw_inquiry_text=request.message,  # ✅ Correct field name
            current_stage="intent_extraction",
            error_log=[],
            conversation_history=conversation_history,
            # Initialize all optional fields as None
            extracted_intent=None,
            extraction_confidence=None,
            prior_intent=None,  # For relaxation request tracking
            is_relaxation_request=None,
            property_matches=None,
            selected_property_id=None,
            application_id=None,
            application_status=None,
            agreement_id=None,
            agreement_status=None,
            agreement_pdf_storage_key=None,
            agreement_pdf_url=None,
            nomba_account_ref=None,
            nomba_virtual_account_number=None,
            expected_payment_amount=None,
            reconciliation_status=None,
            disbursement_merchant_tx_ref=None,
            prior_tenant_memories=None,
            prior_landlord_memories=None,
            landlord_briefing=None,
            is_returning_tenant=None,
            disbursement_amount=None,
            platform_fee=None,
            rejection_reason=None,
            landlord_id=None,
            trust_documents=None,
            trust_references=None,
            trust_consent=None,
            trust_profile_completion=None,
            trust_employment_status=None,
            trust_employer_name=None,
            trust_job_title=None,
            trust_employment_duration=None,
            trust_monthly_income=None,
            trust_emergency_contact_name=None,
            trust_emergency_contact_phone=None,
            trust_phone_number=None,
            trust_move_in_date=None,
            trust_lease_duration=None,
            trust_number_of_occupants=None,
            trust_has_pets=None,
            trust_pet_details=None,
            trust_message=None,
            document_verification_status=None,
            reference_verification_status=None,
        )
        
        print(f"[PROPFLOW] Starting workflow {workflow_id} for user {current_user['id']}")
        print(f"📝 [PROPFLOW] User message: {request.message}")
        
        # Process through PropFlow graph
        if request.mock_mode:
            print("[PROPFLOW] Running in MOCK MODE")
            
        config = {"configurable": {"thread_id": workflow_id}}
        result = await graph.ainvoke(initial_state, config=config)

        print(f"[PROPFLOW] Workflow completed: {result['current_stage']}")

        # Generate response message based on current stage
        response_message = await _generate_response_message(result)

        # Persist the assistant's reply so the NEXT follow-up has full context.
        # Best-effort — if this fails, the user turn is still in the transcript.
        try:
            graph.update_state(
                {"configurable": {"thread_id": workflow_id}},
                {
                    "conversation_history": conversation_history
                    + [{"role": "agent", "text": response_message}],
                },
            )
        except Exception as exc:
            logger.warning(f"[PROPFLOW] Failed to persist conversation history: {exc}")

        return ChatResponse(
            success=True,
            workflow_id=workflow_id,
            current_stage=result["current_stage"],
            response_message=response_message,
            extracted_intent=result.get("extracted_intent"),
            matched_properties=result.get("property_matches"),  # ✅ Correct field name
            application_id=str(result["application_id"]) if result.get("application_id") else None,
        )
        
    except Exception as e:
        print(f"[PROPFLOW] Chat failed: {e}")
        traceback.print_exc()
        return ChatResponse(
            success=False,
            workflow_id=workflow_id if 'workflow_id' in locals() else "unknown",
            current_stage="error",
            response_message="I'm sorry, I encountered an error processing your request. Please try again.",
            error_message=str(e)
        )


@router.post("/chat/guest", response_model=ChatResponse)
async def guest_search(request: ChatRequest):
    """
    Guest (unauthenticated) search-only PropFlow conversation.

    Runs ONLY the search portion of the graph (extract_intent -> match_properties);
    the compiled graph pauses on its own at INTERRUPT #1
    (interrupt_before create_application), so no application / money path
    is reachable. Property selection requires /select, which stays auth-gated.

    NOTE: This endpoint spends ~3 Qwen calls + 1 Supabase read per request,
    unauthenticated. Rate-limiting by IP is a known follow-up before wide
    production exposure.
    """
    try:
        graph = propflow_graph()

        # Guests get the same conversational follow-up support: load the prior
        # guest thread's transcript so a refinement resolves in context.
        # No ownership check needed — guest threads share the sentinel tenant.
        conversation_history = await _load_conversation_history(
            graph, request.workflow_id or "", ""
        )
        conversation_history = (
            conversation_history + [{"role": "user", "text": request.message}]
        )[-20:]

        workflow_id = f"propflow-guest-{uuid.uuid4().hex[:12]}"

        initial_state = PropFlowState(
            workflow_id=workflow_id,
            tenant_id=GUEST_TENANT_UUID,
            raw_inquiry_text=request.message,
            current_stage="intent_extraction",
            error_log=[],
            conversation_history=conversation_history,
            extracted_intent=None,
            extraction_confidence=None,
            prior_intent=None,  # For relaxation request tracking
            is_relaxation_request=None,
            property_matches=None,
            selected_property_id=None,
            application_id=None,
            application_status=None,
            agreement_id=None,
            agreement_status=None,
            agreement_pdf_storage_key=None,
            agreement_pdf_url=None,
            nomba_account_ref=None,
            nomba_virtual_account_number=None,
            expected_payment_amount=None,
            reconciliation_status=None,
            disbursement_merchant_tx_ref=None,
            prior_tenant_memories=None,
            prior_landlord_memories=None,
            landlord_briefing=None,
            is_returning_tenant=None,
            disbursement_amount=None,
            platform_fee=None,
            rejection_reason=None,
            landlord_id=None,
            trust_documents=None,
            trust_references=None,
            trust_consent=None,
            trust_profile_completion=None,
            trust_employment_status=None,
            trust_employer_name=None,
            trust_job_title=None,
            trust_employment_duration=None,
            trust_monthly_income=None,
            trust_emergency_contact_name=None,
            trust_emergency_contact_phone=None,
            trust_phone_number=None,
            trust_move_in_date=None,
            trust_lease_duration=None,
            trust_number_of_occupants=None,
            trust_has_pets=None,
            trust_pet_details=None,
            trust_message=None,
            document_verification_status=None,
            reference_verification_status=None,
        )

        config = {"configurable": {"thread_id": workflow_id}}
        result = await graph.ainvoke(initial_state, config=config)

        response_message = await _generate_response_message(result)

        # Persist the assistant's reply so the next guest follow-up has context.
        try:
            graph.update_state(
                {"configurable": {"thread_id": workflow_id}},
                {
                    "conversation_history": conversation_history
                    + [{"role": "agent", "text": response_message}],
                },
            )
        except Exception as exc:
            logger.warning(f"[PROPFLOW] Failed to persist guest conversation history: {exc}")

        return ChatResponse(
            success=True,
            workflow_id=workflow_id,
            current_stage=result["current_stage"],
            response_message=response_message,
            extracted_intent=result.get("extracted_intent"),
            matched_properties=result.get("property_matches"),
        )
    except Exception as e:
        print(f"[PROPFLOW] Guest search failed: {e}")
        traceback.print_exc()
        return ChatResponse(
            success=False,
            workflow_id="unknown",
            current_stage="error",
            response_message=(
                "I'm sorry, I encountered an error processing your request. "
                "Please try again."
            ),
            error_message=str(e),
        )


@router.post("/select/{workflow_id}", response_model=SelectResponse)
async def select_property(
    workflow_id: str,
    request: SelectRequest,
    current_user = Depends(get_current_user),
):
    """
    Tenant selects a property from the matched results list.

    Records the selection on the paused state but does NOT resume the graph:
    the workflow now waits at the Trust Passport gate (awaiting_trust_profile).
    The application is only created once the tenant completes the trust checks
    via POST /complete-application/{workflow_id}.

    Enhanced to support property_id selection alongside property_index, with
    multiple resolution paths:
    1. Index-based (existing - backward compatible)
    2. State-based (from current thread's matched_properties)
    3. Direct DB lookup (when property_id provided)
    4. Thread resurrection (if thread missing/expired)
    """
    try:
        graph = propflow_graph()
        thread_config = {"configurable": {"thread_id": workflow_id}}

        # Step 1: Get property_matches directly from checkpoint (get_state
        # can lose channel_values during reconstruction — read raw instead).
        # Use async aget_tuple so httpx (not requests.Session) handles SSL.
        saved = await graph.checkpointer.aget_tuple(thread_config)
        channel_values: dict = {}
        if saved:
            channel_values = saved.checkpoint.get("channel_values", {})
            matches = channel_values.get("property_matches", []) or []
        else:
            matches = []

        # ENHANCED: Multiple resolution paths based on which parameter was provided
        selected = None
        selected_id = None
        landlord_id = None

        if request.property_id:
            # Path 2/3/4: property_id provided - use robust resolution
            logger.info(f"[PROPFLOW] Property selection via property_id: {request.property_id}")

            # Validate property_id is a valid UUID
            try:
                uuid.UUID(request.property_id)
            except ValueError:
                return SelectResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message="Invalid property ID format.",
                    error_message=f"property_id {request.property_id} is not a valid UUID",
                )

            # Path 2: Try state-based resolution (property_id in current matches)
            if matches:
                selected = next((m for m in matches if m.get("id") == request.property_id), None)
                if selected:
                    logger.info(f"[PROPFLOW] Property resolved from current thread state")

            # Path 3: Direct DB lookup as primary fallback (simpler than resurrection)
            if not selected:
                logger.info(f"[PROPFLOW] Attempting direct database lookup for property_id: {request.property_id}")
                from app.database import get_supabase_admin
                try:
                    supabase = get_supabase_admin()
                    response = supabase.from_("properties").select(
                        "id, title, location, price, beds, baths, images, landlord_id, property_type, virtual_tour_url"
                    ).eq("id", request.property_id).single().execute()

                    if hasattr(response, 'data') and response.data:
                        selected = response.data
                        logger.info(f"[PROPFLOW] Property found via direct database lookup")
                    else:
                        logger.warning(f"[PROPFLOW] Property not found in database: {request.property_id}")
                except Exception as e:
                    logger.error(f"[PROPFLOW] Database lookup failed: {e}")

            # Path 4: Thread resurrection (only if DB lookup also failed and thread exists)
            if not selected and saved:
                logger.info(f"[PROPFLOW] Attempting thread resurrection for property_id: {request.property_id}")
                from app.propflow.checkpointer import get_checkpointer
                checkpointer = get_checkpointer()

                # Attempt to resurrect the thread at Trust Passport gate
                resurrected = await checkpointer.resurrect_thread(
                    thread_id=workflow_id,
                    tenant_id=str(current_user["id"]),
                    target_property_id=request.property_id,
                    target_property_index=request.property_index
                )

                if resurrected:
                    # Thread resurrected - check if it has the property in matches
                    resurrected_channel_values = resurrected.get("channel_values", {})
                    resurrected_matches = resurrected_channel_values.get("property_matches", []) or []

                    for match in resurrected_matches:
                        if match.get("id") == request.property_id:
                            selected = match
                            matches = resurrected_matches  # Use matches from resurrected thread
                            logger.info(f"[PROPFLOW] Property found in resurrected thread")
                            break
                else:
                    logger.warning(f"[PROPFLOW] Thread resurrection failed")

            if not selected:
                return SelectResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message=f"Property not found or access denied.",
                    error_message=f"Could not resolve property_id {request.property_id} via any path",
                )
        else:
            # Path 1: Original index-based logic (backward compatible)
            logger.info(f"[PROPFLOW] Property selection via index: {request.property_index}")

            if not matches:
                return SelectResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message="No properties found to select from. Please start a new search.",
                    error_message="No property_matches in workflow state",
                )

            if request.property_index < 0 or request.property_index >= len(matches):
                return SelectResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message=f"Invalid selection. Please choose between 1 and {len(matches)}.",
                    error_message=f"property_index {request.property_index} out of range (0-{len(matches)-1})",
                )

            # Get the selected property
            selected = matches[request.property_index]

        # Step 2: Validate and get the selected property with defensive checks
        if not selected:
            return SelectResponse(
                success=False,
                workflow_id=workflow_id,
                current_stage="error",
                response_message="Property selection failed. Please try again.",
                error_message="Selected property is None or invalid",
            )
        
        # Ensure selected has required fields
        if not isinstance(selected, dict):
            logger.error(f"[PROPFLOW] Selected property is not a dict: {type(selected)}")
            return SelectResponse(
                success=False,
                workflow_id=workflow_id,
                current_stage="error",
                response_message="Property data format error. Please try again.",
                error_message=f"Selected property has invalid type: {type(selected)}",
            )
        
        if "id" not in selected:
            logger.error(f"[PROPFLOW] Selected property missing 'id' field: {selected}")
            return SelectResponse(
                success=False,
                workflow_id=workflow_id,
                current_stage="error",
                response_message="Property identification error. Please try again.",
                error_message="Selected property missing 'id' field",
            )
        
        selected_id = uuid.UUID(selected["id"])
        landlord_id = uuid.UUID(selected["landlord_id"]) if selected.get("landlord_id") else None

        # ── Protected-stage guard ──────────────────────────────────────────
        # If the thread already has an active application / lease / payment
        # in flight, do NOT overwrite the stage. Return the existing state so
        # the client can render the correct next-step UI instead of reopening
        # the Trust Passport.
        current_stage = channel_values.get("current_stage", "")
        existing_application_id = channel_values.get("application_id")
        if current_stage in PROTECTED_SELECT_STAGES:
            logger.info(
                f"[PROPFLOW] Select blocked: thread {workflow_id[:16]}... "
                f"is at protected stage '{current_stage}'"
            )
            if current_stage == "disbursement_complete":
                msg = "This tenancy is already active and complete."
            elif current_stage == "rejected":
                msg = (
                    "Your application for this property was not approved. "
                    "You can start a fresh search to find other properties."
                )
            else:
                msg = (
                    "You already have an application in progress for this "
                    "property. Continue from where you left off."
                )
            return SelectResponse(
                success=True,
                workflow_id=workflow_id,
                current_stage=current_stage,
                response_message=msg,
                application_id=str(existing_application_id) if existing_application_id else None,
            )

        # Step 3: Inject selection into the paused state — pause at the Trust
        # Passport gate instead of resuming to create_application.
        graph.update_state(
            thread_config,
            {
                "selected_property_id": selected_id,
                "landlord_id": landlord_id,
                "current_stage": "awaiting_trust_profile",
            },
        )

        beds = selected.get("beds", "?")
        ptype = selected.get("property_type") or "property"
        # Honest message — we only claim what this user actually has. Google OAuth
        # tenants arrive with name + email only (no phone, no employment details),
        # so never claim them. Employment is never known at select time either.
        has_phone = bool(current_user.get("phone_number"))
        greeting = f"Great choice! You're almost ready to apply for this {beds}-bed {ptype}."
        if has_phone:
            response_message = (
                f"{greeting} We already have your name and phone. "
                f"Complete the trust checks below to submit."
            )
        else:
            response_message = (
                f"{greeting} We have your name — you'll add your phone number "
                f"and complete the trust checks below to submit."
            )

        return SelectResponse(
            success=True,
            workflow_id=workflow_id,
            current_stage="awaiting_trust_profile",
            response_message=response_message,
            application_id=None,
        )

    except Exception as e:
        print(f"[ERROR] [PROPFLOW] Select failed: {e}")
        return SelectResponse(
            success=False,
            workflow_id=workflow_id,
            current_stage="error",
            response_message="Failed to process your property selection. Please try again.",
            error_message=str(e),
        )


@router.post("/complete-application/{workflow_id}", response_model=SelectResponse)
async def complete_application(
    workflow_id: str,
    request: CompleteApplicationRequest,
    current_user = Depends(get_current_user),
):
    """
    Trust Passport gate — tenant submits documents, references and consent
    collected on the in-chat card, then the workflow resumes and the
    application is created WITH the trust data attached.

    Steps:
      1. Verify the workflow is paused at awaiting_trust_profile
      2. Inject the trust fields into the paused state
      3. Resume the graph -> create_application (reads trust fields from state)
         -> enrich_and_qualify -> pauses at INTERRUPT #2 (landlord approval)
    """
    try:
        graph = propflow_graph()
        thread_config = {"configurable": {"thread_id": workflow_id}}

        # Step 1: Load the paused state from the checkpointer
        saved = await graph.checkpointer.aget_tuple(thread_config)
        if not saved:
            return SelectResponse(
                success=False,
                workflow_id=workflow_id,
                current_stage="expired",
                response_message="Workflow not found. Please start a new search.",
                error_message="No checkpoint found for this thread_id",
            )

        channel_values = saved.checkpoint.get("channel_values", {})
        if channel_values.get("current_stage") != "awaiting_trust_profile":
            return SelectResponse(
                success=False,
                workflow_id=workflow_id,
                current_stage="error",
                response_message="This workflow is not waiting for trust details.",
                error_message=(
                    f"Expected current_stage 'awaiting_trust_profile', got "
                    f"'{channel_values.get('current_stage')}'"
                ),
            )

        # Role check: only the workflow's tenant may complete their own trust
        # passport (mirrors the resume endpoint's gate verification).
        workflow_tenant_id = str(channel_values.get("tenant_id", ""))
        if current_user.get("user_type") != "tenant" or current_user["id"] != workflow_tenant_id:
            return SelectResponse(
                success=False,
                workflow_id=workflow_id,
                current_stage="error",
                response_message="Only the tenant who started this application can submit their trust details.",
                error_message=(
                    f"Role verification failed at trust gate: "
                    f"caller={current_user['id']} ({current_user.get('user_type')}) "
                    f"≠ workflow_tenant={workflow_tenant_id}"
                ),
            )

        # Step 2: Inject the trust fields into the paused state
        doc_status = {p: "provided" for p in request.documents}
        ref_status = {k: "provided" for k in request.references.keys()}

        graph.update_state(
            thread_config,
            {
                "trust_documents": request.documents,
                "trust_references": request.references,
                "trust_consent": request.consent,
                "trust_profile_completion": True,
                "trust_employment_status": request.employment_status,
                "trust_employer_name": request.employer_name,
                "trust_job_title": request.job_title,
                "trust_employment_duration": request.employment_duration,
                "trust_monthly_income": request.monthly_income,
                "trust_emergency_contact_name": request.emergency_contact_name,
                "trust_emergency_contact_phone": request.emergency_contact_phone,
                "trust_phone_number": request.phone_number,
                "trust_move_in_date": request.move_in_date,
                "trust_lease_duration": request.lease_duration,
                "trust_number_of_occupants": request.number_of_occupants,
                "trust_has_pets": request.has_pets,
                "trust_pet_details": request.pet_details,
                "trust_message": request.message,
                "document_verification_status": doc_status,
                "reference_verification_status": ref_status,
                "current_stage": "property_selected",
            },
        )

        logger.info(
            f"[PROPFLOW][TRUST] workflow={workflow_id} docs={len(request.documents)} "
            f"refs={len(request.references)} consent={request.consent}"
        )

        # Step 3: Resume the graph -> create_application + enrich_and_qualify,
        # pauses at INTERRUPT #2 (landlord approval).
        result = await graph.ainvoke(None, config=thread_config)

        response_message = await _generate_response_message(result)

        return SelectResponse(
            success=True,
            workflow_id=workflow_id,
            current_stage=result.get("current_stage", "unknown"),
            response_message=response_message,
            application_id=str(result.get("application_id")) if result.get("application_id") else None,
        )

    except Exception as e:
        print(f"[ERROR] [PROPFLOW] Complete-application failed: {e}")
        return SelectResponse(
            success=False,
            workflow_id=workflow_id,
            current_stage="error",
            response_message="Failed to submit your application. Please try again.",
            error_message=str(e),
        )


@router.post("/resume/{workflow_id}", response_model=ResumeResponse)
async def resume_propflow_workflow(
    workflow_id: str,
    request: ResumeRequest,
    current_user = Depends(get_current_user)
):
    """
    Resume a paused PropFlow workflow.
    Smart detection of which INTERRUPT the graph is paused at:

    INTERRUPT #2 (before create_agreement) — Landlord decision:
        { decision: "approved" }
        { decision: "rejected", rejection_reason: "..." }

    INTERRUPT #3 (before provision_nomba_dva) — Tenant signing:
        { decision: "signed" }
    """
    try:
        graph = propflow_graph()
        thread_config = {"configurable": {"thread_id": workflow_id}}

        # Step 1: Read workflow state from checkpoint directly (get_state()
        # can lose channel_values during reconstruction — read raw instead).
        # Use async aget_tuple so httpx (not requests.Session) handles SSL.
        saved = await graph.checkpointer.aget_tuple(thread_config)
        if not saved:
            return ResumeResponse(
                success=False,
                workflow_id=workflow_id,
                current_stage="expired",
                response_message="Workflow not found or has expired.",
                error_message="No checkpoint found for this thread_id",
            )

        channel_values = saved.checkpoint.get("channel_values", {})
        workflow_stage = channel_values.get("current_stage", "")
        if not workflow_stage or workflow_stage in ("idle", "unknown"):
            return ResumeResponse(
                success=False,
                workflow_id=workflow_id,
                current_stage="expired",
                response_message=(
                    "This PropFlow session has expired — the server was restarted, "
                    "which cleared in-progress workflows. "
                    "You can still review this application from the Applications page."
                ),
                error_message="Workflow state not found in checkpointer (MemorySaver lost on restart)",
            )

        # Step 2: Determine which interrupt we're at
        # Use current_stage from channel_values for gate detection.
        # next_nodes is intentionally empty — versions_seen.keys() would give
        # ALL nodes, not just the next one. current_stage fallback is reliable.
        next_nodes: list[str] = []
        is_at_landlord_gate = workflow_stage == "awaiting_landlord_approval"
        is_at_signing_gate = workflow_stage in ("agreement_drafted", "awaiting_landlord_signature")
        is_at_payment_gate = workflow_stage in ("nomba_provisioned", "payment_confirmed")

        print(f"🏠 [PROPFLOW] Resume for {workflow_id}: decision={request.decision}, "
              f"next_nodes={next_nodes}, workflow_stage={workflow_stage}")

        # Role verification
        workflow_tenant_id = str(channel_values.get("tenant_id", ""))
        workflow_landlord_id = str(channel_values.get("landlord_id", ""))
        caller_id = current_user["id"]
        caller_type = current_user.get("user_type", "")

        # ── ROLE VERIFICATION ────────────────────────────────────────────────
        # Each gate requires specific role matching — the caller must be the
        # correct party (landlord or tenant) for the workflow they're resuming.
        # These checks prevent any authenticated user from acting on any thread.
        # ──────────────────────────────────────────────────────────────────────

        # Step 3: Handle based on which gate we're at
        if is_at_landlord_gate:
            # ── ROLE CHECK: Only workflow landlord can approve/reject ──────
            if caller_type != "landlord" or caller_id != workflow_landlord_id:
                return ResumeResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message="Only the landlord assigned to this application can approve or reject it.",
                    error_message=(
                        f"Role verification failed at landlord gate: "
                        f"caller={caller_id} ({caller_type}) "
                        f"≠ workflow_landlord={workflow_landlord_id}"
                    ),
                )

            # ── LANDLORD APPROVAL / REJECTION ─────────────────────────────
            if request.decision == "approved":
                graph.update_state(
                    thread_config,
                    {"application_status": "approved"}
                )
                # Fire notification via existing service
                try:
                    await _notify_application_decision(
                        str(channel_values.get("application_id", "")),
                        str(channel_values.get("selected_property_id", "")),
                        "approved",
                        landlord_name=current_user.get("full_name", "Landlord"),
                    )
                except Exception as notify_err:
                    print(f"PROPFLOW Approval notification failed: {notify_err}")
            elif request.decision == "rejected":
                graph.update_state(
                    thread_config,
                    {
                        "application_status": "rejected",
                        "rejection_reason": request.rejection_reason or "Not specified by landlord",
                        "current_stage": "rejected",
                    }
                )
                # Fall through to graph.ainvoke(None) below, which will execute
                # create_agreement_node. The guard there will detect
                # application_status != "approved", set current_stage="rejected",
                # and the graph's conditional edge _route_after_agreement will
                # route to END (cleanly terminating rather than proceeding to
                # Nomba DVA provisioning).
            else:
                return ResumeResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message="Invalid decision. Use 'approved' or 'rejected'.",
                    error_message=f"Got '{request.decision}' expected 'approved' or 'rejected'",
                )

        elif is_at_signing_gate:
            # ── ROLE CHECK: Only workflow tenant or landlord can sign ─────
            is_tenant_signing = caller_type == "tenant" and caller_id == workflow_tenant_id
            is_landlord_signing = caller_type == "landlord" and caller_id == workflow_landlord_id
            if not (is_tenant_signing or is_landlord_signing):
                return ResumeResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message="Only the tenant or landlord involved in this application can sign the lease.",
                    error_message=(
                        f"Role verification failed at signing gate: "
                        f"caller={caller_id} ({caller_type}) "
                        f"∉ [workflow_tenant={workflow_tenant_id}, workflow_landlord={workflow_landlord_id}]"
                    ),
                )

            # ── TENANT / LANDLORD SIGNS LEASE ──────────────────────────────
            # Uses the existing agreement_service.sign_agreement() which handles:
            #   Tenant signs  → tenant_signed_at set → status = PENDING_LANDLORD
            #   Landlord signs → landlord_signed_at set → status = SIGNED
            # Graph only resumes when BOTH parties have signed.
            if request.decision != "signed":
                return ResumeResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message="Invalid decision. Use 'signed' to confirm lease signing.",
                    error_message=f"Got '{request.decision}' expected 'signed'",
                )

            agreement_id = str(channel_values.get("agreement_id", ""))
            if not agreement_id:
                return ResumeResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message="No agreement found to sign.",
                    error_message="agreement_id missing from paused state",
                )

            from app.services.agreement_service import agreement_service

            sign_result = await agreement_service.sign_agreement(
                agreement_id=agreement_id,
                user_id=current_user["id"],
                user_type=current_user.get("user_type", "tenant"),
            )

            if not sign_result:
                return ResumeResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message="Failed to sign the agreement. Please try again.",
                    error_message="sign_agreement returned None",
                )

            new_status = sign_result.get("status", "")

            if new_status == "SIGNED":
                # Both parties signed → resume the graph.
                # as_node="create_agreement" is critical: without it, update_state
                # consumes the pending interrupt at provision_nomba_dva and the
                # subsequent ainvoke(None) becomes a silent no-op, leaving the
                # thread permanently stuck at the signing gate.
                await graph.aupdate_state(
                    thread_config,
                    {"agreement_status": "SIGNED"},
                    as_node="create_agreement",
                )
            else:
                # Only tenant signed → PENDING_LANDLORD, wait for landlord
                return ResumeResponse(
                    success=True,
                    workflow_id=workflow_id,
                    current_stage="awaiting_landlord_signature",
                    response_message="You've signed the lease agreement! Waiting for the landlord to countersign. You'll be notified once it's complete.",
                )
        elif is_at_payment_gate:
            # ── ROLE CHECK: Only workflow landlord can confirm payment ────
            if caller_type != "landlord" or caller_id != workflow_landlord_id:
                return ResumeResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message="Only the landlord assigned to this application can confirm payment.",
                    error_message=(
                        f"Role verification failed at payment gate: "
                        f"caller={caller_id} ({caller_type}) "
                        f"≠ workflow_landlord={workflow_landlord_id}"
                    ),
                )

            # PAYMENT CONFIRMATION (landlord confirms tenant paid)
            if request.decision != "confirm_payment":
                return ResumeResponse(
                    success=False,
                    workflow_id=workflow_id,
                    current_stage="error",
                    response_message="Use 'confirm_payment' to confirm the tenant has paid.",
                    error_message=f"Got '{request.decision}' expected 'confirm_payment'",
                )
            # Payment confirmed — fetch the reconciliation_status from database and inject into state
            # so disburse_landlord_node can see FULL_PAYMENT
            print(f"[PROPFLOW] Payment confirmed for {workflow_id} — resuming graph")

            try:
                agreement_id = channel_values.get("agreement_id")
                if agreement_id:
                    loop = asyncio.get_event_loop()
                    supabase_admin = get_supabase_admin()
                    agreement_result = await loop.run_in_executor(
                        None,
                        lambda: supabase_admin.table("agreements")
                        .select("reconciliation_status, total_received_amount")
                        .eq("id", str(agreement_id))
                        .maybe_single()
                        .execute(),
                    )
                    agreement_data = agreement_result.data
                    if agreement_data:
                        # Inject the database reconciliation_status into the workflow state
                        print(f"[PROPFLOW] Injecting reconciliation_status={agreement_data.get('reconciliation_status')} from database")
                        graph.update_state(
                            thread_config,
                            {
                                "reconciliation_status": agreement_data.get("reconciliation_status"),
                                "total_received_amount": agreement_data.get("total_received_amount"),
                            },
                        )
            except Exception as exc:
                logger.warning(f"[PROPFLOW] Could not inject reconciliation_status: {exc}")

        else:
            # ---- UNKNOWN STATE (fallback) ----
            # The current_stage-based fallback above should catch most cases.
            # If we still land here, the workflow is at a stage that genuinely
            # doesn't support the requested decision.
            current_stage = channel_values.get("current_stage", "unknown")
            stage_hints = {
                "intent_extraction": "still processing the tenant's search request",
                "awaiting_tenant_selection": "waiting for the tenant to select a property",
                "awaiting_trust_profile": "waiting for the tenant to complete the trust checks before the application is submitted",
                "property_selected": "processing property selection",
                "application_created": "preparing the landlord briefing",
                "enrich_and_qualify": "generating the AI briefing for the landlord",
                "agreement_drafted": "lease agreement created — tenant needs to sign first",
                "awaiting_landlord_signature": "tenant signed — landlord must sign via Agreements page",
                "nomba_provisioned": "payment account created — awaiting tenant payment",
                "payment_confirmed": "payment received — awaiting landlord release",
                "awaiting_full_payment": "awaiting payment confirmation",
                "disbursement_complete": "this tenancy is already active",
                "rejected": "this application was already rejected",
                "expired": "this session has expired",
            }
            hint = stage_hints.get(current_stage, f"at stage '{current_stage}'")
            return ResumeResponse(
                success=False,
                workflow_id=workflow_id,
                current_stage=current_stage,
                response_message=f"Workflow is {hint} and cannot process '{request.decision}' here.",
                error_message=f"No matching interrupt gate. next_nodes={next_nodes}, current_stage={current_stage}",
            )

        # Step 4: Resume the graph
        result = await graph.ainvoke(None, config=thread_config)
        response_message = await _generate_response_message(result)

        return ResumeResponse(
            success=True,
            workflow_id=workflow_id,
            current_stage=result.get("current_stage", "unknown"),
            response_message=response_message,
            agreement_id=str(result["agreement_id"]) if result.get("agreement_id") else None,
            virtual_account_number=result.get("nomba_virtual_account_number"),
            agreement_pdf_url=result.get("agreement_pdf_url"),
        )

    except Exception as e:
        print(f"[ERROR] [PROPFLOW] Resume failed: {e}")
        return ResumeResponse(
            success=False,
            workflow_id=workflow_id,
            current_stage="error",
            response_message="Failed to process your request. Please try again.",
            error_message=str(e),
        )

@router.get("/status/{workflow_id}", response_model=StatusResponse)
async def get_propflow_status(
    workflow_id: str,
    current_user = Depends(get_current_user)
):
    """Get current status of PropFlow workflow from the persistent checkpointer."""
    try:
        graph = propflow_graph()
        thread_config = {"configurable": {"thread_id": workflow_id}}

        try:
            state = graph.get_state(thread_config)
        except Exception:
            return StatusResponse(
                success=False,
                workflow_id=workflow_id,
                current_stage="not_found",
                tenant_id=current_user["id"],
                created_at=datetime.utcnow(),
                last_updated=datetime.utcnow(),
                error_log=["Workflow not found in checkpointer"],
            )

        values = state.values
        workflow_stage = values.get("current_stage", "")
        if not workflow_stage or workflow_stage in ("idle", "unknown"):
            # MemorySaver was wiped on restart — empty default returned
            return StatusResponse(
                success=False,
                workflow_id=workflow_id,
                current_stage="expired",
                tenant_id=current_user["id"],
                created_at=datetime.utcnow(),
                last_updated=datetime.utcnow(),
                error_log=["Workflow expired — server restart cleared in-progress state"],
            )

        # ── Safety net: SIGNED + existing VA must never render as awaiting
        #    landlord signature. If the graph checkpoint is stale (e.g. the
        #    sign→advance sync failed mid-flight), correct the stage from the
        #    agreement row, which is the source of truth. Only runs for the
        #    two signing-gate stages so normal status polls pay no extra cost.
        if workflow_stage in ("awaiting_landlord_signature", "agreement_drafted"):
            agreement_id = values.get("agreement_id")
            if agreement_id:
                try:
                    loop = asyncio.get_event_loop()
                    sb = get_supabase_admin()
                    agr_result = await loop.run_in_executor(
                        None,
                        lambda: sb.table("agreements")
                        .select(
                            "status, virtual_account_number, "
                            "virtual_account_name, expected_payment_amount"
                        )
                        .eq("id", str(agreement_id))
                        .maybe_single()
                        .execute(),
                    )
                    agr = agr_result.data
                    if (
                        agr
                        and str(agr.get("status", "")).upper() == "SIGNED"
                        and agr.get("virtual_account_number")
                    ):
                        # Agreement is fully signed AND already has a VA — the
                        # thread is past the signing gate. Correct the stage and
                        # backfill the VA so the chat shows the payment card.
                        values = {
                            **values,
                            "current_stage": "nomba_provisioned",
                            "nomba_virtual_account_number": agr["virtual_account_number"],
                            "expected_payment_amount": (
                                agr.get("expected_payment_amount")
                                or values.get("expected_payment_amount")
                            ),
                        }
                        workflow_stage = "nomba_provisioned"
                        logger.info(
                            "[PROPFLOW] Status safety-net corrected stale stage for %s → nomba_provisioned",
                            workflow_id,
                        )
                except Exception as exc:
                    logger.warning(
                        "[PROPFLOW] Status safety-net check failed for %s: %s",
                        workflow_id, exc,
                    )

        # ── Safety net: payment landed / funds released must never render as
        #    "awaiting_full_payment" or "nomba_provisioned". The agreement row
        #    (reconciliation_status) and the transactions table (disbursement
        #    status) are the source of truth. If the graph checkpoint is stale
        #    (e.g. sync_after_payment resolved a different thread, or the
        #    release webhook never synced the graph), correct the stage here so
        #    the tenant's chat self-heals on the next poll. Only runs for the
        #    payment-waiting stages so normal status polls pay no extra cost.
        if workflow_stage in ("awaiting_full_payment", "nomba_provisioned", "payment_confirmed"):
            agreement_id = values.get("agreement_id")
            if agreement_id:
                try:
                    loop = asyncio.get_event_loop()
                    sb = get_supabase_admin()
                    agr_result = await loop.run_in_executor(
                        None,
                        lambda: sb.table("agreements")
                        .select(
                            "reconciliation_status, total_received_amount, "
                            "virtual_account_number, expected_payment_amount"
                        )
                        .eq("id", str(agreement_id))
                        .maybe_single()
                        .execute(),
                    )
                    agr = agr_result.data
                    if agr:
                        recon = str(agr.get("reconciliation_status") or "").upper()
                        # Has the landlord already released the funds? A released
                        # disbursement row means the tenancy is active even if the
                        # graph never advanced past payment_confirmed.
                        disb_result = await loop.run_in_executor(
                            None,
                            lambda: sb.table("transactions")
                            .select("status")
                            .eq("agreement_id", str(agreement_id))
                            .eq("transaction_type", "nomba_disbursement")
                            .order("created_at", desc=True)
                            .limit(20)
                            .execute(),
                        )
                        disb_rows = disb_result.data or []
                        released = any(r.get("status") == "released" for r in disb_rows)

                        corrected_stage = None
                        if released:
                            corrected_stage = "disbursement_complete"
                        elif recon in ("FULL_PAYMENT", "RECONCILED"):
                            corrected_stage = "payment_confirmed"

                        if corrected_stage and corrected_stage != workflow_stage:
                            values = {
                                **values,
                                "current_stage": corrected_stage,
                                # Backfill the NUBAN + amount so the tenant's
                                # acknowledgment card can show the exact figure.
                                "nomba_virtual_account_number": (
                                    agr.get("virtual_account_number")
                                    or values.get("nomba_virtual_account_number")
                                ),
                                "expected_payment_amount": (
                                    agr.get("expected_payment_amount")
                                    or values.get("expected_payment_amount")
                                ),
                            }
                            workflow_stage = corrected_stage
                            logger.info(
                                "[PROPFLOW] Status safety-net corrected stale payment stage for %s → %s",
                                workflow_id, corrected_stage,
                            )
                except Exception as exc:
                    logger.warning(
                        "[PROPFLOW] Status payment safety-net check failed for %s: %s",
                        workflow_id, exc,
                    )

        return StatusResponse(
            success=True,
            workflow_id=workflow_id,
            current_stage=values.get("current_stage", "unknown"),
            tenant_id=current_user["id"],
            created_at=datetime.utcnow(),
            last_updated=datetime.utcnow(),
            extracted_intent=values.get("extracted_intent"),
            selected_property_id=str(values["selected_property_id"]) if values.get("selected_property_id") else None,
            application_id=str(values["application_id"]) if values.get("application_id") else None,
            agreement_id=str(values["agreement_id"]) if values.get("agreement_id") else None,
            landlord_briefing=values.get("landlord_briefing"),
            virtual_account_number=values.get("nomba_virtual_account_number"),
            expected_payment_amount=values.get("expected_payment_amount"),
            agreement_pdf_url=values.get("agreement_pdf_url"),
            error_log=values.get("error_log", []),
        )

    except Exception as e:
        print(f"[ERROR] [PROPFLOW] Status check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get workflow status: {str(e)}")


@router.post("/simulate-payment/{workflow_id}")
async def simulate_propflow_payment(
    workflow_id: str,
    current_user = Depends(get_current_user)
):
    """
    Simulate a tenant payment for demo purposes.
    Creates a fake payment record and marks the agreement as FULL_PAYMENT,
    so the landlord can then call /resume/{id} with confirm_payment.
    """
    try:
        graph = propflow_graph()
        thread_config = {"configurable": {"thread_id": workflow_id}}

        try:
            state = graph.get_state(thread_config)
        except Exception:
            return {"success": False, "error": "Workflow not found"}

        values = state.values
        agreement_id = values.get("agreement_id")
        virtual_account = values.get("nomba_virtual_account_number")
        expected_amount = values.get("expected_payment_amount")

        if not agreement_id:
            return {"success": False, "error": "No agreement in this workflow yet"}

        loop = asyncio.get_event_loop()
        supabase_admin = get_supabase_admin()

        # The workflow state may not carry expected_payment_amount /
        # virtual_account_number back through the checkpointer (channel not
        # persisted or serialized to null), and the agreement may not have had
        # a VA provisioned (provision_nomba_dva only runs via graph resume, but
        # the frontend signs through the agreements route). So resolve the
        # amount defensively: state → agreement.expected_payment_amount →
        # calculate_expected_amount(rent, frequency). This is the same calc
        # provision_virtual_account uses, so the simulated payment matches.
        agreement_row = None
        try:
            agreement_result = await loop.run_in_executor(
                None,
                lambda: supabase_admin.table("agreements")
                .select(
                    "expected_payment_amount, virtual_account_number, "
                    "nomba_account_ref, rent_amount, payment_frequency"
                )
                .eq("id", str(agreement_id))
                .maybe_single()
                .execute(),
            )
            agreement_row = agreement_result.data
        except Exception as exc:
            logger.warning(
                "[PROPFLOW] Could not read agreement fallback for %s: %s",
                agreement_id, exc,
            )

        agreement = agreement_row or {}
        if expected_amount is None:
            expected_amount = agreement.get("expected_payment_amount")
        if expected_amount is None:
            try:
                rent = float(agreement.get("rent_amount") or 0)
                freq = agreement.get("payment_frequency") or "MONTHLY"
                expected_amount = calculate_expected_amount(rent, freq)
            except (TypeError, ValueError):
                expected_amount = 0.0
        if not virtual_account:
            virtual_account = agreement.get("virtual_account_number")
        if not virtual_account:
            # No real VA was provisioned (provision_nomba_dva only runs via graph
            # resume, which the frontend sign flow skips). Derive a stable
            # 10-digit synthetic VA from the agreement id so the tenant payment
            # page and the transfer row always have a consistent account number.
            digits = "".join(c for c in str(agreement_id) if c.isdigit())
            virtual_account = ("9" + digits)[:10].ljust(10, "0")

        # Single safe float for all inserts and message formatting. Never crashes
        # on a None/str state value from the checkpointer.
        try:
            amount_float = float(expected_amount or 0)
        except (TypeError, ValueError):
            amount_float = 0.0

        # ── Write agreement as FULL_PAYMENT ───────────────────────────────────
        # Backfill expected_payment_amount / virtual_account_number too so the
        # landlord payments page and release flow see a self-consistent row.
        agreement_update = {
            "total_received_amount": amount_float,
            "reconciliation_status": "FULL_PAYMENT",
            "status": "ACTIVE",
        }
        if not agreement.get("expected_payment_amount"):
            agreement_update["expected_payment_amount"] = amount_float
        if not agreement.get("virtual_account_number") and virtual_account:
            agreement_update["virtual_account_number"] = virtual_account

        await loop.run_in_executor(
            None,
            lambda: supabase_admin.table("agreements")
            .update(agreement_update)
            .eq("id", str(agreement_id))
            .execute(),
        )

        # ── Transfer record for the landlord release flow ────────────────────
        uuid_match = re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            str(agreement_id), re.IGNORECASE,
        )
        clean_id = uuid_match.group(0) if uuid_match else str(agreement_id)
        suffixed_ref = f"{clean_id}-SUB"
        request_id = str(uuid.uuid4())
        # Mirrors the Nomba webhook payload shape (the raw_payload column is
        # NOT NULL), so the transfer row looks like a real webhook insert.
        raw_payload = {
            "requestId": request_id,
            "event_type": "payment_success",
            "data": {
                "transaction": {
                    "type": "vact_transfer",
                    "transactionId": f"propflow-sim-{agreement_id[:8]}",
                    "aliasAccountReference": suffixed_ref,
                    "aliasAccountNumber": virtual_account,
                    "transactionAmount": amount_float,
                },
                "customer": {
                    "senderName": "Simulated Payment",
                    "bankName": "PropFlow",
                },
            },
        }

        transfer_payload = {
            "nomba_request_id": request_id,
            "nomba_transaction_id": f"propflow-sim-{agreement_id[:8]}",
            "account_ref": suffixed_ref,
            "account_number": virtual_account,
            # The disburse endpoint looks up the source transfer by this
            # agreement_id column (same as _reconcile_payment sets it in the
            # real webhook path) — without it the release flow 404s.
            "agreement_id": clean_id,
            "amount_received": amount_float,
            "sender_name": "Simulated Payment",
            "sender_bank": "PropFlow",
            "currency": "NGN",
            "event_type": "payment_success",
            "transaction_type": "vact_transfer",
            "raw_payload": raw_payload,
            "signature_valid": True,
            "reconciliation_result": "FULL_PAYMENT",
        }

        # Idempotent upsert: if a transfer already exists for this account ref
        # (e.g. a previous run wrote ₦0), UPDATE its amount rather than stacking
        # a duplicate row. Otherwise insert a new one.
        try:
            existing_result = await loop.run_in_executor(
                None,
                lambda: supabase_admin.table("virtual_account_transfers")
                .select("id")
                .eq("account_ref", suffixed_ref)
                .limit(1)
                .execute(),
            )
            existing = existing_result.data[0] if existing_result.data else None
            if existing:
                await loop.run_in_executor(
                    None,
                    lambda: supabase_admin.table("virtual_account_transfers")
                    .update({
                        "agreement_id": clean_id,
                        "amount_received": amount_float,
                        "account_number": virtual_account,
                        "raw_payload": raw_payload,
                        "reconciliation_result": "FULL_PAYMENT",
                    })
                    .eq("id", existing["id"])
                    .execute(),
                )
            else:
                await loop.run_in_executor(
                    None,
                    lambda: supabase_admin.table("virtual_account_transfers")
                    .insert(transfer_payload)
                    .execute(),
                )
        except Exception as exc:
            logger.warning(
                "[PROPFLOW] Transfer upsert failed (non-fatal) for %s: %s",
                agreement_id, exc,
            )

        logger.info(
            f"[PROPFLOW] Simulated payment for agreement={agreement_id} "
            f"amount=NGN {amount_float:,.0f}"
        )

        # ── Keep the graph thread in sync with the payment so a later
        #     resume/confirm works against a correct stage. Best-effort.
        try:
            from app.services.propflow_graph_sync import sync_after_payment
            await sync_after_payment(str(agreement_id), amount_float, supabase_admin)
        except Exception as sync_err:
            logger.warning(
                f"[PROPFLOW] Graph payment sync failed (non-fatal): {sync_err}"
            )

        return {
            "success": True,
            "message": f"Payment of NGN {amount_float:,.0f} received! The landlord can now confirm and complete the tenancy.",
            "agreement_id": str(agreement_id) if agreement_id else None,
            "virtual_account": virtual_account,
            "amount": amount_float,
        }

    except Exception as e:
        print(f"[ERROR] [PROPFLOW] Simulate payment failed: {e}")
        return {"success": False, "error": str(e)}


@router.get("/health")
async def propflow_health_check():
    """PropFlow system health check."""
    try:
        health_status = {
            "service": "PropFlow AI Agent",
            "status": "healthy",
            "version": "3.1.0",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                "langgraph": "✅ Loaded",
                "qwen_client": "✅ Ready",
                "database": "✅ Connected",
                "mem0": "✅ Available" if propflow_settings.ENABLE_MEM0_MEMORY else "⚠️ Disabled",
                "nomba": "✅ Mock Ready"
            },
            "demo_users": {
                "tenant": "slimmedia0705@gmail.com",
                "landlord": "raphawellnessoptimization@gmail.com"
            },
            "endpoints": [
                "POST /api/v1/propflow/chat",
                "POST /api/v1/propflow/select/{workflow_id}",
                "POST /api/v1/propflow/resume/{workflow_id}",
                "GET /api/v1/propflow/status/{workflow_id}",
                "GET /api/v1/propflow/threads",
                "GET /api/v1/propflow/health"
            ]
        }

        return health_status

    except Exception as e:
        return {
            "service": "PropFlow AI Agent",
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/threads", response_model=ThreadListResponse)
async def list_propflow_threads(
    current_user = Depends(get_current_user),
    status: Optional[str] = Query(None, description="Filter by status: active, completed, error"),
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    List PropFlow threads for the current user.

    - **Tenants** see their own threads (created when they started a chat)
    - **Landlords** see threads for properties they own (when a tenant selected
      one of their properties)
    - **Admins** see all threads

    Each thread shows the current stage, tenant info, and (if applicable)
    the property title from the linked application.
    """
    try:
        user_id = current_user["id"]
        user_type = current_user.get("user_type", "")
        supabase_admin = get_supabase_admin()
        loop = asyncio.get_event_loop()

        # Build query based on user role
        if user_type == "tenant":
            query = supabase_admin.table("propflow_threads") \
                .select("*") \
                .eq("tenant_id", user_id)
        elif user_type == "landlord":
            query = supabase_admin.table("propflow_threads") \
                .select("*") \
                .eq("landlord_id", user_id)
        else:
            # Admin or other — list all threads
            query = supabase_admin.table("propflow_threads") \
                .select("*")

        if status:
            query = query.eq("status", status)

        # Get total count first
        count_result = await loop.run_in_executor(
            None,
            lambda: query.execute(),
        )
        all_threads = count_result.data or []

        # Paginate client-side (PostgREST range doesn't work with count easily)
        paginated = all_threads[offset:offset + limit]

        # Enrich with tenant name + property title
        threads = []
        for t in paginated:
            tid = t.get("tenant_id", "")
            tenant_name = None
            tenant_phone = None
            property_title = None

            # Fetch tenant name from users table
            if tid:
                try:
                    user_res = await loop.run_in_executor(
                        None,
                        lambda: supabase_admin.table("users")
                        .select("full_name, phone_number")
                        .eq("id", tid)
                        .single()
                        .execute(),
                    )
                    if user_res.data:
                        tenant_name = user_res.data.get("full_name")
                        tenant_phone = user_res.data.get("phone_number")
                except Exception:
                    pass

            # Try to get property title via applications.propflow_thread_id
            thread_id = t.get("thread_id", "")
            if thread_id:
                try:
                    app_res = await loop.run_in_executor(
                        None,
                        lambda: supabase_admin.table("applications")
                        .select("property:properties!inner(title)")
                        .eq("propflow_thread_id", thread_id)
                        .maybe_single()
                        .execute(),
                    )
                    if app_res.data:
                        prop = app_res.data.get("property", {})
                        if prop:
                            property_title = prop.get("title") if isinstance(prop, dict) else str(prop)
                except Exception:
                    pass

            threads.append(ThreadInfoResponse(
                thread_id=thread_id,
                tenant_id=tid,
                tenant_name=tenant_name,
                tenant_phone=tenant_phone,
                landlord_id=str(t.get("landlord_id")) if t.get("landlord_id") else None,
                property_title=property_title,
                current_stage=t.get("current_stage", ""),
                status=t.get("status", "active"),
                created_at=t.get("created_at"),
                updated_at=t.get("updated_at"),
            ))

        return ThreadListResponse(
            success=True,
            threads=threads,
            total=len(all_threads),
        )

    except Exception as e:
        logger.error("[PROPFLOW] Thread listing failed: %s", e)
        return ThreadListResponse(
            success=False,
            error_message=str(e),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

async def _notify_application_decision(
    application_id: str,
    property_id: str,
    decision: str,
    rejection_reason: str = "",
    landlord_name: str = "Landlord",
):
    """Update applications table + fire notifications via existing notification_service."""
    loop = asyncio.get_event_loop()
    supabase_admin = get_supabase_admin()

    app_result = await loop.run_in_executor(
        None,
        lambda: supabase_admin.table("applications")
        .select("*, property:properties!inner(id, title, location), user:users!user_id(id, full_name, email, phone_number)")
        .eq("id", application_id)
        .single()
        .execute(),
    )
    if not app_result.data:
        logger.warning(f"[PROPFLOW] Application {application_id} not found")
        return

    app = app_result.data
    prop = app.get("property") or {}
    tenant = app.get("user") or {}

    if decision == "approved":
        await loop.run_in_executor(
            None,
            lambda: supabase_admin.table("applications")
            .update({"status": "approved", "viewed_by_landlord": True})
            .eq("id", application_id)
            .execute(),
        )
    else:
        await loop.run_in_executor(
            None,
            lambda: supabase_admin.table("applications")
            .update({"status": "rejected"})
            .eq("id", application_id)
            .execute(),
        )

    try:
        from app.services.notification_service import notification_service
        if decision == "approved":
            await notification_service.notify_application_approved(
                application_id=application_id,
                property_id=property_id,
                property_title=prop.get("title", "Property"),
                tenant_id=str(tenant.get("id", "")),
                tenant_name=tenant.get("full_name", "Tenant"),
                tenant_email=tenant.get("email"),
                tenant_phone=tenant.get("phone_number"),
                landlord_name=landlord_name,
            )
        else:
            await notification_service.notify_application_rejected(
                application_id=application_id,
                property_id=property_id,
                property_title=prop.get("title", "Property"),
                tenant_id=str(tenant.get("id", "")),
                tenant_name=tenant.get("full_name", "Tenant"),
                tenant_email=tenant.get("email"),
                tenant_phone=tenant.get("phone_number"),
                rejection_reason=rejection_reason,
            )
        logger.info(f"[PROPFLOW] Notification sent for {application_id}")
    except Exception as exc:
        logger.warning(f"[PROPFLOW] Notification unavailable: {exc}")


def _safe_amount(val: Any) -> float | None:
    """Safely convert a value to float. Returns None if unparseable."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


async def _generate_response_message(result: Dict[str, Any], user_type: str = "tenant") -> str:
    """Generate user-friendly response message based on workflow stage and caller role."""
    stage = result.get("current_stage", "unknown")
    
    if stage == "intent_extracted":
        intent = result.get("extracted_intent", {})
        location = intent.get("location", "Lagos")
        bedrooms = intent.get("bedrooms", "")
        budget = _safe_amount(intent.get("budget_monthly"))

        budget_text = f" with budget ₦{budget:,.0f}/month" if budget else ""
        bedroom_text = f"{bedrooms}-bedroom " if bedrooms else ""

        return f"I understand you're looking for a {bedroom_text}apartment in {location}{budget_text}. Let me search for available properties..."

    elif stage == "awaiting_tenant_selection":
        matches = result.get("property_matches", []) or []
        if not matches:
            return "I couldn't find any properties matching your criteria. Would you like to adjust your requirements or budget?"

        match_quality = result.get("match_quality") or "neighbourhood"

        # LLM-grounded reply: honest about whether these are exact matches
        # ('neighbourhood') or expanded recommendations from a wider area
        # ('city'). Best-effort -- falls back to the deterministic template
        # (below) if Qwen is unavailable or errors.
        from app.propflow.services.qwen_client import qwen_client
        try:
            reply = await qwen_client.generate_tenant_reply(
                result.get("extracted_intent") or {},
                matches,
                match_quality,
            )
            if reply and reply.strip():
                return reply.strip()
        except Exception as exc:
            logger.warning(f"LLM tenant reply failed, using template: {exc}")

        # Deterministic fallback -- the client strips the numbered list down to
        # this header when property cards are rendered separately.
        if match_quality == "city":
            header = (
                f"I couldn't find an exact match in "
                f"{result.get('extracted_intent', {}).get('location', 'your area')}, "
                f"but here are the closest options we found. They may differ from "
                f"your request."
            )
        else:
            header = f"I found {len(matches)} properties that match your request. Which one do you prefer?"
        lines = [header]
        for i, p in enumerate(matches):
            title = p.get("title", "Property")
            price = _safe_amount(p.get("price"))
            price_str = f"₦{price:,.0f}/month" if price else "Price N/A"
            location = p.get("location", "")
            beds = p.get("beds")
            # Format beds: studios are 0 beds, show as "Studio"; otherwise show "N bed(s)"
            bed_str = "Studio" if beds == 0 else (f"{beds} bed{'s' if beds and beds != 1 else ''}" if beds else "?")
            lines.append(f"  {i+1}. {title} — {price_str} ({bed_str}, {location})")
        lines.append("Reply with the number you'd like, or tap one of the options above.")
        return "\n".join(lines)
    
    elif stage == "property_matched":
        property_count = len(result.get("property_matches", []) or [])
        if property_count > 0:
            return f"Great! I found {property_count} property(ies) that match your criteria. Creating your application now..."
        else:
            return "I couldn't find any properties matching your criteria. Would you like to adjust your requirements or budget?"
    
    elif stage == "awaiting_trust_profile":
        return (
            "You're almost ready to apply! Complete the checks below (contact, "
            "identity, income evidence, reference, employment and move-in "
            "details), then review and submit your application."
        )

    elif stage == "application_created":
        return "Perfect! I've submitted your application to the landlord. They'll review your profile and get back to you soon."

    elif stage == "agreement_drafted":
        return "The landlord has approved your application! A lease agreement has been drafted and is ready for your review. Please sign to proceed with payment setup."

    elif stage == "enrich_and_qualify" or stage == "awaiting_landlord_approval":
        return "Your application has been sent to the landlord for review. You'll receive a notification once they make a decision."
    
    elif stage == "nomba_provisioned":
        account_number = result.get("nomba_virtual_account_number")
        amount = _safe_amount(result.get("expected_payment_amount"))
        amount_text = f"₦{amount:,.0f}" if amount else "the agreed amount"
        
        if account_number:
            return f"🎉 Your application was approved! Please make payment of {amount_text} to account: {account_number} to activate your tenancy."
        else:
            return "Your application was approved! Payment details will be shared with you shortly."
    
    elif stage == "payment_confirmed":
        amount = _safe_amount(result.get("total_received_amount") or result.get("expected_payment_amount"))
        amount_text = f" of ₦{amount:,.0f}" if amount else ""
        return (
            f"✅ Your payment{amount_text} has been received and verified! "
            "The landlord has been notified. Once they confirm and release the funds, "
            "your tenancy will be fully active. I'll update you here the moment it happens."
        )

    elif stage == "disbursement_complete":
        return (
            "🎉 Payment received and processed! Your tenancy is now active. "
            "Welcome to your new home! You can now schedule your move-in and "
            "coordinate key handover with the landlord."
        )
    
    elif stage == "rejected":
        reason = result.get("rejection_reason", "Landlord requirements not met")
        return f"Unfortunately, your application was not approved. Reason: {reason}. Don't worry, I can help you find other suitable properties!"
    
    elif stage == "awaiting_landlord_signature":
        return "You've signed the lease! Now waiting for the landlord to countersign. You'll be notified once the tenancy is confirmed."

    elif stage == "no_properties_found":
        intent = result.get("extracted_intent", {})
        location = intent.get("location", "your selected area")
        bedrooms = intent.get("bedrooms", "")
        budget = _safe_amount(intent.get("budget_monthly"))
        budget_text = f" of ₦{budget:,.0f}/month" if budget else ""
        bedroom_text = f"{bedrooms}-bedroom " if bedrooms else ""

        return (
            f"I searched for a {bedroom_text}apartment in {location}{budget_text}, but unfortunately "
            f"I couldn't find any properties that match your criteria. "
            f"Would you like to adjust your requirements — perhaps a different location, "
            f"number of bedrooms, or budget range?"
        )

    else:
        return "I'm processing your request. This may take a moment..."


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORT ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

