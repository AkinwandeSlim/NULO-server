"""
[DEPRECATED -- DO NOT USE]

This script used to call POST /v1/accounts/virtual directly against Nomba
(LIVE or TEST) with the parent header to inspect the full validation
response. It was a diagnostic for the parent-scoped Path A provisioning
flow, which silently drops inbound webhooks with 404 "No redirect
configuration" because the hackathon's webhook URL is registered against
the SUB-account, not the parent.

The provision-nomba route now uses Path B (sub-account-scoped, -SUB
suffix) by default. So this diagnostic no longer reflects what the
production flow does, and the raw parent-scoped call is no longer a
useful debugging target.

Use one of these instead:
  - server/scripts/reprovision_live_va_subaccount.py
        Live sub-account VA provisioning (Path B). Use this for live tests
        (prints the full Nomba response on success or error).
  - server/scripts/reprovision_sandbox_va_subaccount.py
        Sandbox sub-account VA provisioning (Path B). Use this for local
        testing with NOMBA_ENV=test.
  - server/scripts/debug_nomba_webhooks.py
        Diagnose webhook delivery issues (event-logs API, parent vs sub).

If you need to inspect what the (now-removed) Path A direct call looked
like, see the git history. The script body is preserved below as comments
for archaeology only.

Original body (Path A, parent-scoped direct call) -- kept for reference:
-------------------------------------------------------------------------
# Step 1: POST {base_url}/auth/token/issue  (client_credentials)
# Step 2: POST {base_url}/accounts/virtual  (parent accountId header,
#          body = {accountRef, accountName})
# Iterate over hard-coded test names and a fresh random accountRef,
# printing the full response body for each.
-------------------------------------------------------------------------
"""
import sys


def main():
    print("=" * 70)
    print("[DEPRECATED] diagnose_va_creation.py")
    print("=" * 70)
    print()
    print("This script is disabled. The parent-scoped Path A direct call it")
    print("made is no longer a useful diagnostic -- the production route")
    print("uses Path B (sub-account-scoped) and the raw parent call drops")
    print("inbound webhooks (404 'No redirect configuration').")
    print()
    print("Use instead:")
    print("  - reprovision_live_va_subaccount.py     (live, Path B)")
    print("  - reprovision_sandbox_va_subaccount.py  (sandbox, Path B)")
    print("  - debug_nomba_webhooks.py               (webhook delivery diag)")
    print()
    print("No Nomba call was made.")
    sys.exit(1)


if __name__ == "__main__":
    main()
