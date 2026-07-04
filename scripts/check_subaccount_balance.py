"""Check the sub-account balance to confirm the 100 NGN is sitting there."""
import os
import sys
import json
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.services.nomba_client import nomba_client
import asyncio

async def main():
    await nomba_client._issue_token()
    headers = await nomba_client._headers()
    sub_id = os.environ.get("NOMBA_SUB_ACCOUNT_ID", "282e5b9b-d14f-4e43-840d-43ddfd90a071")

    print(f"=== Sub-account: {sub_id} ===\n")

    # 1. Balance
    print("[GET] /v1/accounts/{subAccountId}/balance")
    resp = requests.get(
        f"{nomba_client.base_url}/accounts/{sub_id}/balance",
        headers=headers,
        timeout=20,
    )
    print(f"  HTTP: {resp.status_code}")
    try:
        body = resp.json()
        print(f"  body: {json.dumps(body, indent=2)[:1000]}")
    except Exception:
        print(f"  text: {resp.text[:500]}")

    # 2. Sub-account details
    print("\n[GET] /v1/accounts/sub-account-details?accountId=...")
    resp = requests.get(
        f"{nomba_client.base_url}/accounts/sub-account-details",
        headers=headers,
        params={"accountId": sub_id},
        timeout=20,
    )
    print(f"  HTTP: {resp.status_code}")
    try:
        body = resp.json()
        print(f"  body: {json.dumps(body, indent=2)[:1500]}")
    except Exception:
        print(f"  text: {resp.text[:500]}")

    # 3. Parent balance for comparison
    parent_id = os.environ.get("NOMBA_PARENT_ACCOUNT_ID", "f666ef9b-888e-4799-85ce-acb505b28023")
    print(f"\n[GET] /v1/accounts/balance (parent {parent_id})")
    resp = requests.get(
        f"{nomba_client.base_url}/accounts/balance",
        headers=headers,
        timeout=20,
    )
    print(f"  HTTP: {resp.status_code}")
    try:
        body = resp.json()
        print(f"  body: {json.dumps(body, indent=2)[:1000]}")
    except Exception:
        print(f"  text: {resp.text[:500]}")

asyncio.run(main())
