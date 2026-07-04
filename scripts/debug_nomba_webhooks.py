"""
Query Nomba's webhook event-logs endpoint to debug the OPay NGN 100
payment that we did not receive on our endpoint.

Per https://developer.nomba.com/docs/api-basics/troubleshoot-webhooks
- POST /v1/webhooks/event-logs  -- see if webhook was sent and what status
- POST /v1/webhooks/replay     -- re-trigger failed/inconclusive events

auth uses our nomba_client (same token, same accountId header)
"""
import asyncio
import os
import sys
import json
from datetime import datetime, timedelta, timezone

# Make the parent (server/) directory importable so 'app' resolves
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.services.nomba_client import nomba_client


async def main():
    await nomba_client._issue_token()
    headers = await nomba_client._headers()

    # Look back 2 days (the OPay payment was earlier today)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=2)

    # Query for the SUB-account -- our new VAs (3783622764) and any future
    # OPay NGN 100 / Nombank MFB events will be associated with the sub-account
    sub_id = os.environ.get("NOMBA_SUB_ACCOUNT_ID", "282e5b9b-d14f-4e43-840d-43ddfd90a071")
    payload = {
        "coreUserId": sub_id,
        "limit": 20,
        "eventType": "payment_success",
        "startDateTime": start.strftime("%Y-%m-%d"),
        "endDateTime": end.strftime("%Y-%m-%d"),
    }

    print(f"  coreUserId: {sub_id}  (SUB-ACCOUNT)")
    print()

    import requests
    resp = requests.post(
        f"{nomba_client.base_url}/webhooks/event-logs",
        headers=headers,
        json=payload,
        timeout=20,
    )

    print(f"\nHTTP Status: {resp.status_code}")
    print(f"Response body:")
    try:
        body = resp.json()
        # Show count and a small summary of each event
        if body.get("data", {}).get("list"):
            events = body["data"]["list"]
            print(f"Found {len(events)} event(s):\n")
            for e in events:
                payload_str = e.get("responsePayload", "")[:300]
                # Try to extract amount + txn id
                try:
                    inner = json.loads(e.get("responsePayload", "{}"))
                    inner_data = inner.get("data", "")
                    if isinstance(inner_data, str):
                        try:
                            inner_data = json.loads(inner_data)
                        except Exception:
                            pass
                    txn = inner_data.get("transaction_id") if isinstance(inner_data, dict) else "?"
                    amt = inner_data.get("amount") if isinstance(inner_data, dict) else "?"
                    desc = inner.get("description", "?")
                except Exception:
                    txn, amt, desc = "?", "?", "?"
                print(f"  hookRequestId: {e.get('hookRequestId')}")
                print(f"    status:   {e.get('responseHttpStatus')}")
                print(f"    desc:     {desc}")
                print(f"    amount:   {amt}")
                print(f"    txn_id:   {txn}")
                print()
        else:
            print(json.dumps(body, indent=2, default=str)[:1500])
    except Exception:
        print(resp.text[:1000])


if __name__ == "__main__":
    asyncio.run(main())
