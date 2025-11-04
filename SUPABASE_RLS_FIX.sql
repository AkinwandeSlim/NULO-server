-- ============================================
-- FIX: Row-Level Security for Favorites Table
-- ============================================

-- Option 1: Disable RLS (Quick Fix for Development)
ALTER TABLE favorites DISABLE ROW LEVEL SECURITY;

-- Option 2: Enable RLS with Proper Policies (Production Ready)
-- Uncomment these if you want to keep RLS enabled:

/*
ALTER TABLE favorites ENABLE ROW LEVEL SECURITY;

-- Policy: Users can view their own favorites
CREATE POLICY "Users can view own favorites"
ON favorites FOR SELECT
USING (auth.uid()::text = tenant_id);

-- Policy: Users can insert their own favorites
CREATE POLICY "Users can insert own favorites"
ON favorites FOR INSERT
WITH CHECK (auth.uid()::text = tenant_id);

-- Policy: Users can delete their own favorites
CREATE POLICY "Users can delete own favorites"
ON favorites FOR DELETE
USING (auth.uid()::text = tenant_id);
*/

-- ============================================
-- FIX: Row-Level Security for Viewing Requests Table
-- ============================================

-- Option 1: Disable RLS (Quick Fix for Development)
ALTER TABLE viewing_requests DISABLE ROW LEVEL SECURITY;

-- Option 2: Enable RLS with Proper Policies (Production Ready)
-- Uncomment these if you want to keep RLS enabled:

/*
ALTER TABLE viewing_requests ENABLE ROW LEVEL SECURITY;

-- Policy: Tenants can view their own requests
CREATE POLICY "Tenants can view own viewing requests"
ON viewing_requests FOR SELECT
USING (auth.uid()::text = tenant_id);

-- Policy: Landlords can view requests for their properties
CREATE POLICY "Landlords can view requests for their properties"
ON viewing_requests FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM properties
    WHERE properties.id = viewing_requests.property_id
    AND properties.landlord_id = auth.uid()::text
  )
);

-- Policy: Tenants can insert their own requests
CREATE POLICY "Tenants can insert own viewing requests"
ON viewing_requests FOR INSERT
WITH CHECK (auth.uid()::text = tenant_id);

-- Policy: Tenants can update their own requests
CREATE POLICY "Tenants can update own viewing requests"
ON viewing_requests FOR UPDATE
USING (auth.uid()::text = tenant_id);

-- Policy: Landlords can update requests for their properties
CREATE POLICY "Landlords can update requests for their properties"
ON viewing_requests FOR UPDATE
USING (
  EXISTS (
    SELECT 1 FROM properties
    WHERE properties.id = viewing_requests.property_id
    AND properties.landlord_id = auth.uid()::text
  )
);
*/
