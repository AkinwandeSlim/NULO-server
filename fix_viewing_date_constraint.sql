-- QUICK FIX: Remove the future_date constraint immediately
-- Run this in Supabase SQL Editor to fix the issue immediately

-- Step 1: Remove the restrictive constraint
ALTER TABLE viewing_requests DROP CONSTRAINT IF EXISTS future_date;

-- Step 2: (Optional) Add a more reasonable constraint
-- This allows requests up to 30 days in the past
ALTER TABLE viewing_requests 
ADD CONSTRAINT reasonable_date CHECK (
  preferred_date >= CURRENT_DATE - INTERVAL '30 days'
);

-- Step 3: Test the constraint
-- This should work now:
UPDATE viewing_requests 
SET status = 'confirmed', 
    landlord_notes = 'Test confirmation after constraint fix'
WHERE id = '2b1a17c5-fb56-4237-8051-b0dc24a074ec';

-- Verify the update
SELECT id, preferred_date, status, landlord_notes 
FROM viewing_requests 
WHERE id = '2b1a17c5-fb56-4237-8051-b0dc24a074ec';

-- Rollback the test if needed
-- UPDATE viewing_requests 
-- SET status = 'pending', 
--     landlord_notes = NULL
-- WHERE id = '2b1a17c5-fb56-4237-8051-b0dc24a074ec';
