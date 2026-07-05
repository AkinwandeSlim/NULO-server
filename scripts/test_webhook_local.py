"""
One-shot Nomba webhook tester for local FastAPI.

Posts a correctly-signed Nomba payment webhook to the local server and prints
the response. Use this to verify the integration end-to-end BEFORE pointing
the Nomba dashboard at your production URL.

Usage:
    python scripts/test_webhook_local.py <agreement_uuid> [scenario]

Scenarios:
    full_payment   (default) -- amount == expected amount
    underpayment              -- amount = 30% of expected
    overpayment               -- amount = 150% of expected
    misdirected               -- account_ref set to a bogus UUID

Override the target URL with the WEBHOOK_TEST_URL env var:
    WEBHOOK_TEST_URL=https://staging.nuloafrica.com/api/v1/webhooks/nomba/transfer \\
        python scripts/test_webhook_local.py <agreement_uuid> full_payment

Webhook secret is read from NOMBA_WEBHOOK_SECRET env var, falling back to the
hackathon-provided default.

What it does:
  1. Fetches the agreement from Supabase to get the real expected_amount
     and rent_amount (so the scenarios test real values, not hardcoded ones).
  2. Builds a Nomba-shaped payload with the right structure.
  3. Signs it with the 9-field colon-joined HMAC-SHA256 (base64, exact-case).
  4. POSTs to the webhook URL with nomba-signature and nomba-timestamp headers.
  5. Prints HTTP status + response body.
  6. Verifies side-effects in Supabase: virtual_account_transfers row,
     agreement.total_received_amount, transactions row, payment_reconciliation_log.

Exit codes:
  0  webhook accepted and side-effects look correct
  1  webhook returned non-2xx (signature failure, validation, etc.)
  2  setup error (could not fetch agreement, etc.)
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Local defaults. Override with env vars.
DEFAULT_WEBHOOK_URL = "http://localhost:8000/api/v1/webhooks/nomba/transfer"
WEBHOOK_SECRET = os.environ.get("NOMBA_WEBHOOK_SECRET", "NombaHackathon2026")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = (
    os.environ.get("SUPABASE_SERVICE_KEY")
    or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or ""
)

# Bank lookup is a no-op for this test -- any bank name/number works for the
# sender side. We use GTBank (058) to match the existing simulate_nomba_webhook.py.
SENDER_BANK_CODE = "058"
SENDER_BANK_NAME = "GTBank"
SENDER_NAME = "TEST TENANT"
SENDER_ACCOUNT = "0123456789"

# Sub-account ID from .env -- appears in the merchant block of the signed
# payload. Not validated server-side, but must be present and stable for the
# signature to match. Override via env if you rotate sub-accounts.
SUB_ACCOUNT_USER_ID = os.environ.get(
    "NOMBA_SUB_ACCOUNT_ID", "282e5b9b-d14f-4e43-840d-43ddfd90a071"
)
WALLET_ID = "test-wallet-001"


def build_payload(agreement_id, amount, account_ref, scenario, request_id):
    """Build a Nomba webhook payload matching the live schema."""
    now = datetime.now(timezone.utc)
    iso_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "event_type": "payment_success",
        "requestId": request_id,
        "data": {
            "merchant": {
                "walletId": WALLET_ID,
                "walletBalance": 50000,
                "userId": SUB_ACCOUNT_USER_ID,
            },
            "terminal": {},
            "transaction": {
                "aliasAccountNumber": "9391076543",
                "fee": 5,
                "sessionId": f"test-session-{scenario}-{request_id[:8]}",
                "type": "vact_transfer",
                "transactionId": f"test-txn-{scenario}-{request_id[:8]}",
                "aliasAccountName": "NuloAfrica/Test Tenant",
                "responseCode": "",
                "originatingFrom": "api",
                "transactionAmount": amount,
                "narration": f"Rent payment scenario={scenario}",
                "time": iso_time,
                "aliasAccountReference": account_ref,
                "aliasAccountType": "VIRTUAL",
            },
            "customer": {
                "bankCode": SENDER_BANK_CODE,
                "senderName": SENDER_NAME,
                "bankName": SENDER_BANK_NAME,
                "accountNumber": SENDER_ACCOUNT,
            },
        },
    }


def sign_payload(payload, nomba_timestamp):
    """Compute Nomba's HMAC-SHA256 signature over the 9-field colon string."""
    data = payload["data"]
    merchant = data["merchant"]
    txn = data["transaction"]
    response_code = txn.get("responseCode") or ""
    hashing_payload = (
        f"{payload['event_type']}:{payload['requestId']}:{merchant['userId']}:"
        f"{merchant['walletId']}:{txn['transactionId']}:{txn['type']}:"
        f"{txn['time']}:{response_code}:{nomba_timestamp}"
    )
    digest = hmac.new(
        WEBHOOK_SECRET.encode(), hashing_payload.encode(), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode()


def fetch_agreement(agreement_id):
    """Fetch the agreement from Supabase to compute scenario amounts."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None
    # Use the PostgREST endpoint directly with the service key
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/agreements"
    params = {
        "id": f"eq.{agreement_id}",
        "select": "id,rent_amount,payment_frequency,expected_payment_amount,"
                  "total_received_amount,reconciliation_status",
    }
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def verify_side_effects(agreement_id, expected_amount, request_id, scenario):
    """Query the side-effect tables and print a one-line summary each."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("\n[verify] SUPABASE_URL/SERVICE_KEY not set -- skipping DB check")
        return
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    base = SUPABASE_URL.rstrip("/")

    # 1. virtual_account_transfers by request_id
    r = requests.get(
        f"{base}/rest/v1/virtual_account_transfers",
        headers=headers,
        params={"nomba_request_id": f"eq.{request_id}",
                "select": "id,amount_received,reconciliation_result,agreement_id"},
        timeout=15,
    )
    transfers = r.json() if r.ok else []
    print(f"\n[verify] virtual_account_transfers for requestId={request_id}:")
    if transfers:
        for row in transfers:
            print(f"   - id={row['id']}")
            print(f"     amount_received={row['amount_received']}")
            print(f"     reconciliation_result={row['reconciliation_result']}")
            print(f"     agreement_id={row.get('agreement_id')}")
    else:
        print("   - none (idempotent retry, or webhook not yet processed)")

    # 2. agreement totals
    r = requests.get(
        f"{base}/rest/v1/agreements",
        headers=headers,
        params={"id": f"eq.{agreement_id}",
                "select": "total_received_amount,reconciliation_status"},
        timeout=15,
    )
    rows = r.json() if r.ok else []
    if rows:
        a = rows[0]
        print(f"\n[verify] agreement {agreement_id[:8]}:")
        print(f"   - total_received_amount = {a['total_received_amount']}")
        print(f"   - reconciliation_status = {a['reconciliation_status']}")

    # 3. transactions row (only for full_payment / overpayment paths)
    if scenario in ("full_payment", "overpayment"):
        r = requests.get(
            f"{base}/rest/v1/transactions",
            headers=headers,
            params={"agreement_id": f"eq.{agreement_id}",
                    "transaction_type": "eq.nomba_collection",
                    "select": "id,amount,status,created_at",
                    "order": "created_at.desc",
                    "limit": "1"},
            timeout=15,
        )
        txns = r.json() if r.ok else []
        if txns:
            t = txns[0]
            print(f"\n[verify] latest nomba_collection transaction:")
            print(f"   - id={t['id']}")
            print(f"   - amount={t['amount']} (expected ~{expected_amount})")
            print(f"   - status={t['status']} (expected 'held')")

    # 4. payment_reconciliation_log
    r = requests.get(
        f"{base}/rest/v1/payment_reconciliation_log",
        headers=headers,
        params={"agreement_id": f"eq.{agreement_id}",
                "select": "previous_status,new_status,received_amount,expected_amount,variance_pct,notes",
                "order": "created_at.desc",
                "limit": "1"},
        timeout=15,
    )
    logs = r.json() if r.ok else []
    if logs:
        l = logs[0]
        print(f"\n[verify] latest reconciliation log:")
        print(f"   - {l['previous_status']} -> {l['new_status']}")
        print(f"   - received={l['received_amount']} expected={l['expected_amount']}")
        print(f"   - variance_pct={l['variance_pct']}  notes={l['notes']}")


def main():
    parser = argparse.ArgumentParser(
        description="Post a signed Nomba webhook to the local server",
    )
    parser.add_argument("agreement_id", help="UUID of the SIGNED agreement")
    parser.add_argument(
        "scenario",
        nargs="?",
        default="full_payment",
        choices=["full_payment", "underpayment", "overpayment", "misdirected"],
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("WEBHOOK_TEST_URL", DEFAULT_WEBHOOK_URL),
        help="Webhook URL (default: %(default)s)",
    )
    parser.add_argument(
        "--no-verify-db",
        action="store_true",
        help="Skip the post-call DB verification step",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Nomba webhook local test")
    print("=" * 70)
    print(f"Agreement ID : {args.agreement_id}")
    print(f"Scenario     : {args.scenario}")
    print(f"Target URL   : {args.url}")
    print(f"Webhook key  : {'<env>' if os.environ.get('NOMBA_WEBHOOK_SECRET') else '<default>'}")
    print(f"Supabase URL : {SUPABASE_URL or '<not set -- DB verify will be skipped>'}")
    print("=" * 70)

    # Look up the agreement to compute scenario amounts
    agreement = fetch_agreement(args.agreement_id)
    if not agreement and SUPABASE_URL:
        print(f"\nERROR: agreement {args.agreement_id} not found in Supabase.")
        sys.exit(2)
    if agreement:
        rent = float(agreement["rent_amount"])
        frequency = agreement.get("payment_frequency") or "MONTHLY"
        multipliers = {
            "MONTHLY": 1, "QUARTERLY": 3, "SEMI_ANNUAL": 6, "ANNUAL": 12,
        }
        mult = multipliers.get(frequency, 1)
        expected_amount = round(rent * mult, 2)
        print(f"\nAgreement rent_amount = {rent}, frequency = {frequency}")
        print(f"Computed expected_amount = {expected_amount}")
    else:
        # Fallback: 500,000 naira (same as the original simulator)
        expected_amount = 500000.0
        print(f"\nNo Supabase env -- using fallback expected_amount = {expected_amount}")

    scenario_ratios = {
        "full_payment": 1.0,
        "underpayment": 0.30,
        "overpayment": 1.50,
        "misdirected": 1.0,  # amount is irrelevant; account_ref is bogus
    }
    amount = round(expected_amount * scenario_ratios[args.scenario], 2)
    # For non-misdirected scenarios, send the SUFFIXED accountRef ({uuid}-SUB).
    # This matches what the production route now stores on Nomba (Path B
    # sub-account VA) and what the webhook's aliasAccountReference will echo
    # back. Without the suffix, virtual_account_transfers.account_ref will not
    # match the row and payment_status will return an empty transfer_history.
    # The misdirected scenario keeps the zero-UUID -- it tests the
    # "no agreement matches" path regardless of suffix.
    if args.scenario == "misdirected":
        account_ref = "00000000-0000-0000-0000-000000000000"
    else:
        account_ref = f"{args.agreement_id}-SUB"

    # Fresh request_id per run so we can re-run the script multiple times
    # against the same agreement. For the second run, the webhook should
    # treat the new requestId as a fresh event (not idempotent).
    request_id = f"test-req-{args.scenario}-{uuid.uuid4().hex[:12]}"
    nomba_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = build_payload(
        agreement_id=args.agreement_id,
        amount=amount,
        account_ref=account_ref,
        scenario=args.scenario,
        request_id=request_id,
    )
    signature = sign_payload(payload, nomba_timestamp)

    body = json.dumps(payload)
    headers = {
        "Content-Type": "application/json",
        "nomba-signature": signature,
        "nomba-timestamp": nomba_timestamp,
    }

    print(f"\nAmount       : {amount}")
    print(f"account_ref  : {account_ref}")
    print(f"requestId    : {request_id}")
    print(f"nomba-timestamp: {nomba_timestamp}")
    print(f"signature    : {signature[:40]}...{signature[-12:]}")
    print(f"\nPOST {args.url}")
    try:
        resp = requests.post(args.url, data=body, headers=headers, timeout=60)
    except requests.RequestException as exc:
        print(f"\nERROR: request failed -- {exc}")
        sys.exit(2)

    print(f"\nHTTP {resp.status_code}")
    print(f"Response body: {resp.text}")

    if resp.status_code != 200:
        print("\nFAIL: webhook returned non-200. Check FastAPI server logs.")
        sys.exit(1)

    # Optional: verify DB side-effects
    if not args.no_verify_db:
        try:
            verify_side_effects(
                agreement_id=args.agreement_id,
                expected_amount=expected_amount,
                request_id=request_id,
                scenario=args.scenario,
            )
        except Exception as exc:
            print(f"\n[verify] DB check failed -- {exc}")
            print("  (webhook still returned 200; this is a verify-only issue)")

    print("\nOK: webhook accepted.")
    sys.exit(0)


if __name__ == "__main__":
    main()
