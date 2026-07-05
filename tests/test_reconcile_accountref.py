# -*- coding: utf-8 -*-
"""
Tests for the Nomba reconciliation + payout event handlers, focusing on
the pieces the PRD V3.2 changes touched:

1. `_reconcile_payment` -- the `-SUB` suffix extraction from accountRef
   (PRD Part 0: regex strips -SUB, leaving the agreement UUID).
2. `_handle_payout_event` -- the payout webhook status map + idempotency
   (PRD Part 1.4: payout_success->released, payout_failed->failed,
   payout_refund->refunded; no-op if already in target status or ref unknown).

These exercise the real route functions with `supabase_admin` mocked at the
`app.routes.nomba` namespace, using a fluent builder mock that records every
(table, method, filter, payload) call and lets each test stage the `.data`
returned for a given table+method pair.

Run: python -m pytest tests/test_reconcile_accountref.py -v
"""
import asyncio
import os
import sys
from unittest.mock import MagicMock

import pytest

# Make the app package importable when running tests from the server dir
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# app.database prints an emoji at import; keep UTF-8 IO so it doesn't blow up
# on the Windows cp1252 console.
os.environ.setdefault("PYTHONUTF8", "1")

from app.routes import nomba  # noqa: E402

AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
LANDLORD_ID = "11111111-1111-1111-1111-111111111111"
TENANT_ID = "22222222-2222-2222-2222-222222222222"


class FluentSupabase:
    """
    Minimal fluent mock for supabase_admin that records calls and serves
    staged `.data` per table+method. Supports the chaining the route uses:
    .table(t).select(...)/update(...)/insert(...).eq(...).maybe_single().execute()
    """

    def __init__(self):
        # staged returns: keyed by (table, method) -> list of dicts to return
        # in sequence (each .execute() pops the next; last one repeats).
        self.staged = {}
        # record of every (table, method, payload, filters) call, newest last
        self.calls = []

    def stage(self, table, method, data):
        self.staged.setdefault((table, method), []).append(data)
        return self

    def _next_data(self, table, method):
        bucket = self.staged.get((table, method))
        if not bucket:
            return []
        if len(bucket) == 1:
            return bucket[0]
        return bucket.pop(0)

    def table(self, name):
        builder = _TableBuilder(self, name)
        return builder


class _TableBuilder:
    def __init__(self, parent, table):
        self._parent = parent
        self._table = table
        self._method = None
        self._payload = None
        self._filters = []
        self._single = False

    def _clone(self):
        c = _TableBuilder(self._parent, self._table)
        c._method = self._method
        c._payload = self._payload
        c._filters = list(self._filters)
        c._single = self._single
        return c

    def select(self, cols="*"):
        b = self._clone()
        b._method = "select"
        b._payload = cols
        return b

    def update(self, payload):
        b = self._clone()
        b._method = "update"
        b._payload = payload
        return b

    def insert(self, payload):
        b = self._clone()
        b._method = "insert"
        b._payload = payload
        return b

    def eq(self, col, val):
        b = self._clone()
        b._filters.append(("eq", col, val))
        return b

    def in_(self, col, vals):
        b = self._clone()
        b._filters.append(("in", col, vals))
        return b

    def maybe_single(self):
        b = self._clone()
        b._single = True
        return b

    def single(self):
        b = self._clone()
        b._single = True
        return b

    def execute(self):
        self._parent.calls.append(
            {
                "table": self._table,
                "method": self._method,
                "payload": self._payload,
                "filters": list(self._filters),
                "single": self._single,
            }
        )
        data = self._parent._next_data(self._table, self._method)
        result = MagicMock()
        if self._single:
            # maybe_single/single -> .data is one dict (or None)
            result.data = data[0] if isinstance(data, list) and data else None
            if not isinstance(data, list):
                result.data = data
        else:
            # non-single -> .data is a list
            result.data = data if isinstance(data, list) else [data] if data else []
        return result


