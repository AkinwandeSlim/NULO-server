"""Raw dump of Nomba event-logs to see exact response format."""
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

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    print(f"=== Sub-account (282e5b9b) - payment_success - 7d RAW ===")
    payload = {
        "coreUserId": sub_id,
        "limit": 20,
        "eventType": "payment_success",
        "startDateTime": week_ago,
        "endDateTime": today,
    }
    resp = requests.post(f"{base_url}/webhooks/event-logs", headers=headers, json=payload, timeout=20)
    body = resp.json()
    events = body.get("data", {}).get("list", [])
    print(f"Status: {resp.status_code}, Events: {len(events)}")
    print(json.dumps(body, indent=2)[:3000])

    print()
    print(f"=== Sub-account - payout_success - 7d RAW ===")
    payload["eventType"] = "payout_success"
    resp = requests.post(f"{base_url}/webhooks/event-logs", headers=headers, json=payload, timeout=20)
    body = resp.json()
    events = body.get("data", {}).get("list", [])
    print(f"Status: {resp.status_code}, Events: {len(events)}")
    if events:
        for e in events[:3]:
            print(json.dumps(e, indent=2)[:1500])
            print("---")

    print()
    print(f"=== Parent (f666ef9b) - payout_success - 7d RAW (first 3) ===")
    payload["coreUserId"] = parent_id
    resp = requests.post(f"{base_url}/webhooks/event-logs", headers=headers, json=payload, timeout=20)
    body = resp.json()
    events = body.get("data", {}).get("list", [])
    print(f"Status: {resp.status_code}, Events: {len(events)}")
    for e in events[:3]:
        print(json.dumps(e, indent=2)[:2000])
        print("---")

asyncio.run(run())
