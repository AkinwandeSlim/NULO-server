"""
Create Admin User Script for Nulo Africa
Run this script to create an admin user in the database
"""
import os
import sys
from supabase import create_client
import uuid
from datetime import datetime

# Supabase configuration - replace with your actual values
SUPABASE_URL = "https://tqmjcygeykmbdjcfdbga.supabase.co"
SUPABASE_KEY = "your-supabase-service-key-here"  # Use service role key for admin operations

def create_admin_user():
    """Create an admin user in the database"""
    
    # Initialize Supabase client
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Admin user details
    admin_email = "admin@nuloafrica.com"
    admin_password = "Admin123!@#"  # Change this in production
    admin_full_name = "NuloAfrica Admin"
    
    try:
        # Step 1: Create user in Supabase Auth
        auth_response = supabase.auth.admin.create_user({
            "email": admin_email,
            "password": admin_password,
            "email_confirm": True,  # Auto-confirm email
            "user_metadata": {
                "full_name": admin_full_name,
                "role": "admin"
            }
        })
        
        if not auth_response.user:
            print("❌ Failed to create admin user in auth")
            return False
            
        user_id = auth_response.user.id
        print(f"✅ Created auth user: {admin_email} with ID: {user_id}")
        
        # Step 2: Create user profile in database
        profile_data = {
            "id": user_id,
            "email": admin_email,
            "full_name": admin_full_name,
            "user_type": "admin",
            "verification_status": "approved",
            "trust_score": 100,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        profile_response = supabase.table("users").insert(profile_data).execute()
        
        if not profile_response.data:
            print("❌ Failed to create user profile in database")
            return False
            
        print(f"✅ Created user profile for admin: {admin_email}")
        
        # Step 3: Create admin profile (if separate table exists)
        admin_profile_data = {
            "user_id": user_id,
            "permissions": ["all"],  # Full permissions
            "created_at": datetime.now().isoformat()
        }
        
        try:
            admin_response = supabase.table("admin_profiles").insert(admin_profile_data).execute()
            print(f"✅ Created admin profile for: {admin_email}")
        except Exception as e:
            print(f"⚠️ Admin profile table may not exist: {e}")
        
        print("\n🎉 Admin user created successfully!")
        print(f"📧 Email: {admin_email}")
        print(f"🔑 Password: {admin_password}")
        print(f"🌐 Login URL: http://localhost:3000/signin")
        print("\n⚠️  IMPORTANT: Change the password after first login!")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating admin user: {str(e)}")
        return False

def create_admin_sql():
    """Generate SQL commands to create admin user"""
    
    admin_user_id = str(uuid.uuid4())
    admin_email = "admin@nuloafrica.com"
    admin_full_name = "NuloAfrica Admin"
    
    sql_commands = f"""
-- ============================================
-- Create Admin User for Nulo Africa
-- ============================================
-- Run these commands in Supabase SQL Editor

-- Step 1: Create user in auth.users table
INSERT INTO auth.users (
    id, 
    email, 
    encrypted_password, 
    email_confirmed_at, 
    created_at, 
    updated_at, 
    last_sign_in_at, 
    raw_user_meta_data,
    is_super_admin
) VALUES (
    '{admin_user_id}',
    '{admin_email}',
    '$2b$12$placeholder_hash',  -- This will be set by Supabase Auth
    NOW(),
    NOW(),
    NOW(),
    NOW(),
    '{{"full_name": "{admin_full_name}", "role": "admin"}}',
    false
);

-- Step 2: Create user profile
INSERT INTO public.users (
    id,
    email,
    full_name,
    user_type,
    verification_status,
    trust_score,
    created_at,
    updated_at
) VALUES (
    '{admin_user_id}',
    '{admin_email}',
    '{admin_full_name}',
    'admin',
    'approved',
    100,
    NOW(),
    NOW()
);

-- Step 3: Verify admin user creation
SELECT id, email, full_name, user_type, verification_status 
FROM public.users 
WHERE user_type = 'admin';
"""
    
    with open("create_admin_user.sql", "w") as f:
        f.write(sql_commands)
    
    print("📄 Created create_admin_user.sql file")
    print("🔧 Run this SQL in Supabase SQL Editor to create admin user")
    print(f"📧 Admin Email: {admin_email}")
    print(f"🆔 Admin ID: {admin_user_id}")

if __name__ == "__main__":
    print("🚀 Nulo Africa Admin User Creation")
    print("=" * 50)
    
    choice = input("\nChoose creation method:\n1. Python Script (requires Supabase service key)\n2. SQL Commands (manual)\nEnter choice (1 or 2): ")
    
    if choice == "1":
        print("\n⚠️  Make sure to update SUPABASE_KEY in the script")
        create_admin_user()
    elif choice == "2":
        create_admin_sql()
    else:
        print("❌ Invalid choice")
