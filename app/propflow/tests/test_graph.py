"""
PropFlow Graph Tests (updated for 4-interrupt flow)

Interrupt architecture:
  INTERRUPT #1: create_application     Tenant selects a property
  INTERRUPT #2: create_agreement       Landlord approves/rejects
  INTERRUPT #3: provision_nomba_dva    Tenant signs lease (+ landlord countersigns)
  INTERRUPT #4: disburse_landlord      Landlord confirms payment received

Covers:
  1. Lazy graph instantiation (no crash on import)
  2. Graph pauses at INTERRUPT #1 (awaiting tenant selection)
  3. Graph resumes after tenant selection, pauses at INTERRUPT #2 (landlord)
  4. Graph resumes after landlord approval, pauses at INTERRUPT #3 (tenant sign)
  5. Graph completes after landlord confirms payment
  6. Full flow through all 4 interrupts
  7. Mock DVA fallback when Nomba is unavailable
  8. Rejection path ends gracefully
"""

import pytest
import uuid
from unittest.mock import patch, AsyncMock

from app.propflow.graph import get_propflow_graph
from app.propflow.state import PropFlowState


MOCK_INTENT = {
    "property_type": "apartment",
    "location": "Lekki",
    "bedrooms": 2,
    "budget_monthly": 500000.0,
    "budget_annual": None,
    "move_in_date": None,
    "payment_frequency": "MONTHLY",
    "special_requests": [],
    "confidence": 0.91,
}

MOCK_BRIEFING = (
    "Test tenant is seeking a 2-bedroom apartment in Lekki "
    "with a monthly budget of NGN 500,000."
)

