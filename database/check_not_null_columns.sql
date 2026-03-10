-- Check which columns are NOT NULL in properties table
SELECT 
  column_name,
  data_type,
  is_nullable,
  column_default
FROM information_schema.columns 
WHERE table_name = 'properties'
AND is_nullable = 'NO'
ORDER BY ordinal_position;
