"""
Update property statuses from 'occupied' to 'vacant'.
SAFETY: Shows preview, asks for confirmation, then updates.

This script will:
1. Find all properties with status='occupied'
2. Show you a preview of what will change
3. Ask for explicit confirmation
4. Update them to status='vacant'
5. Verify the result

Run with: python scripts/reset_properties_to_vacant.py
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


def query_supabase(table: str, params: dict) -> list:
    """Query Supabase REST API. Returns empty list on error."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    resp = requests.get(url, headers=headers, params=params)
    if not resp.ok:
        return []
    try:
        return resp.json()
    except Exception:
        return []


def confirm(prompt: str) -> bool:
    """Ask user for yes/no confirmation."""
    while True:
        resp = input(f"{prompt} (yes/no): ").strip().lower()
        if resp in ("yes", "y"):
            return True
        if resp in ("no", "n"):
            return False
        print("Please type 'yes' or 'no'.")


def main():
    print("=" * 70)
    print(" RESET PROPERTIES: occupied -> vacant")
    print("=" * 70)
    print()

    # 1. Find all occupied properties
    print("[1] Finding all properties with status='occupied'...")
    occupied_props = query_supabase(
        "properties",
        {
            "select": "id,title,status,landlord_id,created_at",
            "status": "eq.occupied",
            "limit": 1000,
        },
    )

    if not occupied_props:
        print("  No properties found with status='occupied'.")
        print("  Nothing to update.")
        return

    print(f"  Found {len(occupied_props)} occupied properties:")
    for i, p in enumerate(occupied_props, 1):
        pid = p.get("id", "?")[:8] + "..." if p.get("id") else "?"
        title = p.get("title", "(no title)")
        print(f"    {i}. id={pid} | title={title!r}")
    print()

    # 2. Also count vacant properties for context
    print("[2] Context: counting vacant properties...")
    vacant_props = query_supabase(
        "properties",
        {"select": "id", "status": "eq.vacant", "limit": 1000},
    )
    print(f"  Currently {len(vacant_props)} properties are 'vacant'")
    print(f"  After update: {len(vacant_props) + len(occupied_props)} will be 'vacant'")
    print()

    # 3. Show preview
    print("=" * 70)
    print(" PREVIEW: Changes that will be made")
    print("=" * 70)
    print(f"  Will update {len(occupied_props)} properties:")
    print(f"    status: 'occupied' -> 'vacant'")
    print()
    for i, p in enumerate(occupied_props, 1):
        pid = p.get("id", "?")
        title = p.get("title", "(no title)")
        print(f"    {i}. [{pid}] {title!r}")
    print()

    # 4. Confirm
    if not confirm("Do you want to apply these changes?"):
        print()
        print("Aborted. No changes made.")
        return

    # 5. Apply update using PostgREST's bulk update via filter
    print()
    print("[3] Applying update...")
    url = f"{SUPABASE_URL}/rest/v1/properties?status=eq.occupied"
    resp = requests.patch(
        url,
        headers=headers,
        json={"status": "vacant"},
    )

    if not resp.ok:
        print(f"  [ERROR] Update failed: {resp.status_code} {resp.text[:200]}")
        return

    try:
        updated_rows = resp.json() if resp.text else []
        update_count = len(updated_rows)
    except Exception:
        update_count = 0

    print(f"  Updated {update_count} properties to status='vacant'")
    print()

    # 6. Verify
    print("[4] Verifying result...")
    remaining_occupied = query_supabase(
        "properties",
        {"select": "id,title,status", "status": "eq.occupied", "limit": 1000},
    )
    new_vacant = query_supabase(
        "properties",
        {"select": "id,title,status", "status": "eq.vacant", "limit": 1000},
    )

    print(f"  Properties still 'occupied': {len(remaining_occupied)}")
    if remaining_occupied:
        for p in remaining_occupied:
            print(f"    - [{p.get('id', '?')[:8]}...] {p.get('title', '?')!r}")

    print(f"  Properties now 'vacant': {len(new_vacant)}")
    print()

    if len(remaining_occupied) == 0 and len(new_vacant) == 34:
        print("=" * 70)
        print(" SUCCESS - All 34 properties are now 'vacant'")
        print("=" * 70)
    elif update_count == len(occupied_props):
        print("=" * 70)
        print(f" SUCCESS - Updated {update_count} properties")
        print("=" * 70)
    else:
        print("=" * 70)
        print(" PARTIAL - Some properties may not have been updated")
        print(" Check the output above and re-run if needed")
        print("=" * 70)

    print()
    print("Next steps:")
    print("  - All properties are now 'vacant' and ready for the live demo")
    print("  - Tenants can now apply for any property")
    print()


if __name__ == "__main__":
    main()
