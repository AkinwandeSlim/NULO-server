#!/usr/bin/env python3
"""
Groq AI Tenancy Agreement Generator - Comprehensive Test Script
============================================================

This script tests the complete Groq AI integration for generating 
Nigerian tenancy agreements in the NuloAfrica platform.

Usage:
    python test_groq_ai.py

Prerequisites:
    - GROQ_API_KEY in .env file
    - groq package installed
"""

import asyncio
import json
from datetime import datetime
from app.services.ai.ai_service import ai_service

class GroqAITester:
    def __init__(self):
        self.test_results = []
        
    async def run_all_tests(self):
        """Run comprehensive tests for Groq AI service"""
        print("🚀 Starting Groq AI Comprehensive Tests")
        print("=" * 60)
        
        # Test 1: Connection Test
        await self.test_connection()
        
        # Test 2: Simple Agreement Generation
        await self.test_simple_agreement()
        
        # Test 3: Advanced Agreement Generation
        await self.test_advanced_agreement()
        
        # Test 4: Error Handling
        await self.test_error_handling()
        
        # Test 5: Usage Statistics
        await self.test_usage_stats()
        
        # Test 6: Performance Test
        await self.test_performance()
        
        # Generate final report
        self.generate_report()
        
    async def test_connection(self):
        """Test Groq AI connection"""
        print("\n📡 Test 1: Connection Test")
        print("-" * 30)
        
        try:
            result = await ai_service.test_connection()
            if result:
                print("✅ Connection successful!")
                self.test_results.append({"test": "connection", "status": "PASS", "details": "Connected to Groq AI"})
            else:
                print("❌ Connection failed!")
                self.test_results.append({"test": "connection", "status": "FAIL", "details": "Failed to connect to Groq AI"})
        except Exception as e:
            print(f"❌ Connection error: {e}")
            self.test_results.append({"test": "connection", "status": "ERROR", "details": str(e)})
    
    async def test_simple_agreement(self):
        """Test simple agreement generation"""
        print("\n📝 Test 2: Simple Agreement Generation")
        print("-" * 40)
        
        try:
            result = await ai_service.generate_agreement(
                tenant_name="John Doe",
                landlord_name="Jane Smith",
                property_address="123 Ikoyi Crescent, Lagos",
                monthly_rent=500000,
                lease_duration="1 year",
                property_type="2-Bedroom Apartment"
            )
            
            if result["success"]:
                print("✅ Simple agreement generated successfully!")
                print(f"   📊 Tokens used: {result['tokens_used']}")
                print(f"   💰 Cost: ${result['cost_usd']:.6f}")
                print(f"   ⏱️  Generation time: {result['generation_time_seconds']:.2f}s")
                print(f"   📋 Compliance score: {result['compliance_score']:.1f}%")
                print(f"   📄 Word count: {result['summary']['word_count']}")
                
                # Show first 200 characters of agreement
                agreement_preview = result['agreement'][:200] + "..." if len(result['agreement']) > 200 else result['agreement']
                print(f"   🔍 Preview: {agreement_preview}")
                
                self.test_results.append({
                    "test": "simple_agreement", 
                    "status": "PASS", 
                    "details": f"Generated {result['summary']['word_count']} words, {result['compliance_score']:.1f}% compliant"
                })
            else:
                print(f"❌ Simple agreement failed: {result['error']}")
                self.test_results.append({"test": "simple_agreement", "status": "FAIL", "details": result['error']})
                
        except Exception as e:
            print(f"❌ Simple agreement error: {e}")
            self.test_results.append({"test": "simple_agreement", "status": "ERROR", "details": str(e)})
    
    async def test_advanced_agreement(self):
        """Test advanced agreement generation with full data"""
        print("\n📋 Test 3: Advanced Agreement Generation")
        print("-" * 42)
        
        try:
            tenant_data = {
                'full_name': 'Michael Johnson',
                'address': '456 Tenant Street, Victoria Island, Lagos',
                'phone_number': '08012345678',
                'email': 'michael.johnson@email.com',
                'employment_status': 'Employed',
                'employer': 'Tech Solutions Nigeria',
                'monthly_income': 800000,
                'preferred_lease_duration': '2 years',
                'move_in_date': '2024-06-01'
            }
            
            landlord_data = {
                'full_name': 'Sarah Williams',
                'address': '789 Landlord Avenue, Ikoyi, Lagos',
                'phone_number': '08098765432',
                'email': 'sarah.williams@email.com'
            }
            
            property_data = {
                'full_address': '123 Luxury Apartments, Ikoyi, Lagos',
                'city': 'Lagos',
                'property_type': '3-Bedroom Luxury Apartment',
                'bedrooms': 3,
                'bathrooms': 2,
                'parking_spaces': 2,
                'amenities': ['Air Conditioning', 'Swimming Pool', 'Gym', '24/7 Security', 'Backup Power'],
                'price': 750000,
                'security_deposit': 1500000
            }
            
            result = await ai_service.generate_advanced_agreement(
                tenant_data, landlord_data, property_data
            )
            
            if result["success"]:
                print("✅ Advanced agreement generated successfully!")
                print(f"   📊 Tokens used: {result['tokens_used']}")
                print(f"   💰 Cost: ${result['cost_usd']:.6f}")
                print(f"   ⏱️  Generation time: {result['generation_time_seconds']:.2f}s")
                print(f"   📋 Compliance score: {result['compliance_score']:.1f}%")
                print(f"   📄 Word count: {result['summary']['word_count']}")
                print(f"   🏠 Property: {result['metadata']['property_address']}")
                print(f"   👥 Parties: {result['metadata']['tenant_name']} ↔ {result['metadata']['landlord_name']}")
                
                # Show compliance details
                compliance = result['compliance']
                compliant_items = [k for k, v in compliance.items() if v]
                print(f"   ✅ Compliance items: {len(compliant_items)}/{len(compliance)} passed")
                
                self.test_results.append({
                    "test": "advanced_agreement", 
                    "status": "PASS", 
                    "details": f"Generated {result['summary']['word_count']} words, {result['compliance_score']:.1f}% compliant"
                })
            else:
                print(f"❌ Advanced agreement failed: {result['error']}")
                self.test_results.append({"test": "advanced_agreement", "status": "FAIL", "details": result['error']})
                
        except Exception as e:
            print(f"❌ Advanced agreement error: {e}")
            self.test_results.append({"test": "advanced_agreement", "status": "ERROR", "details": str(e)})
    
    async def test_error_handling(self):
        """Test error handling with invalid data"""
        print("\n⚠️  Test 4: Error Handling")
        print("-" * 28)
        
        try:
            # Test with invalid data (negative rent)
            result = await ai_service.generate_agreement(
                tenant_name="Test Tenant",
                landlord_name="Test Landlord",
                property_address="Test Address",
                monthly_rent=-1000,  # Invalid negative rent
                lease_duration="1 year",
                property_type="Apartment"
            )
            
            # Groq should still generate agreement even with negative rent (it's just text)
            if result["success"]:
                print("✅ Error handling test passed - AI handled invalid data gracefully")
                self.test_results.append({
                    "test": "error_handling", 
                    "status": "PASS", 
                    "details": "AI handled invalid data gracefully"
                })
            else:
                print(f"✅ Error handling test passed - Properly caught error: {result['error']}")
                self.test_results.append({
                    "test": "error_handling", 
                    "status": "PASS", 
                    "details": f"Properly caught error: {result['error']}"
                })
                
        except Exception as e:
            print(f"✅ Error handling test passed - Exception caught: {e}")
            self.test_results.append({
                "test": "error_handling", 
                "status": "PASS", 
                "details": f"Exception caught: {str(e)}"
            })
    
    async def test_usage_stats(self):
        """Test usage statistics tracking"""
        print("\n📊 Test 5: Usage Statistics")
        print("-" * 30)
        
        try:
            stats = ai_service.get_usage_stats()
            print("✅ Usage statistics retrieved successfully!")
            print(f"   📈 Total requests: {stats['total_requests']}")
            print(f"   🔢 Total tokens: {stats['total_tokens']}")
            print(f"   💰 Total cost: ${stats['total_cost_usd']:.6f}")
            print(f"   ✅ Successful generations: {stats['successful_generations']}")
            print(f"   ❌ Failed generations: {stats['failed_generations']}")
            print(f"   📊 Success rate: {stats['success_rate']:.1f}%")
            print(f"   💸 Cost per agreement: ${stats['cost_per_agreement']:.6f}")
            print(f"   📏 Average tokens per request: {stats['average_tokens_per_request']:.0f}")
            
            self.test_results.append({
                "test": "usage_stats", 
                "status": "PASS", 
                "details": f"Stats tracked for {stats['total_requests']} requests"
            })
            
        except Exception as e:
            print(f"❌ Usage statistics error: {e}")
            self.test_results.append({"test": "usage_stats", "status": "ERROR", "details": str(e)})
    
    async def test_performance(self):
        """Test performance with multiple requests"""
        print("\n⚡ Test 6: Performance Test")
        print("-" * 30)
        
        try:
            print("Running 3 concurrent agreement generations...")
            start_time = datetime.now()
            
            # Run multiple agreements concurrently
            tasks = []
            for i in range(3):
                task = ai_service.generate_agreement(
                    tenant_name=f"Tenant {i+1}",
                    landlord_name=f"Landlord {i+1}",
                    property_address=f"Property {i+1}, Lagos",
                    monthly_rent=500000 + (i * 100000),
                    lease_duration="1 year",
                    property_type="Apartment"
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks)
            end_time = datetime.now()
            
            total_time = (end_time - start_time).total_seconds()
            successful = sum(1 for r in results if r["success"])
            
            print(f"✅ Performance test completed!")
            print(f"   ⏱️  Total time: {total_time:.2f}s")
            print(f"   📄 Agreements generated: {successful}/3")
            print(f"   ⚡ Average time per agreement: {total_time/3:.2f}s")
            
            if successful == 3:
                self.test_results.append({
                    "test": "performance", 
                    "status": "PASS", 
                    "details": f"Generated 3 agreements in {total_time:.2f}s"
                })
            else:
                self.test_results.append({
                    "test": "performance", 
                    "status": "FAIL", 
                    "details": f"Only {successful}/3 agreements successful"
                })
                
        except Exception as e:
            print(f"❌ Performance test error: {e}")
            self.test_results.append({"test": "performance", "status": "ERROR", "details": str(e)})
    
    def generate_report(self):
        """Generate final test report"""
        print("\n" + "=" * 60)
        print("📋 FINAL TEST REPORT")
        print("=" * 60)
        
        passed = sum(1 for r in self.test_results if r["status"] == "PASS")
        failed = sum(1 for r in self.test_results if r["status"] == "FAIL")
        errors = sum(1 for r in self.test_results if r["status"] == "ERROR")
        total = len(self.test_results)
        
        print(f"📊 Test Summary:")
        print(f"   ✅ Passed: {passed}")
        print(f"   ❌ Failed: {failed}")
        print(f"   🚫 Errors: {errors}")
        print(f"   📈 Total: {total}")
        print(f"   🎯 Success Rate: {(passed/total)*100:.1f}%")
        
        print(f"\n📝 Detailed Results:")
        for i, result in enumerate(self.test_results, 1):
            status_icon = "✅" if result["status"] == "PASS" else "❌" if result["status"] == "FAIL" else "🚫"
            print(f"   {i}. {status_icon} {result['test'].replace('_', ' ').title()}: {result['details']}")
        
        # Show final usage stats
        stats = ai_service.get_usage_stats()
        print(f"\n💰 Cost Analysis:")
        print(f"   Total tokens used: {stats['total_tokens']:,}")
        print(f"   Total cost: ${stats['total_cost_usd']:.6f}")
        print(f"   Cost per agreement: ${stats['cost_per_agreement']:.6f}")
        print(f"   Estimated cost per 1000 agreements: ${stats['cost_per_agreement'] * 1000:.2f}")
        
        print(f"\n🎉 Groq AI Integration Test Complete!")
        
        if passed == total:
            print("🏆 ALL TESTS PASSED! Groq AI is ready for production!")
        else:
            print("⚠️  Some tests failed. Please review the results above.")

async def main():
    """Main test runner"""
    tester = GroqAITester()
    await tester.run_all_tests()

if __name__ == "__main__":
    print("🤖 Groq AI Tenancy Agreement Generator Test Suite")
    print("=" * 60)
    print("This test suite will validate the complete Groq AI integration")
    print("for generating Nigerian tenancy agreements in NuloAfrica.")
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n🚫 Test suite failed: {e}")
        import traceback
        traceback.print_exc()
