-- Test script: Change a completed request back to "confirmed" status
-- This will help you test the "Confirmed Upcoming" stats card

-- Update the second request (today's date) to "confirmed" status
UPDATE viewing_requests 
SET status = 'confirmed', 
    landlord_notes = 'Test confirmed request for stats card'
WHERE id = '5becd90c-c085-4ccb-a938-a2fac6871b19';

-- Verify the update
SELECT id, preferred_date, status, landlord_notes 
FROM viewing_requests 
WHERE id = '5becd90c-c085-4ccb-a938-a2fac6871b19';

-- Check all your requests
SELECT id, preferred_date, status, landlord_notes 
FROM viewing_requests 
WHERE landlord_id = 'ca83139e-be0d-4184-901c-3f719c1b0de4'
ORDER BY preferred_date;
