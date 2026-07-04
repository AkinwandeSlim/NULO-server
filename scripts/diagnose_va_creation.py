"""
Diagnostic: call Nomba live API directly to create a virtual account
and print the FULL response body so we can see exactly what validation
error Nomba is returning.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

env = os.environ.get("NOMBA_ENV", "test")
print(f"NOMBA_ENV = {env}")

if env == "live":
    client_id = os.environ.get("NOMBA_LIVE_CLIENT_ID", "")
    client_secret = os.environ.get("NOMBA_LIVE_CLIENT_SECRET", "")
    base_url = "https://api.nomba.com/v1"
else:
    client_id = os.environ.get("NOMBA_TEST_CLIENT_ID", "")
    client_secret = os.environ.get("NOMBA_TEST_CLIENT_SECRET", "")
    base_url = "https://sandbox.nomba.com/v1"

parent_account_id = os.environ.get("NOMBA_PARENT_ACCOUNT_ID", "")

print(f"base_url     = {base_url}")
print(f"client_id    = {client_id[:12]}...")
print(f"client_secret= {client_secret[:8]}...")
print(f"parent_acct  = {parent_account_id}")
print()

# Step 1: Issue token
print("=" * 60)
print("Step 1: Issue token")
resp = requests.post(
    f"{base_url}/auth/token/issue",
    headers={
        "Content-Type": "application/json",
        "accountId": parent_account_id,
    },
    json={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    },
    timeout=15,
)
print(f"  HTTP Status: {resp.status_code}")
body = resp.json()
print(f"  Body code:   {body.get('code')}")
print(f"  Description: {body.get('description')}")

if body.get("code") != "00":
    print("  TOKEN ISSUE FAILED!")
    print(f"  Full body: {resp.text}")
    exit(1)

token = body["data"]["access_token"]
print(f"  Token: {token[:20]}...")
print()

# Step 2: Try to create virtual account
print("=" * 60)
print("Step 2: Create virtual account")

AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"

# Use a simple test name to isolate whether the issue is the name or the ref
test_names = [
    "NuloAfrica Test VA",
    "NuloAfrica Landlord",
]

for name in test_names:
    print(f"\n  Trying accountName='{name}' (len={len(name)})")
    print(f"  accountRef='{AGREEMENT_ID}' (len={len(AGREEMENT_ID)})")

    resp = requests.post(
        f"{base_url}/accounts/virtual",
        headers={
            "Authorization": f"Bearer {token}",
            "accountId": parent_account_id,
            "Content-Type": "application/json",
        },
        json={
            "accountRef": AGREEMENT_ID,
            "accountName": name,
        },
        timeout=15,
    )

    print(f"  HTTP Status: {resp.status_code}")
    print(f"  Response headers: {dict(resp.headers)}")
    print(f"  FULL Response body:")
    print(f"  {resp.text}")
    print()

    try:
        rb = resp.json()
        if rb.get("code") == "00":
            print(f"  SUCCESS! VA = {rb['data'].get('bankAccountNumber')}")
            break
    except Exception:
        pass

# Also try with a fresh random accountRef to see if the ref is the problem
import uuid
fresh_ref = f"nulo-test-{uuid.uuid4().hex[:20]}"
print(f"\n  Trying with FRESH accountRef='{fresh_ref}' (len={len(fresh_ref)})")
print(f"  accountName='NuloAfrica Test VA'")

resp = requests.post(
    f"{base_url}/accounts/virtual",
    headers={
        "Authorization": f"Bearer {token}",
        "accountId": parent_account_id,
        "Content-Type": "application/json",
    },
    json={
        "accountRef": fresh_ref,
        "accountName": "NuloAfrica Test VA",
    },
    timeout=15,
)

print(f"  HTTP Status: {resp.status_code}")
print(f"  FULL Response body:")
print(f"  {resp.text}")
