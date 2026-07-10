#!/usr/bin/env python3
"""
Fetch and display Nomba supported banks list directly from Nomba API.
This script loads credentials from .env and calls Nomba's banks endpoint.

Usage:
    python scripts/fetch_nomba_banks.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import requests

# Load .env from server directory
server_dir = Path(__file__).parent.parent
env_path = server_dir / ".env"
load_dotenv(env_path)


def get_nomba_token():
    """Get a fresh Nomba access token."""
    client_id = os.environ.get("NOMBA_LIVE_CLIENT_ID")
    client_secret = os.environ.get("NOMBA_LIVE_CLIENT_SECRET")
    parent_account_id = os.environ.get("NOMBA_PARENT_ACCOUNT_ID")
    
    if not client_id or not client_secret or not parent_account_id:
        print("❌ Missing required credentials in .env:")
        print(f"   NOMBA_LIVE_CLIENT_ID: {'SET' if client_id else 'NOT SET'}")
        print(f"   NOMBA_LIVE_CLIENT_SECRET: {'SET' if client_secret else 'NOT SET'}")
        print(f"   NOMBA_PARENT_ACCOUNT_ID: {'SET' if parent_account_id else 'NOT SET'}")
        sys.exit(1)
    
    url = "https://api.nomba.com/v1/auth/token/issue"
    headers = {
        "Content-Type": "application/json",
        "accountId": parent_account_id,
    }
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    
    print(f"Requesting token from Nomba...")
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    response.raise_for_status()
    
    data = response.json()
    if data.get("code") != "00":
        print(f"❌ Token issue failed: {data.get('description', 'Unknown error')}")
        sys.exit(1)
    
    token = data["data"]["access_token"]
    print(f"✅ Token obtained successfully")
    return token, parent_account_id


def main():
    print("=" * 80)
    print("Fetching Nomba Banks List (Direct API Call)")
    print("=" * 80)
    print()
    
    try:
        # Get token
        token, parent_account_id = get_nomba_token()
        print()
        
        # Fetch banks list
        url = "https://api.nomba.com/v1/transfers/banks"
        headers = {
            "Authorization": f"Bearer {token}",
            "accountId": parent_account_id,
        }
        
        print(f"Fetching banks from: {url}")
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        if data.get("code") != "00":
            print(f"❌ Failed to fetch banks: {data.get('description', 'Unknown error')}")
            sys.exit(1)
        
        banks = data["data"]
        print(f"✅ Found {len(banks)} banks\n")
        
        print(f"{'Code':<10} {'Bank Name'}")
        print("-" * 80)
        
        # Sort by bank code for easier lookup
        banks_sorted = sorted(banks, key=lambda x: x.get('code', ''))
        
        for bank in banks_sorted:
            code = bank.get('code', 'N/A')
            name = bank.get('name', 'N/A')
            print(f"{code:<10} {name}")
        
        print("\n" + "=" * 80)
        print("Common bank codes (quick reference):")
        print("=" * 80)
        
        common_banks = {
            "057": "Zenith Bank",
            "058": "Guaranty Trust Bank",
            "044": "Access Bank",
            "035": "Wema Bank",
            "011": "First Bank",
            "033": "United Bank for Africa",
            "082": "Polaris Bank",
            "070": "Fidelity Bank",
            "077": "Zenith Bank (old)",
            "023": "Citibank",
            "051": "First Bank (old)",
            "063": "Diamond Bank (old)",
            "050": "Ecobank",
            "030": "Heritage Bank",
            "084": "Unity Bank",
            "221": "Stanbic IBTC",
            "232": "Sterling Bank",
            "301": "Jaiz Bank",
            "101": "Providus Bank",
            "102": "Suntrust Bank",
            "103": "Parallex Bank",
            "999": "Kuda Bank",
        }
        
        for code, name in sorted(common_banks.items()):
            print(f"{code:<10} {name}")
        
        print("\n" + "=" * 80)
        print("✅ Banks list fetched successfully!")
        print("=" * 80)
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
