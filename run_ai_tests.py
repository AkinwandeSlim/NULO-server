#!/usr/bin/env python3
"""
AI Integration Test Runner
==========================

Quick script to run all AI integration tests for the agreement service.

Usage:
    python run_ai_tests.py
"""

import asyncio
import subprocess
import sys
from pathlib import Path

async def run_test_script(script_name: str, description: str):
    """Run a test script and display results"""
    print(f"\n{'='*60}")
    print(f"🧪 Running: {description}")
    print(f"📁 Script: {script_name}")
    print(f"{'='*60}")
    
    try:
        # Run the test script
        result = subprocess.run(
            [sys.executable, script_name],
            capture_output=False,
            text=True,
            cwd=Path(__file__).parent
        )
        
        if result.returncode == 0:
            print(f"\n✅ {description} completed successfully!")
        else:
            print(f"\n❌ {description} failed with return code {result.returncode}")
            
        return result.returncode == 0
        
    except Exception as e:
        print(f"\n🚫 Error running {description}: {e}")
        return False

async def main():
    """Run all AI integration tests"""
    print("🚀 NuloAfrica AI Integration Test Runner")
    print("=" * 60)
    print("This will run all tests to validate the Groq AI integration")
    print("in the agreement service before frontend integration.")
    print()
    
    tests = [
        ("test_agreement_ai_integration.py", "Comprehensive AI Integration Tests"),
        ("test_agreement_api_endpoints.py", "API-Level Agreement Service Tests"),
    ]
    
    results = []
    
    for script_name, description in tests:
        success = await run_test_script(script_name, description)
        results.append((description, success))
        
        # Ask user if they want to continue
        if not success:
            response = input(f"\n⚠️  {description} failed. Continue with next test? (y/n): ")
            if response.lower() != 'y':
                break
        
        print("\n" + "-"*60)
        input("Press Enter to continue to next test...")
    
    # Final summary
    print(f"\n{'='*60}")
    print("📋 FINAL TEST SUMMARY")
    print(f"{'='*60}")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for description, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"   {status} {description}")
    
    print(f"\n📊 Overall Result: {passed}/{total} test suites passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        print("✅ AI integration is ready for frontend development!")
        print("\n📋 Next Steps:")
        print("1. Run database migration: database_updates/add_ai_fields_to_agreements.sql")
        print("2. Start frontend integration")
        print("3. Test end-to-end user flows")
    else:
        print(f"\n⚠️  {total - passed} test suite(s) failed.")
        print("🔧 Please fix issues before proceeding to frontend integration.")
    
    print(f"\n🏁 Test runner completed!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Test runner interrupted by user")
    except Exception as e:
        print(f"\n🚫 Test runner failed: {e}")
        import traceback
        traceback.print_exc()
