-- ============================================
-- Check Properties Table Structure
-- ============================================
-- Run this in Supabase SQL Editor to see your table structure

-- 1. Check if properties table exists
SELECT EXISTS (
  SELECT FROM information_schema.tables 
  WHERE table_schema = 'public' 
  AND table_name = 'properties'
) as table_exists;

-- 2. List all columns in properties table
SELECT 
  column_name,
  data_type,
  is_nullable,
  column_default
FROM information_schema.columns 
WHERE table_name = 'properties'
ORDER BY ordinal_position;

-- 3. Check constraints
SELECT
  con.conname as constraint_name,
  con.contype as constraint_type,
  CASE con.contype
    WHEN 'p' THEN 'Primary Key'
    WHEN 'f' THEN 'Foreign Key'
    WHEN 'u' THEN 'Unique'
    WHEN 'c' THEN 'Check'
    ELSE con.contype::text
  END as constraint_description
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
WHERE rel.relname = 'properties';

-- 4. Sample data (if any exists)
SELECT 
  id,
  landlord_id,
  title,
  price,
  status,
  created_at
FROM properties 
LIMIT 5;

-- ============================================
-- Expected Columns (Common Structure)
-- ============================================
-- id (uuid)
-- landlord_id (uuid)
-- title (text/varchar)
-- description (text)
-- location (text/varchar)
-- price (numeric/integer)
-- property_type (text/varchar)
-- bedrooms (integer)
-- bathrooms (integer)
-- square_feet (integer/numeric)
-- status (text/varchar)
-- images (text[] array)
-- amenities (text[] array)
-- created_at (timestamp)
-- updated_at (timestamp)
-- ============================================