# ============================================================
# Fixtures: swap supabase_admin on the route module under test
# ============================================================

@pytest.fixture
def fake_supabase(monkeypatch):
    fake = FluentSupabase()
    monkeypatch.setattr(nomba, "supabase_admin", fake)
    return fake


def _run(coro):
    # asyncio.run creates+tears down a fresh event loop per call. On Python 3.14
    # asyncio.get_event_loop() raises "no current event loop" in MainThread when
    # none has been created yet, so we use asyncio.run (same pattern as the
    # existing tests/test_nomba_webhook.py).
    return asyncio.run(coro)


def _agreement_row(expected=500000.0, received=0.0, status="PENDING"):
    return {
        "id": AGREEMENT_ID,
        "tenant_id": TENANT_ID,
        "landlord_id": LANDLORD_ID,
        "application_id": "app-1",
        "property_id": "prop-1",
        "rent_amount": 500000.0,
        "expected_payment_amount": expected,
        "payment_frequency": "MONTHLY",
        "total_received_amount": received,
        "reconciliation_status": status,
    }


# ============================================================
# _reconcile_payment -- -SUB suffix extraction (PRD Part 0)
# ============================================================

def test_reconcile_strips_sub_suffix_and_matches_agreement(fake_supabase):
    """accountRef = '<uuid>-SUB' should reconcile to the agreement (regex match)."""
    fake_supabase.stage("agreements", "select", [_agreement_row(expected=500000.0)])
    # All the write-path calls just need a non-None data to not blow up.
    for table, method in [
        ("agreements", "update"),
        ("virtual_account_transfers", "update"),
        ("payment_reconciliation_log", "insert"),
        ("transactions", "insert"),
    ]:
        fake_supabase.stage(table, method, [{}])

    transfer_row = {"id": "xfer-1"}
    _run(nomba._reconcile_payment(transfer_row, f"{AGREEMENT_ID}-SUB", 500000.0))

    # The agreements SELECT must have been filtered by the bare UUID, not the
    # suffixed ref -- that's the whole point of the regex.
    select_call = next(
        c for c in fake_supabase.calls
        if c["table"] == "agreements" and c["method"] == "select"
    )
    eq_filter = next(f for f in select_call["filters"] if f[1] == "id")
    assert eq_filter[2] == AGREEMENT_ID, (
        f"Expected .eq('id', '{AGREEMENT_ID}'), got {eq_filter[2]!r}"
    )
    # Agreements update should carry FULL_PAYMENT.
    update_call = next(
        c for c in fake_supabase.calls
        if c["table"] == "agreements" and c["method"] == "update"
    )
    assert update_call["payload"]["reconciliation_status"] == "FULL_PAYMENT"


def test_reconcile_bare_uuid_without_sub_suffix_still_matches(fake_supabase):
    """Legacy Path A: accountRef = '<uuid>' (no suffix) still resolves."""
    fake_supabase.stage("agreements", "select", [_agreement_row(expected=500000.0)])
    for table, method in [
        ("agreements", "update"),
        ("virtual_account_transfers", "update"),
        ("payment_reconciliation_log", "insert"),
        ("transactions", "insert"),
    ]:
        fake_supabase.stage(table, method, [{}])

    _run(nomba._reconcile_payment({"id": "xfer-1"}, AGREEMENT_ID, 500000.0))

    select_call = next(
        c for c in fake_supabase.calls
        if c["table"] == "agreements" and c["method"] == "select"
    )
    eq_filter = next(f for f in select_call["filters"] if f[1] == "id")
    assert eq_filter[2] == AGREEMENT_ID


