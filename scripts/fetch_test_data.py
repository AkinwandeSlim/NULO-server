import os
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")

headers = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json"
}

# 1. Get FULL_PAYMENT virtual_account_transfers
print("Fetching FULL_PAYMENT transfers...")
transfers_url = f"{SUPABASE_URL}/rest/v1/virtual_account_transfers"
transfers_params = {
    "reconciliation_result": "eq.FULL_PAYMENT",
    "select": "*",
    "order": "created_at.desc"
}
transfers_resp = requests.get(transfers_url, headers=headers, params=transfers_params)
transfers = transfers_resp.json() if transfers_resp.ok else []
print(f"Found {len(transfers)} FULL_PAYMENT transfers")
if transfers:
    print(f"Latest transfer ID: {transfers[0]['id']}")
    print(f"  Agreement ID: {transfers[0]['agreement_id']}")
    print(f"  Amount: {transfers[0]['amount_received']}")

# 2. Get agreement
print("\nFetching agreement...")
if transfers:
    agreement_url = f"{SUPABASE_URL}/rest/v1/agreements"
    agreement_params = {
        "id": f"eq.{transfers[0]['agreement_id']}",
        "select": "*"
    }
    agreement_resp = requests.get(agreement_url, headers=headers, params=agreement_params)
    agreement = agreement_resp.json()[0] if agreement_resp.ok else None
    if agreement:
        print(f"Agreement ID: {agreement['id']}")
        print(f"  Landlord ID: {agreement['landlord_id']}")
        print(f"  Status: {agreement['status']}")

# 3. Get landlord data from both landlords and landlord_profiles tables
print("\nFetching landlord data...")
if agreement:
    # Check landlords table
    landlords_url = f"{SUPABASE_URL}/rest/v1/landlords"
    landlords_params = {"id": f"eq.{agreement['landlord_id']}", "select": "*"}
    landlords_resp = requests.get(landlords_url, headers=headers, params=landlords_params)
    landlords = landlords_resp.json() if landlords_resp.ok else []
    if landlords:
        print(f"✅ Landlord found in landlords table:")
        print(f"  Bank verified: {landlords[0].get('bank_verified_at')}")
        print(f"  Bank name: {landlords[0].get('bank_name')}")
        print(f"  Account name: {landlords[0].get('account_name')}")
    else:
        print(f"❌ No landlord found in landlords table for ID {agreement['landlord_id']}")
