import os
import time
import requests
from jose import jwt
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
BASE_URL = "http://localhost:8000/api/v1"

# Test data
TEST_LANDLORD_ID = "070671cd-a779-4997-9046-771467394f53"
TEST_AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
TEST_SOURCE_TRANSFER_ID = "ad4d6fb6-07cc-4e7b-960e-747da6683419"

# Generate test JWT token
def generate_test_token(user_id):
    payload = {
        "sub": user_id,
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def main():
    print("Testing disbursement flow...")
    print("=" * 70)
    
    token = generate_test_token(TEST_LANDLORD_ID)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    print(f"Generated test token for user: {TEST_LANDLORD_ID}")

    # Step 1: Lookup bank account (test data)
    print("\nStep 1: Testing bank lookup endpoint...")
    bank_lookup_data = {
        "account_number": "0123456789",
        "bank_code": "058"  # GTBank
    }
    bank_lookup_resp = requests.post(
        f"{BASE_URL}/disbursements/lookup-bank",
        json=bank_lookup_data,
        headers=headers,
        timeout=30
    )
    print(f"Bank lookup status: {bank_lookup_resp.status_code}")
    print(f"Response: {bank_lookup_resp.text}")

    if bank_lookup_resp.status_code != 200:
        print("\nError: Bank lookup failed")
        return

    # Step 2: Test disbursement
    print("\nStep 2: Testing disbursement endpoint...")
    disburse_data = {
        "source_transfer_id": TEST_SOURCE_TRANSFER_ID
    }
    disburse_resp = requests.post(
        f"{BASE_URL}/agreements/{TEST_AGREEMENT_ID}/disburse",
        json=disburse_data,
        headers=headers,
        timeout=60
    )
    print(f"Disbursement status: {disburse_resp.status_code}")
    print(f"Response: {disburse_resp.text}")

    if disburse_resp.status_code == 200:
        disburse_result = disburse_resp.json()
        merchant_tx_ref = disburse_result.get("merchant_tx_ref")
        if merchant_tx_ref:
            print("\nStep 3: Testing disbursement status endpoint...")
            status_resp = requests.get(
                f"{BASE_URL}/disbursements/{merchant_tx_ref}",
                headers=headers,
                timeout=30
            )
            print(f"Status endpoint status: {status_resp.status_code}")
            print(f"Response: {status_resp.text}")

if __name__ == "__main__":
    main()
