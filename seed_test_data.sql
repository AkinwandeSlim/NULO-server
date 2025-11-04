-- ============================================
-- Seed Test Data for Nulo Africa
-- ============================================
-- Run this in Supabase SQL Editor to create test data

-- ============================================
-- 1. Create Test Landlord User
-- ============================================
-- Note: Replace with actual user ID from your Supabase Auth users
-- You can get this by signing up a landlord account first

-- Example: If you have a landlord user with email landlord@test.com
-- Get their ID from auth.users table:
-- SELECT id, email FROM auth.users WHERE email = 'landlord@test.com';

-- For this example, we'll use a placeholder
-- REPLACE 'your-landlord-user-id-here' with actual UUID from auth.users

-- ============================================
-- 2. Create Test Property
-- ============================================
-- First, check what columns exist in your properties table
-- Run this to see the actual structure:
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'properties';

-- Complete INSERT matching your table structure
INSERT INTO properties (
  id,
  landlord_id,
  title,
  description,
  location,
  address,
  city,
  state,
  country,
  price,
  property_type,
  beds,
  baths,
  sqft,
  status,
  featured,
  year_built,
  furnished,
  parking_spaces,
  utilities_included,
  pet_friendly,
  security_deposit,
  lease_duration,
  available_from,
  images,
  amenities,
  rules,
  neighborhood,
  latitude,
  longitude,
  view_count,
  application_count,
  average_rating,
  review_count
) VALUES (
  '00000000-0000-0000-0000-000000000001'::uuid, -- Fixed UUID for property ID 1
  'ea80f3bf-696e-4cea-8779-6ae2809b3de5'::uuid, -- ⚠️ REPLACE THIS with real landlord user ID
  'Luxury Penthouse Victoria Island',
  'This stunning luxury penthouse offers the perfect blend of elegance and modern living in the heart of Victoria Island, Lagos. Featuring contemporary architecture with floor-to-ceiling windows, this property offers breathtaking ocean views and maximizes natural light throughout. The open-plan living area seamlessly connects to a spacious balcony, ideal for entertaining guests while enjoying panoramic city views.',
  'Victoria Island, Lagos, Nigeria',
  'Adeola Odeku Street',
  'Lagos',
  'Lagos State',
  'Nigeria',
  2800000, -- ₦2,800,000/month
  'penthouse',
  4, -- bedrooms
  4, -- bathrooms
  3500, -- square feet
  'vacant', -- status (VALID VALUES: 'vacant', 'occupied', 'maintenance')
  true, -- featured
  2021, -- year_built
  true, -- furnished
  2, -- parking_spaces
  true, -- utilities_included
  false, -- pet_friendly
  5600000, -- security_deposit (2 months)
  '12 months',
  CURRENT_DATE,
  ARRAY[
    '/luxury-apartment-lagos.jpg',
    '/modern-villa-living-room.jpg',
    '/modern-villa-nairobi.jpg',
    '/modern-villa-bathroom.jpg',
    '/modern-villa-pool.jpg',
    '/contemporary-townhouse-johannesburg.jpg'
  ],
  ARRAY[
    'WiFi',
    'Parking',
    'Gym',
    'Pool',
    'Security',
    'Air Conditioning',
    'Smart TV',
    'Balcony',
    'Ocean View',
    'Concierge',
    '24/7 Power',
    'Elevator'
  ],
  ARRAY[
    'No smoking',
    'No pets allowed',
    'No parties or events',
    'Quiet hours: 10 PM - 7 AM'
  ],
  'Victoria Island is Lagos'' premier business and residential district, known for its upscale lifestyle, international restaurants, and proximity to the Atlantic Ocean.',
  6.4281, -- latitude
  3.4219, -- longitude
  0, -- view_count
  0, -- application_count
  4.9, -- average_rating
  32 -- review_count
)
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  price = EXCLUDED.price,
  beds = EXCLUDED.beds,
  baths = EXCLUDED.baths,
  sqft = EXCLUDED.sqft,
  amenities = EXCLUDED.amenities;

-- ============================================
-- 3. Verify Test Data
-- ============================================
-- Check if property was created
SELECT 
  id,
  title,
  price,
  landlord_id,
  status
FROM properties 
WHERE id = '00000000-0000-0000-0000-000000000001'::uuid;

-- ============================================
-- 4. Alternative: Get Existing Property ID
-- ============================================
-- If you already have properties, you can use an existing one:
-- SELECT id, title, landlord_id FROM properties LIMIT 1;

-- Then update your frontend mock data to use that ID

-- ============================================
-- 5. Create Additional Test Properties (Optional)
-- ============================================
INSERT INTO properties (
  landlord_id,
  title,
  description,
  location,
  address,
  city,
  state,
  country,
  price,
  property_type,
  beds,
  baths,
  sqft,
  status,
  featured,
  furnished,
  parking_spaces,
  utilities_included,
  pet_friendly,
  security_deposit,
  lease_duration,
  available_from,
  images,
  amenities,
  latitude,
  longitude
) VALUES 
(
  'ea80f3bf-696e-4cea-8779-6ae2809b3de5'::uuid,
  'Modern 3BR Apartment Lekki',
  'Beautiful modern apartment in the heart of Lekki Phase 1 with contemporary finishes',
  'Lekki Phase 1, Lagos, Nigeria',
  'Admiralty Way',
  'Lagos',
  'Lagos State',
  'Nigeria',
  1500000,
  'apartment',
  3,
  2,
  2000,
  'vacant',
  false,
  true,
  1,
  true,
  true,
  3000000,
  '12 months',
  CURRENT_DATE,
  ARRAY['/luxury-apartment-lagos.jpg'],
  ARRAY['WiFi', 'Parking', 'Security', 'Generator', 'Air Conditioning'],
  6.4474,
  3.4700
),
(
  'your-landlord-user-id-here'::uuid,
  'Spacious 2BR Flat Ikeja',
  'Affordable and spacious flat in Ikeja GRA with serene environment',
  'Ikeja GRA, Lagos, Nigeria',
  'Opebi Road',
  'Lagos',
  'Lagos State',
  'Nigeria',
  800000,
  'apartment',
  2,
  2,
  1500,
  'vacant',
  false,
  false,
  1,
  false,
  false,
  1600000,
  '12 months',
  CURRENT_DATE,
  ARRAY['/modern-villa-living-room.jpg'],
  ARRAY['WiFi', 'Parking', 'Security'],
  6.5964,
  3.3515
)
ON CONFLICT DO NOTHING;

-- ============================================
-- INSTRUCTIONS:
-- ============================================
-- 1. First, create a landlord account via your app's signup
-- 2. Get the landlord's user ID from Supabase Auth dashboard
-- 3. Replace 'your-landlord-user-id-here' with that UUID
-- 4. Run this script in Supabase SQL Editor
-- 5. Verify the property was created
-- 6. Update your frontend to use the property ID: '00000000-0000-0000-0000-000000000001'
-- ============================================
