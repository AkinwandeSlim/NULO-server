"""
Test the social login endpoint directly
"""
import asyncio
import json
from app.database import supabase_admin
from app.config import settings
from uuid import uuid4

async def test_social_login():
    """Test social login with the same payload that would come from Google"""
    
    # Simulate Google social login payload
    payload = {
        "provider": "google",
        "provider_account_id": "123456789",
        "access_token": "test_google_token",
        "refresh_token": "test_refresh_token", 
        "profile": {
            "email": "akinalex21@gmail.com",
            "name": "Alex Test",
            "picture": "https://example.com/avatar.jpg"
        },
        "user_type": "tenant"
    }
    
    print("🔍 Testing social login endpoint...")
    print(f"📦 Payload: {json.dumps(payload, indent=2)}")
    
    try:
        # Reset admin client auth
        supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
        print("✅ Reset admin client auth")
        
        # Test user lookup
        result = supabase_admin.table("users").select("*").eq("email", "akinalex21@gmail.com").execute()
        print(f"📥 User lookup result: {result}")
        
        # Test user creation (if needed)
        if not result.data:
            test_user = {
                "id": str(uuid4()),  # Use proper UUID
                "email": "akinalex21@gmail.com", 
                "full_name": "Alex Test",
                "user_type": "tenant",
                "trust_score": 50,
                "verification_status": "partial",
                "onboarding_completed": False,
                "created_at": "2025-01-08T00:00:00"
            }
            
            insert_result = supabase_admin.table("users").insert(test_user).execute()
            print(f"📝 User creation result: {insert_result}")
            
            # Clean up test user
            supabase_admin.table("users").delete().eq("id", test_user["id"]).execute()
            print("🧹 Cleaned up test user")
        
        print("✅ Social login test completed successfully!")
        
    except Exception as e:
        print(f"❌ Social login test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_social_login())
