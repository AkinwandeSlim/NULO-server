#!/usr/bin/env python3
"""
PropFlow Health Check Script
Comprehensive health diagnostics for PropFlow system.

Usage:
    python scripts/check_propflow_health.py              # Full health check
    python scripts/check_propflow_health.py --api-only   # API services only  
    python scripts/check_propflow_health.py --db-only    # Database only
    python scripts/check_propflow_health.py --verbose    # Verbose output
"""

import asyncio
import argparse
import sys
import json
import time
from pathlib import Path
from typing import Dict, List, Any

# Add the server directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Windows consoles default to cp1252 and cannot print emoji/box-drawing chars —
# force UTF-8 on stdout/stderr so this script runs without PYTHONIOENCODING.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.propflow.config import get_propflow_settings
from app.propflow.services.qwen_client import qwen_client  # ✅ Use global instance
from app.propflow.services.mem0_client import mem0_service  # ✅ Use global instance  
from app.propflow.services.supabase_storage_client import storage_client
from app.propflow.graph import get_propflow_graph  # ✅ Use global graph getter
from app.database import get_supabase_admin


class PropFlowHealthChecker:
    """Comprehensive health check for PropFlow system."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.settings = get_propflow_settings()
        self.results: Dict[str, Any] = {}
        
    def _log(self, message: str, level: str = "info"):
        """Log message with optional verbose mode."""
        if level == "error" or self.verbose:
            print(message)
    
    async def check_configuration(self) -> Dict[str, Any]:
        """Check PropFlow configuration."""
        self._log("🔧 Checking PropFlow configuration...")
        
        result = {
            "status": "healthy",
            "details": {},
            "errors": []
        }
        
        try:
            # Check required settings
            required_settings = [
                ("QWEN_API_URL", self.settings.QWEN_API_URL),
                ("QWEN_MODEL", self.settings.QWEN_MODEL),
                ("QWEN_FALLBACK_MODEL", self.settings.QWEN_FALLBACK_MODEL)
            ]
            
            for setting_name, setting_value in required_settings:
                if setting_value:
                    result["details"][setting_name] = "✓ Configured"
                    self._log(f"   ✅ {setting_name}: {setting_value}")
                else:
                    result["details"][setting_name] = "✗ Missing"
                    result["errors"].append(f"{setting_name} not configured")
                    self._log(f"   ❌ {setting_name}: Not configured")
            
            # Check API key presence (without revealing it)
            if self.settings.QWEN_API_KEY:
                key_preview = self.settings.QWEN_API_KEY[:10] + "..." if len(self.settings.QWEN_API_KEY) > 10 else "***"
                result["details"]["QWEN_API_KEY"] = f"✓ Present ({key_preview})"
                self._log(f"   ✅ QWEN_API_KEY: Present ({key_preview})")
            else:
                result["details"]["QWEN_API_KEY"] = "✗ Missing"
                result["errors"].append("QWEN_API_KEY not configured")
                self._log(f"   ❌ QWEN_API_KEY: Missing")
            
            # Check optional service configs
            optional_configs = [
                ("ENABLE_MEM0_MEMORY", self.settings.ENABLE_MEM0_MEMORY),
                ("AGREEMENT_STORAGE_BUCKET", self.settings.AGREEMENT_STORAGE_BUCKET)
            ]
            
            for config_name, config_value in optional_configs:
                result["details"][config_name] = f"✓ {config_value}" if config_value else "✗ Disabled"
                self._log(f"   📋 {config_name}: {config_value}")
            
            if result["errors"]:
                result["status"] = "unhealthy"
                
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            self._log(f"   ❌ Configuration check failed: {e}", "error")
        
        return result
    
    async def check_qwen_api(self) -> Dict[str, Any]:
        """Check Qwen API connectivity and functionality."""
        self._log("🤖 Checking Qwen API...")
        
        result = {
            "status": "healthy",
            "details": {},
            "errors": []
        }
        
        try:
            # Test basic connectivity using global qwen_client instance
            start_time = time.time()
            test_response = await qwen_client.extract_intent(
                "Test inquiry for health check",
                prior_memories=[]
            )
            response_time = time.time() - start_time
            
            if test_response and "confidence" in test_response:
                result["details"]["connectivity"] = f"✓ Connected ({response_time:.2f}s)"
                result["details"]["model"] = f"✓ {self.settings.QWEN_MODEL}"  # ✅ Use settings instead
                result["details"]["response_format"] = "✓ Valid JSON"
                
                self._log(f"   ✅ Qwen API connectivity: OK ({response_time:.2f}s)")
                self._log(f"   ✅ Model: {self.settings.QWEN_MODEL}")
                self._log(f"   ✅ Response format: Valid JSON")
                
            else:
                result["status"] = "unhealthy"
                result["errors"].append("Invalid response format from Qwen API")
                self._log(f"   ❌ Invalid response format", "error")
            
        except Exception as e:
            result["status"] = "error"  
            result["error"] = str(e)
            
            # Check if it's an authentication error
            if "401" in str(e) or "unauthorized" in str(e).lower():
                result["details"]["auth"] = "✗ Authentication failed"
                self._log(f"   ❌ Qwen API authentication failed", "error")
            else:
                result["details"]["connectivity"] = f"✗ Connection failed: {e}"
                self._log(f"   ❌ Qwen API connection failed: {e}", "error")
        
        return result
    
    async def check_mem0_service(self) -> Dict[str, Any]:
        """Check Mem0 memory service."""
        self._log("🧠 Checking Mem0 service...")
        
        result = {
            "status": "healthy",
            "details": {},
            "errors": []
        }
        
        if not self.settings.ENABLE_MEM0_MEMORY:  # ✅ Use correct setting name
            result["status"] = "disabled"
            result["details"]["service"] = "✗ Disabled in configuration"
            self._log(f"   📋 Mem0: Disabled")
            return result
        
        try:
            # Test basic memory operations using global mem0_service instance
            test_tenant_id = "health-check-tenant"
            test_memory = "Health check memory entry"
            
            # Add memory
            mem0_service.add_tenant_memory(test_tenant_id, test_memory)
            
            # Search memory
            memories = mem0_service.search_tenant_memories(test_tenant_id, "health check")
            
            if memories and len(memories) > 0:
                result["details"]["connectivity"] = "✓ Connected"
                result["details"]["operations"] = "✓ Add/Search working"
                
                self._log(f"   ✅ Mem0 connectivity: OK")
                self._log(f"   ✅ Memory operations: Working")
            else:
                result["status"] = "unhealthy"
                result["errors"].append("Memory operations not working properly")
                self._log(f"   ❌ Memory operations failed", "error")
        
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            self._log(f"   ❌ Mem0 service error: {e}", "error")
        
        return result
    
    async def check_storage_service(self) -> Dict[str, Any]:
        """Check Supabase Storage service (ownership-docs bucket)."""
        self._log("☁️  Checking Supabase Storage...")
        
        result = {
            "status": "healthy",
            "details": {},
            "errors": []
        }
        
        try:
            # Verify the storage client can build a public URL for the
            # agreement bucket (no upload performed — read-only probe).
            bucket = self.settings.AGREEMENT_STORAGE_BUCKET
            probe_path = "agreements/health-check-probe.pdf"
            url = storage_client.get_download_url(probe_path)
            if url:
                result["details"]["bucket_access"] = f"✓ {bucket}"
                result["details"]["public_url_format"] = "✓ get_public_url OK"
                self._log(f"   ✅ Storage configuration: OK")
                self._log(f"   ✅ Bucket: {bucket}")
            else:
                result["status"] = "error"
                result["errors"].append("get_public_url returned None")
                self._log(f"   ❌ Storage probe failed: get_public_url returned None", "error")
            
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            self._log(f"   ❌ Storage service error: {e}", "error")
        
        return result
    
    async def check_database(self) -> Dict[str, Any]:
        """Check database connectivity and required tables."""
        self._log("🗄️  Checking database...")
        
        result = {
            "status": "healthy",
            "details": {},
            "errors": []
        }
        
        try:
            supabase = get_supabase_admin()
            
            # Test basic connectivity
            health_check = supabase.table("users").select("id").limit(1).execute()
            
            if health_check:
                result["details"]["connectivity"] = "✓ Connected"
                self._log(f"   ✅ Database connectivity: OK")
            else:
                result["status"] = "unhealthy"
                result["errors"].append("Database query failed")
                self._log(f"   ❌ Database query failed", "error")
            
            # Check required tables
            required_tables = [
                "users",
                "properties", 
                "applications",
                "agreements",
                "tenant_profiles"
            ]
            
            for table in required_tables:
                try:
                    supabase.table(table).select("id").limit(1).execute()
                    result["details"][f"table_{table}"] = "✓ Exists"
                    self._log(f"   ✅ Table {table}: OK")
                except Exception as e:
                    result["details"][f"table_{table}"] = f"✗ Error: {e}"
                    result["errors"].append(f"Table {table} issue: {e}")
                    self._log(f"   ❌ Table {table}: {e}", "error")
            
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            self._log(f"   ❌ Database check failed: {e}", "error")
        
        return result
    
    async def check_propflow_graph(self) -> Dict[str, Any]:
        """Check PropFlow graph initialization."""
        self._log("🔗 Checking PropFlow graph...")
        
        result = {
            "status": "healthy", 
            "details": {},
            "errors": []
        }
        
        try:
            graph = get_propflow_graph()
            
            if graph:
                result["details"]["initialization"] = "✓ Graph loaded"
                result["details"]["nodes"] = f"✓ {len(graph.nodes)} nodes"
                
                self._log(f"   ✅ PropFlow graph: Loaded")
                self._log(f"   ✅ Nodes: {len(graph.nodes)}")
                
                # Check if we can get state (basic functionality)
                test_config = {"configurable": {"thread_id": "health-check"}}
                try:
                    state = graph.get_state(test_config)
                    result["details"]["state_access"] = "✓ State operations working"
                    self._log(f"   ✅ State operations: Working")
                except Exception as e:
                    result["details"]["state_access"] = f"✗ State error: {e}"
                    result["errors"].append(f"State operations failed: {e}")
                    self._log(f"   ❌ State operations: {e}", "error")
            else:
                result["status"] = "unhealthy"
                result["errors"].append("PropFlow graph failed to load")
                self._log(f"   ❌ PropFlow graph: Failed to load", "error")
        
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            self._log(f"   ❌ PropFlow graph error: {e}", "error")
        
        return result
    
    async def run_full_check(self, api_only: bool = False, db_only: bool = False) -> Dict[str, Any]:
        """Run comprehensive health check."""
        print("🏥 PropFlow Health Check")
        print("=" * 50)
        
        checks_to_run = []
        
        if db_only:
            checks_to_run = [
                ("configuration", self.check_configuration),
                ("database", self.check_database),
                ("propflow_graph", self.check_propflow_graph)
            ]
        elif api_only:
            checks_to_run = [
                ("configuration", self.check_configuration),
                ("qwen_api", self.check_qwen_api),
                ("mem0_service", self.check_mem0_service),
                ("storage_service", self.check_storage_service)
            ]
        else:
            checks_to_run = [
                ("configuration", self.check_configuration),
                ("database", self.check_database),
                ("propflow_graph", self.check_propflow_graph),
                ("qwen_api", self.check_qwen_api),
                ("mem0_service", self.check_mem0_service),
                ("storage_service", self.check_storage_service)
            ]
        
        for check_name, check_func in checks_to_run:
            self.results[check_name] = await check_func()
        
        return self.results
    
    def print_summary(self):
        """Print health check summary."""
        if not self.results:
            print("No health check results available")
            return
        
        print(f"\n{'=' * 50}")
        print("HEALTH CHECK SUMMARY")
        print(f"{'=' * 50}")
        
        healthy_count = 0
        total_count = 0
        
        for service, result in self.results.items():
            total_count += 1
            status = result["status"]
            
            if status == "healthy":
                status_icon = "✅"
                healthy_count += 1
            elif status == "disabled":
                status_icon = "📋"
                healthy_count += 1  # Count disabled as OK
            elif status == "unhealthy":
                status_icon = "⚠️ "
            else:  # error
                status_icon = "❌"
            
            print(f"{status_icon} {service.replace('_', ' ').title()}: {status.upper()}")
            
            # Show errors if any
            if result.get("errors"):
                for error in result["errors"]:
                    print(f"   └─ {error}")
        
        print(f"\n📊 Overall: {healthy_count}/{total_count} services healthy")
        
        if healthy_count == total_count:
            print("🎉 All systems operational!")
        else:
            print("⚠️  Some issues found - check details above")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="PropFlow Health Check")
    parser.add_argument("--api-only", action="store_true", help="Check API services only")
    parser.add_argument("--db-only", action="store_true", help="Check database only")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--output", type=str, help="Save results to JSON file")
    
    args = parser.parse_args()
    
    checker = PropFlowHealthChecker(verbose=args.verbose)
    
    try:
        results = await checker.run_full_check(
            api_only=args.api_only,
            db_only=args.db_only
        )
        
        checker.print_summary()
        
        # Save results if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\n💾 Results saved to: {args.output}")
        
        # Exit with error code if any critical services unhealthy
        critical_services = ["configuration", "database", "propflow_graph"]
        critical_issues = [
            service for service in critical_services 
            if results.get(service, {}).get("status") == "error"
        ]
        
        return 1 if critical_issues else 0
        
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)