import os
import requests
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

# Check existing agreement
agreement_id = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
url = f"{SUPABASE_URL}/rest/v1/agreements?id=eq.{agreement_id}&select=*"
resp = requests.get(url, headers=headers).json()
print("AGREEMENT:")
if resp:
    a = resp[0]
    print(f"  ID: {a['id']}")
    print(f"  Status: {a['status']}")
    print(f"  Landlord: {a['landlord_id']}")
    print(f"  Tenant: {a['tenant_id']}")
    print(f"  Virtual Account: {a.get('virtual_account_number')}")
    print(f"  Virtual Account Name: {a.get('virtual_account_name')}")
    print(f"  Expected Amount: {a.get('expected_payment_amount')}")
    print(f"  Total Received: {a.get('total_received_amount')}")
    print(f"  Reconciliation Status: {a.get('reconciliation_status')}")
    print(f"  Frequency: {a.get('payment_frequency')}")
else:
    print("  NOT FOUND")

print()
print("=" * 60)

# Check landlord
landlord_id = a["landlord_id"] if resp else None
if landlord_id:
    url = f"{SUPABASE_URL}/rest/v1/landlords?id=eq.{landlord_id}&select=*"
    resp = requests.get(url, headers=headers).json()
    print("LANDLORD:")
    if resp:
        l = resp[0]
        print(f"  ID: {l['id']}")
        print(f"  Bank Account: {l.get('bank_account_number')}")
        print(f"  Bank Name: {l.get('bank_name')}")
        print(f"  Account Name: {l.get('account_name')}")
        print(f"  Bank Verified At: {l.get('bank_verified_at')}")
    else:
        print("  NOT FOUND in landlords table")

print()
print("=" * 60)

# Check recent transfers
url = f"{SUPABASE_URL}/rest/v1/virtual_account_transfers?agreement_id=eq.{agreement_id}&order=created_at.desc&limit=5&select=id,amount_received,reconciliation_result,created_at"
resp = requests.get(url, headers=headers).json()
print(f"RECENT TRANSFERS (last 5):")
for t in resp:
    print(f"  ID: {t['id']}")
    print(f"    Amount: {t['amount_received']}")
    print(f"    Result: {t['reconciliation_result']}")
    print(f"    Created: {t['created_at']}")
    print()

print("=" * 60)

# Check tenant
tenant_id = a["tenant_id"] if resp else None
if tenant_id:
    url = f"{SUPABASE_URL}/rest/v1/users?id=eq.{tenant_id}&select=id,email,full_name,user_type"
    resp = requests.get(url, headers=headers).json()
    print("TENANT:")
    if resp:
        t = resp[0]
        print(f"  ID: {t['id']}")
        print(f"  Email: {t.get('email')}")
        print(f"  Full Name: {t.get('full_name')}")
        print(f"  Type: {t.get('user_type')}")
    else:
        print("  NOT FOUND")
