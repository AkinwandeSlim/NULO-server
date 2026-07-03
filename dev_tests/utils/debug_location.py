#!/usr/bin/env python3
"""
Debug script to inspect location data in properties table
Check: What's stored in DB vs what was sent from frontend
"""

import os
import sys
import json

# Load from server directory .env
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

# Try loading from parent too
parent_env = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(parent_env):
    load_dotenv(parent_env)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

print(f"Loaded env from: {parent_env}")
print(f"SUPABASE_URL: {SUPABASE_URL}")
print(f"SUPABASE_SERVICE_KEY: {SUPABASE_SERVICE_KEY[:20]}...")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("❌ Missing Supabase credentials in .env")
    print(f"  SUPABASE_URL: {SUPABASE_URL}")
    print(f"  SUPABASE_SERVICE_KEY: {SUPABASE_SERVICE_KEY}")
    sys.exit(1)

from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

print("=" * 80)
print("🔍 LOCATION DATA DEBUG - Check what's stored in DB")
print("=" * 80)

try:
    # Get LATEST 20 properties (newest first - most recent uploads)
    print("\n📊 Fetching LATEST 20 properties (newest first)...")
    response = supabase.table("properties").select(
        "id, title, address, city, state, location, neighborhood, created_at, landlord_id"
    ).order("created_at", desc=True).limit(20).execute()
    
    if not response.data:
        print("❌ No properties found in database")
        sys.exit(1)
    
    print(f"\n✅ Found {len(response.data)} properties (newest first)\n")
    print("-" * 100)
    
    for i, prop in enumerate(response.data, 1):
        print(f"\n#{i} 🏠 {prop['title']}")
        print(f"   ID: {prop['id']}")
        print(f"   Landlord: {prop['landlord_id']}")
        print(f"   Created: {prop['created_at']}")
        print(f"\n   📍 Location Fields:")
        print(f"      location:     {repr(prop['location'])}")
        print(f"      city:         {repr(prop['city'])}")
        print(f"      state:        {repr(prop['state'])}")
        print(f"      address:      {repr(prop['address'])}")
        print(f"      neighborhood: {repr(prop['neighborhood'])}")
        
        # Analysis
        location_str = str(prop['location'])
        city = str(prop['city'])
        state = str(prop['state'])
        
        print(f"\n   🔍 Analysis:")
        expected = f"{city}, {state}"
        if location_str == expected:
            print(f"      ✅ CORRECT! location = '{location_str}'")
        else:
            print(f"      ❌ MISMATCH!")
            print(f"         Expected: '{expected}'")
            print(f"         Got:      '{location_str}'")
            
            # Check for duplication pattern
            if city in location_str or state in location_str:
                city_count = location_str.count(city)
                state_count = location_str.count(state)
                print(f"         {city} appears {city_count} times")
                print(f"         {state} appears {state_count} times")
        
        print("-" * 100)
    
    # Now check for duplicates in location field
    print("\n🔍 ANALYSIS - Looking for duplication patterns...")
    print("-" * 80)
    
    location_patterns = {}
    for prop in response.data:
        loc = prop.get('location', '')
        if loc not in location_patterns:
            location_patterns[loc] = []
        location_patterns[loc].append(prop['id'])
    
    for loc, ids in location_patterns.items():
        if len(ids) > 1:
            print(f"⚠️ Location appears {len(ids)} times: {loc}")
        else:
            # Check if location contains duplicated city/state
            city = prop.get('city', '')
            state = prop.get('state', '')
            expected = f"{city}, {state}"
            
            if loc and loc != expected and city in loc and state in loc:
                count = loc.count(city) + loc.count(state)
                if count > 2:
                    print(f"🔴 DUPLICATE PATTERN in: {loc}")
                    print(f"   Expected: {expected}")
                    print(f"   Actual:   {loc}")
    
    print("\n✅ Debug complete!")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
