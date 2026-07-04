"""
Re-push failed Nomba webhook events to our endpoint.
Per https://developer.nomba.com/docs/api-basics/troubleshoot-webhooks
- POST /v1/webhooks/re-push   -- single event via hooksRequestId
- POST /v1/webhooks/bulk-re-push -- multiple events
"""
import asyncio
import os
import sys
import json
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.services.nomba_client import nomba_client


async def main():
    await nomba_client._issue_token()
    headers = await nomba_client._headers()

    # The hookRequestIds of the 4 FAILED events from the debug output
    failed_events = [
        "5858b39d-8ef2-4d57-afd8-2c203757635c",  # 500 error
        "9a34b2f5-9953-484b-9441-5a172d0d5406",  # 404 - No redirect
        "40d814f1-e71c-462e-beb8-43f19183ad8a",  # 404 - No redirect
        "956b0af4-81b0-423b-96cb-f5894dc9d0d3",  # 404 - No redirect
        "05ae396d-8174-475f-8804-c03a5c23168c",  # 404 - No redirect
    ]

    print("=" * 70)
    print("Bulk re-push of failed webhook events...")
    print(f"  Count: {len(failed_events)}")
    print("=" * 70)

    payload = {"hooksRequestIds": failed_events}

    resp = requests.post(
        f"{nomba_client.base_url}/webhooks/bulk-re-push",
        headers=headers,
        json=payload,
        timeout=30,
    )

    print(f"\nHTTP Status: {resp.status_code}")
    try:
        print(json.dumps(resp.json(), indent=2)[:2000])
    except Exception:
        print(resp.text[:1000])


if __name__ == "__main__":
    asyncio.run(main())
