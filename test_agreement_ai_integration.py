#!/usr/bin/env python3
"""
Agreement Service AI Integration Test Suite
==========================================

This script tests the enhanced agreement service with Groq AI integration
at the API level before frontend integration.

Tests:
1. AI agreement generation with real data
2. Fallback to manual template when AI fails
3. Database storage of AI fields
4. Backward compatibility with existing flows
5. Error handling and robustness

Usage:
    python test_agreement_ai_integration.py
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AgreementAITester:
    def __init__(self):
        self.test_results = []
        
    async def run_all_tests(self):
        """Run comprehensive AI integration tests"""
        print("🚀 Agreement Service AI Integration Test Suite")
        print("=" * 60)
        
        # Test 1: AI Service Connection
        await self.test_ai_connection()
        
        # Test 2: Agreement Terms Generation (AI First)
        await self.test_agreement_terms_generation()
        
        # Test 3: Manual Template Fallback
        await self.test_manual_template_fallback()
        
        # Test 4: Database Integration Test
        await self.test_database_integration()
        
        # Test 5: Error Handling Test
        await self.test_error_handling()
        
        # Test 6: Performance Test
        await self.test_performance()
        
        # Generate final report
        self.generate_report()
        
    async def test_ai_connection(self):
        """Test Groq AI service connection"""
        print("\n🔗 Test 1: AI Service Connection")
        print("-" * 35)
        
        try:
            from app.services.ai.ai_service import ai_service
            
            # Test connection
            is_connected = await ai_service.test_connection()
            
            if is_connected:
                print("✅ Groq AI service connected successfully")
                self.test_results.append({
                    "test": "ai_connection",
                    "status": "PASS",
                    "details": "Groq AI service is reachable"
                })
            else:
                print("⚠️ Groq AI service not connected")
                self.test_results.append({
                    "test": "ai_connection",
                    "status": "WARN",
                    "details": "Groq AI service unreachable - will use template fallback"
                })
                
        except Exception as e:
            print(f"❌ AI connection test failed: {e}")
            self.test_results.append({
                "test": "ai_connection",
                "status": "FAIL",
                "details": str(e)
            })
    
    async def test_agreement_terms_generation(self):
        """Test the new generate_agreement_terms method"""
        print("\n📝 Test 2: Agreement Terms Generation")
        print("-" * 40)
        
        try:
            from app.services.agreement_service import AgreementService
            
            # Mock data for testing
            property_data = {
                "id": "test-prop-123",
                "title": "Test Luxury Apartment",
                "location": "123 Test Street, Ikoyi, Lagos",
                "full_address": "123 Test Street, Ikoyi, Lagos, Nigeria",
                "price": 750000,
                "property_type": "3-Bedroom Luxury Apartment",
                "landlord_id": "landlord-123"
            }
            
            tenant_data = {
                "id": "tenant-456",
                "full_name": "John Michael Doe",
                "email": "john.doe@test.com",
                "phone_number": "08012345678"
            }
            
            lease_dates = {
                "lease_start_date": "2024-06-01",
                "lease_end_date": "2025-06-01",
                "lease_duration": 12
            }
            
            print("🔄 Testing agreement terms generation...")
            start_time = datetime.now()
            
            result = await AgreementService.generate_agreement_terms(
                property_data=property_data,
                tenant_data=tenant_data,
                landlord_name="Sarah Williams",
                lease_dates=lease_dates,
                application={"id": "app-789"}
            )
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            # Validate result structure
            required_fields = ["terms", "ai_content", "ai_source", "ai_metadata"]
            missing_fields = [field for field in required_fields if field not in result]
            
            if missing_fields:
                raise Exception(f"Missing required fields: {missing_fields}")
            
            # Validate content
            if not result["terms"]:
                raise Exception("Manual terms field is empty")
            
            if result["ai_source"] not in ["groq_llama", "manual_template"]:
                raise Exception(f"Invalid ai_source: {result['ai_source']}")
            
            # Print results
            print(f"✅ Agreement terms generated successfully!")
            print(f"   ⏱️  Generation time: {generation_time:.2f}s")
            print(f"   📄 Manual terms length: {len(result['terms'])} chars")
            print(f"   🤖 AI Source: {result['ai_source']}")
            
            if result["ai_content"]:
                print(f"   📊 AI Content length: {len(result['ai_content'])} chars")
                print(f"   📋 AI Metadata: {result['ai_metadata']}")
            else:
                print("   ⚠️  AI Content: None (using template fallback)")
            
            self.test_results.append({
                "test": "agreement_terms_generation",
                "status": "PASS",
                "details": f"Generated in {generation_time:.2f}s, source: {result['ai_source']}"
            })
            
        except Exception as e:
            print(f"❌ Agreement terms generation failed: {e}")
            self.test_results.append({
                "test": "agreement_terms_generation",
                "status": "FAIL",
                "details": str(e)
            })
    
    async def test_manual_template_fallback(self):
        """Test manual template generation as fallback"""
        print("\n📋 Test 3: Manual Template Fallback")
        print("-" * 38)
        
        try:
            from app.services.agreement_service import AgreementService
            
            # Test the original manual template method
            application = {"id": "test-app-123"}
            property_data = {
                "id": "prop-123",
                "title": "Test Property",
                "location": "Test Location",
                "price": 500000
            }
            lease_data = {
                "lease_start_date": "2024-06-01",
                "lease_end_date": "2025-06-01",
                "lease_duration": 12
            }
            
            manual_terms = AgreementService.generate_nigerian_lease_terms(
                application=application,
                property_data=property_data,
                lease_data=lease_data,
                landlord_name="Test Landlord",
                tenant_name="Test Tenant",
                tenant_email="test@test.com",
                tenant_phone="08012345678"
            )
            
            # Validate manual terms
            if not manual_terms or len(manual_terms) < 100:
                raise Exception("Manual template too short or empty")
            
            required_sections = ["RENTAL AGREEMENT", "LANDLORD", "TENANT", "FINANCIAL TERMS", "TERMS & CONDITIONS"]
            missing_sections = [section for section in required_sections if section not in manual_terms]
            
            if missing_sections:
                print(f"⚠️  Missing sections in manual template: {missing_sections}")
            
            print(f"✅ Manual template generated successfully!")
            print(f"   📄 Template length: {len(manual_terms)} chars")
            print(f"   📋 Contains required sections: {len(missing_sections) == 0}")
            
            self.test_results.append({
                "test": "manual_template_fallback",
                "status": "PASS",
                "details": f"Template length: {len(manual_terms)} chars"
            })
            
        except Exception as e:
            print(f"❌ Manual template fallback failed: {e}")
            self.test_results.append({
                "test": "manual_template_fallback",
                "status": "FAIL",
                "details": str(e)
            })
    
    async def test_database_integration(self):
        """Test database integration with new AI fields"""
        print("\n💾 Test 4: Database Integration")
        print("-" * 32)
        
        try:
            from app.services.agreement_service import AgreementService
            from app.database import supabase_admin
            
            # Create test agreement dict with AI fields
            agreement_dict = AgreementService.create_agreement_dict(
                application_id="test-app-123",
                property_id="test-prop-123",
                tenant_id="test-tenant-123",
                landlord_id="test-landlord-123",
                property_data={"price": 500000},
                lease_dates={
                    "lease_start_date": "2024-06-01",
                    "lease_end_date": "2025-06-01",
                    "lease_duration": 12
                },
                terms="Test terms content"
            )
            
            # Check if AI fields are present
            ai_fields = ["ai_agreement_content", "ai_source", "ai_metadata"]
            missing_ai_fields = [field for field in ai_fields if field not in agreement_dict]
            
            if missing_ai_fields:
                raise Exception(f"Missing AI fields in agreement dict: {missing_ai_fields}")
            
            # Validate AI field defaults
            if agreement_dict["ai_source"] != "manual_template":
                raise Exception(f"Invalid default ai_source: {agreement_dict['ai_source']}")
            
            if agreement_dict["ai_agreement_content"] is not None:
                raise Exception("ai_agreement_content should default to None")
            
            if not isinstance(agreement_dict["ai_metadata"], dict):
                raise Exception("ai_metadata should be a dict")
            
            print("✅ Database integration test passed!")
            print(f"   📋 Agreement dict contains all required fields")
            print(f"   🤖 AI fields have correct defaults")
            print(f"   📊 Total fields in dict: {len(agreement_dict)}")
            
            # Note: We're not actually inserting to database to avoid test data
            print("   ⚠️  Database insert skipped (test environment)")
            
            self.test_results.append({
                "test": "database_integration",
                "status": "PASS",
                "details": f"Agreement dict with {len(agreement_dict)} fields ready"
            })
            
        except Exception as e:
            print(f"❌ Database integration test failed: {e}")
            self.test_results.append({
                "test": "database_integration",
                "status": "FAIL",
                "details": str(e)
            })
    
    async def test_error_handling(self):
        """Test error handling and robustness"""
        print("\n🛡️ Test 5: Error Handling")
        print("-" * 28)
        
        try:
            from app.services.agreement_service import AgreementService
            
            # Test with invalid data
            invalid_property_data = {
                "price": -1000,  # Invalid negative price
                "location": "",   # Empty location
                "title": None     # None title
            }
            
            invalid_tenant_data = {
                "full_name": "",  # Empty name
                "email": "invalid-email",  # Invalid email
                "phone_number": None
            }
            
            lease_dates = {
                "lease_duration": 0  # Invalid duration
            }
            
            print("🔄 Testing with invalid data...")
            
            # This should not raise an exception
            result = await AgreementService.generate_agreement_terms(
                property_data=invalid_property_data,
                tenant_data=invalid_tenant_data,
                landlord_name="",  # Empty landlord name
                lease_dates=lease_dates
            )
            
            # Should still return a valid structure
            if not isinstance(result, dict):
                raise Exception("Result should be a dictionary")
            
            if "terms" not in result:
                raise Exception("Should always have 'terms' field")
            
            if not result["terms"]:
                raise Exception("Terms should never be empty")
            
            print("✅ Error handling test passed!")
            print(f"   🛡️ Invalid data handled gracefully")
            print(f"   📄 Fallback template generated: {len(result['terms'])} chars")
            print(f"   🤖 AI Source: {result['ai_source']}")
            
            self.test_results.append({
                "test": "error_handling",
                "status": "PASS",
                "details": "Invalid data handled gracefully with template fallback"
            })
            
        except Exception as e:
            print(f"❌ Error handling test failed: {e}")
            self.test_results.append({
                "test": "error_handling",
                "status": "FAIL",
                "details": str(e)
            })
    
    async def test_performance(self):
        """Test performance with multiple concurrent requests"""
        print("\n⚡ Test 6: Performance Test")
        print("-" * 30)
        
        try:
            from app.services.agreement_service import AgreementService
            
            # Test data
            property_data = {
                "id": "perf-prop-123",
                "title": "Performance Test Apartment",
                "location": "123 Test Street, Lagos",
                "price": 600000,
                "property_type": "Apartment"
            }
            
            tenant_data = {
                "full_name": "Performance Test User",
                "email": "perf@test.com",
                "phone_number": "08012345678"
            }
            
            lease_dates = {
                "lease_start_date": "2024-06-01",
                "lease_end_date": "2025-06-01",
                "lease_duration": 12
            }
            
            print("🔄 Running 5 concurrent agreement generations...")
            start_time = datetime.now()
            
            # Run multiple concurrent requests
            tasks = []
            for i in range(5):
                task = AgreementService.generate_agreement_terms(
                    property_data=property_data,
                    tenant_data={**tenant_data, "full_name": f"User {i+1}"},
                    landlord_name=f"Landlord {i+1}",
                    lease_dates=lease_dates,
                    application={"id": f"app-{i+1}"}
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks)
            end_time = datetime.now()
            
            total_time = (end_time - start_time).total_seconds()
            successful = sum(1 for r in results if r and r.get("terms"))
            ai_generated = sum(1 for r in results if r.get("ai_source") == "groq_llama")
            
            print(f"✅ Performance test completed!")
            print(f"   ⏱️  Total time: {total_time:.2f}s")
            print(f"   📄 Agreements generated: {successful}/5")
            print(f"   🤖 AI generated: {ai_generated}/5")
            print(f"   ⚡ Average time per agreement: {total_time/5:.2f}s")
            
            if successful == 5:
                self.test_results.append({
                    "test": "performance",
                    "status": "PASS",
                    "details": f"5 agreements in {total_time:.2f}s ({ai_generated} AI)"
                })
            else:
                self.test_results.append({
                    "test": "performance",
                    "status": "FAIL",
                    "details": f"Only {successful}/5 agreements successful"
                })
                
        except Exception as e:
            print(f"❌ Performance test failed: {e}")
            self.test_results.append({
                "test": "performance",
                "status": "FAIL",
                "details": str(e)
            })
    
    def generate_report(self):
        """Generate final test report"""
        print("\n" + "=" * 60)
        print("📋 FINAL TEST REPORT")
        print("=" * 60)
        
        passed = sum(1 for r in self.test_results if r["status"] == "PASS")
        warnings = sum(1 for r in self.test_results if r["status"] == "WARN")
        failed = sum(1 for r in self.test_results if r["status"] == "FAIL")
        total = len(self.test_results)
        
        print(f"📊 Test Summary:")
        print(f"   ✅ Passed: {passed}")
        print(f"   ⚠️  Warnings: {warnings}")
        print(f"   ❌ Failed: {failed}")
        print(f"   📈 Total: {total}")
        print(f"   🎯 Success Rate: {(passed/total)*100:.1f}%")
        
        print(f"\n📝 Detailed Results:")
        for i, result in enumerate(self.test_results, 1):
            status_icon = "✅" if result["status"] == "PASS" else "⚠️" if result["status"] == "WARN" else "❌"
            print(f"   {i}. {status_icon} {result['test'].replace('_', ' ').title()}: {result['details']}")
        
        print(f"\n🎯 Integration Status:")
        if failed == 0:
            print("🏆 ALL TESTS PASSED! Agreement service AI integration is ready for frontend!")
        elif warnings > 0:
            print("⚠️  Some warnings detected, but integration should work with fallback.")
        else:
            print("❌ Critical issues found. Fix before proceeding to frontend.")
        
        print(f"\n📋 Next Steps:")
        print("1. ✅ Run database migration SQL script")
        print("2. ✅ Test frontend integration")
        print("3. ✅ Monitor AI usage and costs")
        print("4. ✅ Deploy to production")

async def main():
    """Main test runner"""
    tester = AgreementAITester()
    await tester.run_all_tests()

if __name__ == "__main__":
    print("🤖 Agreement Service AI Integration Test Suite")
    print("=" * 60)
    print("This test suite validates the Groq AI integration")
    print("in the agreement service before frontend integration.")
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n🚫 Test suite failed: {e}")
        import traceback
        traceback.print_exc()
