#!/usr/bin/env python3
"""
Quick User Check - Bypass SSL issues
Simple REST API check for demo users without SSL verification.
"""

import requests
import json
import os
from dotenv import load_dotenv

# Load environment
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")
    exit(1)

# Demo users
TENANT_EMAIL = "slimmedia0705@gmail.com"
LANDLORD_EMAIL = "raphawellnessoptimization@gmail.com"

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

def check_user(email: str, role: str) -> dict:
    """Check if user exists via REST API."""
    try:
        # Disable SSL verification for testing
        url = f"{SUPABASE_URL}/rest/v1/users?email=eq.{email}&select=*"
        response = requests.get(url, headers=headers, verify=False)
        
        if response.status_code == 200:
            users = response.json()
            if users:
                user = users[0]
                print(f"✅ {role} found: {user.get('full_name')} ({user.get('id')})")
                print(f"   Role: {user.get('role')}")
                print(f"   Phone: {user.get('phone')}")
                return user
            else:
                print(f"❌ {role} not found: {email}")
                return None
        else:
            print(f"❌ Error checking {role}: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Exception checking {role}: {e}")
        return None

def check_properties(landlord_id: str) -> list:
    """Check properties owned by landlord."""
    try:
        url = f"{SUPABASE_URL}/rest/v1/properties?landlord_id=eq.{landlord_id}&select=*"
        response = requests.get(url, headers=headers, verify=False)
        
        if response.status_code == 200:
            properties = response.json()
            print(f"✅ Found {len(properties)} properties for landlord")
            
            available_count = 0
            for prop in properties[:3]:  # Show first 3
                available = (prop.get("status") == "vacant" and 
                           prop.get("verification_status") == "approved")
                if available:
                    available_count += 1
                    
                status_icon = "✅" if available else "⚠️"
                print(f"   {status_icon} {prop.get('title', 'Untitled')} - ₦{prop.get('price', 0):,.0f}/month")
                print(f"      Status: {prop.get('status')} | Verification: {prop.get('verification_status')}")
            
            print(f"✅ {available_count} properties ready for PropFlow demo")
            return properties
        else:
            print(f"❌ Error checking properties: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ Exception checking properties: {e}")
        return []

def main():
    """Main check function."""
    print("🔍 Checking demo users (bypassing SSL)...")
    print("=" * 60)
    
    # Check tenant
    print(f"\n👤 CHECKING TENANT: {TENANT_EMAIL}")
    tenant = check_user(TENANT_EMAIL, "tenant")
    
    # Check landlord  
    print(f"\n🏠 CHECKING LANDLORD: {LANDLORD_EMAIL}")
    landlord = check_user(LANDLORD_EMAIL, "landlord")
    
    # Check landlord properties
    if landlord:
        print(f"\n🏢 CHECKING PROPERTIES...")
        properties = check_properties(landlord["id"])
    else:
        properties = []
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 DEMO READINESS SUMMARY")
    print("=" * 60)
    
    tenant_ready = tenant is not None
    landlord_ready = landlord is not None and len(properties) > 0
    
    print(f"Tenant Ready: {'✅ YES' if tenant_ready else '❌ NO'}")
    print(f"Landlord Ready: {'✅ YES' if landlord_ready else '❌ NO'}")
    print(f"Overall Ready: {'✅ YES' if tenant_ready and landlord_ready else '❌ NO'}")
    
    if tenant_ready and landlord_ready:
        print("\n🚀 PROPFLOW DEMO READY!")
        print("Next steps:")
        print("1. Login as tenant in frontend")
        print("2. Use PropFlow chat widget")
        print("3. Input: 'I want 2-bedroom apartment in Lekki, budget 500k monthly'")
        print("4. Application will be created")
        print("5. Login as landlord to approve")
        print("6. Complete payment flow")
    else:
        print("\n⚠️  Demo not ready - missing accounts or properties")

if __name__ == "__main__":
    # Disable SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    main()