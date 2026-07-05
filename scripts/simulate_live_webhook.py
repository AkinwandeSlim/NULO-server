"""
Fire a simulated Nomba webhook to a live URL.
Usage: python simulate_live_webhook.py <amount>
"""
import base64
import hashlib
import hmac
import json
import os
import sys

import requests
from dotenv import load_dotenv
load_dotenv()

SECRET = "NombaHackathon2026"
TIMESTAMP = "2026-07-03T20:00:00Z"

AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
# Use the sub-account ID (not the parent) -- this is the accountHolderId
# Nomba stores for VAs provisioned via Path B (POST /v1/accounts/virtual/{subAccountId}).
# Previously mislabeled as SUB_ACCOUNT_USER_ID; the parent header still
# goes on the API calls, but the merchant.userId in the signed payload is
# the sub-account that owns the VA.
MERCHANT_USER_ID = os.environ.get(
    "NOMBA_SUB_ACCOUNT_ID", "282e5b9b-d14f-4e43-840d-43ddfd90a071"
)
# Sub-account-scoped VA that successfully delivered a real OPay webhook
# (NUBAN 3783622764 / Nombank MFB, accountHolderId = 282e5b9b-...).
# The legacy parent VA 8404605359 dropped every webhook with
# "No redirect configuration" and is intentionally NOT used here.
VIRTUAL_ACCOUNT_NUMBER = "3783622764"

LIVE_URL = "https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer"

amount = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0
# Use timestamp + random suffix so each run is unique and idempotency allows reprocessing
import time as _time
import random as _random
_unique = f"{int(_time.time())}-{_random.randint(1000, 9999)}"
request_id = f"live-test-{int(amount)}-{_unique}"

payload = {
    "event_type": "payment_success",
    "requestId": request_id,
    "data": {
        "merchant": {
            "walletId": "test-wallet-live",
            "walletBalance": 50000,
            "userId": MERCHANT_USER_ID,
        },
        "terminal": {},
        "transaction": {
            "aliasAccountNumber": VIRTUAL_ACCOUNT_NUMBER,
            "fee": 5,
            "sessionId": f"test-session-live-{int(amount)}",
            "type": "vact_transfer",
            "transactionId": f"test-txn-live-{int(amount)}-{hash(amount) % 10000}",
            "aliasAccountName": "NuloAfrica/Test Tenant",
            "responseCode": "",
            "originatingFrom": "api",
            "transactionAmount": amount,
            "narration": f"Test payment of NGN {amount}",
            "time": TIMESTAMP,
            "aliasAccountReference": f"{AGREEMENT_ID}-SUB",
            "aliasAccountType": "VIRTUAL",
        },
        "customer": {
            "bankCode": "058",
            "senderName": "TEST TENANT LIVE",
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

headers = {
    "nomba-signature": signature,
    "nomba-timestamp": TIMESTAMP,
    "nomba-signature-algorithm": "HmacSHA256",
    "Content-Type": "application/json",
}

print("=" * 70)
print(f"Firing simulated webhook to: {LIVE_URL}")
print(f"Amount: NGN {amount}")
print(f"Request ID: {request_id}")
print(f"Signature: {signature[:30]}...")
print("=" * 70)

resp = requests.post(LIVE_URL, headers=headers, json=payload, timeout=90)

print(f"\nHTTP Status: {resp.status_code}")
print(f"Response: {resp.text[:500]}")

if resp.status_code == 200:
    print("\nSUCCESS! Webhook accepted. Check:")
    print("  1. Render logs (filter: 'webhook' or 'nomba')")
    print("  2. Supabase: virtual_account_transfers table (new row)")
    print("  3. Supabase: payment_reconciliation_log table (new row)")
    print("  4. Supabase: transactions table (status='held')")
    print("  5. Supabase: agreements table (total_received_amount updated)")
else:
    print("\nFAILED! Check the response and Render logs.")
