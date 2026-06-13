#!/usr/bin/env python3
"""
Generate QA Admin Token
=======================

This script generates an authentication token for the QA test admin.
Used for testing webhook signature verification and other admin endpoints.

Usage:
    python generate_qa_token.py

Output:
    Displays the admin token to use in API requests.
"""

import os
import sys
import asyncio
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import supabase_admin

async def generate_qa_token():
    """Generate authentication token for QA admin."""
    
    email = "qatest.admin.prod@gmail.com"
    password = "Admin#ProdNA1@"
    
    print("\n" + "="*70)
    print("QA ADMIN TOKEN GENERATOR")
    print("="*70)
    print(f"\nAttempting to sign in as: {email}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")
    
    try:
        # Sign in with Supabase Auth
        # Python client expects dict as positional argument, not keyword args
        response = supabase_admin.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if response.session:
            access_token = response.session.access_token
            refresh_token = response.session.refresh_token
            user_id = response.user.id
            
            print("✅ AUTHENTICATION SUCCESSFUL!\n")
            print("-" * 70)
            print("QA ADMIN TOKEN (for API requests)")
            print("-" * 70)
            print(f"\nAccess Token:\n{access_token}\n")
            print("-" * 70)
            print("HOW TO USE THIS TOKEN")
            print("-" * 70)
            print("""
1. TEST WEBHOOK SIGNATURE:
   curl -X POST http://localhost:8000/payments/test-webhook \\
     -H "Authorization: Bearer {access_token}" \\
     -H "x-paystack-signature: FAKE_INVALID_SIG" \\
     -H "Content-Type: application/json" \\
     -d '{"event":"charge.success","data":{"reference":"TEST"}}'

2. VIEW WEBHOOK LOGS:
   curl -X GET http://localhost:8000/payments/webhook-logs \\
     -H "Authorization: Bearer {access_token}"

3. CLEAR WEBHOOK LOGS:
   curl -X DELETE http://localhost:8000/payments/webhook-logs \\
     -H "Authorization: Bearer {access_token}"
""".format(access_token=access_token))
            
            print("-" * 70)
            print("TOKEN DETAILS")
            print("-" * 70)
            print(f"User ID:        {user_id}")
            print(f"Email:          {email}")
            print(f"Token Type:     Bearer")
            print(f"Generated:      {datetime.now().isoformat()}")
            print("-" * 70 + "\n")
            
            # Save token to file for easy reference
            token_file = os.path.join(os.path.dirname(__file__), "QA_ADMIN_TOKEN.txt")
            with open(token_file, "w") as f:
                f.write(f"QA Admin Token - Generated {datetime.now().isoformat()}\n")
                f.write(f"Email: {email}\n")
                f.write(f"User ID: {user_id}\n\n")
                f.write(f"Access Token:\n{access_token}\n\n")
                f.write(f"Refresh Token:\n{refresh_token}\n")
            
            print(f"✅ Token saved to: {token_file}\n")
            
            return access_token
        else:
            print("❌ No session returned from authentication")
            return None
            
    except Exception as e:
        print(f"❌ AUTHENTICATION FAILED!")
        print(f"Error: {str(e)}\n")
        print("Troubleshooting:")
        print("1. Verify email and password are correct")
        print("2. Check if admin user exists in Supabase")
        print("3. Verify SUPABASE credentials are set in .env")
        return None

if __name__ == "__main__":
    token = asyncio.run(generate_qa_token())
    sys.exit(0 if token else 1)
