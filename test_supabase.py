"""
Test script to verify Supabase admin connection
"""
import os
import sys
from pathlib import Path

# Add the server directory to the path
server_dir = Path(__file__).parent
sys.path.insert(0, str(server_dir))

from app.database import supabase_admin, supabase
from app.config import settings

def test_supabase_connection():
    """Test Supabase admin connection"""
    print("🔍 Testing Supabase connections...")
    print(f"✅ Supabase URL: {settings.SUPABASE_URL}")
    print(f"✅ Supabase Key exists: {'Yes' if settings.SUPABASE_KEY else 'No'}")
    print(f"✅ Supabase Service Key exists: {'Yes' if settings.SUPABASE_SERVICE_KEY else 'No'}")
    
    # Test admin client
    try:
        print("\n🔍 Testing admin client...")
        result = supabase_admin.table("users").select("count").execute()
        print(f"✅ Admin client works: {result}")
    except Exception as e:
        print(f"❌ Admin client failed: {e}")
        
        # Try to recreate admin client
        try:
            from supabase import create_client
            fresh_admin = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
            fresh_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
            result = fresh_admin.table("users").select("count").execute()
            print(f"✅ Fresh admin client works: {result}")
        except Exception as e2:
            print(f"❌ Fresh admin client also failed: {e2}")
    
    # Test regular client
    try:
        print("\n🔍 Testing regular client...")
        result = supabase.table("users").select("count").execute()
        print(f"✅ Regular client works: {result}")
    except Exception as e:
        print(f"❌ Regular client failed: {e}")

if __name__ == "__main__":
    test_supabase_connection()
