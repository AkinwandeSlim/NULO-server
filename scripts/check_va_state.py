"""
Check VA state and figure out if we're really on live or sandbox.
The /health/nomba endpoint tells us the env.
"""
import os
import requests
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")

db_headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# Check current agreement state
agreement_id = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
url = f"{SUPABASE_URL}/rest/v1/agreements?id=eq.{agreement_id}&select=id,virtual_account_number,virtual_account_name,nomba_account_ref,status,expected_payment_amount,total_received_amount,reconciliation_status"
resp = requests.get(url, headers=db_headers).json()

print("=" * 70)
print("Current Agreement State")
print("=" * 70)
if resp:
    a = resp[0]
    print(f"  Status:        {a.get('status')}")
    print(f"  VA Number:     {a.get('virtual_account_number')}")
    print(f"  VA Name:       {a.get('virtual_account_name')}")
    print(f"  Nomba Ref:     {a.get('nomba_account_ref')}")
    print(f"  Expected:      {a.get('expected_payment_amount')}")
    print(f"  Received:      {a.get('total_received_amount')}")
    print(f"  Reconciled:    {a.get('reconciliation_status')}")
else:
    print("  Agreement not found")

# Check health
print()
print("=" * 70)
print("Health Check")
print("=" * 70)
resp = requests.get("https://api.nuloafrica.com/api/v1/health/nomba").json()
print(f"  Status:         {resp.get('status')}")
print(f"  Nomba Auth:     {resp.get('nomba_auth')}")
print(f"  Environment:    {resp.get('environment')}")
print(f"  Webhook URL:    {resp.get('webhook_url')}")
