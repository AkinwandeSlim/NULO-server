#!/usr/bin/env python3
"""
Check Demo Users Script
Verifies that demo users exist and have proper profiles/properties for PropFlow testing.

Demo Accounts:
- Tenant: slimmedia0705@gmail.com
- Landlord: raphawellnessoptimization@gmail.com (password: nombahackathon2026)

Usage:
    python scripts/check_demo_users.py
    python scripts/check_demo_users.py --setup-missing  # Create missing profiles if needed
"""

import asyncio
import argparse
import sys
import uuid
from pathlib import Path
from datetime import datetime

# Add the server directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import get_supabase_admin


class DemoUserChecker:
    """Check and setup demo users for PropFlow testing."""
    
    def __init__(self):
        self.supabase = get_supabase_admin()
        
        # Demo user details
        self.TENANT_EMAIL = "slimmedia0705@gmail.com"
        self.LANDLORD_EMAIL = "raphawellnessoptimization@gmail.com"
        
    async def check_all_users(self) -> dict:
        """Check both demo users and return comprehensive status."""
        print("🔍 Checking demo user accounts...")
        
        results = {
            "tenant": await self._check_tenant(),
            "landlord": await self._check_landlord(),
            "ready_for_demo": False
        }
        
        # Overall readiness check
        tenant_ready = (
            results["tenant"]["user_exists"] and 
            results["tenant"]["profile_exists"]
        )
        landlord_ready = (
            results["landlord"]["user_exists"] and 
            results["landlord"]["profile_exists"] and
            results["landlord"]["properties_count"] > 0
        )
        
        results["ready_for_demo"] = tenant_ready and landlord_ready
        
        self._print_summary(results)
        return results
    
    async def _check_tenant(self) -> dict:
        """Check tenant user and profile."""
        result = {
            "email": self.TENANT_EMAIL,
            "user_exists": False,
            "user_id": None,
            "user_role": None,
            "profile_exists": False,
            "profile_data": None,
            "issues": []
        }
        
        try:
            # Check user exists
            user_response = self.supabase.table("users").select("*").eq("email", self.TENANT_EMAIL).execute()
            
            if user_response.data:
                user = user_response.data[0]
                result["user_exists"] = True
                result["user_id"] = user["id"]
                result["user_role"] = user.get("role")
                
                print(f"   ✅ Tenant user found: {user['full_name']} ({user['id']})")
                
                # Check role
                if user.get("role") != "tenant":
                    result["issues"].append(f"User role is '{user.get('role')}', expected 'tenant'")
                
                # Check tenant profile
                profile_response = self.supabase.table("tenant_profiles").select("*").eq("id", user["id"]).execute()
                
                if profile_response.data:
                    result["profile_exists"] = True
                    result["profile_data"] = profile_response.data[0]
                    print(f"   ✅ Tenant profile found")
                    
                    # Check profile completeness
                    profile = profile_response.data[0]
                    required_fields = ["employment_status", "monthly_income_range"]
                    for field in required_fields:
                        if not profile.get(field):
                            result["issues"].append(f"Missing tenant profile field: {field}")
                else:
                    result["issues"].append("Tenant profile not found")
                    print(f"   ❌ Tenant profile missing")
                    
            else:
                result["issues"].append("User account not found")
                print(f"   ❌ Tenant user not found: {self.TENANT_EMAIL}")
                
        except Exception as e:
            result["issues"].append(f"Database error: {e}")
            print(f"   ❌ Error checking tenant: {e}")
        
        return result
    
    async def _check_landlord(self) -> dict:
        """Check landlord user, profile, and properties."""
        result = {
            "email": self.LANDLORD_EMAIL,
            "user_exists": False,
            "user_id": None,
            "user_role": None,
            "profile_exists": False,
            "profile_data": None,
            "properties_count": 0,
            "properties": [],
            "issues": []
        }
        
        try:
            # Check user exists
            user_response = self.supabase.table("users").select("*").eq("email", self.LANDLORD_EMAIL).execute()
            
            if user_response.data:
                user = user_response.data[0]
                result["user_exists"] = True
                result["user_id"] = user["id"]
                result["user_role"] = user.get("role")
                
                print(f"   ✅ Landlord user found: {user['full_name']} ({user['id']})")
                
                # Check role
                if user.get("role") != "landlord":
                    result["issues"].append(f"User role is '{user.get('role')}', expected 'landlord'")
                
                # Check landlord profile
                profile_response = self.supabase.table("landlord_profiles").select("*").eq("id", user["id"]).execute()
                
                if profile_response.data:
                    result["profile_exists"] = True
                    result["profile_data"] = profile_response.data[0]
                    print(f"   ✅ Landlord profile found")
                else:
                    result["issues"].append("Landlord profile not found")
                    print(f"   ❌ Landlord profile missing")
                
                # Check properties owned by landlord
                properties_response = self.supabase.table("properties").select("*").eq("landlord_id", user["id"]).execute()
                
                if properties_response.data:
                    result["properties_count"] = len(properties_response.data)
                    result["properties"] = properties_response.data
                    print(f"   ✅ Found {len(properties_response.data)} properties owned by landlord")
                    
                    # Check property status for PropFlow demo
                    available_count = 0
                    for prop in properties_response.data:
                        if (prop.get("status") == "vacant" and 
                            prop.get("verification_status") == "approved"):
                            available_count += 1
                    
                    if available_count == 0:
                        result["issues"].append("No properties with status='vacant' and verification_status='approved'")
                    else:
                        print(f"   ✅ {available_count} properties available for PropFlow matching")
                        
                else:
                    result["issues"].append("No properties found for landlord")
                    print(f"   ❌ No properties found for landlord")
                    
            else:
                result["issues"].append("User account not found")
                print(f"   ❌ Landlord user not found: {self.LANDLORD_EMAIL}")
                
        except Exception as e:
            result["issues"].append(f"Database error: {e}")
            print(f"   ❌ Error checking landlord: {e}")
        
        return result
    
    def _print_summary(self, results: dict):
        """Print formatted summary of results."""
        print("\n" + "=" * 60)
        print(" DEMO USER STATUS SUMMARY")
        print("=" * 60)
        
        # Tenant summary
        tenant = results["tenant"]
        print(f"\n👤 TENANT: {tenant['email']}")
        print(f"   User Account: {'✅ Found' if tenant['user_exists'] else '❌ Missing'}")
        if tenant["user_exists"]:
            print(f"   User ID: {tenant['user_id']}")
            print(f"   Role: {tenant['user_role']}")
        print(f"   Profile: {'✅ Found' if tenant['profile_exists'] else '❌ Missing'}")
        
        if tenant["issues"]:
            print("   Issues:")
            for issue in tenant["issues"]:
                print(f"     • {issue}")
        
        # Landlord summary
        landlord = results["landlord"]
        print(f"\n🏠 LANDLORD: {landlord['email']}")
        print(f"   User Account: {'✅ Found' if landlord['user_exists'] else '❌ Missing'}")
        if landlord["user_exists"]:
            print(f"   User ID: {landlord['user_id']}")
            print(f"   Role: {landlord['user_role']}")
        print(f"   Profile: {'✅ Found' if landlord['profile_exists'] else '❌ Missing'}")
        print(f"   Properties: {landlord['properties_count']} owned")
        
        if landlord["properties"]:
            print("   Property Details:")
            for prop in landlord["properties"][:3]:  # Show first 3
                status_icon = "✅" if (prop.get("status") == "vacant" and 
                                    prop.get("verification_status") == "approved") else "⚠️"
                print(f"     {status_icon} {prop.get('title', 'Untitled')} - ₦{prop.get('price', 0):,.0f}/month")
                print(f"        Status: {prop.get('status')} | Verification: {prop.get('verification_status')}")
        
        if landlord["issues"]:
            print("   Issues:")
            for issue in landlord["issues"]:
                print(f"     • {issue}")
        
        # Overall status
        print(f"\n🎯 PROPFLOW DEMO READINESS")
        if results["ready_for_demo"]:
            print("   ✅ READY - Both accounts configured correctly")
            print("\n   Next Steps:")
            print("   1. Login as tenant: slimmedia0705@gmail.com")
            print("   2. Use PropFlow chat: 'I want 2-bed flat in [location], budget [amount]'")
            print("   3. Login as landlord to approve application")
            print("   4. Complete payment flow")
        else:
            print("   ❌ NOT READY - Fix issues above first")
            print("\n   Run with --setup-missing to auto-fix profile issues")
    
    async def setup_missing_profiles(self) -> bool:
        """Create missing profiles with demo-appropriate data."""
        print("🛠️  Setting up missing profiles...")
        
        results = await self.check_all_users()
        fixed_issues = []
        
        try:
            # Setup missing tenant profile
            if results["tenant"]["user_exists"] and not results["tenant"]["profile_exists"]:
                tenant_profile = {
                    "id": results["tenant"]["user_id"],
                    "identity_verification_status": "verified",
                    "employment_status": "employed",
                    "monthly_income_range": "500000-1000000",
                    "company_name": "Tech Startup Nigeria",
                    "job_title": "Software Developer",
                    "work_location": "Lagos Island",
                    "guarantor_name": "John Doe",
                    "guarantor_phone": "+2348123456789",
                    "emergency_contact_name": "Jane Doe",
                    "emergency_contact_phone": "+2348987654321",
                    "created_at": datetime.utcnow().isoformat()
                }
                
                self.supabase.table("tenant_profiles").insert(tenant_profile).execute()
                fixed_issues.append("Created tenant profile")
                print("   ✅ Created tenant profile")
            
            # Setup missing landlord profile
            if results["landlord"]["user_exists"] and not results["landlord"]["profile_exists"]:
                landlord_profile = {
                    "id": results["landlord"]["user_id"],
                    "verification_status": "verified",
                    "bank_account_name": "Rapha Wellness Optimization",
                    "bank_account_number": "1234567890",
                    "bank_name": "GTBank",
                    "bvn": "12345678901",
                    "created_at": datetime.utcnow().isoformat()
                }
                
                self.supabase.table("landlord_profiles").insert(landlord_profile).execute()
                fixed_issues.append("Created landlord profile")
                print("   ✅ Created landlord profile")
            
            if fixed_issues:
                print(f"\n✅ Fixed {len(fixed_issues)} issues:")
                for fix in fixed_issues:
                    print(f"   • {fix}")
                return True
            else:
                print("   ℹ️  No missing profiles to create")
                return True
                
        except Exception as e:
            print(f"❌ Error setting up profiles: {e}")
            return False


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Check PropFlow Demo Users")
    parser.add_argument("--setup-missing", action="store_true", 
                       help="Create missing profiles automatically")
    
    args = parser.parse_args()
    
    checker = DemoUserChecker()
    
    try:
        if args.setup_missing:
            success = await checker.setup_missing_profiles()
            return 0 if success else 1
        else:
            results = await checker.check_all_users()
            return 0 if results["ready_for_demo"] else 1
            
    except Exception as e:
        print(f"❌ Script failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)