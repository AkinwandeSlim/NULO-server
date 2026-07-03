#!/usr/bin/env python3
"""
Test AI Data Fix - Verify AI uses real data instead of placeholders
====================================================================

This test verifies that the AI service now uses actual data instead of 
generating placeholders like [Insert Address] or [Insert Name].
"""

import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_ai_data_fix():
    """Test that AI uses real data instead of placeholders"""
    print("🔧 TESTING AI DATA FIX")
    print("=" * 50)
    
    try:
        # Import the AI service
        from app.services.ai.ai_service import ai_service
        
        print("✅ AI Service imported successfully")
        
        # Test data with real values
        test_data = {
            "tenant_name": "Eze Uchenna Gerald",
            "landlord_name": "Raphawellness optimization", 
            "property_address": "123 Ikoyi Boulevard, Ikoyi, Lagos, Nigeria",
            "monthly_rent": 990000,
            "lease_duration": "12 months",
            "property_type": "2-Bedroom Apartment"
        }
        
        print(f"\n🧪 Testing with real data:")
        print(f"   Tenant: {test_data['tenant_name']}")
        print(f"   Landlord: {test_data['landlord_name']}")
        print(f"   Address: {test_data['property_address']}")
        print(f"   Rent: ₦{test_data['monthly_rent']:,}")
        
        print(f"\n🤖 Generating AI agreement...")
        start_time = asyncio.get_event_loop().time()
        
        # Generate agreement
        result = await ai_service.generate_agreement(
            tenant_name=test_data["tenant_name"],
            landlord_name=test_data["landlord_name"],
            property_address=test_data["property_address"],
            monthly_rent=test_data["monthly_rent"],
            lease_duration=test_data["lease_duration"],
            property_type=test_data["property_type"]
        )
        
        generation_time = asyncio.get_event_loop().time() - start_time
        
        if result["success"]:
            agreement_text = result["agreement"]
            
            print(f"✅ AI agreement generated successfully!")
            print(f"   ⏱️  Generation time: {generation_time:.2f}s")
            print(f"   📄 Length: {len(agreement_text)} chars")
            print(f"   📊 Tokens: {result.get('tokens_used', 'N/A')}")
            print(f"   📈 Compliance: {result.get('compliance_score', 0):.1f}%")
            
            # Check for placeholders
            placeholders_to_check = [
                "[Insert Address]",
                "[Insert Name]", 
                "[Insert Phone]",
                "[Insert Email]",
                "[Insert Account]",
                "[Insert"
            ]
            
            found_placeholders = []
            for placeholder in placeholders_to_check:
                if placeholder in agreement_text:
                    count = agreement_text.count(placeholder)
                    found_placeholders.append(f"{placeholder} ({count}x)")
            
            # Check for real data usage
            real_data_checks = [
                ("Tenant name", test_data["tenant_name"]),
                ("Landlord name", test_data["landlord_name"]),
                ("Property address", test_data["property_address"]),
                ("Monthly rent", f"₦{test_data['monthly_rent']:,}"),
                ("Annual rent", f"₦{test_data['monthly_rent'] * 12:,}"),
                ("Security deposit", f"₦{test_data['monthly_rent'] * 2:,}")
            ]
            
            found_real_data = []
            missing_real_data = []
            
            for check_name, expected_value in real_data_checks:
                if expected_value in agreement_text:
                    found_real_data.append(check_name)
                else:
                    missing_real_data.append(check_name)
            
            print(f"\n🔍 RESULTS ANALYSIS:")
            print(f"   📋 Placeholders found: {len(found_placeholders)}")
            if found_placeholders:
                for placeholder in found_placeholders:
                    print(f"      ❌ {placeholder}")
            else:
                print(f"      ✅ NO PLACEHOLDERS FOUND!")
            
            print(f"   📊 Real data used: {len(found_real_data)}/{len(real_data_checks)}")
            for data in found_real_data:
                print(f"      ✅ {data}")
            
            if missing_real_data:
                print(f"   ⚠️  Missing real data:")
                for data in missing_real_data:
                    print(f"      ❌ {data}")
            
            # Overall assessment
            if len(found_placeholders) == 0 and len(found_real_data) >= len(real_data_checks) * 0.8:
                print(f"\n🎉 SUCCESS: AI is using real data correctly!")
                print(f"   ✅ No placeholders found")
                print(f"   ✅ Real data properly integrated")
                print(f"   ✅ Agreement ready for production")
                return True
            else:
                print(f"\n⚠️  PARTIAL SUCCESS: Some issues found")
                if found_placeholders:
                    print(f"   ❌ Still has {len(found_placeholders)} placeholder types")
                if missing_real_data:
                    print(f"   ❌ Missing {len(missing_real_data)} real data elements")
                return False
                
        else:
            print(f"❌ AI generation failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Main test runner"""
    print("🚀 AI Data Fix Test")
    print("=" * 50)
    print("Testing that AI uses real data instead of placeholders...")
    print()
    
    success = await test_ai_data_fix()
    
    if success:
        print(f"\n🎉 TEST PASSED!")
        print(f"   ✅ AI integration working correctly")
        print(f"   ✅ Real data being used")
        print(f"   ✅ No placeholders in output")
        print(f"   ✅ Ready for production use")
    else:
        print(f"\n🔧 TEST FAILED!")
        print(f"   ⚠️  AI still generating placeholders")
        print(f"   ⚠️  Need further prompt optimization")
        print(f"   ⚠️  Check AI service configuration")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Test interrupted")
    except Exception as e:
        print(f"\n🚫 Test failed: {e}")
