#!/usr/bin/env python3
"""
Test script to verify the complete manual signup email flow
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.notification_service import notification_service
import asyncio

async def test_manual_signup_flow():
    print("=== Testing Manual Signup Email Flow ===")
    
    # Test data for manual signup user
    test_user_id = "manual-signup-user-123"
    test_email = "akinwandealex95@gmail.com"
    test_name = "Manual Signup User"
    test_user_type = "tenant"
    
    print(f"Testing manual signup flow:")
    print(f"  Email: {test_email}")
    print(f"  Name: {test_name}")
    print(f"  User Type: {test_user_type}")
    print()
    
    try:
        # Step 1: Simulate what happens after user clicks Supabase verification link
        print("🔄 Step 1: User clicked Supabase verification link")
        print("   → Calling /notifications/internal/create endpoint...")
        
        # This simulates the call from client/app/auth/callback/route.ts
        # The payload that gets sent to /api/v1/notifications/internal/create
        notification_payload = {
            "user_id": test_user_id,
            "title": "🎉 Email Verified!",
            "message": "Your email has been confirmed. Complete your profile to start browsing verified properties.",
            "type": "email_verified",
            "link": "/onboarding/tenant/step-1"
        }
        
        print(f"   Payload: {notification_payload}")
        print()
        
        # Step 2: This triggers notify_email_verified which sends the welcome email
        print("🔄 Step 2: Backend sends welcome email via notify_email_verified...")
        await notification_service.notify_email_verified(
            user_id=test_user_id,
            user_email=test_email,
            user_name=test_name,
            user_type=test_user_type
        )
        print("✅ Welcome email sent successfully!")
        
    except Exception as e:
        print(f"❌ Error in manual signup flow: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n=== Manual Signup Flow Test Complete ===")
    print()
    print("Expected behavior for manual signup:")
    print("1. User signs up → Supabase sends verification email")
    print("2. User clicks verification link → Callback route runs")
    print("3. Callback calls /notifications/internal/create")
    print("4. Backend sends welcome email via notify_email_verified()")
    print("5. User receives welcome email with next steps")

if __name__ == "__main__":
    asyncio.run(test_manual_signup_flow())
