"""
One-shot data fix: align the agreement's virtual_account_number and
virtual_account_name with the LIVE sub-account VA that its nomba_account_ref
already points at.

Background:
  In a previous session, update_agreement_ref.py set agreements.nomba_account_ref
  = "{uuid}-SUB" so the webhook reconciliation would work. But the agreement's
  virtual_account_number + virtual_account_name were never updated -- they
  still hold the OLD parent-scoped VA 8404605359 that silently dropped every
  webhook with 404 "No redirect configuration".

  The webhook flow doesn't care (it keys on account_ref from Nomba, not on
  virtual_account_number on the agreement), but the landlord/tenant dashboards
  display virtual_account_number as the NUBAN to pay into. Showing 8404605359
  is wrong -- payments to that NUBAN never reach us.

This script:
  1. Fetches the live sub-account VA from Nomba via get_virtual_account(sub_ref)
  2. Updates the agreement with the canonical bankAccountNumber + bankAccountName
  3. Re-fetches the agreement to print the final state for verification

Idempotent: safe to re-run. Will not touch a correctly-aligned agreement
unless values actually differ.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.database import supabase_admin
from app.services.nomba_client import NombaAPIError, nomba_client


AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
SUB_ACCOUNT_REF = f"{AGREEMENT_ID}-SUB"


async def fetch_live_va():
    """Fetch the live sub-account VA from Nomba."""
    print("=" * 70)
    print("Step 1: Fetch live sub-account VA from Nomba")
    print("=" * 70)
    print(f"  accountRef : {SUB_ACCOUNT_REF}")
    try:
        data = await nomba_client.get_virtual_account(SUB_ACCOUNT_REF)
    except NombaAPIError as exc:
        print(f"  FAILED: {exc}")
        return None
    if not data:
        print("  Not found (Nomba returned None / 404)")
        return None
    if data.get("expired"):
        print(f"  Found but EXPIRED: {data}")
        return None
    print(f"  bankAccountNumber : {data.get('bankAccountNumber')}")
    print(f"  bankAccountName   : {data.get('bankAccountName')}")
    print(f"  bankName          : {data.get('bankName')}")
    print(f"  accountHolderId   : {data.get('accountHolderId')}")
    print(f"  expired           : {data.get('expired')}")
    return data


async def fetch_agreement():
    """Fetch the current agreement state for the diff."""
    print()
    print("=" * 70)
    print("Step 2: Fetch current agreement state (BEFORE)")
    print("=" * 70)
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .select("id, virtual_account_number, virtual_account_name, nomba_account_ref")
            .eq("id", AGREEMENT_ID)
            .single()
            .execute(),
    )
    a = result.data
    if not a:
        print(f"  Agreement {AGREEMENT_ID} not found")
        return None
    print(f"  virtual_account_number : {a.get('virtual_account_number')}")
    print(f"  virtual_account_name   : {a.get('virtual_account_name')}")
    print(f"  nomba_account_ref      : {a.get('nomba_account_ref')}")
    return a


async def update_agreement(va):
    """Update the agreement to point at the live VA."""
    new_nuban = va.get("bankAccountNumber")
    new_name = va.get("bankAccountName")
    if not new_nuban or not new_name:
        print("  VA data missing bankAccountNumber or bankAccountName; aborting")
        return None
    # The on-Nomba accountRef (which Nomba will echo back as
    # aliasAccountReference on inbound webhooks) is {uuid}-SUB. The
    # agreement's nomba_account_ref column should mirror that exactly so
    # the three columns stay aligned. The previous session's
    # update_agreement_ref.py either didn't run or got reverted, leaving
    # this field as the bare UUID.
    new_ref = SUB_ACCOUNT_REF
    print()
    print("=" * 70)
    print("Step 3: Update agreement")
    print("=" * 70)
    print(f"  virtual_account_number -> {new_nuban}")
    print(f"  virtual_account_name   -> {new_name}")
    print(f"  nomba_account_ref      -> {new_ref}")
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .update({
                "virtual_account_number": new_nuban,
                "virtual_account_name": new_name,
                "nomba_account_ref": new_ref,
            })
            .eq("id", AGREEMENT_ID)
            .execute(),
    )
    return result.data


async def verify_agreement():
    """Re-fetch the agreement to confirm the update landed."""
    print()
    print("=" * 70)
    print("Step 4: Verify (AFTER)")
    print("=" * 70)
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .select("id, virtual_account_number, virtual_account_name, nomba_account_ref")
            .eq("id", AGREEMENT_ID)
            .single()
            .execute(),
    )
    a = result.data
    print(f"  virtual_account_number : {a.get('virtual_account_number')}")
    print(f"  virtual_account_name   : {a.get('virtual_account_name')}")
    print(f"  nomba_account_ref      : {a.get('nomba_account_ref')}")
    return a


async def main():
    # Safety: this script needs the LIVE VA, so refuse to run if pointed at
    # sandbox. Otherwise we'd query the sandbox API for an accountRef that
    # only exists on live and 404.
    if "sandbox" in nomba_client.base_url:
        print("=" * 70)
        print("REFUSING TO RUN: nomba_client.base_url =", nomba_client.base_url)
        print("=" * 70)
        print()
        print("This script fetches the LIVE sub-account VA 3783622764.")
        print("Set NOMBA_ENV=live in your server/.env and re-run.")
        print("If you intentionally want to point this agreement at the SANDBOX")
        print("VA 5456240035 instead, edit AGREEMENT_ID / SUB_ACCOUNT_REF above.")
        return

    va = await fetch_live_va()
    if not va:
        print()
        print("ABORT: could not fetch live VA. Run this against the env that has it.")
        return
    before = await fetch_agreement()
    if not before:
        return
    # Quick check: skip the write only if ALL three fields are already aligned.
    # A partial drift (e.g. nomba_account_ref still bare UUID) must still
    # trigger the update so the script self-heals on re-runs.
    if (before.get("virtual_account_number") == va.get("bankAccountNumber")
            and before.get("virtual_account_name") == va.get("bankAccountName")
            and before.get("nomba_account_ref") == SUB_ACCOUNT_REF):
        print()
        print("Agreement is already aligned with the live VA -- no write needed.")
        return
    await update_agreement(va)
    await verify_agreement()
    print()
    print("=" * 70)
    print("DONE. The agreement now points at the live sub-account VA.")
    print("The landlord/tenant dashboards will display the correct NUBAN.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
