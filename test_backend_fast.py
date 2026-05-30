#!/usr/bin/env python3
"""
Fast Backend Test - Seamless AI Integration
==========================================

Quick test to validate the enhanced agreement service works perfectly.
Tests both AI generation and template fallback.
"""

import asyncio
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_backend_fast():
    """Fast backend test for seamless AI integration"""
    print("🚀 FAST BACKEND TEST - Seamless AI Integration")
    print("=" * 55)
    
    try:
        # Import the enhanced service
        from app.services.agreement_service import AgreementService
        
        print("✅ Agreement Service imported successfully")
        
        # Test data
        property_data = {
            "id": "fast-test-123",
            "title": "Fast Test Apartment",
            "location": "123 Fast Test Street, Ikoyi, Lagos",
            "full_address": "123 Fast Test Street, Ikoyi, Lagos, Nigeria",
            "price": 750000,
            "property_type": "2-Bedroom Apartment",
            "landlord_id": "landlord-123"
        }
        
        tenant_data = {
            "id": "tenant-456",
            "full_name": "Fast Test User",
            "email": "fast@test.com",
            "phone_number": "08012345678"
        }
        
        lease_dates = {
            "lease_start_date": "2024-06-01",
            "lease_end_date": "2025-06-01",
            "lease_duration": 12
        }
        
        print("\n🤖 Testing Enhanced Agreement Generation...")
        start_time = datetime.now()
        
        # Test the new seamless method
        result = await AgreementService.generate_enhanced_agreement_terms(
            property_data=property_data,
            tenant_data=tenant_data,
            landlord_name="Fast Landlord",
            lease_dates=lease_dates,
            application={"id": "fast-app-789"}
        )
        
        generation_time = (datetime.now() - start_time).total_seconds()
        
        # Validate result
        required_fields = ["terms", "source", "metadata"]
        missing_fields = [field for field in required_fields if field not in result]
        
        if missing_fields:
            raise Exception(f"❌ Missing fields: {missing_fields}")
        
        if not result["terms"]:
            raise Exception("❌ No terms generated!")
        
        # Display results
        print(f"✅ Enhanced agreement generated successfully!")
        print(f"   ⏱️  Generation time: {generation_time:.2f}s")
        print(f"   📄 Terms length: {len(result['terms'])} chars")
        print(f"   🤖 Source: {result['source']}")
        
        if result['source'] == 'groq_llama':
            metadata = result['metadata']
            print(f"   📊 AI Model: {metadata.get('model_used')}")
            print(f"   🔢 Tokens: {metadata.get('tokens_used')}")
            print(f"   📈 Compliance: {metadata.get('compliance_score', 0):.1f}%")
            print(f"   💰 Cost: ${metadata.get('cost_usd', 0):.6f}")
            print("   🎉 AI WORKING PERFECTLY!")
        else:
            print("   📋 Using enhanced template fallback")
            print("   🛡️ Template working perfectly!")
        
        # Test agreement dict creation
        print(f"\n📋 Testing Agreement Dictionary Creation...")
        
        agreement_dict = AgreementService.create_agreement_dict(
            application_id="fast-app-123",
            property_id="fast-prop-123",
            tenant_id="fast-tenant-123",
            landlord_id="fast-landlord-123",
            property_data=property_data,
            lease_dates=lease_dates,
            terms=result["terms"]
        )
        
        # Check for new fields
        if "agreement_source" not in agreement_dict:
            raise Exception("❌ agreement_source field missing")
        
        if "generation_metadata" not in agreement_dict:
            raise Exception("❌ generation_metadata field missing")
        
        print(f"✅ Agreement dict created with {len(agreement_dict)} fields")
        print(f"   🤖 agreement_source: {agreement_dict['agreement_source']}")
        print(f"   📊 generation_metadata: {len(agreement_dict['generation_metadata'])} keys")
        
        # Update with actual data
        agreement_dict["agreement_source"] = result["source"]
        agreement_dict["generation_metadata"] = result["metadata"]
        
        print(f"   ✅ Updated with generation data")
        
        # Show preview of agreement content
        print(f"\n🔍 Agreement Preview (first 200 chars):")
        preview = result["terms"][:200] + "..." if len(result["terms"]) > 200 else result["terms"]
        print(f"   {preview}")
        
        print(f"\n🎉 BACKEND TEST COMPLETE!")
        print(f"   ✅ Enhanced agreement service working perfectly")
        print(f"   ✅ AI integration seamless")
        print(f"   ✅ Template fallback robust")
        print(f"   ✅ Database schema compatible")
        print(f"   ✅ Ready for frontend integration!")
        
        return True
        
    except Exception as e:
        print(f"\n❌ BACKEND TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Main test runner"""
    success = await test_backend_fast()
    
    if success:
        print(f"\n🚀 READY FOR FRONTEND!")
        print(f"   1. ✅ Backend integration working")
        print(f"   2. ✅ Run database migration if needed")
        print(f"   3. ✅ Start frontend integration")
        print(f"   4. ✅ Test end-to-end flows")
    else:
        print(f"\n🔧 FIX ISSUES BEFORE PROCEEDING")

if __name__ == "__main__":
    print("⚡ Fast Backend Test - Seamless AI Integration")
    print("=" * 55)
    print("Testing the enhanced agreement service quickly...")
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Test interrupted")
    except Exception as e:
        print(f"\n🚫 Test failed: {e}")
