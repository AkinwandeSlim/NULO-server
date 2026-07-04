"""Get the nomba_transfer_ref of the pending disbursement."""
import os
import requests
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"

h = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}

# Find the pending disbursement
r = requests.get(
    f"{SUPABASE_URL}/rest/v1/transactions",
    headers=h,
    params={
        "agreement_id": f"eq.{AGREEMENT_ID}",
        "transaction_type": "eq.nomba_disbursement",
        "status": "eq.pending",
        "select": "id,amount,nomba_transfer_ref,nomba_transfer_id,status",
    }
).json()

print("Pending disbursements:")
print(f"  type: {type(r)}")
print(f"  raw: {r}")
print()

if isinstance(r, list) and r:
    for t in r:
        print(f"  id:                 {t.get('id')}")
        print(f"  amount:             {t.get('amount')}")
        print(f"  nomba_transfer_ref: {t.get('nomba_transfer_ref')}")
        print(f"  nomba_transfer_id:  {t.get('nomba_transfer_id')}")
        print(f"  merchant_tx_ref:    {t.get('merchant_tx_ref')}")
        print(f"  status:             {t.get('status')}")
        print()
elif isinstance(r, list):
    print("No pending disbursement found (empty list).")
else:
    print("Unexpected response format.")