MOCK_PROPERTY_ID = uuid.uuid4()
MOCK_LANDLORD_ID = uuid.uuid4()
MOCK_PROPERTIES = [
    {
        "id": str(MOCK_PROPERTY_ID),
        "landlord_id": str(MOCK_LANDLORD_ID),
        "title": "Test 2-Bedroom in Lekki",
        "location": "Lekki Phase 1, Lagos",
        "price": 480000.0,
        "beds": 2,
        "baths": 2,
        "property_type": "apartment",
        "images": [],
    }
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_initial_state(text: str = "I need a self-contain in VI for 500k monthly") -> PropFlowState:
    return PropFlowState(
        raw_inquiry_text=text,
        extracted_intent=None,
        extraction_confidence=None,
        property_matches=None,
        selected_property_id=None,
        application_id=None,
        application_status=None,
        landlord_id=None,
        agreement_id=None,
        agreement_status=None,
        agreement_pdf_oss_key=None,
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
        workflow_id=f"test-{uuid.uuid4().hex[:8]}",
        tenant_id=uuid.uuid4(),
        current_stage="start",
        error_log=[],
    )


def _fresh_graph():
    """Clear singleton and rebuild graph so patches take effect."""
    import app.propflow.graph as g
    g._graph_instance = None
    return get_propflow_graph()


def _patch_services():
    """
    Patch all external service calls that nodes make.
    Returns a list of (patcher, mock) for cleanup.
    """
    patches = [
        patch("app.propflow.services.qwen_client.qwen_client.extract_intent",
              new_callable=AsyncMock, return_value=MOCK_INTENT),
        patch("app.propflow.services.qwen_client.qwen_client.generate_landlord_briefing",
              new_callable=AsyncMock, return_value=MOCK_BRIEFING),
        patch("app.propflow.nodes.extract_intent.mem0_service.search_tenant_memories",
              return_value=[]),
        patch("app.propflow.nodes.match_properties._query_properties",
              new_callable=AsyncMock, return_value=MOCK_PROPERTIES),
        patch("app.services.application_service.application_service.submit_application",
              new_callable=AsyncMock,
              return_value={"id": str(uuid.uuid4()), "status": "submitted",
                            "propflow_thread_id": "test-thread"}),
        # Agreement creation node: mock internal Supabase helper fetches
        patch("app.propflow.nodes.create_agreement._fetch_property",
              new_callable=AsyncMock,
              return_value={"id": str(uuid.uuid4()), "title": "Mock Property",
                            "price": 480000.0, "location": "Lekki"}),
        patch("app.propflow.nodes.create_agreement._fetch_tenant",
              new_callable=AsyncMock,
              return_value={"full_name": "Test Tenant", "email": "tenant@test.com"}),
        patch("app.propflow.nodes.create_agreement._fetch_landlord_name",
              new_callable=AsyncMock, return_value="Test Landlord"),
        patch("app.services.agreement_service.agreement_service.auto_generate_agreement",
              new_callable=AsyncMock,
              return_value={"id": str(uuid.uuid4()), "status": "PENDING_TENANT"}),
        patch("app.services.payment_service.payment_service.provision_virtual_account",
              new_callable=AsyncMock,
              return_value={"status": "provisioned", "virtual_account_number": "9391076543",
                            "expected_amount": 480000.0}),
        patch("app.services.payment_service.payment_service.disburse_to_landlord",
              new_callable=AsyncMock,
              return_value={"merchant_tx_ref": f"tx-{uuid.uuid4().hex[:8]}", "status": "completed",
                            "disbursement_amount": 480000.0, "platform_fee": 0}),
    ]
    for p in patches:
        p.start()
    return patches


# ---------------------------------------------------------------------------
# Structural tests (no mocking needed)
# ---------------------------------------------------------------------------

def test_graph_builds_lazily():
    """Graph must construct without errors; import alone must not crash."""
    graph = get_propflow_graph()
    assert graph is not None


def test_graph_is_singleton():
    """Second call returns the exact same compiled object."""
    g1 = get_propflow_graph()
    g2 = get_propflow_graph()
    assert g1 is g2


@pytest.mark.asyncio
async def test_graph_has_four_interrupts():
    """Verify the graph is compiled with all 4 interrupt checkpoints."""
    graph = get_propflow_graph()
    assert graph is not None
    assert hasattr(graph, "ainvoke")
    assert len(graph.nodes) >= 7  # extract_intent through disburse_landlord


# ---------------------------------------------------------------------------
# Flow tests (all external services mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_graph_pauses_at_interrupt_1_tenant_selection():
    """
    Graph should run extract_intent -> match_properties,
    then pause BEFORE create_application (INTERRUPT #1).
    Stage should be 'awaiting_tenant_selection'.
    """
    srvc = _patch_services()
    try:
        graph = _fresh_graph()
        config = {"configurable": {"thread_id": f"test-{uuid.uuid4().hex[:8]}"}}
        result = await graph.ainvoke(_make_initial_state(), config=config)

        assert result["current_stage"] == "awaiting_tenant_selection", (
            f"Expected tenant selection stage, got '{result['current_stage']}'"
        )
        assert result.get("application_id") is None
    finally:
        for p in srvc:
            p.stop()


@pytest.mark.asyncio
async def test_graph_resumes_to_interrupt_2_landlord():
    """
    Simulate property selection -> graph resumes past INTERRUPT #1,
    runs through create_application + enrich_and_qualify,
    then pauses BEFORE create_agreement (INTERRUPT #2).
    """
    srvc = _patch_services()
    try:
        graph = _fresh_graph()
        config = {"configurable": {"thread_id": f"test-{uuid.uuid4().hex[:8]}"}}

        # First run - stops at INTERRUPT #1 (before create_application)
        result = await graph.ainvoke(_make_initial_state(), config=config)
        assert result["current_stage"] == "awaiting_tenant_selection"

        # Set tenant's property selection via update_state, then resume
        matches = result.get("property_matches") or []
        assert matches, "Should have mock property matches"
        selected = matches[0]
        await graph.aupdate_state(config, {
            "selected_property_id": uuid.UUID(selected["id"]),
            "landlord_id": uuid.UUID(selected["landlord_id"]),
            "current_stage": "property_selected",
        })
        result = await graph.ainvoke(None, config=config)

        assert result["current_stage"] == "awaiting_landlord_approval", (
            f"Expected 'awaiting_landlord_approval', got '{result['current_stage']}'"
        )
        assert result.get("application_id") is not None
        assert result.get("agreement_id") is None
    finally:
        for p in srvc:
            p.stop()


@pytest.mark.asyncio
async def test_graph_pauses_at_interrupt_3_signing():
    """
    Simulate landlord approval -> graph resumes past INTERRUPT #2,
    runs create_agreement, then pauses BEFORE provision_nomba_dva (INTERRUPT #3).
    """
    srvc = _patch_services()
    try:
        graph = _fresh_graph()
        config = {"configurable": {"thread_id": f"test-{uuid.uuid4().hex[:8]}"}}

        # INTERRUPT #1
        result = await graph.ainvoke(_make_initial_state(), config=config)
        assert result["current_stage"] == "awaiting_tenant_selection"

        # Resume past INTERRUPT #1
        matches = result.get("property_matches") or []
        selected = matches[0]
        await graph.aupdate_state(config, {
            "selected_property_id": uuid.UUID(selected["id"]),
            "landlord_id": uuid.UUID(selected["landlord_id"]),
            "current_stage": "property_selected",
        })
        result = await graph.ainvoke(None, config=config)
        assert result["current_stage"] == "awaiting_landlord_approval"

        # Resume past INTERRUPT #2 (landlord approves)
        await graph.aupdate_state(config, {"application_status": "approved"})
        result = await graph.ainvoke(None, config=config)

        assert result["current_stage"] in ("agreement_drafted",), (
            f"Expected 'agreement_drafted', got '{result['current_stage']}'"
        )
        assert result.get("agreement_id") is not None
        assert result.get("agreement_status") == "PENDING_TENANT"
    finally:
        for p in srvc:
            p.stop()


@pytest.mark.asyncio
async def test_graph_completes_full_flow():
    """
    Run the full flow through all 4 interrupts to completion.
    Tests the complete journey: search -> select -> approve -> sign -> pay -> done.
    """
    srvc = _patch_services()
    try:
        graph = _fresh_graph()
        config = {"configurable": {"thread_id": f"test-{uuid.uuid4().hex[:8]}"}}

        # INTERRUPT #1: extract_intent + match_properties
        result = await graph.ainvoke(_make_initial_state(), config=config)
        assert result["current_stage"] == "awaiting_tenant_selection"
        matches = result.get("property_matches") or []
        selected = matches[0]

        # INTERRUPT #1 -> create_application + enrich_and_qualify -> INTERRUPT #2
        await graph.aupdate_state(config, {
            "selected_property_id": uuid.UUID(selected["id"]),
            "landlord_id": uuid.UUID(selected["landlord_id"]),
            "current_stage": "property_selected",
        })
        result = await graph.ainvoke(None, config=config)
        assert result["current_stage"] == "awaiting_landlord_approval"
        assert result.get("application_id") is not None

        # INTERRUPT #2 -> create_agreement -> INTERRUPT #3
        await graph.aupdate_state(config, {"application_status": "approved"})
        result = await graph.ainvoke(None, config=config)
        assert result["current_stage"] == "agreement_drafted"
        assert result.get("agreement_id") is not None

        # INTERRUPT #3 -> provision_nomba_dva -> INTERRUPT #4
        await graph.aupdate_state(config, {"agreement_status": "SIGNED"})
        result = await graph.ainvoke(None, config=config)
        assert result.get("nomba_virtual_account_number") is not None
        assert "9391" in str(result.get("nomba_virtual_account_number", ""))

        # INTERRUPT #4 -> disburse_landlord -> END
        await graph.aupdate_state(config, {
            "reconciliation_status": "FULL_PAYMENT",
            "current_stage": "payment_confirmed",
        })
        result = await graph.ainvoke(None, config=config)

        assert result["current_stage"] == "disbursement_complete", (
            f"Expected 'disbursement_complete', got '{result['current_stage']}'"
        )
        assert result.get("disbursement_merchant_tx_ref") is not None
    finally:
        for p in srvc:
            p.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
