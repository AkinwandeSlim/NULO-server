"""
[DEPRECATED -- DO NOT USE]

This script used to call POST /agreements/{id}/provision-nomba on Render
(LIVE) to reprovision a VA. It was the entry point for the parent-scoped
Path A provisioning flow, which silently drops inbound webhooks with
404 "No redirect configuration" because the hackathon's webhook URL is
registered against the SUB-account, not the parent.

The provision-nomba route now uses Path B (sub-account-scoped, -SUB
suffix) by default. So even if you re-run this script, the route itself
will now produce a working sub-account VA. BUT this script's name still
implies "Path A on LIVE", and the docstring/logic still references the
parent path. To avoid future confusion, the script has been disabled.

Use one of these instead:
  - server/scripts/reprovision_live_va_subaccount.py
        Live sub-account VA provisioning (Path B). Use this for live tests.
  - server/scripts/reprovision_sandbox_va_subaccount.py
        Sandbox sub-account VA provisioning (Path B). Use this for local
        testing with NOMBA_ENV=test.

Or, for the normal app flow, just call the production endpoint:
  POST /api/v1/agreements/{id}/provision-nomba
  -- it now provisions a sub-account-scoped VA automatically.

If you need to inspect what the (now-removed) Path A direct call looked
like, see the git history. The script body is preserved below as comments
for archaeology only.

Original body (Path A, parent-scoped) -- kept for reference:
-------------------------------------------------------------------------
# Step 1-2: clear existing VA fields on the agreement
# Step 3: generate a landlord JWT
# Step 4: POST {BASE_URL}/agreements/{AGREEMENT_ID}/provision-nomba
#         (which then internally called create_virtual_account(...) on the
#          parent -- this is the call that broke webhook delivery)
-------------------------------------------------------------------------
"""
import sys


def main():
    print("=" * 70)
    print("[DEPRECATED] reprovision_live_va.py")
    print("=" * 70)
    print()
    print("This script is disabled. The parent-scoped Path A provisioning")
    print("flow silently drops inbound webhooks (404 'No redirect")
    print("configuration') because the hackathon's webhook URL is")
    print("registered on the sub-account, not the parent.")
    print()
    print("Use instead:")
    print("  - reprovision_live_va_subaccount.py     (live, Path B)")
    print("  - reprovision_sandbox_va_subaccount.py  (sandbox, Path B)")
    print("  - POST /api/v1/agreements/{id}/provision-nomba  (app route, now Path B)")
    print()
    print("No VA was created. No Nomba call was made.")
    sys.exit(1)


if __name__ == "__main__":
    main()