def test_reconcile_unknown_uuid_with_sub_is_misdirected(fake_supabase):
    """Unknown UUID + '-SUB' -> MISDIRECTED; the transfer row is flagged."""
    # No agreement SELECT row staged -> .data = [] -> MISDIRECTED branch.
    fake_supabase.stage("agreements", "select", [])
    fake_supabase.stage("virtual_account_transfers", "update", [{}])

    _run(
        nomba._reconcile_payment(
            {"id": "xfer-mis"},
            "00000000-0000-0000-0000-000000000000-SUB",
            500000.0,
        )
    )

    misdirected_update = next(
        c for c in fake_supabase.calls
        if c["table"] == "virtual_account_transfers" and c["method"] == "update"
    )
    assert misdirected_update["payload"]["reconciliation_result"] == "MISDIRECTED"
    # No agreements UPDATE should have run on the misdirected branch.
    assert not any(
        c["table"] == "agreements" and c["method"] == "update"
        for c in fake_supabase.calls
    )


def test_reconcile_underpayment_status(fake_supabase):
    """received < expected -> UNDERPAYMENT."""
    fake_supabase.stage("agreements", "select", [_agreement_row(expected=500000.0)])
    for table, method in [
        ("agreements", "update"),
        ("virtual_account_transfers", "update"),
        ("payment_reconciliation_log", "insert"),
        ("transactions", "insert"),
    ]:
        fake_supabase.stage(table, method, [{}])

    _run(nomba._reconcile_payment({"id": "xfer-2"}, f"{AGREEMENT_ID}-SUB", 100000.0))

    update_call = next(
        c for c in fake_supabase.calls
        if c["table"] == "agreements" and c["method"] == "update"
    )
    assert update_call["payload"]["reconciliation_status"] == "UNDERPAYMENT"


def test_reconcile_overpayment_status(fake_supabase):
    """received > expected -> OVERPAYMENT."""
    fake_supabase.stage("agreements", "select", [_agreement_row(expected=500000.0)])
    for table, method in [
        ("agreements", "update"),
        ("virtual_account_transfers", "update"),
        ("payment_reconciliation_log", "insert"),
        ("transactions", "insert"),
    ]:
        fake_supabase.stage(table, method, [{}])

    _run(nomba._reconcile_payment({"id": "xfer-3"}, AGREEMENT_ID, 800000.0))

    update_call = next(
        c for c in fake_supabase.calls
        if c["table"] == "agreements" and c["method"] == "update"
    )
    assert update_call["payload"]["reconciliation_status"] == "OVERPAYMENT"


def test_reconcile_inserts_held_transaction(fake_supabase):
    """Inbound collection must insert a transactions row with status='held'
    (PRD Part 3.5: 'completed' is NOT allowed; collection -> held)."""
    fake_supabase.stage("agreements", "select", [_agreement_row(expected=500000.0)])
    for table, method in [
        ("agreements", "update"),
        ("virtual_account_transfers", "update"),
        ("payment_reconciliation_log", "insert"),
        ("transactions", "insert"),
    ]:
        fake_supabase.stage(table, method, [{}])

    _run(nomba._reconcile_payment({"id": "xfer-4"}, AGREEMENT_ID, 500000.0))

    tx_insert = next(
        c for c in fake_supabase.calls
        if c["table"] == "transactions" and c["method"] == "insert"
    )
    assert tx_insert["payload"]["status"] == "held"
    assert tx_insert["payload"]["transaction_type"] == "nomba_collection"
    assert tx_insert["payload"]["amount"] == 500000.0


# ============================================================
# _handle_payout_event -- status map + idempotency (PRD Part 1.4)
# ============================================================

MERCHANT_TX_REF = "NULO-DISB-DEADBEEF"


def _payout_payload(event_type, ref=MERCHANT_TX_REF, request_id="req-1"):
    txn_type = "transfer" if event_type == "payout_success" else ""
    return {
        "event_type": event_type,
        "requestId": request_id,
        "data": {
            "merchantTxRef": ref,
            "id": "nomba-txn-123",
            "transaction": {
                "type": txn_type,
                "transactionId": "nomba-txn-123",
                "responseCode": "00",
                "time": "2026-07-05T10:00:00Z",
                "transactionAmount": 100.0,
            },
            "merchant": {"userId": "f666ef9b-888e-4799-85ce-acb505b28023",
                          "walletId": "w-1"},
        },
    }


