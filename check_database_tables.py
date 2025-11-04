"""
Script to check which database tables exist in Supabase
"""
import os
import sys
from supabase import create_client, Client
from dotenv import load_dotenv

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

if not supabase_url or not supabase_key:
    print("[ERROR] SUPABASE_URL or SUPABASE_SERVICE_KEY not found in .env")
    exit(1)

supabase: Client = create_client(supabase_url, supabase_key)

print("[INFO] Checking database tables...\n")

# List of required tables
required_tables = [
    "viewing_requests",
    "conversations",
    "messages",
    "favorites",
    "notifications",
    "properties",
    "profiles",
    "users"
]

# Check each table
for table_name in required_tables:
    try:
        # Try to query the table with limit 0 (doesn't fetch data, just checks if table exists)
        response = supabase.table(table_name).select("*", count="exact").limit(0).execute()
        count = response.count if hasattr(response, 'count') else 0
        print(f"[OK] {table_name:<25} EXISTS (rows: {count})")
    except Exception as e:
        error_msg = str(e)
        if "relation" in error_msg.lower() and "does not exist" in error_msg.lower():
            print(f"[MISSING] {table_name:<25} MISSING")
        else:
            print(f"[ERROR] {table_name:<25} ERROR: {error_msg[:50]}...")

print("\n" + "="*60)
print("[SUMMARY]")
print("="*60)

# Check if critical tables exist
critical_tables = ["viewing_requests", "conversations", "messages", "favorites"]
missing_tables = []

for table_name in critical_tables:
    try:
        supabase.table(table_name).select("*").limit(0).execute()
    except Exception as e:
        if "relation" in str(e).lower() and "does not exist" in str(e).lower():
            missing_tables.append(table_name)

if missing_tables:
    print(f"\n[ERROR] Missing {len(missing_tables)} critical table(s):")
    for table in missing_tables:
        print(f"   - {table}")
    print("\n[ACTION REQUIRED]")
    print("   Run the SQL script: CREATE_DATABASE_TABLES.sql")
    print("   in your Supabase SQL Editor to create missing tables.")
else:
    print("\n[OK] All critical tables exist!")
    print("[SUCCESS] Your database is ready for testing!")

print("\n" + "="*60)
