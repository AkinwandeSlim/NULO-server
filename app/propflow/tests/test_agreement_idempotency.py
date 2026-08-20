"""
Idempotency-guard tests for AgreementService.auto_generate_agreement
=====================================================================

These tests lock in the guard that prevents a single application from ever
producing more than one agreement row.

Background (see docs/PROPFLOW_COMPLETE_AUDIT.md, Gap #7 / Recommendation #7):
the landlord-approval bridge has TWO paths that can both create an agreement
for the same application:

  1. The PropFlow graph path:  approve -> graph.ainvoke() -> create_agreement
     node -> auto_generate_agreement()
  2. The manual fallback path (routes/applications.py): if the PropFlow resume
     fails silently, the route falls back and calls auto_generate_agreement()
     itself -- and a later graph retry would run create_agreement again.

Both paths funnel through auto_generate_agreement(), so the guard lives there
as the single chokepoint covering double-approvals, graph re-runs, and the
approve/fallback race. The `agreements` table has NO unique constraint on
`application_id`, so this guard is the only thing preventing duplicates.

Guard contract under test:
  * Case A -- an agreement already exists for the application_id -> return the
              existing row immediately; AI generation and the insert are NOT
              run (so no duplicate "agreement created" notification fires).
  * Case B -- no existing agreement -> fall through and create a new one.
  * Case C -- the existence check raises (transient read failure) -> do NOT
              block; fall through and attempt creation.

All Supabase traffic is mocked through the module-level `run_db_async` helper,
so these tests never touch the network.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agreement_service import AgreementService, agreement_service

APP_ID = "app-1234"
PROPERTY_DATA = {"id": "prop-1", "landlord_id": "landlord-1", "title": "Test Property"}
TENANT_DATA = {"id": "tenant-1", "full_name": "Test Tenant", "email": "t@t.com"}


def _db_result(rows):
    """Stand-in for a supabase-py PostgrestResponse (the code reads `.data`)."""
    result = MagicMock()
    result.data = rows
    return result


def _kwargs():
    return dict(
        application_id=APP_ID,
        property_data=PROPERTY_DATA,
        tenant_data=TENANT_DATA,
        landlord_name="Test Landlord",
        landlord_email="l@l.com",
        landlord_phone="08012345678",
    )


@pytest.mark.asyncio
async def test_guard_returns_existing_agreement_and_skips_creation():
    """Case A: a pre-existing agreement for the application is returned and no
    generation/insert happens (no duplicate, no duplicate notification)."""
    existing_row = {
        "id": "existing-agreement-uuid",
        "application_id": APP_ID,
        "status": "PENDING_TENANT",
    }

    with patch(
        "app.services.agreement_service.run_db_async",
        new_callable=AsyncMock,
        return_value=_db_result([existing_row]),
    ) as mock_db, patch(
        "app.services.agreement_service.AgreementService.generate_enhanced_agreement_terms",
        new_callable=AsyncMock,
    ) as mock_generate:
        result = await agreement_service.auto_generate_agreement(**_kwargs())

    # The existing row is returned verbatim.
    assert result == existing_row
    assert result["id"] == "existing-agreement-uuid"

    # AI generation was never re-run ...
    mock_generate.assert_not_awaited()
    # ... and the only DB call made was the existence check (no insert).
    assert mock_db.await_count == 1


@pytest.mark.asyncio
async def test_guard_creates_agreement_when_none_exists():
    """Case B: no existing agreement -> the guard falls through and a new row
    is inserted and returned."""
    new_row = {
        "id": "new-agreement-uuid",
        "application_id": APP_ID,
        "status": "PENDING_TENANT",
    }

    # 1st run_db_async call = existence check (empty); 2nd = insert (new row).
    mock_db = AsyncMock(side_effect=[_db_result([]), _db_result([new_row])])

    with patch("app.services.agreement_service.run_db_async", mock_db), patch(
        "app.services.agreement_service.AgreementService.generate_enhanced_agreement_terms",
        new_callable=AsyncMock,
        return_value={"terms": "Terms text", "source": "template", "metadata": {}},
    ) as mock_generate, patch(
        "app.services.agreement_service.AgreementService.create_agreement_dict",
        return_value={"id": "new-agreement-uuid", "application_id": APP_ID},
    ), patch(
        "app.services.notification_service.notification_service.notify_agreement_created",
        new_callable=AsyncMock,
    ):
        result = await agreement_service.auto_generate_agreement(**_kwargs())

    # A new agreement was created and returned.
    assert result == new_row
    assert result["id"] == "new-agreement-uuid"

    # Generation ran (we got past the guard) and exactly two DB calls happened:
    # the existence check plus the insert.
    mock_generate.assert_awaited_once()
    assert mock_db.await_count == 2


@pytest.mark.asyncio
async def test_guard_falls_through_on_transient_read_failure():
    """Case C: the existence check raises (transient read failure) -> the guard
    must NOT block creation; it falls through and attempts the insert."""
    new_row = {
        "id": "created-after-failure-uuid",
        "application_id": APP_ID,
        "status": "PENDING_TENANT",
    }

    # 1st run_db_async call (existence check) raises; 2nd (insert) succeeds.
    mock_db = AsyncMock(
        side_effect=[ConnectionError("connection reset"), _db_result([new_row])]
    )

    with patch("app.services.agreement_service.run_db_async", mock_db), patch(
        "app.services.agreement_service.AgreementService.generate_enhanced_agreement_terms",
        new_callable=AsyncMock,
        return_value={"terms": "Terms text", "source": "template", "metadata": {}},
    ) as mock_generate, patch(
        "app.services.agreement_service.AgreementService.create_agreement_dict",
        return_value={"id": "created-after-failure-uuid", "application_id": APP_ID},
    ), patch(
        "app.services.notification_service.notification_service.notify_agreement_created",
        new_callable=AsyncMock,
    ):
        result = await agreement_service.auto_generate_agreement(**_kwargs())

    # Creation proceeded despite the failed read; the inserted row is returned.
    assert result == new_row
    mock_generate.assert_awaited_once()
