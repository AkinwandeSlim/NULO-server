#!/usr/bin/env python3
"""
PropFlow Select Property Endpoint Tests
========================================
Comprehensive tests for the enhanced property selection endpoint
with support for multiple resolution paths.

Tests cover:
1. Path 1: Index-based selection (backward compatible)
2. Path 2: State-based resolution (property_id in matches)
3. Path 3: Direct DB lookup (property_id not in matches)
4. Path 4: Thread resurrection (missing/expired threads)
5. Edge cases and error scenarios

Usage:
    pytest tests/test_propflow_select_property.py -v
"""

import pytest
import uuid
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime

# Mock FastAPI dependencies
from fastapi import HTTPException


class TestSelectPropertyEndpoint:
    """Tests for POST /api/v1/propflow/select/{workflow_id}"""

    @pytest.fixture
    def mock_current_user(self):
        """Mock authenticated user."""
        return {
            "id": str(uuid.uuid4()),
            "email": "test.tenant@example.com",
            "user_type": "tenant",
            "phone_number": "+2348012345678",
            "full_name": "Test Tenant"
        }

    @pytest.fixture
    def mock_property_matches(self):
        """Mock property matches from search results."""
        return [
            {
                "id": str(uuid.uuid4()),
                "title": "2-Bedroom Apartment",
                "location": "Lekki",
                "price": 800000,
                "beds": 2,
                "baths": 2,
                "landlord_id": str(uuid.uuid4()),
                "property_type": "apartment"
            },
            {
                "id": str(uuid.uuid4()),
                "title": "3-Bedroom House",
                "location": "Victoria Island",
                "price": 1200000,
                "beds": 3,
                "baths": 3,
                "landlord_id": str(uuid.uuid4()),
                "property_type": "house"
            }
        ]

    @pytest.fixture
    def mock_checkpoint(self, mock_property_matches):
        """Mock checkpoint with property matches."""
        return Mock(
            checkpoint={
                "channel_values": {
                    "property_matches": mock_property_matches,
                    "current_stage": "awaiting_tenant_selection"
                }
            }
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Path 1: Index-based Selection (Backward Compatible)
    # ═══════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_select_by_index_success(self, mock_current_user, mock_property_matches, mock_checkpoint):
        """Test successful property selection by index (Path 1)."""
        from app.routes.propflow import select_property, SelectRequest

        # Mock graph and checkpointer
        with patch('app.routes.propflow.propflow_graph') as mock_graph_func:
            mock_graph = Mock()
            mock_graph.checkpointer.aget_tuple = AsyncMock(return_value=mock_checkpoint)
            mock_graph.update_state = Mock()
            mock_graph_func.return_value = mock_graph

            # Test data
            workflow_id = str(uuid.uuid4())
            request = SelectRequest(property_index=0)

            # Execute
            response = await select_property(workflow_id, request, mock_current_user)

            # Assertions
            assert response.success is True
            assert response.workflow_id == workflow_id
            assert response.current_stage == "awaiting_trust_profile"
            assert "Great choice" in response.response_message
            mock_graph.update_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_by_index_out_of_range(self, mock_current_user, mock_property_matches, mock_checkpoint):
        """Test selection fails when index is out of range."""
        from app.routes.propflow import select_property, SelectRequest

        with patch('app.routes.propflow.propflow_graph') as mock_graph_func:
            mock_graph = Mock()
            mock_graph.checkpointer.aget_tuple = AsyncMock(return_value=mock_checkpoint)
            mock_graph_func.return_value = mock_graph

            workflow_id = str(uuid.uuid4())
            request = SelectRequest(property_index=99)  # Out of range

            response = await select_property(workflow_id, request, mock_current_user)

            assert response.success is False
            assert response.current_stage == "error"
            assert "Invalid selection" in response.response_message
            assert "out of range" in response.error_message

    @pytest.mark.asyncio
    async def test_select_by_index_no_matches(self, mock_current_user):
        """Test selection fails when no property matches exist."""
        from app.routes.propflow import select_property, SelectRequest

        # Mock empty checkpoint
        empty_checkpoint = Mock(
            checkpoint={"channel_values": {"property_matches": []}}
        )

        with patch('app.routes.propflow.propflow_graph') as mock_graph_func:
            mock_graph = Mock()
            mock_graph.checkpointer.aget_tuple = AsyncMock(return_value=empty_checkpoint)
            mock_graph_func.return_value = mock_graph

            workflow_id = str(uuid.uuid4())
            request = SelectRequest(property_index=0)

            response = await select_property(workflow_id, request, mock_current_user)

            assert response.success is False
            assert response.current_stage == "error"
            assert "No properties found" in response.response_message

    # ═══════════════════════════════════════════════════════════════════════
    # Path 2: State-based Resolution (property_id in matches)
    # ═══════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_select_by_property_id_from_state(self, mock_current_user, mock_property_matches, mock_checkpoint):
        """Test property selection by ID when property exists in current matches (Path 2)."""
        from app.routes.propflow import select_property, SelectRequest

        with patch('app.routes.propflow.propflow_graph') as mock_graph_func:
            mock_graph = Mock()
            mock_graph.checkpointer.aget_tuple = AsyncMock(return_value=mock_checkpoint)
            mock_graph.update_state = Mock()
            mock_graph_func.return_value = mock_graph

            workflow_id = str(uuid.uuid4())
            target_property_id = mock_property_matches[1]["id"]  # Second property
            request = SelectRequest(property_id=target_property_id)

            response = await select_property(workflow_id, request, mock_current_user)

            assert response.success is True
            assert response.current_stage == "awaiting_trust_profile"
            mock_graph.update_state.assert_called_once()

    # ═══════════════════════════════════════════════════════════════════════
    # Path 3: Direct DB Lookup
    # ═══════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_select_by_property_id_from_db(self, mock_current_user):
        """Test property selection by ID via direct DB lookup (Path 3)."""
        from app.routes.propflow import select_property, SelectRequest

        property_id = str(uuid.uuid4())
        landlord_id = str(uuid.uuid4())
        
        mock_db_property = {
            "id": property_id,
            "title": "Luxury Villa",
            "location": "Banana Island",
            "price": 5000000,
            "beds": 5,
            "baths": 4,
            "landlord_id": landlord_id,
            "property_type": "villa"
        }

        # Mock empty matches (property not in state)
        empty_checkpoint = Mock(
            checkpoint={"channel_values": {"property_matches": []}}
        )

        with patch('app.routes.propflow.propflow_graph') as mock_graph_func, \
             patch('app.database.get_supabase_admin') as mock_supabase:
            
            # Setup mocks
            mock_graph = Mock()
            mock_graph.checkpointer.aget_tuple = AsyncMock(return_value=empty_checkpoint)
            mock_graph.update_state = Mock()
            mock_graph_func.return_value = mock_graph

            # Mock Supabase response
            mock_response = Mock()
            mock_response.data = mock_db_property
            mock_supabase.return_value.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_response

            workflow_id = str(uuid.uuid4())
            request = SelectRequest(property_id=property_id)

            response = await select_property(workflow_id, request, mock_current_user)

            assert response.success is True
            assert response.current_stage == "awaiting_trust_profile"
            mock_graph.update_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_by_property_id_not_found(self, mock_current_user):
        """Test selection fails when property_id doesn't exist in DB."""
        from app.routes.propflow import select_property, SelectRequest

        empty_checkpoint = Mock(
            checkpoint={"channel_values": {"property_matches": []}}
        )

        with patch('app.routes.propflow.propflow_graph') as mock_graph_func, \
             patch('app.propflow.checkpointer.get_checkpointer') as mock_get_checkpointer, \
             patch('app.database.get_supabase_admin') as mock_supabase:
            
            mock_graph = Mock()
            mock_graph.checkpointer.aget_tuple = AsyncMock(return_value=empty_checkpoint)
            mock_graph_func.return_value = mock_graph

            # Mock checkpointer so the resurrection path (Path 4) returns None
            mock_checkpointer = Mock()
            mock_checkpointer.resurrect_thread = AsyncMock(return_value=None)
            mock_get_checkpointer.return_value = mock_checkpointer

            # Mock Supabase empty response
            mock_response = Mock()
            mock_response.data = None
            mock_supabase.return_value.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_response

            workflow_id = str(uuid.uuid4())
            request = SelectRequest(property_id=str(uuid.uuid4()))

            response = await select_property(workflow_id, request, mock_current_user)

            assert response.success is False
            assert response.current_stage == "error"
            assert "Property not found" in response.response_message

    # ═══════════════════════════════════════════════════════════════════════
    # Path 4: Thread Resurrection
    # ═══════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_select_with_thread_resurrection(self, mock_current_user, mock_property_matches):
        """Test property selection with thread resurrection (Path 4)."""
        from app.routes.propflow import select_property, SelectRequest

        property_id = mock_property_matches[0]["id"]
        
        # Mock saved checkpoint (thread exists)
        saved_checkpoint = Mock(
            checkpoint={"channel_values": {"property_matches": []}}  # Empty matches triggers resurrection
        )

        # Mock resurrected checkpoint with property
        resurrected_checkpoint = {
            "channel_values": {
                "property_matches": [mock_property_matches[0]],
                "current_stage": "awaiting_trust_profile"
            }
        }

        with patch('app.routes.propflow.propflow_graph') as mock_graph_func, \
             patch('app.propflow.checkpointer.get_checkpointer') as mock_get_checkpointer, \
             patch('app.database.get_supabase_admin') as mock_supabase:
            
            mock_graph = Mock()
            mock_graph.checkpointer.aget_tuple = AsyncMock(return_value=saved_checkpoint)
            mock_graph.update_state = Mock()
            mock_graph_func.return_value = mock_graph

            # Mock checkpointer resurrection
            mock_checkpointer = Mock()
            mock_checkpointer.resurrect_thread = AsyncMock(return_value=resurrected_checkpoint)
            mock_get_checkpointer.return_value = mock_checkpointer

            # Mock DB lookup fails (to trigger resurrection)
            mock_response = Mock()
            mock_response.data = None
            mock_supabase.return_value.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_response

            workflow_id = str(uuid.uuid4())
            request = SelectRequest(property_id=property_id)

            response = await select_property(workflow_id, request, mock_current_user)

            assert response.success is True
            mock_checkpointer.resurrect_thread.assert_called_once()

    # ═══════════════════════════════════════════════════════════════════════
    # Validation & Edge Cases
    # ═══════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_select_invalid_uuid_format(self, mock_current_user):
        """Test selection fails with invalid UUID format for property_id."""
        from app.routes.propflow import select_property, SelectRequest

        empty_checkpoint = Mock(
            checkpoint={"channel_values": {"property_matches": []}}
        )

        with patch('app.routes.propflow.propflow_graph') as mock_graph_func:
            mock_graph = Mock()
            mock_graph.checkpointer.aget_tuple = AsyncMock(return_value=empty_checkpoint)
            mock_graph_func.return_value = mock_graph

            workflow_id = str(uuid.uuid4())
            request = SelectRequest(property_id="invalid-uuid-format")

            response = await select_property(workflow_id, request, mock_current_user)

            assert response.success is False
            assert response.current_stage == "error"
            assert "Invalid property ID format" in response.response_message

    @pytest.mark.asyncio
    async def test_select_mutually_exclusive_parameters(self):
        """Test that SelectRequest enforces mutual exclusivity."""
        from app.routes.propflow import SelectRequest
        from pydantic import ValidationError

        # Test both parameters provided (should fail)
        with pytest.raises(ValidationError):
            SelectRequest(property_index=0, property_id=str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_select_no_parameters(self):
        """Test that SelectRequest requires at least one parameter."""
        from app.routes.propflow import SelectRequest
        from pydantic import ValidationError

        # Test no parameters provided (should fail)
        with pytest.raises(ValidationError):
            SelectRequest()

    @pytest.mark.asyncio
    async def test_select_exception_handling(self, mock_current_user):
        """Test that unexpected exceptions are handled gracefully."""
        from app.routes.propflow import select_property, SelectRequest

        with patch('app.routes.propflow.propflow_graph') as mock_graph_func:
            mock_graph = Mock()
            mock_graph.checkpointer.aget_tuple = AsyncMock(side_effect=Exception("Database connection failed"))
            mock_graph_func.return_value = mock_graph

            workflow_id = str(uuid.uuid4())
            request = SelectRequest(property_index=0)

            response = await select_property(workflow_id, request, mock_current_user)

            assert response.success is False
            assert response.current_stage == "error"
            assert "Failed to process" in response.response_message

    # ═══════════════════════════════════════════════════════════════════════
    # User Context Tests
    # ═══════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_select_user_with_phone(self, mock_property_matches, mock_checkpoint):
        """Test response message for user with phone number."""
        from app.routes.propflow import select_property, SelectRequest

        user_with_phone = {
            "id": str(uuid.uuid4()),
            "email": "test@example.com",
            "phone_number": "+2348012345678"
        }

        with patch('app.routes.propflow.propflow_graph') as mock_graph_func:
            mock_graph = Mock()
            mock_graph.checkpointer.aget_tuple = AsyncMock(return_value=mock_checkpoint)
            mock_graph.update_state = Mock()
            mock_graph_func.return_value = mock_graph

            workflow_id = str(uuid.uuid4())
            request = SelectRequest(property_index=0)

            response = await select_property(workflow_id, request, user_with_phone)

            assert response.success is True
            assert "already have your name and phone" in response.response_message

    @pytest.mark.asyncio
    async def test_select_user_without_phone(self, mock_property_matches, mock_checkpoint):
        """Test response message for user without phone number (Google OAuth)."""
        from app.routes.propflow import select_property, SelectRequest

        user_without_phone = {
            "id": str(uuid.uuid4()),
            "email": "test@example.com",
            "phone_number": None
        }

        with patch('app.routes.propflow.propflow_graph') as mock_graph_func:
            mock_graph = Mock()
            mock_graph.checkpointer.aget_tuple = AsyncMock(return_value=mock_checkpoint)
            mock_graph.update_state = Mock()
            mock_graph_func.return_value = mock_graph

            workflow_id = str(uuid.uuid4())
            request = SelectRequest(property_index=0)

            response = await select_property(workflow_id, request, user_without_phone)

            assert response.success is True
            assert "add your phone number" in response.response_message


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
