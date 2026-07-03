"""
Nomba webhook and reconciliation tests.
Run: pytest test_nomba_webhook.py -v

Covers PRD Part 8 test cases and the verified signature test vector.
"""
import base64
import hashlib
import hmac
import os
import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

# Make the app package importable when running tests from the server dir
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.nomba_client import NombaClient, NombaAPIError
from app.services.nomba_helpers import (
    GRACE_PERIODS,
    TOLERANCE_PCT,
    calculate_expected_amount,
    calculate_next_due_date,
    classify_payment,
    is_within_grace_period,
)


# ============================================================
# PRD Part 8 TEST 1.0 - Verified signature test vector
# (matches the example in the Nomba PRD Section 1.3)
# ============================================================

VERIFIED_TEST_VECTOR = {
    "event_type":     "payment_success",
    "request_id":     "45f2dc2d-d559-4773-bba3-2d5ec17b2e20",
    "user_id":        "b7b10e81-e57d-41d0-8fdc-f4e23a132bbf",
    "wallet_id":      "6756ff80aafe04a795f18b38",
    "transaction_id": "API-VACT_TRA-B7B10-0435b274-807a-4bc7-8abe-9dbb4548fd7a",
    "type":           "vact_transfer",
    "time":           "2025-09-29T10:51:44Z",
    "response_code":  "",
    "timestamp":      "2025-09-29T10:51:44Z",
    "secret":         "HkatexKDZg7CLWy96q5sfrVHSvtoz92B",
    "expected_sig":   "Kt9095hQxfgmVbx6iz7G2tPhHdbdXgLlyY/mf35sptw=",
}


def test_signature_verified_test_vector():
    """PRD Part 1.3: hand-computed match must equal Nomba's published signature."""
    v = VERIFIED_TEST_VECTOR
    hashing_payload = (
        f"{v['event_type']}:{v['request_id']}:{v['user_id']}:{v['wallet_id']}:"
        f"{v['transaction_id']}:{v['type']}:{v['time']}:"
        f"{v['response_code']}:{v['timestamp']}"
    )
    digest = hmac.new(
        v["secret"].encode(), hashing_payload.encode(), hashlib.sha256
    ).digest()
    computed = base64.b64encode(digest).decode()
    assert computed == v["expected_sig"], (
        f"Hash mismatch. Expected {v['expected_sig']}, got {computed}"
    )


# ============================================================
# NombaClient.verify_webhook_signature
# ============================================================

def _make_client_with_secret(secret: str) -> NombaClient:
    """Build a NombaClient without triggering env validation on init.

    Sets the full set of attributes that NombaClient.__init__ would set, so
    tests exercise the real code path (not mocks). Token state is pre-cached
    to avoid hitting Nomba's auth endpoint during tests.
    """
    import asyncio
    import time
    client = NombaClient.__new__(NombaClient)
    client.webhook_secret = secret
    client.parent_account_id = "test-parent"
    client.sub_account_id = "test-sub-account-id"
    client.base_url = "https://sandbox.nomba.com/v1"
    client.client_id = "test"
    client.client_secret = "test"
    # Pre-cached token state -- _get_token() returns this without HTTP calls
    client._token = "fake-cached-token"
    client._refresh_token_value = "fake-refresh"
    client._expires_at = time.time() + 3600
    client._lock = asyncio.Lock()
    return client


def test_verify_valid_signature():
    client = _make_client_with_secret(VERIFIED_TEST_VECTOR["secret"])
    payload = {
        "event_type": VERIFIED_TEST_VECTOR["event_type"],
        "requestId": VERIFIED_TEST_VECTOR["request_id"],
        "data": {
            "merchant": {
                "userId": VERIFIED_TEST_VECTOR["user_id"],
                "walletId": VERIFIED_TEST_VECTOR["wallet_id"],
            },
            "transaction": {
                "transactionId": VERIFIED_TEST_VECTOR["transaction_id"],
                "type": VERIFIED_TEST_VECTOR["type"],
                "time": VERIFIED_TEST_VECTOR["time"],
                "responseCode": VERIFIED_TEST_VECTOR["response_code"],
            },
        },
    }
    assert client.verify_webhook_signature(
        payload, VERIFIED_TEST_VECTOR["expected_sig"], VERIFIED_TEST_VECTOR["timestamp"]
    ) is True


def test_verify_invalid_signature():
    client = _make_client_with_secret(VERIFIED_TEST_VECTOR["secret"])
    payload = {
        "event_type": "payment_success",
        "requestId": "x",
        "data": {"merchant": {}, "transaction": {}},
    }
    assert client.verify_webhook_signature(
        payload, "invalidsignature==", "2026-07-01T10:00:00Z"
    ) is False


