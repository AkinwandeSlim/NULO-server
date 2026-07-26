#!/usr/bin/env python3
"""
PropFlow Demo Setup Script
Sets up database with sample data for PropFlow demonstrations.

Usage:
    python scripts/setup_propflow_demo.py              # Setup with sample data
    python scripts/setup_propflow_demo.py --clean      # Clean existing PropFlow data
    python scripts/setup_propflow_demo.py --verify     # Verify setup
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
from app.propflow.tests.fixtures import SAMPLE_TENANTS, SAMPLE_PROPERTIES, SAMPLE_LANDLORDS


class PropFlowDemoSetup:
    """Database setup for PropFlow demonstrations."""
    
    def __init__(self):
        self.supabase = get_supabase_admin()
        
    async def setup_sample_data(self):
        """Insert sample tenants, landlords, and properties for demo."""
        print("🏗️  Setting up PropFlow demo data...")
        
        try:
            # Setup tenants
            print("👥 Creating sample tenants...")
            await self._setup_tenants()
            
            # Setup landlords  
            print("🏠 Creating sample landlords...")
            await self._setup_landlords()
            
            # Setup properties
            print("🏢 Creating sample properties...")
            await self._setup_properties()
            
            print("✅ Demo data setup complete!")
            
        except Exception as e:
            print(f"❌ Setup failed: {e}")
            raise
    
    async def _setup_tenants(self):
        """Create sample tenant accounts and profiles."""
        for tenant_data in SAMPLE_TENANTS:
            # Check if tenant exists
            existing = self.supabase.table("users").select("id").eq("id", tenant_data["id"]).execute()
            
            if existing.data:
                print(f"   ↳ Tenant {tenant_data['full_name']} already exists")
                continue
            
            # Create user record
            user_record = {
                "id": tenant_data["id"],
                "email": tenant_data["email"],
                "full_name": tenant_data["full_name"],
                "phone": tenant_data["phone"],
                "role": "tenant",
                "created_at": datetime.utcnow().isoformat(),
                "email_verified": True
            }
            
            self.supabase.table("users").insert(user_record).execute()
            
            # Create tenant profile
            profile_record = {
                "id": tenant_data["id"],  # Same as user ID
                **tenant_data["profile"],
                "created_at": datetime.utcnow().isoformat()
            }
            
            self.supabase.table("tenant_profiles").upsert(profile_record).execute()
            
            print(f"   ✅ Created tenant: {tenant_data['full_name']}")
    
    async def _setup_landlords(self):
        """Create sample landlord accounts and profiles."""
        for landlord_data in SAMPLE_LANDLORDS:
            # Check if landlord exists
            existing = self.supabase.table("users").select("id").eq("id", landlord_data["id"]).execute()
            
            if existing.data:
                print(f"   ↳ Landlord {landlord_data['full_name']} already exists")
                continue
            
            # Create user record
            user_record = {
                "id": landlord_data["id"],
                "email": landlord_data["email"],
                "full_name": landlord_data["full_name"],
                "phone": landlord_data["phone"],
                "role": "landlord",
                "created_at": datetime.utcnow().isoformat(),
                "email_verified": True
            }
            
            self.supabase.table("users").insert(user_record).execute()
            
            # Create landlord profile
            profile_record = {
                "id": landlord_data["id"],  # Same as user ID
                **landlord_data["profile"],
                "created_at": datetime.utcnow().isoformat()
            }
            
            self.supabase.table("landlord_profiles").upsert(profile_record).execute()
            
            print(f"   ✅ Created landlord: {landlord_data['full_name']}")
    
    async def _setup_properties(self):
        """Create sample properties."""
        for property_data in SAMPLE_PROPERTIES:
            # Check if property exists
            existing = self.supabase.table("properties").select("id").eq("id", property_data["id"]).execute()
            
            if existing.data:
                print(f"   ↳ Property {property_data['title']} already exists")
                continue
            
            # Create property record
            property_record = {
                "id": property_data["id"],
                "title": property_data["title"],
                "location": property_data["location"],
                "address": property_data["address"],
                "price": property_data["price"],
                "beds": property_data["beds"],
                "baths": property_data["baths"],
                "size_sqm": property_data["size_sqm"],
                "property_type": property_data["property_type"],
                "status": property_data["status"],
                "verification_status": property_data["verification_status"],
                "landlord_id": property_data["landlord_id"],
                "amenities": property_data["amenities"],
                "images": property_data["images"],
                "created_at": property_data["created_at"],
                "deleted_at": None
            }
            
            self.supabase.table("properties").insert(property_record).execute()
            
            print(f"   ✅ Created property: {property_data['title']}")
    
    async def clean_propflow_data(self):
        """Clean existing PropFlow test data."""
        print("🧹 Cleaning PropFlow demo data...")
        
        try:
            # Clean applications with propflow_thread_id
            applications = self.supabase.table("applications").delete().not_.is_("propflow_thread_id", None).execute()
            print(f"   🗑️  Deleted {len(applications.data or [])} PropFlow applications")
            
            # Clean agreements related to PropFlow
            # Note: This is a simplified cleanup - in production you'd want more careful cascade deletion
            
            # Clean sample users (be careful here - only delete test users)
            test_user_ids = [t["id"] for t in SAMPLE_TENANTS] + [l["id"] for l in SAMPLE_LANDLORDS]
            
            for user_id in test_user_ids:
                # Delete profiles first
                self.supabase.table("tenant_profiles").delete().eq("id", user_id).execute()
                self.supabase.table("landlord_profiles").delete().eq("id", user_id).execute()
                
                # Delete user
                self.supabase.table("users").delete().eq("id", user_id).execute()
            
            print(f"   🗑️  Deleted {len(test_user_ids)} test users and profiles")
            
            # Clean sample properties
            property_ids = [p["id"] for p in SAMPLE_PROPERTIES]
            for prop_id in property_ids:
                self.supabase.table("properties").delete().eq("id", prop_id).execute()
            
            print(f"   🗑️  Deleted {len(property_ids)} test properties")
            
            print("✅ Cleanup complete!")
            
        except Exception as e:
            print(f"❌ Cleanup failed: {e}")
            raise
    
    async def verify_setup(self):
        """Verify that demo data is properly set up."""
        print("🔍 Verifying PropFlow demo setup...")
        
        errors = []
        
        # Check tenants
        for tenant_data in SAMPLE_TENANTS:
            user = self.supabase.table("users").select("*").eq("id", tenant_data["id"]).execute()
            if not user.data:
                errors.append(f"Missing tenant user: {tenant_data['full_name']}")
                continue
            
            profile = self.supabase.table("tenant_profiles").select("*").eq("id", tenant_data["id"]).execute()
            if not profile.data:
                errors.append(f"Missing tenant profile: {tenant_data['full_name']}")
        
        print(f"   👥 Tenants: {len(SAMPLE_TENANTS) - len([e for e in errors if 'tenant' in e])}/{len(SAMPLE_TENANTS)} OK")
        
        # Check landlords
        for landlord_data in SAMPLE_LANDLORDS:
            user = self.supabase.table("users").select("*").eq("id", landlord_data["id"]).execute()
            if not user.data:
                errors.append(f"Missing landlord user: {landlord_data['full_name']}")
                continue
                
            profile = self.supabase.table("landlord_profiles").select("*").eq("id", landlord_data["id"]).execute()
            if not profile.data:
                errors.append(f"Missing landlord profile: {landlord_data['full_name']}")
        
        print(f"   🏠 Landlords: {len(SAMPLE_LANDLORDS) - len([e for e in errors if 'landlord' in e])}/{len(SAMPLE_LANDLORDS)} OK")
        
        # Check properties
        for property_data in SAMPLE_PROPERTIES:
            prop = self.supabase.table("properties").select("*").eq("id", property_data["id"]).execute()
            if not prop.data:
                errors.append(f"Missing property: {property_data['title']}")
        
        print(f"   🏢 Properties: {len(SAMPLE_PROPERTIES) - len([e for e in errors if 'property' in e])}/{len(SAMPLE_PROPERTIES)} OK")
        
        # Check critical tables exist
        try:
            self.supabase.table("applications").select("id").limit(1).execute()
            print("   📝 Applications table: OK")
        except Exception as e:
            errors.append(f"Applications table issue: {e}")
        
        try:
            self.supabase.table("agreements").select("id").limit(1).execute()
            print("   📋 Agreements table: OK")
        except Exception as e:
            errors.append(f"Agreements table issue: {e}")
        
        if errors:
            print(f"\n❌ Verification found {len(errors)} issues:")
            for error in errors:
                print(f"   • {error}")
            return False
        else:
            print("\n✅ All verification checks passed!")
            return True


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="PropFlow Demo Setup")
    parser.add_argument("--clean", action="store_true", help="Clean existing demo data")
    parser.add_argument("--verify", action="store_true", help="Verify demo setup")
    parser.add_argument("--force", action="store_true", help="Force operation without confirmation")
    
    args = parser.parse_args()
    
    setup = PropFlowDemoSetup()
    
    try:
        if args.clean:
            if not args.force:
                response = input("⚠️  This will delete all PropFlow demo data. Continue? (y/N): ")
                if response.lower() != 'y':
                    print("Operation cancelled.")
                    return 0
            
            await setup.clean_propflow_data()
            
        elif args.verify:
            success = await setup.verify_setup()
            return 0 if success else 1
            
        else:
            # Default: setup demo data
            await setup.setup_sample_data()
            
            # Verify after setup
            success = await setup.verify_setup()
            if success:
                print("\n🎉 PropFlow demo environment ready!")
                print("   • Run: python scripts/quick_propflow_demo.py")
                print("   • Or: python -m app.propflow.tests.eval_agent --mock")
                return 0
            else:
                print("\n❌ Demo setup completed but verification failed")
                return 1
                
    except Exception as e:
        print(f"❌ Operation failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)