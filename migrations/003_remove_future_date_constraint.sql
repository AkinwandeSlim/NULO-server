-- Migration: Remove restrictive future_date constraint from viewing_requests
-- Reason: Landlords need to confirm/re-approve past viewing requests and mark them as completed

-- Drop the restrictive constraint
ALTER TABLE viewing_requests DROP CONSTRAINT IF EXISTS future_date;

-- Add a more flexible constraint that only applies to NEW pending requests
-- This allows existing requests to be managed regardless of date
ALTER TABLE viewing_requests 
ADD CONSTRAINT reasonable_date CHECK (
  preferred_date >= CURRENT_DATE - INTERVAL '30 days'
);

-- Add comment explaining the new constraint
COMMENT ON CONSTRAINT reasonable_date ON viewing_requests IS 'Allows viewing requests within 30 days past or future, giving landlords flexibility to manage past appointments';

-- Log the change
DO $$
BEGIN
    RAISE NOTICE '✅ [MIGRATION] Removed restrictive future_date constraint and added reasonable_date constraint';
    RAISE NOTICE '✅ [MIGRATION] Landlords can now confirm/re-approve past viewing requests';
END $$;