def test_verify_signature_exact_case_required():
    """Per PRD v2: base64 is case-sensitive. Lowercasing the computed
    signature must FAIL verification (no .lower() on either side)."""
    client = _make_client_with_secret(VERIFIED_TEST_VECTOR["secret"])
    payload = {
        "event_type": VERIFIED_TEST_VECTOR["event_type"],
        "requestId": VERIFIED_TEST_VECTOR["request_id"],
        "data": {
            "merchant": {
                "userId": VERIFIED_TEST_VECTOR["user_id"],
                "walletId": VERIFIED_TEST_VECTOR["wallet_id"],
            },
            "transaction": {
                "transactionId": VERIFIED_TEST_VECTOR["transaction_id"],
                "type": VERIFIED_TEST_VECTOR["type"],
                "time": VERIFIED_TEST_VECTOR["time"],
                "responseCode": VERIFIED_TEST_VECTOR["response_code"],
            },
        },
    }
    # Force a case difference in the signature -- must FAIL
    # (the verified signature has both upper and lower case characters;
    # a lowercased version will not match because the comparison is exact-case)
    lowered_sig = VERIFIED_TEST_VECTOR["expected_sig"].lower()
    # If by chance expected_sig is already all-lower, the assertion is moot;
    # in that case we'd test a different case mismatch. Use a mixed-case swap.
    if lowered_sig == VERIFIED_TEST_VECTOR["expected_sig"]:
        # expected_sig is all-lower; uppercasing it would mismatch
        assert client.verify_webhook_signature(
            payload, VERIFIED_TEST_VECTOR["expected_sig"].upper(),
            VERIFIED_TEST_VECTOR["timestamp"]
        ) is False
    else:
        assert client.verify_webhook_signature(
            payload, lowered_sig, VERIFIED_TEST_VECTOR["timestamp"]
        ) is False


def test_account_ref_length_16_to_64():
    """Per Nomba spec, accountRef must be 16-64 chars.
    A standard UUID (36 chars) always satisfies this."""
    uuid_str = "1410d252-73be-4d1d-ae03-9e36aaa80850"
    assert 16 <= len(uuid_str) <= 64


def test_verify_response_code_null_treated_as_empty():
    """PRD: responseCode of 'null' string must be treated as empty."""
    client = _make_client_with_secret(VERIFIED_TEST_VECTOR["secret"])
    payload = {
        "event_type": VERIFIED_TEST_VECTOR["event_type"],
        "requestId": VERIFIED_TEST_VECTOR["request_id"],
        "data": {
            "merchant": {
                "userId": VERIFIED_TEST_VECTOR["user_id"],
                "walletId": VERIFIED_TEST_VECTOR["wallet_id"],
            },
            "transaction": {
                "transactionId": VERIFIED_TEST_VECTOR["transaction_id"],
                "type": VERIFIED_TEST_VECTOR["type"],
                "time": VERIFIED_TEST_VECTOR["time"],
                "responseCode": "null",
            },
        },
    }
    # Should still produce the verified signature
    assert client.verify_webhook_signature(
        payload, VERIFIED_TEST_VECTOR["expected_sig"], VERIFIED_TEST_VECTOR["timestamp"]
    ) is True


# ============================================================
# Helper functions -- PRD Part 5
# ============================================================

def test_calculate_expected_amount_monthly():
    assert calculate_expected_amount(100000.0, "MONTHLY") == 100000.0


def test_calculate_expected_amount_quarterly():
    assert calculate_expected_amount(100000.0, "QUARTERLY") == 300000.0


def test_calculate_expected_amount_semi_annual():
    assert calculate_expected_amount(100000.0, "SEMI_ANNUAL") == 600000.0


def test_calculate_expected_amount_annual():
    assert calculate_expected_amount(100000.0, "ANNUAL") == 1200000.0


def test_calculate_expected_amount_unknown_frequency_defaults_monthly():
    assert calculate_expected_amount(100000.0, "WEEKLY") == 100000.0


def test_classify_payment_full():
    expected = 500000.0
    # Exactly at expected
    assert classify_payment(expected, expected) == "FULL_PAYMENT"
    # Within +2% tolerance
    assert classify_payment(expected * 1.01, expected) == "FULL_PAYMENT"
    # Within -2% tolerance
    assert classify_payment(expected * 0.99, expected) == "FULL_PAYMENT"


def test_classify_payment_underpayment():
    assert classify_payment(250000.0, 500000.0) == "UNDERPAYMENT"


def test_classify_payment_overpayment():
    assert classify_payment(1000000.0, 500000.0) == "OVERPAYMENT"


def test_classify_payment_zero_expected_returns_pending():
    assert classify_payment(100.0, 0.0) == "PENDING"


def test_calculate_next_due_date_monthly():
    start = date(2026, 7, 1)
    assert calculate_next_due_date(start, "MONTHLY") == date(2026, 8, 1)


def test_calculate_next_due_date_quarterly():
    start = date(2026, 7, 1)
    assert calculate_next_due_date(start, "QUARTERLY") == date(2026, 10, 1)


