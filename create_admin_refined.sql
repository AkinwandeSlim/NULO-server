-- ============================================
-- Refined Admin User Creation for Nulo Africa
-- ============================================
-- This script matches your exact database structure
-- Run these commands in Supabase SQL Editor

-- Step 1: Check if admin user already exists
SELECT id, email, user_type, verification_status 
FROM users 
WHERE email = 'nuloafrica26@outlook.com';

-- Step 2: Create admin user in auth.users table
-- Note: You need to create the auth user first via frontend signup
-- Then get the UUID from auth.users table
SELECT id, email, created_at FROM auth.users WHERE email = 'nuloafrica26@outlook.com';

-- Step 3: Insert admin user into users table (replace UUID with actual auth user ID)
INSERT INTO users (
    id,
    email,
    phone_number,
    password_hash,
    full_name,
    avatar_url,
    trust_score,
    verification_status,
    user_type,
    last_login_at,
    created_at,
    updated_at,
    phone_verified,
    location,
    onboarding_completed
) VALUES (
    'YOUR_AUTH_USER_UUID_HERE',  -- Replace with actual UUID from auth.users
    'nuloafrica26@outlook.com',
    '+2348000000000',  -- Optional phone number
    '',  -- Password hash (handled by auth.users)
    'NuloAfrica Admin',
    '',  -- Avatar URL (optional)
    100,
    'approved',
    'admin',
    NOW(),
    NOW(),
    NOW(),
    true,
    'Lagos, Nigeria',
    true
) ON CONFLICT (id) DO UPDATE SET
    user_type = 'admin',
    verification_status = 'approved',
    trust_score = 100,
    updated_at = NOW();

-- Step 4: Create admin profile in admins table
INSERT INTO admins (
    id,
    role_level,
    permissions,
    last_action_at,
    created_at
) VALUES (
    'YOUR_AUTH_USER_UUID_HERE',  -- Same UUID as users table
    1,  -- Super admin level
    '{"all": true, "tenant_verification": true, "landlord_verification": true, "property_verification": true}',  -- Full permissions
    NOW(),
    NOW()
) ON CONFLICT (id) DO UPDATE SET
    role_level = 1,
    permissions = '{"all": true, "tenant_verification": true, "landlord_verification": true, "property_verification": true}',
    last_action_at = NOW();

-- Step 5: Verify admin user creation
SELECT 
    u.id,
    u.email,
    u.full_name,
    u.user_type,
    u.verification_status,
    u.trust_score,
    a.role_level,
    a.permissions,
    u.created_at
FROM users u
LEFT JOIN admins a ON u.id = a.id
WHERE u.user_type = 'admin';

-- Step 6: Alternative - Create admin user directly (if you have auth user UUID)
-- First, get your auth user UUID by signing up via frontend, then run:
-- UPDATE users SET user_type = 'admin', verification_status = 'approved', trust_score = 100 WHERE id = 'YOUR_UUID';

-- Step 7: Check all existing users to see who can be converted to admin
SELECT 
    id,
    email,
    full_name,
    user_type,
    verification_status,
    trust_score,
    created_at
FROM users 
ORDER BY created_at DESC 
LIMIT 10;

-- Step 8: Convert existing user to admin (uncomment and update UUID)
-- UPDATE users 
-- SET 
--     user_type = 'admin',
--     verification_status = 'approved',
--     trust_score = 100,
--     updated_at = NOW()
-- WHERE id = 'EXISTING_USER_UUID_HERE';

-- Then create admin profile:
-- INSERT INTO admins (id, role_level, permissions, created_at)
-- VALUES (
--     'EXISTING_USER_UUID_HERE',
--     1,
--     '{"all": true}',
--     NOW()
-- ) ON CONFLICT (id) DO UPDATE SET
--     role_level = 1,
--     permissions = '{"all": true}';
