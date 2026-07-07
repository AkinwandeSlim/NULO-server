"""
Inspect property statuses in the database.
READ-ONLY - does NOT modify any data.

This script helps us understand the current state of properties
before making any bulk updates. It will show:
- All distinct property statuses and their counts
- Sample properties for each status
- Any properties that might need attention

Run with: python scripts/inspect_property_statuses.py
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


def column_exists(table: str, column: str) -> bool:
    """Check if a column exists in a table by trying a small query."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?select={column}&limit=1"
    resp = requests.get(url, headers=headers)
    return resp.ok


def main():
    print("=" * 70)
    print(" PROPERTY STATUS INSPECTION (READ-ONLY)")
    print("=" * 70)
    print()

    # 1. Get total property count
    print("[1] Counting total properties...")
    url = f"{SUPABASE_URL}/rest/v1/properties?select=id"
    resp = requests.get(url, headers={**headers, "Prefer": "count=exact"})
    if resp.ok:
        cr = resp.headers.get("Content-Range", "")
        if "/" in cr:
            total = int(cr.split("/")[-1])
            print(f"  Total properties: {total}")
    print()

    # 2. Detect which status column exists
    has_property_status = column_exists("properties", "property_status")
    has_status = column_exists("properties", "status")

    print("[2] Detecting status column...")
    print(f"  'property_status' column: {'YES' if has_property_status else 'NO'}")
    print(f"  'status' column: {'YES' if has_status else 'NO'}")
    print()

    if not has_property_status and not has_status:
        print("  ERROR: Neither 'property_status' nor 'status' column found.")
        print("  Cannot continue inspection.")
        return

    # Pick the column that exists
    status_column = "property_status" if has_property_status else "status"
    print(f"  Using column: {status_column!r}")
    print()

    # 3. Get all distinct status values
    print(f"[3] Querying distinct {status_column} values...")
    rows = query_supabase(
        "properties",
        {"select": status_column, "limit": 1000},
    )
    if not rows:
        print("  No properties found or query failed.")
        return

    # Count occurrences
    status_counts = {}
    for row in rows:
        status = row.get(status_column, "NULL")
        status_counts[status] = status_counts.get(status, 0) + 1

    print(f"  Found {len(status_counts)} distinct status value(s):")
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"    - {status!r}: {count} properties")
    print()

    # 4. Sample properties for each status
    print("[4] Sample properties per status (first 3 per status):")
    for status in status_counts.keys():
        filter_param = (
            f"eq.{status}" if status != "NULL" else "is.null"
        )
        rows = query_supabase(
            "properties",
            {
                "select": f"id,title,{status_column},created_at,landlord_id",
                status_column: filter_param,
                "limit": 3,
            },
        )
        if rows:
            print(f"\n  Status = {status!r} ({status_counts[status]} total):")
            for p in rows:
                pid = p.get("id", "?")[:8] + "..." if p.get("id") else "?"
                title = p.get("title", "(no title)")[:50]
                print(f"    - id={pid} | title={title!r}")
    print()

    # 5. Cross-check with agreements
    print("[5] Cross-checking: properties with active agreements...")
    rows = query_supabase(
        "agreements",
        {"select": "property_id,status,reconciliation_status", "limit": 1000},
    )
    if rows:
        props_with_agreements = {}
        for a in rows:
            pid = a.get("property_id")
            if pid:
                props_with_agreements[pid] = {
                    "status": a.get("status"),
                    "reconciliation": a.get("reconciliation_status"),
                }
        print(f"  {len(props_with_agreements)} properties have agreements")
        for pid, info in list(props_with_agreements.items())[:5]:
            print(
                f"    - {pid[:8]}... | agreement.status={info['status']!r} "
                f"| reconciliation={info['reconciliation']!r}"
            )
    else:
        print("  No agreements found (database already cleaned!)")
    print()

    print("=" * 70)
    print(" INSPECTION COMPLETE")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  - Review the status distribution above")
    print("  - Decide which statuses should map to 'vacant'")
    print("  - Run the update script (separate file) only after confirming")
    print()


if __name__ == "__main__":
    main()
