"""
Clean database for live demo.
DESTRUCTIVE - deletes ALL test data including ALL agreements.
KEEPS: properties, users, landlord/tenant profiles.

This script respects foreign key constraints by deleting in the correct order:
1. Reconciliation logs (no FKs pointing to them)
2. Webhook event logs
3. Virtual account transfers (FK -> agreements, properties)
4. Disbursement queue items
5. Transactions (FK -> agreements, properties, users)
6. Applications (FK -> properties, users)
7. Viewing requests (FK -> properties, users)
8. Notifications
9. Maintenance requests
10. Messages / conversations
11. Favourites
12. ALL Agreements (FK -> properties, users) - complete clean slate

Run with: python scripts/clean_database_for_demo.py
"""

import os
import sys
import requests
from dotenv import load_dotenv

# Load env from server/.env
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(SCRIPT_DIR)
load_dotenv(os.path.join(SERVER_DIR, ".env"))

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_SERVICE_KEY")
)

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
    sys.exit(1)

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def confirm(prompt: str) -> bool:
    """Ask user for yes/no confirmation."""
    while True:
        resp = input(f"{prompt} (yes/no): ").strip().lower()
        if resp in ("yes", "y"):
            return True
        if resp in ("no", "n"):
            return False
        print("Please type 'yes' or 'no'.")


def count(table: str, filters: str = "") -> int:
    """Count rows in a table (HEAD request with Prefer: count=exact).

    Returns -1 if the table doesn't exist, otherwise the row count.
    """
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if filters:
        url += f"?{filters}"
    resp = requests.head(
        url, headers={**headers, "Prefer": "count=exact"}, verify=False
    )
    if not resp.ok:
        # 404 = table doesn't exist; anything else is a real error
        if resp.status_code == 404:
            return -1
        return -1
    # Content-Range header looks like: "0-9/123"
    cr = resp.headers.get("Content-Range", "")
    if "/" in cr:
        try:
            return int(cr.split("/")[-1])
        except (ValueError, IndexError):
            return -1
    return 0


def delete_all(table: str, filters: str = "") -> int:
    """Delete rows from a table. Returns number deleted (best effort).

    Supabase requires a WHERE clause for DELETE operations. When no
    filter is supplied we add a permissive `id=gt.00000000-0000-0000-0000-000000000000`
    predicate that matches every row in the table.
    """
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if filters:
        url += f"?{filters}"
    else:
        url += "?id=gt.00000000-0000-0000-0000-000000000000"
    resp = requests.delete(url, headers=headers, verify=False)
    if not resp.ok:
        print(f"  [WARN] {table}: HTTP {resp.status_code} — re-run indicates: {resp.text[:120]}")
        return 0
    try:
        return len(resp.json()) if resp.text else 0
    except Exception:
        return 0


