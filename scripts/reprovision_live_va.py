"""
Re-provision virtual account in live environment.
1. Clear the existing VA fields from the agreement (so provision creates a new one)
2. Call the provision-nomba endpoint (uses live credentials from Render)
3. Get the new live VA details
"""
import os
import requests
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
BASE_URL = "https://api.nuloafrica.com/api/v1"

AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
LANDLORD_ID = "070671cd-a779-4997-9046-771467394f53"

db_headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

print("=" * 70)
print("RE-PROVISIONING VIRTUAL ACCOUNT IN LIVE ENVIRONMENT")
print("=" * 70)
print(f"Agreement: {AGREEMENT_ID}")
print(f"Landlord:  {LANDLORD_ID}")
print()

# Step 1: Check current state
print("Step 1: Check current agreement state...")
url = f"{SUPABASE_URL}/rest/v1/agreements?id=eq.{AGREEMENT_ID}&select=id,virtual_account_number,virtual_account_name,nomba_account_ref,status"
resp = requests.get(url, headers=db_headers).json()
if resp:
    a = resp[0]
    print(f"  Status:        {a.get('status')}")
    print(f"  VA Number:     {a.get('virtual_account_number')}")
    print(f"  VA Name:       {a.get('virtual_account_name')}")
    print(f"  Nomba Ref:     {a.get('nomba_account_ref')}")
else:
    print("  Agreement not found!")
    exit(1)

# Step 2: Clear existing VA fields
print("\nStep 2: Clear existing VA fields so we can re-provision in live...")
url = f"{SUPABASE_URL}/rest/v1/agreements?id=eq.{AGREEMENT_ID}"
resp = requests.patch(
    url,
    headers=db_headers,
    json={
        "virtual_account_number": None,
        "virtual_account_name": None,
        "nomba_account_ref": None,
    }
)
print(f"  PATCH status: {resp.status_code}")

# Step 3: Generate landlord JWT
print("\nStep 3: Generate landlord JWT...")
from jose import jwt
from datetime import datetime, timedelta, timezone

JWT_SECRET = os.environ.get("JWT_SECRET_KEY")
JWT_ALGO = os.environ.get("JWT_ALGORITHM", "HS256")

token = jwt.encode(
    {
        "sub": LANDLORD_ID,
        "user_id": LANDLORD_ID,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "iat": datetime.now(timezone.utc),
    },
    JWT_SECRET,
    algorithm=JWT_ALGO,
)
api_headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}
print(f"  Token generated for: {LANDLORD_ID}")

# Step 4: Call provision-nomba
print(f"\nStep 4: Call provision-nomba on Render (will use live credentials)...")
print(f"  URL: {BASE_URL}/agreements/{AGREEMENT_ID}/provision-nomba")
resp = requests.post(
    f"{BASE_URL}/agreements/{AGREEMENT_ID}/provision-nomba",
    headers=api_headers,
    timeout=60,
)

print(f"  HTTP Status: {resp.status_code}")
print(f"  Response: {resp.text}")

if resp.status_code == 200:
    data = resp.json()
    print()
    print("=" * 70)
    print("SUCCESS! New live VA provisioned")
    print("=" * 70)
    print(f"  VA Number: {data.get('virtual_account_number')}")
    print(f"  VA Name:   {data.get('virtual_account_name')}")
    print(f"  Expected:  {data.get('expected_amount')}")
    print(f"  Frequency: {data.get('frequency')}")
    print()
    print("NEXT STEPS:")
    print("  1. Make a real small transfer (e.g., NGN 100) to the new VA")
    print("  2. Wait for the webhook to fire and reconcile")
    print("  3. Test the disbursement flow")
else:
    print()
    print("FAILED!")
    try:
        err = resp.json()
        print(f"  Error detail: {err.get('detail', err)}")
    except Exception:
        print(f"  Raw: {resp.text}")
