"""
Tests for enhanced PropFlow select API with property_id support, thread resurrection,
and protected-stage guards.
"""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.propflow.checkpointer import SupabaseRestCheckpointer
from app.propflow.state import PropFlowState
from app.routes.propflow import router, PROTECTED_SELECT_STAGES


# ─── Test PROTECTED_SELECT_STAGES constant ─────────────────────────────────

def test_protected_select_stages_defined():
    """PROTECTED_SELECT_STAGES must include all post-application stages."""
    assert "application_created" in PROTECTED_SELECT_STAGES
    assert "awaiting_landlord_approval" in PROTECTED_SELECT_STAGES
    assert "agreement_drafted" in PROTECTED_SELECT_STAGES
    assert "awaiting_landlord_signature" in PROTECTED_SELECT_STAGES
    assert "nomba_provisioned" in PROTECTED_SELECT_STAGES
    assert "payment_confirmed" in PROTECTED_SELECT_STAGES
    assert "awaiting_full_payment" in PROTECTED_SELECT_STAGES
    assert "disbursement_complete" in PROTECTED_SELECT_STAGES
    assert "rejected" in PROTECTED_SELECT_STAGES


# ─── Helper: build a CheckpointTuple-like namedtuple ───────────────────────

from collections import namedtuple
_CheckpointTuple = namedtuple(
    "CheckpointTuple",
    ["config", "checkpoint", "metadata", "parent_config", "pending_writes"],
    defaults=(None, None, None, None, None),
)

def _ckpt(channel_values: dict) -> _CheckpointTuple:
    return _CheckpointTuple(checkpoint={"channel_values": channel_values})


PROPERTY_ID = "550e8400-e29b-41d4-a716-446655440000"
LANDLORD_ID = "660e8400-e29b-41d4-a716-446655440000"
TENANT_ID = "f4a8c2b1-9b6e-4d3c-8a7b-123456789abc"

MOCK_PROPERTY = {
    "id": PROPERTY_ID,
    "title": "Test 2-Bedroom in Lekki",
    "location": "Lekki Phase 1, Lagos",
    "price": 480000,
    "beds": 2,
    "landlord_id": LANDLORD_ID,
}

_MOCK_CURRENT_USER = {"id": TENANT_ID, "user_type": "tenant", "phone_number": None}


class MockSupabaseResponse:
    """Emulates the Supabase response object with .data attribute."""
    def __init__(self, data):
        self.data = data


def _mock_db_found(mock_supabase, data: dict):
    """Configure the mock Supabase chain so .single().execute() returns .data."""
    mock_supabase.return_value.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MockSupabaseResponse(data)


def _mock_db_not_found(mock_supabase):
    """Configure the mock Supabase chain to raise 404 (PGRST116)."""
    exc = Exception({"message": "Cannot coerce the result to a single JSON object", "code": "PGRST116"})
    mock_supabase.return_value.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = exc


# ─── select_property_id: resolved from checkpoint state ────────────────────

@patch("app.database.get_supabase_admin")
@patch("app.routes.propflow.get_current_user", return_value=_MOCK_CURRENT_USER)
def test_select_property_id_from_state(mock_user, mock_supabase):
    """property_id resolves from thread channel_values (no DB call needed)."""
    thread_id = "propflow-state-resolve"
    _mock_db_not_found(mock_supabase)

    mock_checkpointer = AsyncMock()
    mock_checkpointer.aget_tuple.return_value = _ckpt({
        "tenant_id": TENANT_ID,
        "property_matches": [MOCK_PROPERTY],
        "current_stage": "intent_extraction",
    })
    mock_graph = MagicMock()
    mock_graph.checkpointer = mock_checkpointer
    mock_graph.update_state = MagicMock()

    with patch("app.routes.propflow.propflow_graph", return_value=mock_graph):
        from app.routes.propflow import select_property
        import asyncio
        result = asyncio.run(select_property(
            workflow_id=thread_id,
            request=type("Req", (), {"property_id": PROPERTY_ID, "property_index": None})(),
            current_user=_MOCK_CURRENT_USER,
        ))

    assert result.success is True
    assert result.current_stage == "awaiting_trust_profile"
    mock_graph.update_state.assert_called_once()


# ─── select_property_id: resolved from DB (not in state) ──────────────────

@patch("app.database.get_supabase_admin")
@patch("app.routes.propflow.get_current_user", return_value=_MOCK_CURRENT_USER)
def test_select_property_id_from_db(mock_user, mock_supabase):
    """property_id not in state → resolved via direct Supabase lookup."""
    thread_id = "propflow-db-resolve"
    _mock_db_found(mock_supabase, MOCK_PROPERTY)

    mock_checkpointer = AsyncMock()
    mock_checkpointer.aget_tuple.return_value = _ckpt({
        "tenant_id": TENANT_ID,
        "property_matches": [],
        "current_stage": "intent_extraction",
    })
    mock_graph = MagicMock()
    mock_graph.checkpointer = mock_checkpointer
    mock_graph.update_state = MagicMock()

    with patch("app.routes.propflow.propflow_graph", return_value=mock_graph):
        from app.routes.propflow import select_property
        import asyncio
        result = asyncio.run(select_property(
            workflow_id=thread_id,
            request=type("Req", (), {"property_id": PROPERTY_ID, "property_index": None})(),
            current_user=_MOCK_CURRENT_USER,
        ))

    assert result.success is True
    assert result.current_stage == "awaiting_trust_profile"
    mock_graph.update_state.assert_called_once()


