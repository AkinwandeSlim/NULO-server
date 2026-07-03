-- ============================================
-- Quick Test Insert with Landlord UUID
-- ============================================
-- Run this to find valid status and test insert

-- STEP 1: Find valid status values
SELECT
  pg_get_constraintdef(con.oid) as valid_status_values
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
WHERE rel.relname = 'properties'
AND con.conname = 'properties_status_check';

-- STEP 2: Check if landlord exists
SELECT id, email, full_name, user_type 
FROM users 
WHERE id = 'ea80f3bf-696e-4cea-8779-6ae2809b3de5'::uuid;

-- STEP 3: Quick test insert (minimal data with required fields)
-- Try different status values until one works
INSERT INTO properties (
  id,
  landlord_id,
  title,
  location,
  price,
  property_type,
  beds,
  baths,
  sqft,
  status
) VALUES (
  gen_random_uuid(),
  'ea80f3bf-696e-4cea-8779-6ae2809b3de5'::uuid,
  'Test Property',
  'Lagos, Nigeria',  -- location is required (NOT NULL)
  1000000,
  'apartment',
  2,
  2,
  1000,
  'vacant'  -- Valid values: 'vacant', 'occupied', 'maintenance'
);

-- STEP 4: If test worked, check it
SELECT id, title, status FROM properties WHERE title = 'Test Property';

-- STEP 5: Clean up test
DELETE FROM properties WHERE title = 'Test Property';

-- ============================================
-- Once you find the valid status value:
-- 1. Update seed_test_data.sql with that status
-- 2. Run the full seed_test_data.sql script
-- ============================================
