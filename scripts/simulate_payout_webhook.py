"""
Fire a simulated payout_success Nomba webhook to mark the pending
disbursement as 'released' on the live server.

Usage: python simulate_payout_webhook.py
"""
import base64
import hashlib
import hmac
import json
import time
import random

import requests
from dotenv import load_dotenv
load_dotenv()

SECRET = "NombaHackathon2026"
TIMESTAMP = "2026-07-04T07:30:00Z"

# From the pending disbursement we discovered in the DB
MERCHANT_TX_REF = "NULO-DISB-DA05F51F"
AMOUNT = 990000.0

LIVE_URL = "https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer"

_unique = f"{int(time.time())}-{random.randint(1000, 9999)}"
request_id = f"payout-test-{_unique}"

# Nomba payout_success structure (PRD Part 1.4):
#   data.merchantTxRef = our nomba_transfer_ref
#   data.transaction.type = "transfer"
#   event_type = "payout_success"
payload = {
    "event_type": "payout_success",
    "requestId": request_id,
    "data": {
        "merchantTxRef": MERCHANT_TX_REF,
        "transaction": {
            "type": "transfer",
            "transactionId": f"payout-txn-{_unique}",
            "responseCode": "00",
            "transactionAmount": AMOUNT,
            "time": TIMESTAMP,
        },
        "merchant": {
            "userId": "f666ef9b-888e-4799-85ce-acb505b28023",  # parent account id
            "walletId": "test-wallet-live",
        },
    },
}

# Build the same 9-field colon-joined signature the production handler expects
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
print(f"Firing simulated payout_success webhook to: {LIVE_URL}")
print(f"merchantTxRef: {MERCHANT_TX_REF}")
print(f"Amount:        NGN {AMOUNT}")
print(f"Request ID:    {request_id}")
print(f"Signature:     {signature[:30]}...")
print("=" * 70)

resp = requests.post(LIVE_URL, headers=headers, json=payload, timeout=90)

print(f"\nHTTP Status: {resp.status_code}")
print(f"Response: {resp.text[:500]}")

if resp.status_code == 200:
    print("\nWebhook delivered. Check Render logs and DB:")
    print("  - transactions row should now have status='released' and released_at set")
    print("  - payment_reconciliation_log gets a new audit row (if applicable)")
