import os
import requests
from dotenv import load_dotenv
load_dotenv()

# Use a dummy token for testing - we need to get a real one
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

from jose import jwt
from datetime import datetime, timedelta, timezone

def generate_test_token(user_id):
    payload = {
        "sub": user_id,
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

# Test data
TEST_LANDLORD_ID = "070671cd-a779-4997-9046-771467394f53"
TEST_AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
TEST_SOURCE_TRANSFER_ID = "ad4d6fb6-07cc-4e7b-960e-747da6683419"
BASE_URL = "http://localhost:8000/api/v1"

token = generate_test_token(TEST_LANDLORD_ID)
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

body = {
    "source_transfer_id": TEST_SOURCE_TRANSFER_ID
}

print("Testing disbursement...")
print(f"URL: {BASE_URL}/agreements/{TEST_AGREEMENT_ID}/disburse")
print(f"Headers: {headers}")
print(f"Body: {body}")

try:
    resp = requests.post(
        f"{BASE_URL}/agreements/{TEST_AGREEMENT_ID}/disburse",
        json=body,
        headers=headers,
        timeout=60
    )
    print(f"\nResponse status: {resp.status_code}")
    print(f"Response text: {resp.text}")
except Exception as e:
    print(f"\nError: {e}")
    import traceback
    traceback.print_exc()
