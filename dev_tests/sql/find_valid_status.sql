-- ============================================
-- Find Valid Status Values
-- ============================================

-- Method 1: Check the constraint definition
SELECT
  con.conname as constraint_name,
  pg_get_constraintdef(con.oid) as constraint_definition
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
WHERE rel.relname = 'properties'
AND con.conname = 'properties_status_check';

-- Method 2: Check if there are any existing properties to see what status values work
SELECT DISTINCT status 
FROM properties 
WHERE status IS NOT NULL
LIMIT 10;

-- Method 3: Try to see the table definition
SELECT 
  column_name,
  data_type,
  column_default,
  is_nullable
FROM information_schema.columns 
WHERE table_name = 'properties' 
AND column_name = 'status';
