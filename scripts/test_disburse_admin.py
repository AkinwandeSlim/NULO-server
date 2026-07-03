import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from app.routes.disbursements import disburse_agreement
from app.routes.nomba import nomba_client
from app.database import supabase_admin
from fastapi import FastAPI
import asyncio
from datetime import datetime

# Test data
TEST_AGREEMENT_ID = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
TEST_SOURCE_TRANSFER_ID = "ad4d6fb6-07cc-4e7b-960e-747da6683419"
TEST_LANDLORD_ID = "070671cd-a779-4997-9046-771467394f53"

async def test_disbursement():
    print("Testing disbursement flow...")
    print("=" * 70)
    
    # Mock current user
    current_user = {
        "id": TEST_LANDLORD_ID,
        "email": "test@example.com",
        "user_type": "landlord"
    }
    
    # Test disbursement
    try:
        result = await disburse_agreement(
            agreement_id=TEST_AGREEMENT_ID,
            source_transfer_id=TEST_SOURCE_TRANSFER_ID,
            current_user=current_user
        )
        print(f"✅ Disbursement successful!")
        print(f"   Merchant Tx Ref: {result.merchant_tx_ref}")
        print(f"   Status: {result.status}")
        print(f"   Response: {result.nomba_response}")
        return result
    except Exception as e:
        print(f"❌ Disbursement failed: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    asyncio.run(test_disbursement())