def main():
    print("=" * 70)
    print(" CLEAN DATABASE FOR LIVE DEMO")
    print(" DESTRUCTIVE - DELETES ALL TEST DATA")
    print("=" * 70)
    print()
    print("This script will delete:")
    print("  - All payment reconciliation logs")
    print("  - All virtual account transfers")
    print("  - All nomba_collection + nomba_disbursement transactions")
    print("  - All webhook event logs")
    print("  - All applications (test)")
    print("  - All viewing requests (test)")
    print("  - All notifications (test)")
    print("  - All maintenance requests (test)")
    print("  - All messages / conversations (test)")
    print("  - All favourites (test)")
    print("  - ALL agreements (regardless of Nomba VA status)")
    print()
    print("This script will KEEP:")
    print("  - Users / profiles (landlords + tenants)")
    print("  - Properties (all of them)")
    print("  - Property verifications + media")
    print()
    print("Result: Complete clean slate - you can demo the full flow")
    print("        from property -> application -> agreement -> payment.")
    print()

    if not confirm("Are you sure you want to proceed?"):
        print("Aborted.")
        sys.exit(0)

    print()
    print("=" * 70)
    print(" STARTING CLEANUP")
    print("=" * 70)

    # 1. Payment reconciliation logs
    print("\n[1/12] Deleting payment_reconciliation_log...")
    n = delete_all("payment_reconciliation_log")
    print(f"  Deleted {n} rows")

    # 2. No webhook tables exist in current schema — skipping

    # 3. Transactions (must be deleted BEFORE virtual_account_transfers due to FK)
    print("\n[3/12] Deleting transactions...")
    n = delete_all("transactions", "transaction_type=eq.nomba_collection")
    print(f"  nomba_collection: {n} rows")
    n = delete_all("transactions", "transaction_type=eq.nomba_disbursement")
    print(f"  nomba_disbursement: {n} rows")
    n = delete_all("transactions", "transaction_type=eq.paystack_collection")
    print(f"  paystack_collection: {n} rows")
    n = delete_all("transactions", "transaction_type=eq.paystack_disbursement")
    print(f"  paystack_disbursement: {n} rows")
    n = delete_all("transactions", "transaction_type=eq.payment")
    print(f"  payment: {n} rows")
    # Catch-all: delete any remaining transactions (e.g. with type='other')
    n = delete_all("transactions")
    if n:
        print(f"  other types: {n} rows")

    # 4. Virtual account transfers (must be deleted AFTER transactions)
    print("\n[4/12] Deleting virtual_account_transfers...")
    n = delete_all("virtual_account_transfers")
    print(f"  Deleted {n} rows")

    # 5. No separate disbursement tables exist (transactions table covers this)

    # 6. Applications
    print("\n[6/12] Deleting applications...")
    n = delete_all("applications")
    print(f"  Deleted {n} applications")

    # 7. Viewing requests
    print("\n[7/12] Deleting viewing_requests...")
    n = delete_all("viewing_requests")
    print(f"  Deleted {n} viewing_requests")

    # 8. Notifications
    print("\n[8/12] Deleting notifications...")
    n = delete_all("notifications")
    print(f"  Deleted {n} notifications")

    # 9. Maintenance requests
    print("\n[9/12] Deleting maintenance_requests...")
    n = delete_all("maintenance_requests")
    print(f"  Deleted {n} maintenance_requests")

    # 10. Messages / conversations
    print("\n[10/12] Deleting messages + conversations...")
    n = delete_all("messages")
    print(f"  messages: {n} rows")
    n = delete_all("conversations")
    print(f"  conversations: {n} rows")

    # 11. Favourites
    print("\n[11/12] Deleting favourites...")
    n = delete_all("favorites")
    print(f"  Deleted {n} favorites")

    # 12. Agreements - DELETE ALL (clean slate for live demo)
    print("\n[12/13] Deleting ALL agreements (clean slate)...")
    total_agreements = count("agreements")
    print(f"  Total agreements before: {total_agreements}")
    n = delete_all("agreements")
    print(f"  Deleted {n} agreements (all of them)")
    remaining = count("agreements")
    print(f"  Agreements remaining: {remaining}")
    # 13. Reset property status from 'occupied' to 'vacant'
    print("\n[13/13] Resetting property status from 'occupied' to 'vacant'...")
    occupied_count = count("properties", "status=eq.occupied")
    print(f"  Found {occupied_count} occupied properties")
    
    if occupied_count > 0:
        url = f"{SUPABASE_URL}/rest/v1/properties?status=eq.occupied"
        resp = requests.patch(url, headers=headers, json={"status": "vacant"}, verify=False)
        
        if resp.ok:
            try:
                updated = resp.json() if resp.text else []
                print(f"  Reset {len(updated)} properties to 'vacant'")
            except Exception:
                print(f"  Reset completed (count unavailable)")
        else:
            print(f"  [ERROR] Failed to reset property status: {resp.status_code}")
    else:
        print("  No occupied properties found - nothing to reset")

    # ── PropFlow: check that landlord_briefing column exists on applications ──
    # PropFlow's enrich_and_qualify node writes to applications.landlord_briefing.
    # This column is NOT in the original schema — it must be added via migration
    # before running PropFlow. We check for it here and warn if missing.
    print("\n[PROPFLOW CHECK] Verifying applications.landlord_briefing column...")
    _check_url = f"{SUPABASE_URL}/rest/v1/applications?select=landlord_briefing&limit=0"
    _check_resp = requests.get(_check_url, headers=headers, verify=False)
    if _check_resp.status_code == 400 and "landlord_briefing" in _check_resp.text:
        print("  [WARN] applications.landlord_briefing column MISSING.")
        print("  Run this migration before using PropFlow:")
        print("  ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS")
        print("    landlord_briefing TEXT;")
        print("  ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS")
        print("    propflow_thread_id TEXT;")
    elif _check_resp.ok:
        print("  [OK] applications.landlord_briefing column exists.")
    else:
        print(f"  [INFO] Could not verify column (status {_check_resp.status_code}) - run migration to be safe.")

    # Final verification
    print()
    print("=" * 70)
    print(" VERIFICATION")
    print("=" * 70)

    # Tables that should have data after cleanup
    kept_tables = ["properties", "users"]
    # Tables that should be empty after cleanup (only real tables from schema)
    deleted_tables = [
        "agreements",
        "applications",
        "viewing_requests",
        "virtual_account_transfers",
        "transactions",
        "payment_reconciliation_log",
        "notifications",
        "maintenance_requests",
        "messages",
        "conversations",
        "favorites",
    ]

    print("\nKEPT (should have data):")
    for t in kept_tables:
        try:
            n = count(t)
            if n >= 0:
                print(f"  {t}: {n} rows")
            else:
                print(f"  {t}: (table not found)")
        except Exception as e:
            print(f"  {t}: ERROR {e}")

    print("\nDELETED (should be 0):")
    for t in deleted_tables:
        try:
            n = count(t)
            if n < 0:
                print(f"  -- {t}: (table not found, skipped)")
            else:
                status = "[OK]" if n == 0 else "[WARN]"
                print(f"  {status} {t}: {n} rows")
        except Exception as e:
            print(f"  {t}: ERROR {e}")

    print()
    print("=" * 70)
    print(" CLEANUP COMPLETE")
    print("=" * 70)
    print()
    print("Next steps for the live demo:")
    print("  1. Run PropFlow migration if not done:")
    print("     ALTER TABLE public.applications")
    print("       ADD COLUMN IF NOT EXISTS landlord_briefing TEXT,")
    print("       ADD COLUMN IF NOT EXISTS propflow_thread_id TEXT;")
    print()
    print("  2. Seed the demo tenant profile (if not already done):")
    print("     python scripts\\seed_propflow_demo.py")
    print()
    print("  3. Start the PropFlow demo via chat widget or API:")
    print("     POST /api/v1/propflow/chat")
    print("     { message: 'I need 2-bed flat in Lekki, 500k/month' }")
    print()
    print("  4. As landlord, approve the application:")
    print("     POST /api/v1/propflow/resume/{thread_id}")
    print("     { decision: 'approved' }")
    print()
    print("  5. Sign the agreement (tenant + landlord in app)")
    print()
    print("  6. Simulate a tenant payment:")
    print("     python scripts\\test_webhook_local.py <agreement-uuid> full_payment")
    print()
    print("  7. Verify payment reflects in landlord dashboard")
    print("     and disbursement triggers automatically.")
    print()


if __name__ == "__main__":
    main()