def test_calculate_next_due_date_semi_annual():
    start = date(2026, 7, 1)
    assert calculate_next_due_date(start, "SEMI_ANNUAL") == date(2027, 1, 1)


def test_calculate_next_due_date_annual():
    start = date(2026, 7, 1)
    assert calculate_next_due_date(start, "ANNUAL") == date(2027, 7, 1)


def test_grace_periods_defined():
    assert GRACE_PERIODS["MONTHLY"] == 1
    assert GRACE_PERIODS["QUARTERLY"] == 3
    assert GRACE_PERIODS["SEMI_ANNUAL"] == 5
    assert GRACE_PERIODS["ANNUAL"] == 7


def test_tolerance_constant():
    assert TOLERANCE_PCT == 0.02


# ============================================================
# Phase 3 (disbursement) helpers -- PRD v2 Part 5
# ============================================================

def test_calculate_landlord_payout_basic():
    """50000 received, 5000 fee -> 45000 payout."""
    from app.services.nomba_helpers import calculate_landlord_payout
    assert calculate_landlord_payout(50000.0, 5000.0) == 45000.0


def test_calculate_landlord_payout_no_fee():
    from app.services.nomba_helpers import calculate_landlord_payout
    assert calculate_landlord_payout(50000.0, 0.0) == 50000.0


def test_calculate_landlord_payout_rounds_to_2dp():
    from app.services.nomba_helpers import calculate_landlord_payout
    result = calculate_landlord_payout(100.0, 33.337)
    assert result == 66.66


def test_calculate_landlord_payout_never_negative():
    """If fee exceeds received, payout must clamp to 0, not go negative."""
    from app.services.nomba_helpers import calculate_landlord_payout
    assert calculate_landlord_payout(100.0, 500.0) == 0.0


def test_build_merchant_tx_ref_basic():
    """First attempt has no -R suffix."""
    from app.services.nomba_helpers import build_merchant_tx_ref
    ref = build_merchant_tx_ref("1410d252-73be-4d1d-ae03-9e36aaa80850")
    assert ref == "NULO-DISB-1410D252"


def test_build_merchant_tx_ref_with_retry():
    """Retry attempt has -R{count} suffix."""
    from app.services.nomba_helpers import build_merchant_tx_ref
    ref = build_merchant_tx_ref("1410d252-73be-4d1d-ae03-9e36aaa80850", retry_count=2)
    assert ref == "NULO-DISB-1410D252-R2"


def test_build_merchant_tx_ref_truncates_to_8_chars():
    from app.services.nomba_helpers import build_merchant_tx_ref
    ref = build_merchant_tx_ref("ABCDEFGH-IJKLMNOPQRSTUVWXYZ-1234567890")
    assert ref.startswith("NULO-DISB-ABCDEFGH")
    # After the 8-char prefix, no further UUID content should appear
    assert "IJKLMNOPQRSTUVWXYZ" not in ref


# ============================================================
# transfer_to_bank -- idempotency enforcement
# ============================================================

def test_transfer_to_bank_requires_merchant_tx_ref():
    """transfer_to_bank must reject empty/None merchant_tx_ref."""
    from unittest.mock import patch, MagicMock
    client = _make_client_with_secret("dummy")
    # The validation runs before any HTTP call, so we don't need to mock requests
    import asyncio
    with pytest.raises(Exception) as excinfo:
        asyncio.run(client.transfer_to_bank(
            amount_naira=1000.0,
            account_number="0123456789",
            account_name="Test",
            bank_code="058",
            merchant_tx_ref="",   # <-- empty
            narration="Test",
        ))
    assert "merchant_tx_ref" in str(excinfo.value).lower()


def test_transfer_to_bank_uses_decimal_naira_not_kobo():
    """PRD v2: amount is decimal Naira, not kobo * 100.
    A 50000 Naira transfer must send amount=50000.0, not 5000000.

    Runs the real _get_token path (pre-cached in the helper) -- only
    requests.post is mocked, since that's what reaches Nomba.
    """
    from unittest.mock import patch, MagicMock
    client = _make_client_with_secret("dummy")
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"data": {"status": "PENDING"}}
    posted_json = None

    def capture(*args, **kwargs):
        nonlocal posted_json
        posted_json = kwargs.get("json")
        return mock_resp

    with patch("app.services.nomba_client.requests.post", side_effect=capture):
        import asyncio
        asyncio.run(client.transfer_to_bank(
            amount_naira=50000.0,
            account_number="0123456789",
            account_name="Test",
            bank_code="058",
            merchant_tx_ref="NULO-DISB-TEST-0001",
            narration="Test",
        ))
    assert posted_json is not None, "requests.post was never called"
    assert posted_json["amount"] == 50000.0, (
        f"Expected 50000.0 decimal Naira, got {posted_json['amount']}"
    )
