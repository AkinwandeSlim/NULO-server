"""
Admin Setup Helper for Nulo Africa
This script helps create an admin user and provides login credentials
Updated to match the exact database structure
"""
import os
import sys
from supabase import create_client
import uuid
from datetime import datetime

# Configuration - UPDATE THESE VALUES
SUPABASE_URL = "https://tqmjcygeykmbdjcfdbga.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRxbWpjeWd5a21iZGpjZmRiZ2EiLCJyb2xlIjoiYW5vbiIsImlhdCI6MTczNjQwNjY3MSwiZXhwIjoyMDUxOTgyNjcxfQ.5BtU2hW2lFg3Y6k3m3e3d3f3e3d3f3e3d3f3e3d3f3e3d3f3e3d3f3e3d3f3e"

def create_admin_via_signup():
    """Create admin user via Supabase Auth signup"""
    
    supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    
    admin_email = "nuloafrica26@outlook.com"
    admin_password = "Admin123!@#"
    admin_full_name = "NuloAfrica Admin"
    
    try:
        # Step 1: Sign up user via Supabase Auth
        auth_response = supabase.auth.sign_up({
            "email": admin_email,
            "password": admin_password,
            "options": {
                "data": {
                    "full_name": admin_full_name,
                    "user_type": "admin"
                }
            }
        })
        
        if auth_response.user:
            user_id = auth_response.user.id
            print(f"✅ Auth user created: {admin_email}")
            print(f"🆔 User ID: {user_id}")
            
            # Step 2: Create user profile in users table
            try:
                profile_data = {
                    "id": user_id,
                    "email": admin_email,
                    "phone_number": "+2348000000000",
                    "password_hash": "",  # Handled by auth.users
                    "full_name": admin_full_name,
                    "avatar_url": "",
                    "trust_score": 100,
                    "verification_status": "approved",
                    "user_type": "admin",
                    "last_login_at": datetime.now().isoformat(),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "phone_verified": True,
                    "location": "Lagos, Nigeria",
                    "onboarding_completed": True
                }
                
                profile_response = supabase.table("users").insert(profile_data).execute()
                
                if profile_response.data:
                    print(f"✅ User profile created for admin")
                    
                    # Step 3: Create admin profile in admins table
                    admin_data = {
                        "id": user_id,
                        "role_level": 1,
                        "permissions": {
                            "all": True,
                            "tenant_verification": True,
                            "landlord_verification": True,
                            "property_verification": True
                        },
                        "last_action_at": datetime.now().isoformat(),
                        "created_at": datetime.now().isoformat()
                    }
                    
                    admin_response = supabase.table("admins").insert(admin_data).execute()
                    
                    if admin_response.data:
                        print(f"✅ Admin profile created with full permissions")
                    else:
                        print(f"⚠️ Admin profile creation may have failed")
                        
                else:
                    print(f"⚠️ Profile creation may have failed, but auth user exists")
                    
            except Exception as e:
                print(f"⚠️ Profile creation error: {e}")
                print("🔧 You may need to create the profile manually in SQL")
            
            print("\n🎉 Admin user setup complete!")
            print(f"📧 Email: {admin_email}")
            print(f"🔑 Password: {admin_password}")
            print(f"🌐 Login URL: http://localhost:3000/signin")
            print("\n📋 Next Steps:")
            print("1. Go to http://localhost:3000/signin")
            print("2. Login with the credentials above")
            print("3. Navigate to http://localhost:3000/(dashboard)/admin")
            
            return True
        else:
            print(f"❌ Auth signup failed")
            return False
            
    except Exception as e:
        print(f"❌ Error creating admin user: {str(e)}")
        return False

def convert_existing_user_to_admin():
    """Convert an existing user to admin"""
    
    supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    
    print("🔍 Finding existing users...")
    
    try:
        # Get existing users
        users_response = supabase.table("users").select("id, email, full_name, user_type").execute()
        
        if not users_response.data:
            print("❌ No users found in database")
            return False
        
        users = users_response.data
        print("\n📋 Existing Users:")
        for i, user in enumerate(users, 1):
            print(f"{i}. {user['email']} ({user.get('user_type', 'unknown')})")
        
        choice = input(f"\n🔧 Enter user number to convert to admin (1-{len(users)}): ")
        
        try:
            user_index = int(choice) - 1
            if user_index < 0 or user_index >= len(users):
                print("❌ Invalid user number")
                return False
            
            selected_user = users[user_index]
            user_id = selected_user['id']
            user_email = selected_user['email']
            
            # Update user to admin
            update_response = supabase.table("users").update({
                "user_type": "admin",
                "verification_status": "approved",
                "trust_score": 100,
                "updated_at": datetime.now().isoformat()
            }).eq("id", user_id).execute()
            
            if update_response.data:
                # Create admin profile
                admin_data = {
                    "id": user_id,
                    "role_level": 1,
                    "permissions": {
                        "all": True,
                        "tenant_verification": True,
                        "landlord_verification": True,
                        "property_verification": True
                    },
                    "last_action_at": datetime.now().isoformat(),
                    "created_at": datetime.now().isoformat()
                }
                
                admin_response = supabase.table("admins").insert(admin_data).execute()
                
                print(f"✅ User {user_email} converted to admin!")
                print(f"🌐 Login URL: http://localhost:3000/signin")
                print(f"📧 Use their existing password to login")
                print(f"🎯 Then navigate to: http://localhost:3000/(dashboard)/admin")
                return True
            else:
                print(f"❌ Failed to update user")
                return False
                
        except ValueError:
            print("❌ Invalid input")
            return False
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def check_existing_admin():
    """Check if admin user already exists"""
    
    supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    
    try:
        # Check for existing admin users
        admin_response = supabase.table("users").select("*").eq("user_type", "admin").execute()
        
        if admin_response.data:
            print("\n👑 Existing Admin Users:")
            for admin in admin_response.data:
                print(f"📧 {admin['email']} - Status: {admin['verification_status']}")
            return True
        else:
            print("\n❌ No admin users found")
            return False
            
    except Exception as e:
        print(f"❌ Error checking admin users: {str(e)}")
        return False

def main():
    print("🚀 Nulo Africa Admin Setup Helper (Refined)")
    print("=" * 50)
    
    # Check existing admins first
    check_existing_admin()
    
    choice = input("\nChoose option:\n1. Create new admin user (nuloafrica26@outlook.com)\n2. Convert existing user to admin\n3. Check admin users\n4. Exit\n\nEnter choice (1-4): ")
    
    if choice == "1":
        create_admin_via_signup()
    elif choice == "2":
        convert_existing_user_to_admin()
    elif choice == "3":
        check_existing_admin()
    elif choice == "4":
        print("👋 Goodbye!")
    else:
        print("❌ Invalid choice")

if __name__ == "__main__":
    main()
