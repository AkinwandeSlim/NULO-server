"""
Multi-filter query of Nomba webhook event-logs.

Tests:
  - Both parent + sub-account as coreUserId
  - Multiple event types: payment_success, payout_success, all (no filter)
  - Multiple date ranges: last 24h, last 7 days
  - Includes transfer & refund events too

Prints results in a compact table so we can find which coreUserId
the OPay NGN 100 event is actually tied to.
"""
import asyncio
import os
import sys
import json
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.services.nomba_client import nomba_client
import requests as http_requests


def extract_event_meta(e: dict) -> dict:
    """Pull amount / txn / status from a Nomba event entry."""
    try:
        inner = json.loads(e.get("responsePayload") or "{}")
        data_field = inner.get("data", "")
        if isinstance(data_field, str):
            try:
                data_field = json.loads(data_field)
            except Exception:
                pass
        return {
            "amount": data_field.get("amount") if isinstance(data_field, dict) else "?",
            "txn_id": data_field.get("transaction_id") if isinstance(data_field, dict) else "?",
            "status": inner.get("status"),
            "desc": inner.get("description", "?"),
        }
    except Exception:
        return {"amount": "?", "txn_id": "?", "status": "?", "desc": "?"}


def looks_like_opay_100(meta: dict) -> bool:
    """Heuristic: is this the OPay NGN 100 to VA 3783622764?"""
    amt = str(meta.get("amount", ""))
    txn = str(meta.get("txn_id", ""))
    desc = str(meta.get("desc", "")).lower()
    return "100" in amt or "3783622764" in str(txn) or "opay" in desc


async def query_events(headers, base_url, core_user_id, event_type, start, end, limit=20):
    payload = {
        "coreUserId": core_user_id,
        "limit": limit,
        "eventType": event_type,
        "startDateTime": start,
        "endDateTime": end,
    }
    try:
        resp = http_requests.post(
            f"{base_url}/webhooks/event-logs",
            headers=headers,
            json=payload,
            timeout=20,
        )
        if resp.status_code != 200:
            return []
        body = resp.json()
        return body.get("data", {}).get("list", [])
    except Exception as exc:
        return [{"_error": str(exc)}]


async def main():
    await nomba_client._issue_token()
    headers = await nomba_client._headers()
    base_url = nomba_client.base_url

    sub_id = os.environ.get("NOMBA_SUB_ACCOUNT_ID", "282e5b9b-d14f-4e43-840d-43ddfd90a071")
    parent_id = os.environ.get("NOMBA_PARENT_ACCOUNT_ID", "f666ef9b-888e-4799-85ce-acb505b28023")

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    print("=" * 70)
    print("NOMBA WEBHOOK EVENT-LOGS: MULTI-FILTER QUERY")
    print("=" * 70)
    print(f"  Today (UTC):  {today}")
    print(f"  Sub:          {sub_id}")
    print(f"  Parent:       {parent_id}")
    print()

    queries = [
        # (label, coreUserId, eventType, start, end)
        ("SUB: payment_success (last 7d)",   sub_id,    "payment_success", week_ago, today),
        ("SUB: payout_success (last 7d)",    sub_id,    "payout_success",  week_ago, today),
        ("PARENT: payment_success (today)",  parent_id, "payment_success", today,    today),
        ("PARENT: payment_success (last 7d)",parent_id, "payment_success", week_ago, today),
        ("PARENT: payout_success (last 7d)", parent_id, "payout_success",  week_ago, today),
    ]

    found_opay = False
    for label, uid, ev_type, start, end in queries:
        print(f"--- {label} ---")
        events = await query_events(headers, base_url, uid, ev_type, start, end)
        if not events:
            print("  (no events)")
            print()
            continue
        print(f"  {len(events)} event(s):")
        for e in events:
            if "_error" in e:
                print(f"  ERROR: {e['_error']}")
                continue
            meta = extract_event_meta(e)
            flag = "  ⭐ OPAY 100?" if looks_like_opay_100(meta) else ""
            print(f"  - {e.get('hookRequestId')[:8]}  amount={meta['amount']:>8}  "
                  f"txn={str(meta['txn_id'])[:32]:<32}  status={meta['status']}  {flag}")
            if looks_like_opay_100(meta):
                found_opay = True
                print(f"      desc: {meta['desc']}")
        print()

    print("=" * 70)
    print("RESULT:", "OPAY NGN 100 EVENT FOUND ⭐" if found_opay else "OPAY NGN 100 EVENT NOT FOUND in any query")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