# ─── select_property_id: dead thread → resurrection path ──────────────────

@patch("app.database.get_supabase_admin")
@patch("app.routes.propflow.get_current_user", return_value=_MOCK_CURRENT_USER)
def test_select_property_id_dead_thread(mock_user, mock_supabase):
    """Thread is missing → DB lookup resolves property, no update_state (no prior state)."""
    thread_id = "propflow-dead-thread"
    _mock_db_found(mock_supabase, MOCK_PROPERTY)

    mock_checkpointer = AsyncMock()
    mock_checkpointer.aget_tuple.return_value = None
    mock_graph = MagicMock()
    mock_graph.checkpointer = mock_checkpointer
    mock_graph.update_state = MagicMock()

    with patch("app.routes.propflow.propflow_graph", return_value=mock_graph):
        from app.routes.propflow import select_property
        import asyncio
        result = asyncio.run(select_property(
            workflow_id=thread_id,
            request=type("Req", (), {"property_id": PROPERTY_ID, "property_index": None})(),
            current_user=_MOCK_CURRENT_USER,
        ))

    assert result.success is True
    assert result.current_stage == "awaiting_trust_profile"
    mock_graph.update_state.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════
# PROTECTED-STAGE TESTS
# ══════════════════════════════════════════════════════════════════════════


@patch("app.database.get_supabase_admin")
@patch("app.routes.propflow.get_current_user", return_value=_MOCK_CURRENT_USER)
def test_select_blocked_application_created(mock_user, mock_supabase):
    """select on thread at application_created → keeps existing stage, returns app_id."""
    thread_id = "propflow-prot-appcreated"
    _mock_db_found(mock_supabase, MOCK_PROPERTY)

    ckpt_tuple = _ckpt({
        "tenant_id": TENANT_ID,
        "property_matches": [MOCK_PROPERTY],
        "current_stage": "application_created",
        "application_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
    })
    mock_checkpointer = AsyncMock()
    mock_checkpointer.aget_tuple.return_value = ckpt_tuple
    mock_graph = MagicMock()
    mock_graph.checkpointer = mock_checkpointer
    mock_graph.update_state = MagicMock()

    with patch("app.routes.propflow.propflow_graph", return_value=mock_graph):
        from app.routes.propflow import select_property
        import asyncio
        result = asyncio.run(select_property(
            workflow_id=thread_id,
            request=type("Req", (), {"property_id": PROPERTY_ID, "property_index": None})(),
            current_user=_MOCK_CURRENT_USER,
        ))

    assert result.success is True
    assert result.current_stage == "application_created"
    assert result.application_id == "00000000-0000-0000-0000-000000000001"
    mock_graph.update_state.assert_not_called()


@patch("app.database.get_supabase_admin")
@patch("app.routes.propflow.get_current_user", return_value=_MOCK_CURRENT_USER)
def test_select_blocked_awaiting_landlord_approval(mock_user, mock_supabase):
    """select on thread awaiting_landlord_approval → not clobbered."""
    thread_id = "propflow-prot-awaiting-landlord"
    _mock_db_found(mock_supabase, MOCK_PROPERTY)

    ckpt_tuple = _ckpt({
        "tenant_id": TENANT_ID,
        "property_matches": [MOCK_PROPERTY],
        "current_stage": "awaiting_landlord_approval",
        "application_id": uuid.UUID("00000000-0000-0000-0000-000000000002"),
    })
    mock_checkpointer = AsyncMock()
    mock_checkpointer.aget_tuple.return_value = ckpt_tuple
    mock_graph = MagicMock()
    mock_graph.checkpointer = mock_checkpointer
    mock_graph.update_state = MagicMock()

    with patch("app.routes.propflow.propflow_graph", return_value=mock_graph):
        from app.routes.propflow import select_property
        import asyncio
        result = asyncio.run(select_property(
            workflow_id=thread_id,
            request=type("Req", (), {"property_id": PROPERTY_ID, "property_index": None})(),
            current_user=_MOCK_CURRENT_USER,
        ))

    assert result.success is True
    assert result.current_stage == "awaiting_landlord_approval"
    mock_graph.update_state.assert_not_called()


