"""
Poll the live server and DB for the OPay webhook arrival.
Hits the agreements endpoint every 5 seconds for up to 2 minutes.
"""
import os
import time
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

def get_total_received():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/agreements",
        headers=h,
        params={"id": f"eq.{AGREEMENT_ID}", "select": "total_received_amount,reconciliation_status"}
    ).json()
    if r:
        return r[0].get("total_received_amount"), r[0].get("reconciliation_status")
    return None, None

print("Polling for OPay webhook arrival (max 2 minutes)...")
print("Looking for: total_received_amount = 100.0")
print()

start_total, start_status = get_total_received()
print(f"Start: total={start_total}  status={start_status}")
print()

for i in range(24):  # 24 * 5s = 120s
    time.sleep(5)
    total, status = get_total_received()
    elapsed = (i + 1) * 5
    print(f"  [{elapsed:3d}s] total_received={total}  reconciliation_status={status}")
    if total and float(total) > 0:
        print()
        print("=" * 70)
        print("WEBHOOK ARRIVED!")
        print("=" * 70)
        print(f"  total_received:        {total}")
        print(f"  reconciliation_status: {status}")
        break
else:
    print()
    print("Did not arrive in 2 minutes. The webhook URL may not be activated yet by Nomba.")
    print("Fallback: use the simulated webhook script to complete the demo flow.")
