#!/usr/bin/env python3
"""
PropFlow End-to-End Test Script
Comprehensive testing framework for PropFlow AI agent.

Usage:
    python scripts/test_propflow_e2e.py --mock                    # Mock mode
    python scripts/test_propflow_e2e.py --scenario "Happy Path"   # Specific scenario
    python scripts/test_propflow_e2e.py --all-scenarios          # All scenarios
    python scripts/test_propflow_e2e.py --help                   # Show help
"""

import asyncio
import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add the server directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.propflow.tests.fixtures import (
    TEST_SCENARIOS,
    SAMPLE_TENANTS,
    SAMPLE_INQUIRIES,
    create_mock_thread_id
)
from app.propflow.graph import get_propflow_graph
from app.propflow.config import get_propflow_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PropFlowE2ETester:
    """End-to-end test runner for PropFlow scenarios."""
    
    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode
        self.settings = get_propflow_settings()
        self.graph = None
        self.results: List[Dict[str, Any]] = []
        
    async def setup(self):
        """Initialize test environment."""
        logger.info("Setting up PropFlow E2E test environment...")
        
        try:
            self.graph = get_propflow_graph()
            logger.info("✅ PropFlow graph initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize PropFlow graph: {e}")
            raise
            
        # Verify configuration
        if not self.mock_mode:
            if not self.settings.QWEN_API_KEY:
                raise ValueError("QWEN_API_KEY required for real API mode")
            logger.info("✅ Qwen API key configured")
        else:
            logger.info("✅ Mock mode - no API keys required")
    
    async def run_scenario(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single test scenario."""
        scenario_name = scenario["name"]
        logger.info(f"\n🧪 Running scenario: {scenario_name}")
        
        start_time = time.time()
        thread_id = create_mock_thread_id()
        
        result = {
            "scenario": scenario_name,
            "thread_id": thread_id,
            "start_time": start_time,
            "success": False,
            "error": None,
            "stages_completed": [],
            "final_stage": None,
            "execution_time": None
        }
        
        try:
            # Build initial state
            tenant = scenario["tenant"]
            inquiry = scenario["inquiry"]
            
            initial_state = {
                "workflow_id": thread_id,
                "tenant_id": tenant["id"],
                "raw_inquiry_text": inquiry,
                "current_stage": "started",
                "error_log": []
            }
            
            logger.info(f"📝 Tenant: {tenant['full_name']} ({tenant['email']})")
            logger.info(f"💬 Inquiry: {inquiry[:60]}...")
            
            # Configure graph for test
            config = {"configurable": {"thread_id": thread_id}}
            
            # Run the workflow
            logger.info("🚀 Starting PropFlow workflow...")
            
            final_state = await self.graph.ainvoke(initial_state, config=config)
            
            if final_state:
                result["success"] = True
                result["final_stage"] = final_state.get("current_stage", "unknown")
                result["stages_completed"] = self._extract_stages_from_state(final_state)
                
                logger.info(f"✅ Workflow completed successfully")
                logger.info(f"📊 Final stage: {result['final_stage']}")
                logger.info(f"🏁 Stages completed: {len(result['stages_completed'])}")
                
                # Validate expected outcomes
                if "expected_final_stage" in scenario:
                    expected = scenario["expected_final_stage"]
                    actual = result["final_stage"]
                    
                    if actual == expected:
                        logger.info(f"✅ Expected stage reached: {expected}")
                    else:
                        logger.warning(f"⚠️  Stage mismatch - Expected: {expected}, Got: {actual}")
                
                # Check property matches
                if "expected_property_matches" in scenario:
                    expected_matches = scenario["expected_property_matches"]
                    actual_matches = len(final_state.get("property_matches", []))
                    
                    if actual_matches == expected_matches:
                        logger.info(f"✅ Property matches correct: {actual_matches}")
                    else:
                        logger.warning(f"⚠️  Property match count - Expected: {expected_matches}, Got: {actual_matches}")
                
            else:
                result["error"] = "Workflow returned None"
                logger.error("❌ Workflow returned None - this should not happen")
                
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"❌ Scenario failed: {e}")
            
        finally:
            result["execution_time"] = time.time() - start_time
            logger.info(f"⏱️  Execution time: {result['execution_time']:.2f}s")
            
        return result
    
    def _extract_stages_from_state(self, state: Dict[str, Any]) -> List[str]:
        """Extract completed stages from final state."""
        stages = ["started"]
        
        if state.get("extracted_intent"):
            stages.append("intent_extracted")
            
        if state.get("property_matches"):
            stages.append("property_matched")
        elif state.get("current_stage") == "no_properties_found":
            stages.append("no_properties_found")
            
        if state.get("application_id"):
            stages.append("application_created")
            
        if state.get("landlord_briefing"):
            stages.append("enrich_qualified")
            
        if state.get("application_status") == "approved":
            stages.append("landlord_approved")
        elif state.get("application_status") == "rejected":
            stages.append("rejected")
            
        if state.get("agreement_id"):
            stages.append("agreement_created")
            
        if state.get("nomba_virtual_account_number"):
            stages.append("nomba_provisioned")
            
        if state.get("disbursement_merchant_tx_ref"):
            stages.append("disbursement_complete")
            
        return stages
    
    async def run_scenarios(self, scenarios: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run multiple test scenarios."""
        logger.info(f"🎯 Running {len(scenarios)} test scenario(s)")
        
        for i, scenario in enumerate(scenarios, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"SCENARIO {i}/{len(scenarios)}")
            logger.info(f"{'='*60}")
            
            result = await self.run_scenario(scenario)
            self.results.append(result)
            
            # Brief pause between scenarios
            await asyncio.sleep(1)
        
        return self.results
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate test execution report."""
        if not self.results:
            return {"error": "No test results available"}
        
        total_scenarios = len(self.results)
        successful_scenarios = sum(1 for r in self.results if r["success"])
        failed_scenarios = total_scenarios - successful_scenarios
        
        total_time = sum(r["execution_time"] for r in self.results)
        avg_time = total_time / total_scenarios if total_scenarios > 0 else 0
        
        report = {
            "test_summary": {
                "total_scenarios": total_scenarios,
                "successful": successful_scenarios,
                "failed": failed_scenarios,
                "success_rate": successful_scenarios / total_scenarios * 100,
                "total_execution_time": total_time,
                "average_execution_time": avg_time
            },
            "scenario_results": self.results,
            "test_mode": "mock" if self.mock_mode else "real_api",
            "timestamp": time.time()
        }
        
        return report
    
    def print_summary(self):
        """Print test execution summary."""
        if not self.results:
            print("No test results available")
            return
        
        print(f"\n{'='*60}")
        print("PROPFLOW E2E TEST SUMMARY")
        print(f"{'='*60}")
        
        total = len(self.results)
        successful = sum(1 for r in self.results if r["success"])
        failed = total - successful
        
        print(f"📊 Total scenarios: {total}")
        print(f"✅ Successful: {successful}")
        print(f"❌ Failed: {failed}")
        print(f"📈 Success rate: {successful/total*100:.1f}%")
        
        if failed > 0:
            print(f"\n❌ Failed scenarios:")
            for result in self.results:
                if not result["success"]:
                    print(f"   • {result['scenario']}: {result['error']}")
        
        print(f"\n⏱️  Execution times:")
        for result in self.results:
            status = "✅" if result["success"] else "❌"
            print(f"   {status} {result['scenario']}: {result['execution_time']:.2f}s")
        
        total_time = sum(r["execution_time"] for r in self.results)
        avg_time = total_time / total if total > 0 else 0
        print(f"\n🏁 Total time: {total_time:.2f}s")
        print(f"📊 Average time: {avg_time:.2f}s")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="PropFlow End-to-End Test Runner")
    parser.add_argument("--mock", action="store_true", help="Use mock mode (no API calls)")
    parser.add_argument("--scenario", type=str, help="Run specific scenario by name")
    parser.add_argument("--all-scenarios", action="store_true", help="Run all available scenarios")
    parser.add_argument("--output", type=str, help="Save results to JSON file")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Determine which scenarios to run
    scenarios_to_run = []
    
    if args.scenario:
        # Find specific scenario
        matching_scenarios = [s for s in TEST_SCENARIOS if s["name"] == args.scenario]
        if not matching_scenarios:
            print(f"❌ Scenario '{args.scenario}' not found")
            print("Available scenarios:")
            for scenario in TEST_SCENARIOS:
                print(f"  • {scenario['name']}")
            return 1
        scenarios_to_run = matching_scenarios
    elif args.all_scenarios:
        scenarios_to_run = TEST_SCENARIOS
    else:
        # Default: run first scenario
        scenarios_to_run = TEST_SCENARIOS[:1]
    
    # Initialize tester
    tester = PropFlowE2ETester(mock_mode=args.mock)
    
    try:
        await tester.setup()
        results = await tester.run_scenarios(scenarios_to_run)
        
        # Print summary
        tester.print_summary()
        
        # Save results if requested
        if args.output:
            report = tester.generate_report()
            with open(args.output, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"\n💾 Results saved to: {args.output}")
        
        # Exit with error code if any tests failed
        failed_count = sum(1 for r in results if not r["success"])
        return 1 if failed_count > 0 else 0
        
    except Exception as e:
        logger.error(f"❌ Test setup failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)