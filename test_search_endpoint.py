#!/usr/bin/env python3
"""
Test the properties search endpoint with location parameter
"""

import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_search():
    print("=" * 80)
    print("🧪 Testing Properties Search Endpoint")
    print("=" * 80)
    
    # Test 1: Simple search without location
    print("\n✅ Test 1: Search without location filter")
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/properties/search",
            params={"page": 1, "limit": 5}
        )
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Found {len(data.get('data', []))} properties")
            print(f"✅ PASS\n")
        else:
            print(f"Error: {response.text}")
            print(f"❌ FAIL\n")
    except Exception as e:
        print(f"❌ FAIL: {e}\n")
    
    # Test 2: Search with location = "Maitama, FCT"
    print("✅ Test 2: Search with location='Maitama, FCT'")
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/properties/search",
            params={
                "location": "Maitama, FCT",
                "page": 1,
                "limit": 20
            }
        )
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Found {len(data.get('data', []))} properties")
            print(f"✅ PASS\n")
        else:
            print(f"Error: {response.text}")
            print(f"❌ FAIL\n")
    except Exception as e:
        print(f"❌ FAIL: {e}\n")
    
    # Test 3: Search with location = "Maitama"
    print("✅ Test 3: Search with location='Maitama'")
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/properties/search",
            params={
                "location": "Maitama",
                "page": 1,
                "limit": 20
            }
        )
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Found {len(data.get('data', []))} properties")
            print(f"✅ PASS\n")
        else:
            print(f"Error: {response.text}")
            print(f"❌ FAIL\n")
    except Exception as e:
        print(f"❌ FAIL: {e}\n")
    
    # Test 4: Search with location = "Abuja"
    print("✅ Test 4: Search with location='Abuja'")
    try:
        response = requests.get(
            f"{BASE_URL}/api/v1/properties/search",
            params={
                "location": "Abuja",
                "page": 1,
                "limit": 20
            }
        )
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Found {len(data.get('data', []))} properties")
            if data.get('data'):
                print(f"Sample property location: {data['data'][0].get('location')}")
            print(f"✅ PASS\n")
        else:
            print(f"Error: {response.text}")
            print(f"❌ FAIL\n")
    except Exception as e:
        print(f"❌ FAIL: {e}\n")
    
    print("=" * 80)
    print("🎉 Search tests completed!")
    print("=" * 80)

if __name__ == "__main__":
    test_search()
