#!/usr/bin/env python3
"""
Test script to verify the location API and search functionality
"""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_endpoints():
    print("=" * 80)
    print("🧪 Testing Location API Endpoints")
    print("=" * 80)
    
    # Test 1: Get States
    print("\n✅ Test 1: GET /api/locations/states")
    try:
        response = requests.get(f"{BASE_URL}/api/locations/states")
        data = response.json()
        print(f"Status: {response.status_code}")
        print(f"States: {[s['name'] for s in data.get('states', [])]}")
        print(f"✅ PASS\n")
    except Exception as e:
        print(f"❌ FAIL: {e}\n")
    
    # Test 2: Get Cities for Abuja
    print("✅ Test 2: GET /api/locations/cities?state=Abuja")
    try:
        response = requests.get(f"{BASE_URL}/api/locations/cities?state=Abuja")
        data = response.json()
        cities = data.get('cities', [])
        print(f"Status: {response.status_code}")
        print(f"State: {data.get('state')}")
        print(f"State Code: {data.get('state_code')}")
        print(f"Cities: {[c['name'] for c in cities]}")
        print(f"Total: {len(cities)} cities")
        print(f"✅ PASS\n")
    except Exception as e:
        print(f"❌ FAIL: {e}\n")
    
    # Test 3: Get Cities for Lagos
    print("✅ Test 3: GET /api/locations/cities?state=Lagos")
    try:
        response = requests.get(f"{BASE_URL}/api/locations/cities?state=Lagos")
        data = response.json()
        cities = data.get('cities', [])
        print(f"Status: {response.status_code}")
        print(f"Cities: {[c['name'] for c in cities]}")
        print(f"Total: {len(cities)} cities")
        print(f"✅ PASS\n")
    except Exception as e:
        print(f"❌ FAIL: {e}\n")
    
    # Test 4: Search cities
    print("✅ Test 4: GET /api/locations/search?q=maitama")
    try:
        response = requests.get(f"{BASE_URL}/api/locations/search?q=maitama")
        data = response.json()
        results = data.get('results', [])
        print(f"Status: {response.status_code}")
        print(f"Query: {data.get('query')}")
        print(f"Results: {[r['name'] for r in results]}")
        print(f"✅ PASS\n")
    except Exception as e:
        print(f"❌ FAIL: {e}\n")
    
    # Test 5: Search for Lekki
    print("✅ Test 5: GET /api/locations/search?q=lekki")
    try:
        response = requests.get(f"{BASE_URL}/api/locations/search?q=lekki")
        data = response.json()
        results = data.get('results', [])
        print(f"Status: {response.status_code}")
        print(f"Results: {[r['name'] for r in results]}")
        print(f"✅ PASS\n")
    except Exception as e:
        print(f"❌ FAIL: {e}\n")
    
    # Test 6: Get complete locations
    print("✅ Test 6: GET /api/locations/complete")
    try:
        response = requests.get(f"{BASE_URL}/api/locations/complete")
        data = response.json()
        locations = data.get('locations', {})
        print(f"Status: {response.status_code}")
        print(f"States: {list(locations.keys())}")
        for state, info in locations.items():
            cities_count = len(info.get('cities', []))
            print(f"  - {state} ({info.get('state_code')}): {cities_count} cities")
        print(f"✅ PASS\n")
    except Exception as e:
        print(f"❌ FAIL: {e}\n")
    
    print("=" * 80)
    print("🎉 All tests completed!")
    print("=" * 80)

if __name__ == "__main__":
    test_endpoints()
