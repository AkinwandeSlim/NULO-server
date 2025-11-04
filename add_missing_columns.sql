-- ============================================
-- Add Missing Columns to Properties Table
-- ============================================
-- Run this in Supabase SQL Editor to add columns needed for mock data

-- Add missing columns
ALTER TABLE properties 
ADD COLUMN IF NOT EXISTS address TEXT,
ADD COLUMN IF NOT EXISTS state TEXT,
ADD COLUMN IF NOT EXISTS full_address TEXT,
ADD COLUMN IF NOT EXISTS year_built_display TEXT,
ADD COLUMN IF NOT EXISTS rules TEXT[],
ADD COLUMN IF NOT EXISTS nearby_places JSONB,
ADD COLUMN IF NOT EXISTS virtual_tour_url TEXT,
ADD COLUMN IF NOT EXISTS video_tour_url TEXT;

-- Add indexes for better performance
CREATE INDEX IF NOT EXISTS idx_properties_city ON properties(city);
CREATE INDEX IF NOT EXISTS idx_properties_state ON properties(state);
CREATE INDEX IF NOT EXISTS idx_properties_status ON properties(status);
CREATE INDEX IF NOT EXISTS idx_properties_price ON properties(price);
CREATE INDEX IF NOT EXISTS idx_properties_featured ON properties(featured);

-- Verify columns were added
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'properties'
AND column_name IN ('address', 'state', 'full_address', 'rules')
ORDER BY column_name;

-- ============================================
-- SUCCESS! Columns added.
-- ============================================
