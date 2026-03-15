#!/usr/bin/env python3
"""
Test script to verify the complete email verification flow
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.notification_service import notification_service
from app.services.email_service import email_service
import asyncio

async def test_email_flow():
    print("=== Testing Email Verification Flow ===")
    
    # Test data - using a valid UUID format
    test_user_id = "550e8400-e29b-41d4-a716-446655440000"  # Valid UUID format
    test_email = "akinwandealex95@gmail.com"
    test_name = "Test User"
    test_user_type = "tenant"
    
    print(f"Testing with:")
    print(f"  Email: {test_email}")
    print(f"  Name: {test_name}")
    print(f"  User Type: {test_user_type}")
    print()
    
    try:
        # Test the email verification notification (this is what sends the welcome email)
        print("🔄 Testing notify_email_verified...")
        await notification_service.notify_email_verified(
            user_id=test_user_id,
            user_email=test_email,
            user_name=test_name,
            user_type=test_user_type
        )
        print("✅ notify_email_verified completed successfully")
        
    except Exception as e:
        print(f"❌ Error in email flow: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(test_email_flow())
