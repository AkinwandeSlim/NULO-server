"""
Reset test data to a clean slate for live demo.
DESTRUCTIVE - deletes transfer records and resets agreement totals.
"""
import os
import requests
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"

print("=" * 70)
print("RESET TEST DATA - DESTRUCTIVE OPERATION")
print("=" * 70)
print(f"Agreement ID: {AGREEMENT_ID}")
print()

# 1. Delete all payment_reconciliation_log entries FIRST (they reference transfers)
print("Step 1: Delete all payment_reconciliation_log entries FIRST (FK order matters)...")
url = f"{SUPABASE_URL}/rest/v1/payment_reconciliation_log?agreement_id=eq.{AGREEMENT_ID}"
resp = requests.delete(url, headers=headers)
print(f"  Status: {resp.status_code}")

# 2. Now delete all virtual_account_transfers
print("\nStep 2: Delete all virtual_account_transfers for this agreement...")
url = f"{SUPABASE_URL}/rest/v1/virtual_account_transfers?agreement_id=eq.{AGREEMENT_ID}"
resp = requests.delete(url, headers=headers)
print(f"  Status: {resp.status_code}")
print(f"  Response: {resp.text[:200]}")

# 3. Delete nomba_collection transactions
print("\nStep 3: Delete nomba_collection transactions for this agreement...")
url = f"{SUPABASE_URL}/rest/v1/transactions?agreement_id=eq.{AGREEMENT_ID}&transaction_type=eq.nomba_collection"
resp = requests.delete(url, headers=headers)
print(f"  Status: {resp.status_code}")

# 4. Delete nomba_disbursement transactions
print("\nStep 4: Delete nomba_disbursement transactions for this agreement...")
url = f"{SUPABASE_URL}/rest/v1/transactions?agreement_id=eq.{AGREEMENT_ID}&transaction_type=eq.nomba_disbursement"
resp = requests.delete(url, headers=headers)
print(f"  Status: {resp.status_code}")

# 5. Reset agreement totals
print("\nStep 5: Reset agreement total_received_amount and reconciliation_status...")
url = f"{SUPABASE_URL}/rest/v1/agreements?id=eq.{AGREEMENT_ID}"
resp = requests.patch(
    url,
    headers=headers,
    json={
        "total_received_amount": 0,
        "reconciliation_status": "PENDING"
    }
)
print(f"  Status: {resp.status_code}")

print()
print("=" * 70)
print("RESET COMPLETE!")
print("=" * 70)

# Verify
print("\nVerification:")
url = f"{SUPABASE_URL}/rest/v1/agreements?id=eq.{AGREEMENT_ID}&select=id,total_received_amount,reconciliation_status,virtual_account_number"
resp = requests.get(url, headers=headers).json()
if resp:
    a = resp[0]
    print(f"  Agreement total_received_amount: {a['total_received_amount']}")
    print(f"  Reconciliation status: {a['reconciliation_status']}")
    print(f"  Virtual account still: {a['virtual_account_number']}")

url = f"{SUPABASE_URL}/rest/v1/virtual_account_transfers?agreement_id=eq.{AGREEMENT_ID}&select=id"
resp = requests.get(url, headers=headers).json()
print(f"  Transfers remaining: {len(resp)}")

url = f"{SUPABASE_URL}/rest/v1/transactions?agreement_id=eq.{AGREEMENT_ID}&select=id,transaction_type"
resp = requests.get(url, headers=headers).json()
print(f"  Transactions remaining: {len(resp)}")
