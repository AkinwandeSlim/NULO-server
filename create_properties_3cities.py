"""
Script to create 25 sample properties for landlord jaydam@gmail.com across 3 cities
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import supabase_admin
from datetime import datetime

# Sample property data with diverse images and details (using correct database field names)
properties_data = [
    # LAGOS PROPERTIES (8 properties)
    {
        "title": "Modern 3-Bedroom Apartment in Lekki Phase 1",
        "description": "Spacious and modern apartment with excellent finishing, 24/7 security, and proximity to shopping centers.",
        "price": 850000,
        "security_deposit": 850000,
        "location": "Lekki Phase 1",
        "address": "23 Admiralty Way, Lekki Phase 1",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 3,
        "baths": 2,
        "sqft": 1200,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking", "Swimming Pool"],
        "images": ["https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Luxury 2-Bedroom Duplex in Victoria Island",
        "description": "Elegant duplex with premium finishes, sea view, and modern amenities.",
        "price": 1200000,
        "security_deposit": 1200000,
        "location": "Victoria Island",
        "address": "45 Ahmadu Bello Way, Victoria Island",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 2,
        "baths": 2,
        "sqft": 950,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Gym"],
        "images": ["https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Cozy 1-Bedroom Studio in Ikoyi",
        "description": "Compact and stylish studio perfect for young professionals.",
        "price": 450000,
        "security_deposit": 450000,
        "location": "Ikoyi",
        "address": "12 Awolowo Road, Ikoyi",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 1,
        "baths": 1,
        "sqft": 600,
        "property_type": "studio",
        "amenities": ["Air Conditioning", "Security", "Gym"],
        "images": ["https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Spacious 4-Bedroom House in Ikeja GRA",
        "description": "Beautiful detached house with garden, perfect for large families.",
        "price": 1500000,
        "security_deposit": 1500000,
        "location": "Ikeja GRA",
        "address": "78 Obafemi Awolowo Way, Ikeja GRA",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 4,
        "baths": 3,
        "sqft": 2000,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Garden"],
        "images": ["https://images.unsplash.com/photo-1580587771525-78b9dba3b914?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Penthouse Suite in Eko Atlantic",
        "description": "Ultra-luxury penthouse with panoramic ocean views and private elevator.",
        "price": 3500000,
        "security_deposit": 3500000,
        "location": "Eko Atlantic",
        "address": "Ocean View Towers, Eko Atlantic",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 5,
        "baths": 4,
        "sqft": 3500,
        "property_type": "penthouse",
        "amenities": ["Air Conditioning", "Security", "Parking", "Swimming Pool"],
        "images": ["https://images.unsplash.com/photo-1586023492125-27b2c045efd7?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Modern 2-Bedroom Flat in Yaba",
        "description": "Contemporary apartment near universities and tech hubs.",
        "price": 380000,
        "security_deposit": 380000,
        "location": "Yaba",
        "address": "45 Herbert Macaulay Way, Yaba",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 2,
        "baths": 1,
        "sqft": 750,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "3-Bedroom Townhouse in Lekki Phase 2",
        "description": "Modern townhouse with private garden and community amenities.",
        "price": 950000,
        "security_deposit": 950000,
        "location": "Lekki Phase 2",
        "address": "15 Freedom Way, Lekki Phase 2",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 3,
        "baths": 2,
        "sqft": 1400,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Garden"],
        "images": ["https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Executive 1-Bedroom in Banana Island",
        "description": "Premium apartment in Nigeria's most exclusive neighborhood.",
        "price": 1800000,
        "security_deposit": 1800000,
        "location": "Banana Island",
        "address": "8 Banana Island Road, Ikoyi",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 1,
        "baths": 1,
        "sqft": 800,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking", "Gym"],
        "images": ["https://images.unsplash.com/photo-1445019980578-5996b9c8272e?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    
    # ABUJA PROPERTIES (8 properties)
    {
        "title": "Modern 3-Bedroom Apartment in Asokoro",
        "description": "Spacious apartment in Abuja's most exclusive district with excellent security and amenities.",
        "price": 1200000,
        "security_deposit": 1200000,
        "location": "Asokoro",
        "address": "15 Aso Drive, Asokoro",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria",
        "beds": 3,
        "baths": 2,
        "sqft": 1300,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking", "Swimming Pool"],
        "images": ["https://images.unsplash.com/photo-1560185007-c5ca9d2c014d?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Luxury 4-Bedroom Duplex in Maitama",
        "description": "Elegant duplex in Abuja's high-brow area with premium finishes and modern amenities.",
        "price": 2500000,
        "security_deposit": 2500000,
        "location": "Maitama",
        "address": "22 Maitama Street, Maitama",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria",
        "beds": 4,
        "baths": 3,
        "sqft": 2200,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Gym"],
        "images": ["https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Cozy 1-Bedroom Studio in Wuse",
        "description": "Modern studio perfect for professionals in Abuja's bustling business district.",
        "price": 350000,
        "security_deposit": 350000,
        "location": "Wuse",
        "address": "45 Wuse Market Road, Wuse",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria",
        "beds": 1,
        "baths": 1,
        "sqft": 550,
        "property_type": "studio",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Spacious 5-Bedroom Villa in Gwarinpa",
        "description": "Beautiful detached house with garden in Abuja's largest residential estate.",
        "price": 1800000,
        "security_deposit": 1800000,
        "location": "Gwarinpa",
        "address": "78 Gwarinpa Estate Road, Gwarinpa",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria",
        "beds": 5,
        "baths": 4,
        "sqft": 2800,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Garden"],
        "images": ["https://images.unsplash.com/photo-1580587771525-78b9dba3b914?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Executive 2-Bedroom Apartment in Jabi",
        "description": "Premium apartment near Jabi Lake with excellent amenities and views.",
        "price": 950000,
        "security_deposit": 950000,
        "location": "Jabi",
        "address": "12 Jabi Lake Road, Jabi",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria",
        "beds": 2,
        "baths": 2,
        "sqft": 1000,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking", "Gym"],
        "images": ["https://images.unsplash.com/photo-1586023492125-27b2c045efd7?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Modern 3-Bedroom Flat in Garki",
        "description": "Contemporary apartment in Abuja's central business district area.",
        "price": 650000,
        "security_deposit": 650000,
        "location": "Garki",
        "address": "34 Garki Road, Garki",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria",
        "beds": 3,
        "baths": 2,
        "sqft": 1100,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Penthouse Suite in Central Area",
        "description": "Ultra-luxury penthouse in Abuja's CBD with panoramic city views.",
        "price": 3200000,
        "security_deposit": 3200000,
        "location": "Central Business District",
        "address": "1001 CBD Towers, Central Area",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria",
        "beds": 4,
        "baths": 3,
        "sqft": 3000,
        "property_type": "penthouse",
        "amenities": ["Air Conditioning", "Security", "Parking", "Swimming Pool"],
        "images": ["https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Budget 2-Bedroom in Kubwa",
        "description": "Affordable apartment in growing Kubwa district with good transport links.",
        "price": 280000,
        "security_deposit": 280000,
        "location": "Kubwa",
        "address": "56 Kubwa Express Road, Kubwa",
        "city": "Abuja",
        "state": "FCT",
        "country": "Nigeria",
        "beds": 2,
        "baths": 1,
        "sqft": 750,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1484154218962-a197022b5858?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    
    # PORT HARCOURT PROPERTIES (8 properties)
    {
        "title": "Modern 3-Bedroom Apartment in GRA Port Harcourt",
        "description": "Spacious apartment in Port Harcourt's Government Reserved Area with excellent amenities.",
        "price": 750000,
        "security_deposit": 750000,
        "location": "GRA Port Harcourt",
        "address": "23 Olu Obasanjo Way, GRA",
        "city": "Port Harcourt",
        "state": "Rivers State",
        "country": "Nigeria",
        "beds": 3,
        "baths": 2,
        "sqft": 1200,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking", "Swimming Pool"],
        "images": ["https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Luxury 4-Bedroom Duplex in Rumuola",
        "description": "Elegant duplex in one of Port Harcourt's most prestigious residential areas.",
        "price": 1600000,
        "security_deposit": 1600000,
        "location": "Rumuola",
        "address": "45 Rumuola Road, Rumuola",
        "city": "Port Harcourt",
        "state": "Rivers State",
        "country": "Nigeria",
        "beds": 4,
        "baths": 3,
        "sqft": 2000,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Gym"],
        "images": ["https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Cozy 1-Bedroom Studio in D-Line",
        "description": "Modern studio perfect for professionals in Port Harcourt's commercial hub.",
        "price": 250000,
        "security_deposit": 250000,
        "location": "D-Line",
        "address": "12 D-Line Road, D-Line",
        "city": "Port Harcourt",
        "state": "Rivers State",
        "country": "Nigeria",
        "beds": 1,
        "baths": 1,
        "sqft": 500,
        "property_type": "studio",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Spacious 5-Bedroom House in Rumuokwuta",
        "description": "Beautiful detached house with garden in a serene Port Harcourt neighborhood.",
        "price": 1200000,
        "security_deposit": 1200000,
        "location": "Rumuokwuta",
        "address": "78 Rumuokwuta Road, Rumuokwuta",
        "city": "Port Harcourt",
        "state": "Rivers State",
        "country": "Nigeria",
        "beds": 5,
        "baths": 3,
        "sqft": 2500,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Garden"],
        "images": ["https://images.unsplash.com/photo-1580587771525-78b9dba3b914?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Executive 2-Bedroom Apartment in Trans Amadi",
        "description": "Premium apartment in Port Harcourt's industrial area with modern amenities.",
        "price": 550000,
        "security_deposit": 550000,
        "location": "Trans Amadi",
        "address": "34 Trans Amadi Road, Trans Amadi",
        "city": "Port Harcourt",
        "state": "Rivers State",
        "country": "Nigeria",
        "beds": 2,
        "baths": 2,
        "sqft": 900,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking", "Gym"],
        "images": ["https://images.unsplash.com/photo-1586023492125-27b2c045efd7?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Modern 3-Bedroom Flat in Rumuogbolu",
        "description": "Contemporary apartment in a quiet residential area of Port Harcourt.",
        "price": 450000,
        "security_deposit": 450000,
        "location": "Rumuogbolu",
        "address": "56 Rumuogbolu Estate Road, Rumuogbolu",
        "city": "Port Harcourt",
        "state": "Rivers State",
        "country": "Nigeria",
        "beds": 3,
        "baths": 2,
        "sqft": 1000,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Luxury Penthouse in Old GRA",
        "description": "Ultra-luxury penthouse with city views in Port Harcourt's exclusive Old GRA.",
        "price": 2200000,
        "security_deposit": 2200000,
        "location": "Old GRA Port Harcourt",
        "address": "1001 Old GRA Towers, Old GRA",
        "city": "Port Harcourt",
        "state": "Rivers State",
        "country": "Nigeria",
        "beds": 4,
        "baths": 3,
        "sqft": 2800,
        "property_type": "penthouse",
        "amenities": ["Air Conditioning", "Security", "Parking", "Swimming Pool"],
        "images": ["https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Budget 2-Bedroom in Elekahia",
        "description": "Affordable apartment in Elekahia with good access to city amenities.",
        "price": 200000,
        "security_deposit": 200000,
        "location": "Elekahia",
        "address": "78 Elekahia Road, Elekahia",
        "city": "Port Harcourt",
        "state": "Rivers State",
        "country": "Nigeria",
        "beds": 2,
        "baths": 1,
        "sqft": 700,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1484154218962-a197022b5858?w=800&h=600&fit=crop"],
        "status": "vacant"
    }
]

def create_properties():
    """Create 24 properties for landlord jaydam@gmail.com across 3 cities"""
    landlord_id = "8e7992b4-e136-44a0-aa2c-271c3a653736"
    
    print(f"Creating {len(properties_data)} properties across 3 cities for landlord {landlord_id}...")
    
    success_count = 0
    error_count = 0
    
    for i, prop_data in enumerate(properties_data, 1):
        try:
            # Add required fields based on the actual database schema
            property_data = {
                "landlord_id": landlord_id,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "featured": False,
                "year_built": None,
                "furnished": False,
                "parking_spaces": 0,
                "utilities_included": False,
                "pet_friendly": False,
                "lease_duration": "12 months",
                "available_from": None,
                "rules": [],
                "neighborhood": None,
                "latitude": None,
                "longitude": None,
                "view_count": 0,
                **prop_data
            }
            
            print(f"\n📝 Creating property {i}: {prop_data['title']} ({prop_data['city']})")
            
            # Insert property
            result = supabase_admin.table("properties").insert(property_data).execute()
            
            if result.data and len(result.data) > 0:
                created_property = result.data[0]
                print(f"✅ Property created successfully with ID: {created_property.get('id')}")
                success_count += 1
            else:
                print(f"❌ Failed to create property - no data returned")
                error_count += 1
                
        except Exception as e:
            print(f"❌ Error creating property {i}: {str(e)}")
            error_count += 1
    
    print(f"\n📊 Summary:")
    print(f"✅ Successfully created: {success_count} properties")
    print(f"❌ Failed to create: {error_count} properties")
    print(f"📈 Total processed: {success_count + error_count} properties")
    
    # City breakdown
    cities = {}
    for prop in properties_data:
        city = prop['city']
        cities[city] = cities.get(city, 0) + 1
    
    print(f"\n🏙️ City Distribution:")
    for city, count in cities.items():
        print(f"  {city}: {count} properties")

if __name__ == "__main__":
    create_properties()
