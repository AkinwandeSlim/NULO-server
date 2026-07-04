"""Quick check of agreement state after UUID fix deployment."""
import os
import sys
import json
import requests
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"

h = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

print("=" * 70)
print("LIVE AGREEMENT STATE CHECK (post-UUID-fix)")
print("=" * 70)
print(f"Agreement: {AGREEMENT_ID}")
print()

# 1. Agreement
try:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/agreements",
        headers=h,
        params={"id": f"eq.{AGREEMENT_ID}", "select": "id,status,virtual_account_number,total_received_amount,reconciliation_status,expected_payment_amount"},
        timeout=15,
    ).json()
    if r:
        a = r[0]
        print("--- agreements ---")
        print(f"  status:                {a.get('status')}")
        print(f"  virtual_account_number:{a.get('virtual_account_number')}")
        print(f"  expected_payment:      {a.get('expected_payment_amount')}")
        print(f"  total_received:        {a.get('total_received_amount')}")
        print(f"  reconciliation:        {a.get('reconciliation_status')}")
    else:
        print("  Agreement NOT FOUND")
except Exception as exc:
    print(f"  ERROR: {exc}")
print()

# 2. virtual_account_transfers
try:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/virtual_account_transfers",
        headers=h,
        params={"agreement_id": f"eq.{AGREEMENT_ID}", "select": "id,amount_received,reconciliation_result,nomba_transaction_id,sender_name,created_at", "order": "created_at.desc", "limit": "5"},
        timeout=15,
    ).json()
    print("--- virtual_account_transfers (most recent 5) ---")
    if r:
        for t in r:
            print(f"  amount={t.get('amount_received')}  result={t.get('reconciliation_result')}  txn={t.get('nomba_transaction_id')}  sender={t.get('sender_name')}  at={t.get('created_at')}")
    else:
        print("  No transfers")
except Exception as exc:
    print(f"  ERROR: {exc}")
print()

# 3. transactions
try:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/transactions",
        headers=h,
        params={"agreement_id": f"eq.{AGREEMENT_ID}", "select": "id,amount,status,transaction_type,created_at", "order": "created_at.desc", "limit": "5"},
        timeout=15,
    ).json()
    print("--- transactions (most recent 5) ---")
    if r:
        for t in r:
            print(f"  type={t.get('transaction_type')}  amount={t.get('amount')}  status={t.get('status')}  at={t.get('created_at')}")
    else:
        print("  No transactions")
except Exception as exc:
    print(f"  ERROR: {exc}")
print()

# 4. reconciliation log
try:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/payment_reconciliation_log",
        headers=h,
        params={"agreement_id": f"eq.{AGREEMENT_ID}", "select": "*", "order": "created_at.desc", "limit": "5"},
        timeout=15,
    ).json()
    print("--- payment_reconciliation_log (most recent 5) ---")
    if r:
        for x in r:
            print(f"  new_status={x.get('new_status')}  prev={x.get('previous_status')}  variance={x.get('variance_pct')}  at={x.get('created_at')}")
    else:
        print("  No reconciliation log")
except Exception as exc:
    print(f"  ERROR: {exc}")

print()
print("=" * 70)
