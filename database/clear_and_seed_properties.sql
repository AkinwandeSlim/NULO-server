-- ============================================
-- Clear and Seed Properties - Fresh Start
-- ============================================
-- This script will:
-- 1. Delete all existing properties
-- 2. Get actual landlord users from your database
-- 3. Insert real properties with actual landlord IDs

-- ============================================
-- STEP 1: Clear Existing Properties
-- ============================================
-- WARNING: This will delete ALL properties and related data!

-- First, delete related data (foreign key constraints)
DELETE FROM favorites;
DELETE FROM viewing_requests;
DELETE FROM messages;
DELETE FROM conversations;

-- Then delete properties
DELETE FROM properties;

-- Verify all deleted
SELECT COUNT(*) as remaining_properties FROM properties;
-- Should show 0

-- ============================================
-- STEP 2: Get Actual Landlord Users
-- ============================================
-- Run this to see your actual landlords:
SELECT 
  id,
  email,
  full_name,
  phone_number,
  created_at
FROM users 
WHERE user_type = 'landlord'
ORDER BY created_at DESC;

-- Copy the landlord IDs you want to use for properties below

-- ============================================
-- STEP 3: Insert Properties with Real Landlords
-- ============================================
-- Replace 'LANDLORD_UUID_1', 'LANDLORD_UUID_2', etc. with actual UUIDs from Step 2

-- Property 1: Luxury Penthouse Victoria Island
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
  longitude
) VALUES (
  '00000000-0000-0000-0000-000000000001'::uuid,
  'LANDLORD_UUID_1'::uuid, -- ⚠️ Replace with actual landlord UUID
  'Luxury Penthouse Victoria Island',
  'This stunning luxury penthouse offers the perfect blend of elegance and modern living in the heart of Victoria Island, Lagos. Featuring contemporary architecture with floor-to-ceiling windows, this property offers breathtaking ocean views and maximizes natural light throughout.',
  'Victoria Island, Lagos, Nigeria',
  'Adeola Odeku Street',
  'Lagos',
  'Lagos State',
  'Nigeria',
  2800000,
  'penthouse',
  4,
  4,
  3500,
  'vacant',
  true,
  2021,
  true,
  2,
  true,
  false,
  5600000,
  '12 months',
  CURRENT_DATE,
  ARRAY['/luxury-apartment-lagos.jpg', '/modern-villa-living-room.jpg', '/modern-villa-nairobi.jpg'],
  ARRAY['WiFi', 'Parking', 'Gym', 'Pool', 'Security', 'Air Conditioning', 'Smart TV', 'Balcony', 'Ocean View', 'Concierge', '24/7 Power', 'Elevator'],
  ARRAY['No smoking', 'No pets allowed', 'No parties or events', 'Quiet hours: 10 PM - 7 AM'],
  'Victoria Island is Lagos'' premier business and residential district, known for its upscale lifestyle, international restaurants, and proximity to the Atlantic Ocean.',
  6.4281,
  3.4219
);

-- Property 2: Modern 3BR Apartment Lekki
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
) VALUES (
  'LANDLORD_UUID_2'::uuid, -- ⚠️ Replace with actual landlord UUID (can be same or different)
  'Modern 3BR Apartment Lekki Phase 1',
  'Beautiful modern apartment in the heart of Lekki Phase 1 with contemporary finishes, spacious rooms, and excellent natural lighting. Perfect for families or professionals.',
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
  ARRAY['WiFi', 'Parking', 'Security', 'Generator', 'Air Conditioning', 'Fitted Kitchen'],
  6.4474,
  3.4700
);

-- Property 3: Spacious 2BR Flat Ikeja
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
) VALUES (
  'LANDLORD_UUID_3'::uuid, -- ⚠️ Replace with actual landlord UUID
  'Spacious 2BR Flat Ikeja GRA',
  'Affordable and spacious flat in Ikeja GRA with serene environment. Great for young professionals and small families. Close to shopping centers and major roads.',
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
  ARRAY['WiFi', 'Parking', 'Security', 'Prepaid Meter'],
  6.5964,
  3.3515
);

-- Property 4: Executive 4BR Duplex Ikoyi
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
) VALUES (
  'LANDLORD_UUID_1'::uuid, -- Can reuse landlords
  'Executive 4BR Duplex Ikoyi',
  'Luxurious 4-bedroom duplex in the prestigious Ikoyi neighborhood. Features modern amenities, spacious compound, and 24/7 security. Perfect for executives and diplomats.',
  'Ikoyi, Lagos, Nigeria',
  'Banana Island Road',
  'Lagos',
  'Lagos State',
  'Nigeria',
  3500000,
  'house',
  4,
  5,
  4000,
  'vacant',
  true,
  true,
  3,
  true,
  false,
  7000000,
  '12 months',
  CURRENT_DATE,
  ARRAY['/contemporary-townhouse-johannesburg.jpg'],
  ARRAY['WiFi', 'Parking', 'Gym', 'Pool', 'Security', 'Air Conditioning', 'Smart Home', 'Garden', 'BQ', 'Generator'],
  6.4541,
  3.4316
);

-- Property 5: Cozy Studio Yaba
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
) VALUES (
  'LANDLORD_UUID_2'::uuid,
  'Cozy Studio Apartment Yaba',
  'Affordable studio apartment in vibrant Yaba. Perfect for students and young professionals. Close to universities, tech hubs, and entertainment spots.',
  'Yaba, Lagos, Nigeria',
  'Herbert Macaulay Way',
  'Lagos',
  'Lagos State',
  'Nigeria',
  450000,
  'studio',
  1,
  1,
  600,
  'vacant',
  false,
  true,
  0,
  true,
  false,
  900000,
  '12 months',
  CURRENT_DATE,
  ARRAY['/luxury-apartment-lagos.jpg'],
  ARRAY['WiFi', 'Security', 'Prepaid Meter', 'Water Supply'],
  6.5074,
  3.3719
);

-- ============================================
-- STEP 4: Verify Properties Created
-- ============================================
SELECT 
  p.id,
  p.title,
  p.price,
  p.status,
  p.beds,
  p.baths,
  u.full_name as landlord_name,
  u.email as landlord_email
FROM properties p
JOIN users u ON p.landlord_id = u.id
ORDER BY p.created_at DESC;

-- ============================================
-- INSTRUCTIONS:
-- ============================================
-- 1. Run STEP 2 to see your actual landlords
-- 2. Copy their UUIDs
-- 3. Replace LANDLORD_UUID_1, LANDLORD_UUID_2, LANDLORD_UUID_3 in STEP 3
-- 4. Run STEP 1 (delete) then STEP 3 (insert)
-- 5. Run STEP 4 to verify
-- ============================================
