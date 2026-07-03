-- ============================================
-- Create Admin User for Nulo Africa
-- ============================================
-- Run these commands in Supabase SQL Editor
-- Replace the UUID with your actual user ID from auth.users

-- Step 1: First, create a user through the frontend signup
-- Then get their ID from auth.users table:
-- SELECT id, email FROM auth.users WHERE email = 'your-admin-email@example.com';

-- Step 2: Update the user to be admin (replace with actual UUID)
UPDATE public.users 
SET 
    user_type = 'admin',
    verification_status = 'approved',
    trust_score = 100,
    updated_at = NOW()
WHERE id = 'YOUR_USER_UUID_HERE';

-- Step 3: Verify admin user creation
SELECT id, email, full_name, user_type, verification_status, trust_score 
FROM public.users 
WHERE user_type = 'admin';

-- Alternative: Create admin user directly (if you have auth.users UUID)
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
    'YOUR_AUTH_USER_UUID_HERE',  -- Get this from auth.users table
    'admin@nuloafrica.com',
    'NuloAfrica Admin',
    'admin',
    'approved',
    100,
    NOW(),
    NOW()
);
