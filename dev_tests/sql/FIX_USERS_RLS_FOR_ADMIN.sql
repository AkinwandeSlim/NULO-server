-- ============================================================================
-- FIX: Row-Level Security for USERS Table - Allow Admin Access
-- ============================================================================
-- Problem: Admin users cannot read user profiles due to RLS blocking
-- Solution: Add admin-level policy to allow system-wide user access

-- Step 1: Drop old confusing policies (optional, comment out if you want to keep them)
-- DROP POLICY "Users can view own profile" ON users;
-- DROP POLICY "Public profiles viewable" ON users;

-- Step 2: Add admin access policy (THIS IS THE FIX)
CREATE POLICY "Admins can view all users" ON users
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM admins WHERE admins.id = auth.uid())
  );

-- Step 3: Admins can update any user (optional, for future admin capabilities)
CREATE POLICY "Admins can update users" ON users
  FOR UPDATE USING (
    EXISTS (SELECT 1 FROM admins WHERE admins.id = auth.uid())
  );

-- Step 4: Make sure regular users still work
-- Users can view own profile (already exists, leave as is)
-- Users can see public profiles for landlord info (already exists, leave as is)

-- Verification query - Run this to check if the policy is working:
-- SELECT * FROM users WHERE id = '19cd3930-5e0e-4471-bfea-2dd6611a984e';
-- (Run as the admin user, should return the admin's own record)
