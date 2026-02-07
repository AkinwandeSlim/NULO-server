"""
Script to create 25 sample properties for landlord jaydam@gmail.com
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import supabase_admin
from datetime import datetime

# Sample property data with diverse images and details (using correct database field names)
properties_data = [
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
    {
        "title": "Budget 2-Bedroom in Surulere",
        "description": "Affordable and well-maintained apartment in a central location.",
        "price": 320000,
        "security_deposit": 320000,
        "location": "Surulere",
        "address": "78 Bode Thomas Street, Surulere",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 2,
        "baths": 1,
        "sqft": 700,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1484154218962-a197022b5858?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Luxury 3-Bedroom Duplex in Ajah",
        "description": "Spacious duplex with modern architecture and premium finishes.",
        "price": 1100000,
        "security_deposit": 1100000,
        "location": "Ajah",
        "address": "124 Lekki-Epe Expressway, Ajah",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 3,
        "baths": 3,
        "sqft": 1600,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Gym"],
        "images": ["https://images.unsplash.com/photo-1560185007-c5ca9d2c014d?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Modern Studio in Maryland",
        "description": "Compact and efficient studio perfect for singles.",
        "price": 280000,
        "security_deposit": 280000,
        "location": "Maryland",
        "address": "45 Ikorodu Road, Maryland",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 0,
        "baths": 1,
        "sqft": 450,
        "property_type": "studio",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1502672260266-1c1a7bf8a2f0?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "4-Bedroom Maisonette in Gbagada",
        "description": "Spacious maisonette with multiple levels and private garden.",
        "price": 1300000,
        "security_deposit": 1300000,
        "location": "Gbagada",
        "address": "23 Gbagada Expressway, Gbagada",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 4,
        "baths": 3,
        "sqft": 2200,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Garden"],
        "images": ["https://images.unsplash.com/photo-1416339134316-0e91dc9ded92?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "2-Bedroom Flat in Festac Town",
        "description": "Well-maintained apartment in a planned residential area.",
        "price": 350000,
        "security_deposit": 350000,
        "location": "Festac Town",
        "address": "123 Festac Town Road, Festac",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 2,
        "baths": 1,
        "sqft": 800,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1578662996442-48f60103fc96?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Executive 3-Bedroom in Ikoyi",
        "description": "Premium apartment in one of Lagos' most prestigious neighborhoods.",
        "price": 2000000,
        "security_deposit": 2000000,
        "location": "Ikoyi",
        "address": "67 Ikoyi Club Road, Ikoyi",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 3,
        "baths": 3,
        "sqft": 1800,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking", "Gym"],
        "images": ["https://images.unsplash.com/photo-1582268611958-ebfd16135945?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "1-Bedroom Flat in Mushin",
        "description": "Affordable apartment in a central location with easy access to transportation.",
        "price": 220000,
        "security_deposit": 220000,
        "location": "Mushin",
        "address": "45 Mushin Road, Mushin",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 1,
        "baths": 1,
        "sqft": 550,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security"],
        "images": ["https://images.unsplash.com/photo-1521788772331-1c028f6204d3?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "5-Bedroom Villa in Lekki",
        "description": "Luxurious villa with private pool, garden, and staff quarters.",
        "price": 2800000,
        "security_deposit": 2800000,
        "location": "Lekki",
        "address": "15 Lekki Peninsula Scheme 1, Lekki",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 5,
        "baths": 4,
        "sqft": 4000,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Swimming Pool"],
        "images": ["https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "2-Bedroom Apartment in Apapa",
        "description": "Modern apartment near the port with excellent connectivity.",
        "price": 480000,
        "security_deposit": 480000,
        "location": "Apapa",
        "address": "78 Creek Road, Apapa",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 2,
        "baths": 2,
        "sqft": 850,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking", "Gym"],
        "images": ["https://images.unsplash.com/photo-1600566753376-12c8ab7fb75b?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "3-Bedroom Flat in Oshodi",
        "description": "Spacious apartment in a bustling commercial area.",
        "price": 420000,
        "security_deposit": 420000,
        "location": "Oshodi",
        "address": "45 Oshodi Road, Oshodi",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 3,
        "baths": 2,
        "sqft": 1100,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1600566753190-98b26bd0f849?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Luxury Studio in Victoria Island",
        "description": "High-end studio with premium finishes and excellent amenities.",
        "price": 550000,
        "security_deposit": 550000,
        "location": "Victoria Island",
        "address": "89 Adeola Odeku Street, Victoria Island",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 0,
        "baths": 1,
        "sqft": 650,
        "property_type": "studio",
        "amenities": ["Air Conditioning", "Security", "Parking", "Gym"],
        "images": ["https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "4-Bedroom Duplex in Magodo",
        "description": "Elegant duplex in a gated community with excellent security.",
        "price": 1450000,
        "security_deposit": 1450000,
        "location": "Magodo",
        "address": "15 Magodo GRA Road, Magodo",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 4,
        "baths": 3,
        "sqft": 2400,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Gym"],
        "images": ["https://images.unsplash.com/photo-1600047509807-ba8f800d6342?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "1-Bedroom in Ketu",
        "description": "Affordable and well-located apartment with easy access to mainland.",
        "price": 260000,
        "security_deposit": 260000,
        "location": "Ketu",
        "address": "34 Ketu Road, Ketu",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 1,
        "baths": 1,
        "sqft": 500,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1600585154526-990dced4db0b?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "3-Bedroom House in Anthony Village",
        "description": "Spacious house in a quiet residential area.",
        "price": 780000,
        "security_deposit": 780000,
        "location": "Anthony Village",
        "address": "67 Anthony Village Road, Anthony",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 3,
        "baths": 2,
        "sqft": 1500,
        "property_type": "house",
        "amenities": ["Air Conditioning", "Security", "Parking", "Garden"],
        "images": ["https://images.unsplash.com/photo-1416339134316-0e91dc9ded92?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "2-Bedroom in Ilupeju",
        "description": "Modern apartment in an industrial-commercial area.",
        "price": 410000,
        "security_deposit": 410000,
        "location": "Ilupeju",
        "address": "23 Ilupeju Industrial Road, Ilupeju",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 2,
        "baths": 1,
        "sqft": 780,
        "property_type": "apartment",
        "amenities": ["Air Conditioning", "Security", "Parking"],
        "images": ["https://images.unsplash.com/photo-1600607687644-c8175b97f2be?w=800&h=600&fit=crop"],
        "status": "vacant"
    },
    {
        "title": "Executive Penthouse in Victoria Island",
        "description": "Ultra-luxury penthouse with 360-degree city views and private pool.",
        "price": 4200000,
        "security_deposit": 4200000,
        "location": "Victoria Island",
        "address": "1001 Towers, Victoria Island",
        "city": "Lagos",
        "state": "Lagos State",
        "country": "Nigeria",
        "beds": 6,
        "baths": 5,
        "sqft": 5000,
        "property_type": "penthouse",
        "amenities": ["Air Conditioning", "Security", "Parking", "Swimming Pool"],
        "images": ["https://images.unsplash.com/photo-1600566753190-98b26bd0f849?w=800&h=600&fit=crop"],
        "status": "vacant"
    }
]

def create_properties():
    """Create 25 properties for landlord jaydam@gmail.com"""
    landlord_id = "8e7992b4-e136-44a0-aa2c-271c3a653736"
    
    print(f"Creating {len(properties_data)} properties for landlord {landlord_id}...")
    
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
            
            print(f"\n📝 Creating property {i}: {prop_data['title']}")
            
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

if __name__ == "__main__":
    create_properties()