@patch("app.database.get_supabase_admin")
@patch("app.routes.propflow.get_current_user", return_value=_MOCK_CURRENT_USER)
def test_select_blocked_agreement_drafted(mock_user, mock_supabase):
    """select on thread at agreement_drafted → not clobbered."""
    thread_id = "propflow-prot-agreement"
    _mock_db_found(mock_supabase, MOCK_PROPERTY)

    ckpt_tuple = _ckpt({
        "tenant_id": TENANT_ID,
        "property_matches": [MOCK_PROPERTY],
        "current_stage": "agreement_drafted",
        "application_id": uuid.UUID("00000000-0000-0000-0000-000000000003"),
    })
    mock_checkpointer = AsyncMock()
    mock_checkpointer.aget_tuple.return_value = ckpt_tuple
    mock_graph = MagicMock()
    mock_graph.checkpointer = mock_checkpointer
    mock_graph.update_state = MagicMock()

    with patch("app.routes.propflow.propflow_graph", return_value=mock_graph):
        from app.routes.propflow import select_property
        import asyncio
        result = asyncio.run(select_property(
            workflow_id=thread_id,
            request=type("Req", (), {"property_id": PROPERTY_ID, "property_index": None})(),
            current_user=_MOCK_CURRENT_USER,
        ))

    assert result.success is True
    assert result.current_stage == "agreement_drafted"
    mock_graph.update_state.assert_not_called()


@patch("app.database.get_supabase_admin")
@patch("app.routes.propflow.get_current_user", return_value=_MOCK_CURRENT_USER)
def test_select_blocked_nomba_provisioned(mock_user, mock_supabase):
    """select on thread at nomba_provisioned → not clobbered."""
    thread_id = "propflow-prot-nomba"
    _mock_db_found(mock_supabase, MOCK_PROPERTY)

    ckpt_tuple = _ckpt({
        "tenant_id": TENANT_ID,
        "property_matches": [MOCK_PROPERTY],
        "current_stage": "nomba_provisioned",
        "application_id": uuid.UUID("00000000-0000-0000-0000-000000000004"),
    })
    mock_checkpointer = AsyncMock()
    mock_checkpointer.aget_tuple.return_value = ckpt_tuple
    mock_graph = MagicMock()
    mock_graph.checkpointer = mock_checkpointer
    mock_graph.update_state = MagicMock()

    with patch("app.routes.propflow.propflow_graph", return_value=mock_graph):
        from app.routes.propflow import select_property
        import asyncio
        result = asyncio.run(select_property(
            workflow_id=thread_id,
            request=type("Req", (), {"property_id": PROPERTY_ID, "property_index": None})(),
            current_user=_MOCK_CURRENT_USER,
        ))

    assert result.success is True
    assert result.current_stage == "nomba_provisioned"
    mock_graph.update_state.assert_not_called()


@patch("app.database.get_supabase_admin")
@patch("app.routes.propflow.get_current_user", return_value=_MOCK_CURRENT_USER)
def test_select_blocked_disbursement_complete(mock_user, mock_supabase):
    """select on thread at disbursement_complete → not clobbered, terminal message."""
    thread_id = "propflow-prot-disburse"
    _mock_db_found(mock_supabase, MOCK_PROPERTY)

    ckpt_tuple = _ckpt({
        "tenant_id": TENANT_ID,
        "property_matches": [MOCK_PROPERTY],
        "current_stage": "disbursement_complete",
        "application_id": uuid.UUID("00000000-0000-0000-0000-000000000005"),
    })
    mock_checkpointer = AsyncMock()
    mock_checkpointer.aget_tuple.return_value = ckpt_tuple
    mock_graph = MagicMock()
    mock_graph.checkpointer = mock_checkpointer
    mock_graph.update_state = MagicMock()

    with patch("app.routes.propflow.propflow_graph", return_value=mock_graph):
        from app.routes.propflow import select_property
        import asyncio
        result = asyncio.run(select_property(
            workflow_id=thread_id,
            request=type("Req", (), {"property_id": PROPERTY_ID, "property_index": None})(),
            current_user=_MOCK_CURRENT_USER,
        ))

    assert result.success is True
    assert result.current_stage == "disbursement_complete"
    assert "already active" in result.response_message.lower()
    mock_graph.update_state.assert_not_called()


@patch("app.database.get_supabase_admin")
@patch("app.routes.propflow.get_current_user", return_value=_MOCK_CURRENT_USER)
def test_select_blocked_rejected(mock_user, mock_supabase):
    """select on thread at rejected → not clobbered, rejection message."""
    thread_id = "propflow-prot-rejected"
    _mock_db_found(mock_supabase, MOCK_PROPERTY)

    ckpt_tuple = _ckpt({
        "tenant_id": TENANT_ID,
        "property_matches": [MOCK_PROPERTY],
        "current_stage": "rejected",
        "application_id": None,
    })
    mock_checkpointer = AsyncMock()
    mock_checkpointer.aget_tuple.return_value = ckpt_tuple
    mock_graph = MagicMock()
    mock_graph.checkpointer = mock_checkpointer
    mock_graph.update_state = MagicMock()

    with patch("app.routes.propflow.propflow_graph", return_value=mock_graph):
        from app.routes.propflow import select_property
        import asyncio
        result = asyncio.run(select_property(
            workflow_id=thread_id,
            request=type("Req", (), {"property_id": PROPERTY_ID, "property_index": None})(),
            current_user=_MOCK_CURRENT_USER,
        ))

    assert result.success is True
    assert result.current_stage == "rejected"
    assert "not approved" in result.response_message.lower()
    mock_graph.update_state.assert_not_called()
