"""Diagnostic: figure out why landlord_profiles / tenant_profiles 400 on read.
   This tests from a different client (Python requests) to rule out PowerShell issues."""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv(".env")

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_KEY")
if not url or not key:
    print("ERROR: SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    sys.exit(1)

headers = {
    "apikey": key,
    "Authorization": f"Bearer {key}",
}

landlord_id = "070671cd-a779-4997-9046-771467394f53"
tenant_id = "05c71152-a018-423e-8c27-f701727f4935"

tests = [
    # (label, table, params)
    ("landlord_profiles (no filter, limit 1)", "landlord_profiles", {"select": "*", "limit": 1}),
    ("landlord_profiles (id filter)", "landlord_profiles", {"id": f"eq.{landlord_id}", "select": "*"}),
    ("landlord_profiles (id filter, all-rows count)", "landlord_profiles", {"select": "id", "limit": 1000}),
    ("tenant_profiles (no filter, limit 1)", "tenant_profiles", {"select": "*", "limit": 1}),
    ("tenant_profiles (id filter)", "tenant_profiles", {"id": f"eq.{tenant_id}", "select": "*"}),
    ("tenants (id filter)", "tenants", {"id": f"eq.{tenant_id}", "select": "*"}),
    ("landlord_onboarding (user_id filter)", "landlord_onboarding", {"user_id": f"eq.{landlord_id}", "select": "*"}),
]

for label, table, params in tests:
    print(f"=== {label} ===")
    r = requests.get(f"{url}/rest/v1/{table}", headers=headers, params=params)
    body = r.text[:600]
    print(f"Status: {r.status_code}")
    print(f"Body: {body}")
    print()
