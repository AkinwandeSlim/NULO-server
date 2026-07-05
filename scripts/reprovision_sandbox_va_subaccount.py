"""
Test the SUB-ACCOUNT VA provisioning endpoint against the SANDBOX environment.

This is the local-testing companion to reprovision_live_va_subaccount.py.
Run with NOMBA_ENV=test (the default in .env.test) and the test credentials.

Per https://developer.nomba.com/nomba-api-reference/
virtual-accounts/create-virtual-account-for-sub-account

The provisioning call uses the same nomba_client that the production route
uses, so the request/response shape is identical to what the running server
will produce. The only differences are:
  - base_url: https://sandbox.nomba.com/v1 (auto-selected by nomba_client
    when NOMBA_ENV != "live")
  - credentials: NOMBA_TEST_CLIENT_ID / NOMBA_TEST_CLIENT_SECRET
  - parent_account_id: NOMBA_PARENT_ACCOUNT_ID (same in both envs)
  - sub_account_id: NOMBA_SUB_ACCOUNT_ID (same in both envs; the sandbox
    uses the same Nomba-owned hackathon sub-account the live env uses,
    so webhook routing works the same way during local testing)

Uses a NEW accountRef (with -SUB suffix) so we don't conflict with the
existing parent-scoped VA (8404605359) or the live sub-account VA
(3783622764).
"""
import asyncio
import os
import sys
import json

import requests as http_requests  # noqa: F401  (kept for parity w/ live script)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.services.nomba_client import nomba_client
from app.config import settings  # noqa: F401  (kept for parity w/ live script)


async def main():
    sub_account_id = os.environ.get("NOMBA_SUB_ACCOUNT_ID")
    if not sub_account_id:
        print("ERROR: NOMBA_SUB_ACCOUNT_ID not set in environment.")
        return

    # Confirm we're pointed at the sandbox, not live
    if "sandbox" not in nomba_client.base_url:
        print(
            f"REFUSING TO RUN: nomba_client.base_url={nomba_client.base_url}\n"
            "This script is for SANDBOX only. Set NOMBA_ENV=test and re-run."
        )
        return

    await nomba_client._issue_token()

    # Use a fresh accountRef so we don't collide with the live sub-account VA.
    # Parent VA test agreement UUID (shared fixture across scripts).
    parent_va_agreement = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
    new_account_ref = f"{parent_va_agreement}-SANDBOX"  # 49 chars, within 16-64 spec

    # 8-64 chars; ASCII alnum + space (matches route's sanitization)
    account_name = "NuloAfrica Sandbox VA"  # 21 chars, ASCII-only

    print("=" * 70)
    print("SANDBOX -- Provisioning a sub-account scoped VA on Nomba TEST")
    print("=" * 70)
    print(f"  Base URL:      {nomba_client.base_url}")
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
        print("SUCCESS! New SANDBOX sub-account VA provisioned:")
        print(json.dumps(data, indent=2, default=str))
        print()
        print("Next: make a real transfer to the bankAccountNumber and watch for")
        print("the webhook to land at your local /api/v1/webhooks/nomba/transfer.")
        print()
        print("Capture the bankAccountNumber above -- you'll need it for:")
        print("  - update_agreement_ref.py (point test agreement at this VA)")
        print("  - test_webhook_local.py (use this accountRef to simulate)")
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
