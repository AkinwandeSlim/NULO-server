"""
Test script to check API endpoints directly
"""
import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_URL = "http://localhost:8000/api/v1"

# Get token from environment or use a test token
# You'll need to replace this with an actual valid token
TOKEN = os.getenv("TEST_TOKEN", "")

if not TOKEN:
    print("[ERROR] No TEST_TOKEN found in .env file")
    print("Please add a valid JWT token to your .env file as TEST_TOKEN=your_token_here")
    print("\nTo get a token:")
    print("1. Sign in to your app")
    print("2. Open browser DevTools > Application > Local Storage")
    print("3. Copy the 'token' value")
    exit(1)

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

print("[INFO] Testing API Endpoints...\n")
print("="*60)

# Test 1: Favorites API
print("\n[TEST 1] GET /favorites")
try:
    response = requests.get(f"{BASE_URL}/favorites", headers=headers)
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"[OK] Favorites count: {data.get('count', 0)}")
    else:
        print(f"[ERROR] {response.text}")
except Exception as e:
    print(f"[ERROR] {str(e)}")

# Test 2: Viewing Requests API
print("\n[TEST 2] GET /viewing-requests")
try:
    response = requests.get(f"{BASE_URL}/viewing-requests", headers=headers)
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"[OK] Viewing requests count: {data.get('count', 0)}")
    else:
        print(f"[ERROR] {response.text}")
except Exception as e:
    print(f"[ERROR] {str(e)}")

# Test 3: Messages/Conversations API
print("\n[TEST 3] GET /messages/conversations")
try:
    response = requests.get(f"{BASE_URL}/messages/conversations", headers=headers)
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        conversations = data.get('conversations', [])
        print(f"[OK] Conversations count: {len(conversations)}")
    else:
        print(f"[ERROR] {response.text}")
except Exception as e:
    print(f"[ERROR] {str(e)}")

print("\n" + "="*60)
print("[INFO] API endpoint testing complete!")
