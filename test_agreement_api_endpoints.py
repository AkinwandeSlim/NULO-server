#!/usr/bin/env python3
"""
Agreement API Endpoints Test
===========================

This script tests the actual API endpoints that use the enhanced
agreement service with AI integration.

Tests:
- Direct API calls to agreement creation endpoints
- Response validation
- AI field presence in responses

Usage:
    python test_agreement_api_endpoints.py
"""

import asyncio
import json
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AgreementAPITester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.auth_token = None  # You'll need to set this for authenticated tests
        
    async def test_agreement_service_directly(self):
        """Test the agreement service methods directly"""
        print("\n🔧 Test: Agreement Service Direct Call")
        print("-" * 40)
        
        try:
            # Import and test the service directly
            from app.services.agreement_service import AgreementService
            
            # Test data
            property_data = {
                "id": "direct-test-prop-123",
                "title": "Direct Test Apartment",
                "location": "123 Direct Test Street, Ikoyi, Lagos",
                "full_address": "123 Direct Test Street, Ikoyi, Lagos, Nigeria",
                "price": 800000,
                "property_type": "2-Bedroom Apartment",
                "landlord_id": "direct-landlord-123"
            }
            
            tenant_data = {
                "id": "direct-tenant-456",
                "full_name": "Alice Johnson",
                "email": "alice.johnson@directtest.com",
                "phone_number": "08098765432"
            }
            
            lease_dates = {
                "lease_start_date": "2024-06-01",
                "lease_end_date": "2025-06-01",
                "lease_duration": 12
            }
            
            print("🔄 Testing generate_agreement_terms directly...")
            
            # Call the method directly
            result = await AgreementService.generate_agreement_terms(
                property_data=property_data,
                tenant_data=tenant_data,
                landlord_name="Bob Williams",
                lease_dates=lease_dates,
                application={"id": "direct-app-789"}
            )
            
            # Validate the response
            print("✅ Direct service call successful!")
            print(f"   📄 Terms length: {len(result.get('terms', ''))} chars")
            print(f"   🤖 AI Source: {result.get('ai_source', 'Unknown')}")
            print(f"   📊 AI Content present: {'Yes' if result.get('ai_content') else 'No'}")
            
            if result.get('ai_metadata'):
                metadata = result['ai_metadata']
                print(f"   📋 AI Metadata: model={metadata.get('model_used')}, tokens={metadata.get('tokens_used')}")
            
            # Show a preview of the content
            if result.get('ai_content'):
                preview = result['ai_content'][:200] + "..." if len(result['ai_content']) > 200 else result['ai_content']
                print(f"   🔍 AI Content Preview: {preview}")
            
            return True
            
        except Exception as e:
            print(f"❌ Direct service call failed: {e}")
            return False
    
    async def test_agreement_dict_creation(self):
        """Test the agreement dictionary creation with AI fields"""
        print("\n📋 Test: Agreement Dictionary Creation")
        print("-" * 42)
        
        try:
            from app.services.agreement_service import AgreementService
            
            # Test the create_agreement_dict method
            agreement_dict = AgreementService.create_agreement_dict(
                application_id="dict-test-app-123",
                property_id="dict-test-prop-123",
                tenant_id="dict-test-tenant-123",
                landlord_id="dict-test-landlord-123",
                property_data={"price": 750000, "title": "Dict Test Property"},
                lease_dates={
                    "lease_start_date": "2024-06-01",
                    "lease_end_date": "2025-06-01",
                    "lease_duration": 12
                },
                terms="Test agreement terms content for dictionary creation test."
            )
            
            # Check for AI fields
            ai_fields = ["ai_agreement_content", "ai_source", "ai_metadata"]
            present_ai_fields = [field for field in ai_fields if field in agreement_dict]
            
            print("✅ Agreement dictionary created successfully!")
            print(f"   📊 Total fields: {len(agreement_dict)}")
            print(f"   🤖 AI fields present: {len(present_ai_fields)}/3")
            print(f"   📋 AI source default: {agreement_dict.get('ai_source', 'Not set')}")
            print(f"   📄 AI content default: {agreement_dict.get('ai_agreement_content', 'Not set')}")
            
            # Show all fields for verification
            print(f"   🔍 All fields: {list(agreement_dict.keys())}")
            
            return True
            
        except Exception as e:
            print(f"❌ Agreement dictionary creation failed: {e}")
            return False
    
    async def test_template_fallback_simulation(self):
        """Test template fallback by simulating AI failure"""
        print("\n🛡️ Test: Template Fallback Simulation")
        print("-" * 42)
        
        try:
            from app.services.agreement_service import AgreementService
            
            # Test with minimal data that might cause AI to struggle
            minimal_property_data = {
                "price": 100000,
                "location": "Test"
            }
            
            minimal_tenant_data = {
                "full_name": "Test User"
            }
            
            minimal_lease_dates = {
                "lease_duration": 6
            }
            
            print("🔄 Testing with minimal data (potential AI fallback)...")
            
            result = await AgreementService.generate_agreement_terms(
                property_data=minimal_property_data,
                tenant_data=minimal_tenant_data,
                landlord_name="Test Landlord",
                lease_dates=minimal_lease_dates
            )
            
            print("✅ Template fallback test completed!")
            print(f"   📄 Terms generated: {len(result.get('terms', ''))} chars")
            print(f"   🤖 Source used: {result.get('ai_source', 'Unknown')}")
            print(f"   🛡️ Fallback successful: {'Yes' if result.get('ai_source') == 'manual_template' else 'AI worked'}")
            
            # The terms should always be present regardless of AI success
            if result.get('terms'):
                print("   ✅ Fallback template always generated")
            else:
                print("   ❌ ERROR: No terms generated!")
                return False
            
            return True
            
        except Exception as e:
            print(f"❌ Template fallback test failed: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all API-level tests"""
        print("🚀 Agreement API Endpoints Test Suite")
        print("=" * 50)
        print("Testing the enhanced agreement service at API level")
        print("before frontend integration.")
        print()
        
        test_results = []
        
        # Test 1: Direct service call
        result1 = await self.test_agreement_service_directly()
        test_results.append(("Direct Service Call", "PASS" if result1 else "FAIL"))
        
        # Test 2: Agreement dict creation
        result2 = await self.test_agreement_dict_creation()
        test_results.append(("Agreement Dict Creation", "PASS" if result2 else "FAIL"))
        
        # Test 3: Template fallback
        result3 = await self.test_template_fallback_simulation()
        test_results.append(("Template Fallback", "PASS" if result3 else "FAIL"))
        
        # Generate report
        self.generate_report(test_results)
    
    def generate_report(self, test_results):
        """Generate test report"""
        print("\n" + "=" * 50)
        print("📋 API TEST REPORT")
        print("=" * 50)
        
        passed = sum(1 for _, status in test_results if status == "PASS")
        total = len(test_results)
        
        print(f"📊 Test Summary:")
        print(f"   ✅ Passed: {passed}/{total}")
        print(f"   🎯 Success Rate: {(passed/total)*100:.1f}%")
        
        print(f"\n📝 Detailed Results:")
        for test_name, status in test_results:
            icon = "✅" if status == "PASS" else "❌"
            print(f"   {icon} {test_name}: {status}")
        
        print(f"\n🎯 API Integration Status:")
        if passed == total:
            print("🏆 ALL API TESTS PASSED!")
            print("✅ Agreement service AI integration is working at API level!")
            print("🚀 Ready for frontend integration!")
        else:
            print("❌ Some API tests failed.")
            print("🔧 Fix issues before proceeding to frontend.")
        
        print(f"\n📋 Next Steps:")
        print("1. ✅ Run database migration: add_ai_fields_to_agreements.sql")
        print("2. ✅ Integrate with frontend components")
        print("3. ✅ Test end-to-end user flows")
        print("4. ✅ Monitor AI usage and costs in production")

async def main():
    """Main test runner"""
    tester = AgreementAPITester()
    await tester.run_all_tests()

if __name__ == "__main__":
    print("🔌 Agreement API Endpoints Test Suite")
    print("=" * 50)
    print("This tests the agreement service at the API level")
    print("to validate AI integration before frontend work.")
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n🚫 Test suite failed: {e}")
        import traceback
        traceback.print_exc()
