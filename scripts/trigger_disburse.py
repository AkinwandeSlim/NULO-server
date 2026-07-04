"""
Trigger a real disbursement against the live server.

Usage: python trigger_disburse.py [source_transfer_id]

If no source_transfer_id is given, the script picks the most recent
UNDERPAYMENT transfer on the test agreement.
"""
import os
import sys
import json
import asyncio
import time
import requests
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
LANDLORD_ID = "070671cd-a779-4997-9046-771467394f53"
LIVE_BASE = "https://api.nuloafrica.com"


def get_latest_underpayment_transfer() -> str:
    """Find the most recent UNDERPAYMENT virtual_account_transfers row for our agreement."""
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/virtual_account_transfers",
        headers=h,
        params={
            "agreement_id": f"eq.{AGREEMENT_ID}",
            "reconciliation_result": "eq.UNDERPAYMENT",
            "select": "id,amount_received,reconciliation_result,created_at",
            "order": "created_at.desc",
            "limit": "5",
        },
        timeout=15,
    ).json()
    if not r:
        raise RuntimeError("No UNDERPAYMENT transfers found for this agreement")
    for t in r:
        # Skip if a disbursement already exists for this source transfer
        existing = requests.get(
            f"{SUPABASE_URL}/rest/v1/transactions",
            headers=h,
            params={
                "source_transfer_id": f"eq.{t['id']}",
                "transaction_type": "eq.nomba_disbursement",
                "select": "id,status",
                "limit": "1",
            },
            timeout=15,
        ).json()
        if not existing:
            print(f"  picked: id={t['id']}  amount={t['amount_received']}  at={t['created_at']}")
            return t["id"]
    raise RuntimeError("All UNDERPAYMENT transfers already have a disbursement attempt")


def get_or_generate_landlord_jwt() -> str:
    """Generate a landlord JWT for the test landlord (matches the format in app/routes/auth.py)."""
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from app.config import settings
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": LANDLORD_ID, "exp": int(expire.timestamp())},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


async def main():
    source_transfer_id = sys.argv[1] if len(sys.argv) > 1 else get_latest_underpayment_transfer()
    print(f"\n=== Triggering real disbursement ===")
    print(f"  agreement:        {AGREEMENT_ID}")
    print(f"  source_transfer:  {source_transfer_id}")
    print(f"  force:            true (UNDERPAYMENT override)")

    # Generate landlord JWT
    token = get_or_generate_landlord_jwt()
    print(f"  jwt:              {token[:30]}...")

    url = f"{LIVE_BASE}/api/v1/agreements/{AGREEMENT_ID}/disburse"
    payload = {
        "source_transfer_id": source_transfer_id,
        "force": True,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    print(f"\n  POST {url}")
    print(f"  body: {json.dumps(payload)}")
    print(f"  ---")

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    print(f"\n  HTTP: {resp.status_code}")
    print(f"  body: {resp.text[:1000]}")

    if resp.status_code == 200:
        body = resp.json()
        print(f"\n  Disbursement submitted!")
        print(f"    status:           {body.get('status')}")
        print(f"    merchant_tx_ref:  {body.get('merchant_tx_ref')}")
        print(f"    amount_ngn:       {body.get('amount_ngn')}")
        print(f"\n  Now wait for the payout_success webhook to fire and reconcile.")
    else:
        print(f"\n  FAILED. See body above for details.")


if __name__ == "__main__":
    asyncio.run(main())
