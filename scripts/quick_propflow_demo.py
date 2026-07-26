#!/usr/bin/env python3
"""
Quick PropFlow Demo Script
Simple script to demonstrate PropFlow capabilities.

Usage:
    python scripts/quick_propflow_demo.py           # Basic demo
    python scripts/quick_propflow_demo.py --real    # Use real Qwen API 
    python scripts/quick_propflow_demo.py --help    # Show options
"""

import asyncio
import argparse
import sys
import time
from pathlib import Path

# Add the server directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.propflow.tests.fixtures import SAMPLE_INQUIRIES, create_mock_thread_id
from app.propflow.graph import get_propflow_graph


async def run_demo(use_real_api: bool = False):
    """Run a quick PropFlow demonstration."""
    
    print("🏠 PropFlow AI Agent Demo")
    print("=" * 50)
    print(f"Mode: {'Real Qwen API' if use_real_api else 'Mock Mode'}")
    print()
    
    try:
        # Initialize PropFlow
        print("🔧 Initializing PropFlow...")
        graph = get_propflow_graph()
        print("✅ PropFlow ready!")
        
        # Test inquiry
        inquiry = SAMPLE_INQUIRIES["pidgin_basic"]
        thread_id = create_mock_thread_id()
        
        print(f"\n💬 Test Inquiry: '{inquiry}'")
        print(f"🆔 Thread ID: {thread_id}")
        
        # Build initial state
        initial_state = {
            "workflow_id": thread_id,
            "tenant_id": "550e8400-e29b-41d4-a716-446655440001",  # Sample tenant
            "raw_inquiry_text": inquiry,
            "current_stage": "started",
            "error_log": []
        }
        
        print("\n🚀 Running PropFlow workflow...")
        start_time = time.time()
        
        # Run the graph
        config = {"configurable": {"thread_id": thread_id}}
        final_state = await graph.ainvoke(initial_state, config=config)
        
        execution_time = time.time() - start_time
        
        if final_state:
            print(f"✅ Workflow completed in {execution_time:.2f} seconds")
            print(f"📊 Final stage: {final_state.get('current_stage', 'unknown')}")
            
            # Show key results
            if final_state.get("extracted_intent"):
                intent = final_state["extracted_intent"]
                print(f"🎯 Intent extracted: {intent.get('location', 'N/A')} - {intent.get('bedrooms', 'N/A')} beds - ₦{intent.get('budget_monthly', 0):,}")
                
            property_matches = final_state.get("property_matches", [])
            if property_matches:
                print(f"🏠 Property matches: {len(property_matches)}")
                for i, prop in enumerate(property_matches[:2], 1):  # Show first 2
                    print(f"   {i}. {prop.get('title', 'Unknown')} - ₦{prop.get('price', 0):,}/month")
            
            if final_state.get("application_id"):
                print(f"📝 Application created: {final_state['application_id']}")
                
            if final_state.get("landlord_briefing"):
                briefing = final_state["landlord_briefing"][:100] + "..." if len(final_state["landlord_briefing"]) > 100 else final_state["landlord_briefing"]
                print(f"📋 Landlord briefing: {briefing}")
                
            print("\n✅ Demo completed successfully!")
            
        else:
            print("❌ Workflow returned no results")
            return False
            
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        return False
    
    return True


def show_api_setup_help():
    """Show API setup instructions."""
    print("\n🔑 API Setup Instructions")
    print("=" * 30)
    print("To use real Qwen API, set up your .env file:")
    print()
    print("1. Get Qwen API key from: https://dashscope-intl.aliyuncs.com/")
    print("2. Add to server/.env:")
    print("   QWEN_API_KEY=sk-your-actual-key-here")
    print("   QWEN_API_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    print("   QWEN_ENABLED=true")
    print()
    print("3. Run with: python scripts/quick_propflow_demo.py --real")
    print()


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Quick PropFlow Demo")
    parser.add_argument("--real", action="store_true", help="Use real Qwen API (requires API key)")
    parser.add_argument("--help-setup", action="store_true", help="Show API setup instructions")
    
    args = parser.parse_args()
    
    if args.help_setup:
        show_api_setup_help()
        return 0
    
    print("Starting PropFlow demo...")
    print("This will test the complete AI rental workflow.")
    
    if args.real:
        print("\n⚠️  Real API mode will consume Qwen API credits")
        response = input("Continue? (y/N): ")
        if response.lower() != 'y':
            print("Demo cancelled.")
            return 0
    
    success = await run_demo(use_real_api=args.real)
    
    if success:
        print("\n🎉 Demo successful!")
        if not args.real:
            print("\n💡 Try --real flag to test with actual Qwen API")
        print("📚 See docs/hackathon/Qwen/SETUP_AND_TESTING_GUIDE.md for full setup")
        return 0
    else:
        print("\n💥 Demo failed - check configuration and try again")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)