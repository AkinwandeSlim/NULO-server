#!/usr/bin/env python3
"""
Test script to verify SSL timeout fixes
"""
import asyncio
import sys
import os

# Add server to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import supabase_admin

async def test_supabase_connection():
    """Test Supabase connection with SSL fixes"""
    print("🔍 Testing Supabase connection...")
    
    try:
        # Test basic connection
        response = supabase_admin.table("users").select("count").execute()
        print(f"✅ Connection successful: {response.data}")
        
        # Test with timeout
        response = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: supabase_admin.table("users").select("id, email").limit(5).execute()
            ),
            timeout=15.0
        )
        print(f"✅ Query with timeout successful: {len(response.data)} users")
        
        return True
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_supabase_connection())
    if success:
        print("🎉 SSL timeout fixes working!")
    else:
        print("⚠️ SSL timeout issues persist")
