-- Check valid property_type values
SELECT
  pg_get_constraintdef(con.oid) as constraint_definition
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
WHERE rel.relname = 'properties'
AND con.conname = 'properties_property_type_check';

-- Also check existing property types
SELECT DISTINCT property_type 
FROM properties 
WHERE property_type IS NOT NULL
LIMIT 10;
        