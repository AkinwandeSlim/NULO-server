"""Quick check for OPay NGN 100 event in Nomba event-logs (sub + parent)."""
import os
import sys
import json
import requests
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.services.nomba_client import nomba_client
import asyncio

async def run():
    await nomba_client._issue_token()
    headers = await nomba_client._headers()
    base_url = nomba_client.base_url

    sub_id = os.environ.get("NOMBA_SUB_ACCOUNT_ID", "282e5b9b-d14f-4e43-840d-43ddfd90a071")
    parent_id = os.environ.get("NOMBA_PARENT_ACCOUNT_ID", "f666ef9b-888e-4799-85ce-acb505b28023")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    print(f"Today (UTC): {today}")
    print(f"Sub: {sub_id}")
    print(f"Parent: {parent_id}")
    print()

    queries = [
        ("SUB payment_success 7d",  sub_id,    "payment_success", week_ago, today),
        ("PARENT payment_success today",  parent_id, "payment_success", today,    today),
        ("PARENT payment_success 7d", parent_id, "payment_success", week_ago, today),
        ("SUB payout_success 7d",   sub_id,    "payout_success",  week_ago, today),
        ("PARENT payout_success 7d",parent_id, "payout_success",  week_ago, today),
    ]

    for label, uid, ev_type, start, end in queries:
        payload = {
            "coreUserId": uid,
            "limit": 20,
            "eventType": ev_type,
            "startDateTime": start,
            "endDateTime": end,
        }
        print(f"--- {label} ---")
        try:
            resp = requests.post(
                f"{base_url}/webhooks/event-logs",
                headers=headers,
                json=payload,
                timeout=15,
            )
            body = resp.json()
            events = body.get("data", {}).get("list", [])
            if not events:
                print("  (no events)")
            for e in events:
                # extract amount and txn
                try:
                    inner = json.loads(e.get("responsePayload") or "{}")
                    data_field = inner.get("data", "")
                    if isinstance(data_field, str):
                        try:
                            data_field = json.loads(data_field)
                        except Exception:
                            pass
                    amt = data_field.get("amount") if isinstance(data_field, dict) else "?"
                    txn = data_field.get("transaction_id") if isinstance(data_field, dict) else "?"
                    desc = inner.get("description", "?")
                except Exception:
                    amt, txn, desc = "?", "?", "?"
                flag = " ⭐OPAY?" if str(amt) == "100" or "3783622764" in str(txn) else ""
                print(f"  {e.get('hookRequestId')[:8]} amt={amt:>8} txn={str(txn)[:30]:<30} {flag}")
                if flag:
                    print(f"      desc: {desc}")
        except Exception as exc:
            print(f"  ERROR: {exc}")
        print()

asyncio.run(run())
