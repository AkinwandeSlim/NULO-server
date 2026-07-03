"""
Local webhook simulation script.
Run: python simulate_nomba_webhook.py <agreement_uuid> <scenario>
Copy the output signature and payload into Thunder Client.

Scenarios: full_payment | underpayment | overpayment | misdirected
"""
import base64
import hashlib
import hmac
import json
import sys

SECRET = "NombaHackathon2026"
TIMESTAMP = "2026-07-01T10:00:00Z"

# Replace with a real agreement.id from your Supabase agreements table
AGREEMENT_ID = sys.argv[1] if len(sys.argv) > 1 else "YOUR-AGREEMENT-UUID-HERE"
SUB_ACCOUNT_USER_ID = "YOUR-SUB-ACCOUNT-ID-HERE"

SCENARIOS = {
    "full_payment": 500000.0,
    "underpayment": 100000.0,
    "overpayment": 800000.0,
    "misdirected": 500000.0,
}

scenario = sys.argv[2] if len(sys.argv) > 2 else "full_payment"
amount = SCENARIOS.get(scenario, 500000.0)
request_id = f"test-req-{scenario}-001"

account_ref = AGREEMENT_ID
if scenario == "misdirected":
    account_ref = "00000000-0000-0000-0000-000000000000"

payload = {
    "event_type": "payment_success",
    "requestId": request_id,
    "data": {
        "merchant": {
            "walletId": "test-wallet-001",
            "walletBalance": 50000,
            "userId": SUB_ACCOUNT_USER_ID,
        },
        "terminal": {},
        "transaction": {
            "aliasAccountNumber": "9391076543",
            "fee": 5,
            "sessionId": f"test-session-{scenario}",
            "type": "vact_transfer",
            "transactionId": f"test-txn-{scenario}-001",
            "aliasAccountName": "NuloAfrica/Test Tenant",
            "responseCode": "",
            "originatingFrom": "api",
            "transactionAmount": amount,
            "narration": f"Rent payment scenario={scenario}",
            "time": TIMESTAMP,
            "aliasAccountReference": account_ref,
            "aliasAccountType": "VIRTUAL",
        },
        "customer": {
            "bankCode": "058",
            "senderName": "TEST TENANT",
            "bankName": "GTBank",
            "accountNumber": "0123456789",
        },
    },
}

t = payload["data"]["transaction"]
m = payload["data"]["merchant"]
hashing_payload = (
    f"{payload['event_type']}:{payload['requestId']}:{m['userId']}:{m['walletId']}:"
    f"{t['transactionId']}:{t['type']}:{t['time']}:{t['responseCode']}:{TIMESTAMP}"
)

digest = hmac.new(SECRET.encode(), hashing_payload.encode(), hashlib.sha256).digest()
signature = base64.b64encode(digest).decode()

print("=" * 60)
print(f"Scenario: {scenario}")
print(f"Agreement ID: {AGREEMENT_ID}")
print(f"Amount: {amount}")
print("=" * 60)
print(f"nomba-signature: {signature}")
print(f"nomba-timestamp: {TIMESTAMP}")
print(f"Content-Type: application/json")
print("=" * 60)
print("Body:")
print(json.dumps(payload, indent=2))
