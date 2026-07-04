"""
Test the SUB-ACCOUNT VA provisioning endpoint.
Per https://developer.nomba.com/nomba-api-reference/
virtual-accounts/create-virtual-account-for-sub-account

Uses a NEW accountRef (with -SUB suffix) so we don't conflict with the
existing parent-scoped VA (8404605359).
"""
import asyncio
import os
import sys
import json
import requests as http_requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.services.nomba_client import nomba_client
from app.config import settings


async def main():
    sub_account_id = os.environ.get("NOMBA_SUB_ACCOUNT_ID")
    if not sub_account_id:
        print("ERROR: NOMBA_SUB_ACCOUNT_ID not set in environment.")
        return

    await nomba_client._issue_token()

    # Use a fresh accountRef so we don't collide with the existing parent VA
    parent_va_agreement = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
    new_account_ref = f"{parent_va_agreement}-SUB"  # 41 chars, within 16-64 spec

    # 8-64 chars; ASCII alnum + space (matches route's sanitization)
    account_name = "Raphawellness Modern Apt"  # 25 chars, ASCII-only

    print("=" * 70)
    print("Provisioning a sub-account scoped VA on LIVE Nomba")
    print("=" * 70)
    print(f"  Sub-account ID: {sub_account_id}")
    print(f"  Parent account: {nomba_client.parent_account_id}")
    print(f"  accountRef:     {new_account_ref}")
    print(f"  accountName:    {account_name}")
    print()

    try:
        data = await nomba_client.create_virtual_account_for_subaccount(
            sub_account_id=sub_account_id,
            account_ref=new_account_ref,
            account_name=account_name,
        )
        print("SUCCESS! New sub-account VA provisioned on live:")
        print(json.dumps(data, indent=2, default=str))
        print()
        print("Next: make a real transfer to the bankAccountNumber and watch for")
        print("the webhook to land at https://api.nuloafrica.com/api/v1/webhooks/nomba/transfer")
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
