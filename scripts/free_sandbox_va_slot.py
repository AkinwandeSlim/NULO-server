"""
Free a Nomba SANDBOX virtual-account slot by expiring an existing VA.

WHY
----
The Nomba sandbox enforces a hard limit of 2 virtual accounts per
sub-account holder. Once your sub-account (NOMBA_SUB_ACCOUNT_ID) has 2 VAs,
any new provisioning for a 3rd agreement fails with:

    400 {"description": "Only 2 sandbox virtual accounts are allowed per account holder"}

This helper frees a slot so you can then click "Generate NUBAN" in the
tenant payments UI to provision a fresh VA for your demo agreement.

USAGE
-----
    # 1) List every agreement that currently holds a sandbox VA (read-only):
    python scripts/free_sandbox_va_slot.py --list

    # 2) Expire the VA on Nomba AND null the agreement's VA columns in the DB
    #    (pass the accountRef, which is usually "{agreement_id}-SUB"):
    python scripts/free_sandbox_va_slot.py --expire "<accountRef>"

    # 3) After expiring one, go to /tenant/payments in the browser and click
    #    "Generate NUBAN" on the demo agreement's row. A fresh VA is created
    #    in the now-free slot.

SAFETY
------
- REFUSES TO RUN unless nomba_client.base_url contains "sandbox" — so you
  can never accidentally expire a LIVE Nomba VA.
- Asks for explicit "yes" confirmation before expiring.
- Only nulls DB columns on the ONE agreement whose nomba_account_ref matches
  the accountRef you passed; touches nothing else.

NOTE
----
Column names cross-checked against database/newupdateDB.csv:
  agreements: id, nomba_account_ref, virtual_account_number,
              virtual_account_name, property_id, status, payment_frequency
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.services.nomba_client import nomba_client, NombaAPIError
from app.config import settings  # noqa: F401  (ensures env is loaded)
from app.database import supabase_admin


def _refuse_if_live():
    if "sandbox" not in nomba_client.base_url:
        print(
            f"REFUSING TO RUN: nomba_client.base_url={nomba_client.base_url}\n"
            "This script is for SANDBOX only. Set NOMBA_ENV=test and re-run."
        )
        sys.exit(1)


def list_vas() -> None:
    """Print every agreements row that has a Nomba VA attached."""
    _refuse_if_live()
    resp = (
        supabase_admin
        .table("agreements")
        .select("id, nomba_account_ref, virtual_account_number, "
                "virtual_account_name, status, payment_frequency")
        .not_.is_("nomba_account_ref", "null")
        .order("created_at", desc=True)
        .execute()
    )
    rows = resp.data or []
    print("=" * 72)
    print(f" SANDBOX VAs currently tracked in the agreements table ({len(rows)})")
    print(f" nomba base_url: {nomba_client.base_url}")
    print("=" * 72)
    if not rows:
        print("  No agreements have a nomba_account_ref in the DB.")
        print("  (The 2 sandbox slots are held by VAs the DB no longer tracks —")
        print("   run --expire on any known accountRef to free a slot manually.)")
        return
    for r in rows:
        print(f"\n  agreement_id        : {r.get('id')}")
        print(f"  nomba_account_ref   : {r.get('nomba_account_ref')}")
        print(f"  virtual_account_no  : {r.get('virtual_account_number')}")
        print(f"  virtual_account_name : {r.get('virtual_account_name')}")
        print(f"  status              : {r.get('status')}  "
              f"| payment_frequency: {r.get('payment_frequency')}")
    print("\n" + "=" * 72)
    print(" To free a slot, run:")
    print('   python scripts/free_sandbox_va_slot.py --expire "<accountRef>"')
    print(" where <accountRef> is one of the nomba_account_ref values above.")
    print("=" * 72)


async def expire_va(account_ref: str) -> None:
    _refuse_if_live()

    # Find the agreement row this VA is attached to so we can null its columns.
    resp = (
        supabase_admin
        .table("agreements")
        .select("id, virtual_account_number, virtual_account_name, status")
        .eq("nomba_account_ref", account_ref)
        .maybe_single()
        .execute()
    )
    row = resp.data if hasattr(resp, "data") else resp

    print("=" * 72)
    print(f" EXPIRE SANDBOX VA")
    print("=" * 72)
    print(f"  account_ref        : {account_ref}")
    print(f"  nomba base_url     : {nomba_client.base_url}")
    if row:
        print(f"  attached agreement : {row.get('id')}")
        print(f"  VA number in DB    : {row.get('virtual_account_number')}")
        print(f"  agreement status   : {row.get('status')}")
    else:
        print("  Attached agreement : NOT FOUND in DB")
        print("  (The VA exists on Nomba but no agreement row references it.")
        print("   The VA will still be expired on Nomba; no DB rows to null.)")

    print()
    confirm = input("Expire this sandbox VA on Nomba and null its DB columns? (yes/no): ")
    if confirm.strip().lower() != "yes":
        print("Aborted. Nothing was changed.")
        return

    print("\n[1/2] Expiring VA on Nomba (DELETE /v1/accounts/virtual/{ref}) ...")
    try:
        await nomba_client._issue_token()
        ok = await nomba_client.expire_virtual_account(account_ref)
        if ok:
            print("  ✅ Nomba reported the VA expired (code 00).")
        else:
            print("  ⚠️  Nomba returned a non-00 code — the VA may already be expired,")
            print("      or the accountRef did not match an existing VA.")
    except NombaAPIError as exc:
        print(f"  ❌ Nomba rejected the expire call: {exc}")
        print("  Aborting before touching the DB.")
        return

    if not row:
        print("\n[2/2] No DB row to update. Done.")
        print("\nNext: click 'Generate NUBAN' on the demo agreement's row in")
        print("/tenant/payments to provision a fresh VA in the freed slot.")
        return

    print(f"\n[2/2] Nulling VA columns on agreement {row['id']} ...")
    upd = (
        supabase_admin
        .table("agreements")
        .update({
            "nomba_account_ref": None,
            "virtual_account_number": None,
            "virtual_account_name": None,
        })
        .eq("nomba_account_ref", account_ref)
        .execute()
    )
    print(f"  ✅ Updated {len(upd.data or [])} agreement row(s).")

    print("\n" + "=" * 72)
    print(" DONE — a sandbox VA slot is now free.")
    print("=" * 72)
    print("Next: go to /tenant/payments in the browser and click")
    print("'Generate NUBAN' on the demo agreement's row. A fresh VA will be")
    print("created in the now-free slot and attached to that agreement.")
    print("(If --list showed two VAs and you only need one slot freed,")
    print(" you're done. Repeat for the second only if you need two slots.)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Free a Nomba SANDBOS VA slot.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true",
                       help="List agreements that currently hold a sandbox VA (read-only).")
    group.add_argument("--expire", metavar="ACCOUNT_REF",
                       help="Expire the VA with this accountRef on Nomba and null its DB columns.")
    args = parser.parse_args()

    if args.list:
        list_vas()
    else:
        asyncio.run(expire_va(args.expire))


if __name__ == "__main__":
    main()