def test_payout_success_marks_released_and_sets_released_at(fake_supabase):
    # current status lookup -> held (not yet target)
    fake_supabase.stage("transactions", "select", [{"id": "tx-1", "status": "held"}])
    # the update at the end
    fake_supabase.stage("transactions", "update", [{}])

    _run(nomba._handle_payout_event(_payout_payload("payout_success"), "payout_success", "req-1"))

    update_call = next(
        c for c in fake_supabase.calls
        if c["table"] == "transactions" and c["method"] == "update"
    )
    assert update_call["payload"]["status"] == "released"
    assert update_call["payload"].get("released_at") is not None
    assert update_call["payload"].get("nomba_transfer_id") == "nomba-txn-123"
    # refunded_at must NOT be set on a success.
    assert "refunded_at" not in update_call["payload"]


def test_payout_failed_marks_failed_no_timestamp(fake_supabase):
    fake_supabase.stage("transactions", "select", [{"id": "tx-1", "status": "pending"}])
    fake_supabase.stage("transactions", "update", [{}])

    _run(nomba._handle_payout_event(_payout_payload("payout_failed"), "payout_failed", "req-2"))

    update_call = next(
        c for c in fake_supabase.calls
        if c["table"] == "transactions" and c["method"] == "update"
    )
    assert update_call["payload"]["status"] == "failed"
    assert "released_at" not in update_call["payload"]
    assert "refunded_at" not in update_call["payload"]


def test_payout_refund_marks_refunded_and_sets_refunded_at(fake_supabase):
    fake_supabase.stage("transactions", "select", [{"id": "tx-1", "status": "released"}])
    fake_supabase.stage("transactions", "update", [{}])

    _run(nomba._handle_payout_event(_payout_payload("payout_refund"), "payout_refund", "req-3"))

    update_call = next(
        c for c in fake_supabase.calls
        if c["table"] == "transactions" and c["method"] == "update"
    )
    assert update_call["payload"]["status"] == "refunded"
    assert update_call["payload"].get("refunded_at") is not None
    assert "released_at" not in update_call["payload"]


def test_payout_idempotent_if_already_in_target_status(fake_supabase):
    """If the row is already 'released', a second payout_success must NOT
    fire an update (idempotency)."""
    fake_supabase.stage("transactions", "select", [{"id": "tx-1", "status": "released"}])
    # No update should be needed; if one runs, the test below catches it.

    _run(nomba._handle_payout_event(_payout_payload("payout_success"), "payout_success", "req-4"))

    assert not any(
        c["table"] == "transactions" and c["method"] == "update"
        for c in fake_supabase.calls
    ), "Idempotent payout_success should not update an already-released row"


def test_payout_unknown_merchant_tx_ref_is_noop(fake_supabase):
    """Unknown ref -> current lookup returns None -> no update, no crash."""
    fake_supabase.stage("transactions", "select", [None])  # maybe_single -> None

    _run(nomba._handle_payout_event(_payout_payload("payout_success"), "payout_success", "req-5"))

    assert not any(
        c["table"] == "transactions" and c["method"] == "update"
        for c in fake_supabase.calls
    )


def test_payout_missing_merchant_tx_ref_is_noop(fake_supabase):
    """No merchantTxRef in the payload -> handler returns early, zero DB calls."""
    payload = _payout_payload("payout_success")
    payload["data"]["merchantTxRef"] = None

    _run(nomba._handle_payout_event(payload, "payout_success", "req-6"))

    assert fake_supabase.calls == [], (
        "Missing merchantTxRef must short-circuit before any DB call"
    )
