-- ============================================
-- Complete Admin User Creation for Nulo Africa
-- ============================================
-- Run these commands in Supabase SQL Editor in order

-- Step 1: Check if users table exists and has correct structure
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'users' 
AND table_schema = 'public'
ORDER BY ordinal_position;

-- Step 2: Create admin user in auth.users (you need to do this via frontend first)
-- After signing up a user, get their ID from this query:
-- SELECT id, email FROM auth.users WHERE email = 'your-admin-email@example.com';

-- Step 3: For testing, let's create a mock admin user directly
-- Replace 'your-admin-email@example.com' with actual email you'll use
DO $$
DECLARE
    admin_user_id UUID := gen_random_uuid();
    admin_email TEXT := 'nuloafrica26@outlook.com';
    admin_full_name TEXT := 'NuloAfrica Admin';
BEGIN
    -- Insert into auth.users (this might fail due to constraints, but let's try)
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
        admin_user_id,
        admin_email,
        '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj6ukx.LrUpm', -- hashed 'Admin123!'
        NOW(),
        NOW(),
        NOW(),
        NOW(),
        '{"full_name": "' || admin_full_name || '", "role": "admin"}',
        false
    ) ON CONFLICT (id) DO NOTHING;
    
    -- Insert into public.users
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
        admin_user_id,
        admin_email,
        admin_full_name,
        'admin',
        'approved',
        100,
        NOW(),
        NOW()
    ) ON CONFLICT (id) DO UPDATE SET
        user_type = 'admin',
        verification_status = 'approved',
        trust_score = 100,
        updated_at = NOW();
    
    RAISE NOTICE 'Admin user created with ID: %', admin_user_id;
END $$;

-- Step 4: Verify admin user creation
SELECT 
    u.id,
    u.email,
    u.full_name,
    u.user_type,
    u.verification_status,
    u.trust_score,
    au.email_confirmed_at
FROM public.users u
LEFT JOIN auth.users au ON u.id = au.id
WHERE u.user_type = 'admin';

-- Step 5: Check if there are any existing users you can convert to admin
SELECT 
    id,
    email,
    full_name,
    user_type,
    verification_status,
    created_at
FROM public.users 
ORDER BY created_at DESC 
LIMIT 10;

-- Step 6: If you have existing users, convert one to admin (uncomment and update ID)
-- UPDATE public.users 
-- SET 
--     user_type = 'admin',
--     verification_status = 'approved',
--     trust_score = 100,
--     updated_at = NOW()
-- WHERE id = 'your-existing-user-id-here';
