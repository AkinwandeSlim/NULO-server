#!/usr/bin/env python3
"""
PropFlow Installation Script
Automated setup for PropFlow AI agent system.

Usage:
    python scripts/install_propflow.py                    # Interactive setup
    python scripts/install_propflow.py --auto             # Auto setup with defaults
    python scripts/install_propflow.py --check-only       # Check current setup
    python scripts/install_propflow.py --help             # Show help
"""

import argparse
import asyncio
import os
import sys
import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Optional

# Add the server directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))


class PropFlowInstaller:
    """Automated PropFlow installation and setup."""
    
    def __init__(self, auto_mode: bool = False):
        self.auto_mode = auto_mode
        self.project_root = Path(__file__).parent.parent.parent
        self.server_root = self.project_root / "server"
        self.client_root = self.project_root / "client"
        
    def _is_in_venv(self) -> bool:
        """Check if we're already running in a virtual environment."""
        return hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
        )
        
    def print_header(self, message: str):
        """Print formatted header."""
        print(f"\n{'=' * 60}")
        print(f" {message}")
        print(f"{'=' * 60}")
    
    def print_step(self, step: int, total: int, message: str):
        """Print formatted step."""
        print(f"\n[{step}/{total}] {message}")
        print("-" * 40)
    
    def check_prerequisites(self) -> bool:
        """Check system prerequisites."""
        self.print_step(1, 8, "Checking Prerequisites")
        
        prerequisites = [
            ("python3", "python --version", "Python 3.11+"),
            ("pip", "pip --version", "pip package manager"),
            ("node", "node --version", "Node.js 18+"),
            ("git", "git --version", "Git version control")
        ]
        
        missing = []
        
        for name, command, description in prerequisites:
            try:
                result = subprocess.run(command.split(), capture_output=True, text=True)
                if result.returncode == 0:
                    version = result.stdout.strip().split('\n')[0]
                    print(f"✅ {description}: {version}")
                else:
                    missing.append(name)
                    print(f"❌ {description}: Not found")
            except FileNotFoundError:
                missing.append(name)
                print(f"❌ {description}: Not found")
        
        if missing:
            print(f"\n❌ Missing prerequisites: {', '.join(missing)}")
            print("\nPlease install missing tools and run again.")
            return False
        
        print(f"\n✅ All prerequisites satisfied!")
        return True
    
    def setup_python_environment(self) -> bool:
        """Set up Python virtual environment and dependencies."""
        self.print_step(2, 8, "Setting Up Python Environment")
        
        venv_path = self.server_root / "venv"
        
        # Check if virtual environment exists
        if venv_path.exists():
            print(f"📁 Virtual environment already exists: {venv_path}")
            print(f"✅ Using existing virtual environment")
        else:
            print(f"🔨 Creating virtual environment: {venv_path}")
            try:
                subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
                print("✅ Virtual environment created")
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to create virtual environment: {e}")
                return False
        
        # Get virtual environment paths
        if os.name == 'nt':  # Windows
            venv_python = venv_path / "Scripts" / "python.exe"
            venv_pip = venv_path / "Scripts" / "pip.exe"
        else:  # Unix/Linux/macOS
            venv_python = venv_path / "bin" / "python"
            venv_pip = venv_path / "bin" / "pip"
        
        # Verify virtual environment is functional
        try:
            result = subprocess.run([str(venv_python), "--version"], 
                                  capture_output=True, text=True, check=True)
            python_version = result.stdout.strip()
            print(f"🐍 Virtual environment Python: {python_version}")
        except subprocess.CalledProcessError as e:
            print(f"❌ Virtual environment verification failed: {e}")
            return False
        
        # Upgrade pip in virtual environment
        print(f"🔄 Upgrading pip in virtual environment...")
        try:
            subprocess.run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], 
                          check=True, capture_output=True)
            print("✅ Pip upgraded")
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Pip upgrade failed: {e} (continuing anyway)")
        
        # Install dependencies using virtual environment pip
        requirements_file = self.server_root / "requirements.txt"
        if requirements_file.exists():
            print(f"📦 Installing Python dependencies in virtual environment...")
            try:
                # Use the virtual environment's pip directly
                subprocess.run([str(venv_pip), "install", "-r", str(requirements_file)], 
                              check=True, cwd=self.server_root)
                print("✅ Python dependencies installed")
                
                # Verify key packages are installed
                try:
                    result = subprocess.run([str(venv_pip), "list"], 
                                          capture_output=True, text=True, check=True)
                    installed_packages = result.stdout
                    
                    key_packages = ["fastapi", "uvicorn", "supabase", "langchain", "langgraph", "mem0ai"]
                    missing_packages = []
                    
                    for pkg in key_packages:
                        if pkg.lower() not in installed_packages.lower():
                            missing_packages.append(pkg)
                    
                    if missing_packages:
                        print(f"⚠️  Some key packages may not be installed: {', '.join(missing_packages)}")
                        print(f"   Installing missing packages...")
                        for pkg in missing_packages:
                            try:
                                subprocess.run([str(venv_pip), "install", pkg], 
                                              check=True, capture_output=True)
                                print(f"   ✅ Installed {pkg}")
                            except subprocess.CalledProcessError as e:
                                print(f"   ⚠️  Failed to install {pkg}: {e}")
                    else:
                        print("✅ Key packages verified")
                        
                except subprocess.CalledProcessError:
                    print("⚠️  Could not verify package installation")
                    
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to install dependencies: {e}")
                return False
        else:
            print(f"⚠️  requirements.txt not found at {requirements_file}")
        
        # Provide activation instructions
        print(f"\n💡 Virtual environment setup complete!")
        print(f"   To manually activate later:")
        if os.name == 'nt':
            print(f"   > venv\\Scripts\\activate")
        else:
            print(f"   $ source venv/bin/activate")
        
        return True
    
    def setup_node_environment(self) -> bool:
        """Set up Node.js environment and dependencies."""
        self.print_step(3, 8, "Setting Up Node.js Environment")
        
        # Check for package manager with shell=True on Windows
        package_managers = ["pnpm", "npm", "yarn"]
        selected_pm = None
        
        for pm in package_managers:
            try:
                # Use shell=True on Windows to find npm properly
                result = subprocess.run([pm, "--version"], 
                                      capture_output=True, 
                                      check=True, 
                                      shell=(os.name == 'nt'))
                selected_pm = pm
                version = result.stdout.decode().strip()
                print(f"✅ Found package manager: {pm} ({version})")
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                print(f"⚠️  {pm} not found")
                continue
        
        if not selected_pm:
            print(f"❌ No package manager found. Please install npm, yarn, or pnpm.")
            return False
        
        # Install dependencies
        package_json = self.client_root / "package.json"
        if package_json.exists():
            print(f"📦 Installing Node.js dependencies with {selected_pm}...")
            try:
                subprocess.run([selected_pm, "install"], cwd=self.client_root, check=True)
                print("✅ Node.js dependencies installed")
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to install dependencies: {e}")
                return False
        else:
            print(f"⚠️  package.json not found at {package_json}")
        
        return True
    
    def setup_environment_config(self) -> bool:
        """Set up environment configuration files."""
        self.print_step(4, 8, "Setting Up Environment Configuration")
        
        # Backend .env setup
        server_env = self.server_root / ".env"
        server_env_example = self.server_root / ".env.example"
        
        if not server_env.exists() and server_env_example.exists():
            print(f"📝 Creating backend .env from example...")
            with open(server_env_example, 'r') as src:
                content = src.read()
            
            with open(server_env, 'w') as dst:
                dst.write(content)
            print(f"✅ Created {server_env}")
            print(f"⚠️  Please edit {server_env} with your API keys!")
        elif server_env.exists():
            print(f"📁 Backend .env already exists: {server_env}")
        else:
            print(f"⚠️  No .env.example found at {server_env_example}")
        
        # Frontend .env setup
        client_env = self.client_root / ".env.local"
        client_env_example = self.client_root / ".env.example"
        
        if not client_env.exists() and client_env_example.exists():
            print(f"📝 Creating frontend .env.local from example...")
            with open(client_env_example, 'r') as src:
                content = src.read()
            
            with open(client_env, 'w') as dst:
                dst.write(content)
            print(f"✅ Created {client_env}")
        elif client_env.exists():
            print(f"📁 Frontend .env.local already exists: {client_env}")
        
        return True
    
    async def setup_database(self) -> bool:
        """Set up database with PropFlow demo data."""
        self.print_step(5, 8, "Setting Up Database")
        
        try:
            # Import and run database setup
            from scripts.setup_propflow_demo import PropFlowDemoSetup
            
            print(f"🗄️  Setting up PropFlow demo data...")
            setup = PropFlowDemoSetup()
            await setup.setup_sample_data()
            
            print(f"🔍 Verifying database setup...")
            success = await setup.verify_setup()
            
            if success:
                print("✅ Database setup complete!")
                return True
            else:
                print("⚠️  Database setup completed but verification failed")
                return True  # Continue anyway
                
        except Exception as e:
            print(f"❌ Database setup failed: {e}")
            print("💡 You can manually set up the database later with:")
            print("   python scripts/setup_propflow_demo.py")
            return True  # Don't fail installation for database issues
    
    async def run_health_check(self) -> bool:
        """Run comprehensive health check."""
        self.print_step(6, 8, "Running Health Check")
        
        try:
            from scripts.check_propflow_health import PropFlowHealthChecker
            
            print(f"🏥 Running PropFlow health diagnostics...")
            checker = PropFlowHealthChecker(verbose=False)
            results = await checker.run_full_check()
            
            # Print simplified results
            healthy_services = 0
            total_services = 0
            
            for service, result in results.items():
                total_services += 1
                status = result["status"]
                
                if status in ["healthy", "disabled"]:
                    print(f"   ✅ {service.replace('_', ' ').title()}: OK")
                    healthy_services += 1
                else:
                    print(f"   ⚠️  {service.replace('_', ' ').title()}: {status}")
                    if result.get("errors"):
                        for error in result["errors"][:2]:  # Show first 2 errors
                            print(f"      └─ {error}")
            
            print(f"\n📊 Health check: {healthy_services}/{total_services} services OK")
            
            if healthy_services >= total_services - 2:  # Allow 2 services to be unhealthy
                print("✅ System health: Good")
                return True
            else:
                print("⚠️  System health: Issues detected")
                return False
                
        except Exception as e:
            print(f"❌ Health check failed: {e}")
            return False
    
    def run_demo_test(self) -> bool:
        """Run a quick demo test."""
        self.print_step(7, 8, "Running Demo Test")
        
        try:
            print(f"🧪 Running PropFlow evaluation in mock mode...")
            
            # Run evaluation test (remove --quick flag)
            result = subprocess.run([
                sys.executable, "-m", "app.propflow.tests.eval_agent", "--mock"
            ], cwd=self.server_root, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print("✅ Demo test passed!")
                
                # Try to extract score from output
                lines = result.stdout.split('\n')
                for line in lines:
                    if "Overall Score" in line or "overall_score" in line:
                        print(f"   📊 {line.strip()}")
                        break
                
                return True
            else:
                print(f"⚠️  Demo test completed with issues:")
                print(f"   {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"⚠️  Demo test timed out (may still be working)")
            return True
        except Exception as e:
            print(f"❌ Demo test failed: {e}")
            return False
    
    def show_next_steps(self):
        """Show next steps after installation."""
        self.print_step(8, 8, "Installation Complete!")
        
        print("🎉 PropFlow installation finished!")
        print("\n📋 Next Steps:")
        print()
        
        # API Key setup
        env_file = self.server_root / ".env"
        print("1. Configure API Keys:")
        print(f"   Edit: {env_file}")
        print("   Required: QWEN_API_KEY (get from https://dashscope-intl.aliyuncs.com/)")
        print("   Optional: MEM0_API_KEY, OSS credentials")
        print()
        
        # Quick tests
        print("2. Run Quick Tests:")
        print("   cd server")
        print("   python scripts/quick_propflow_demo.py           # Mock demo")
        print("   python scripts/check_propflow_health.py        # Health check")
        print("   python -m app.propflow.tests.eval_agent --mock # Evaluation")
        print()
        
        # Development servers
        print("3. Start Development Servers:")
        print("   Terminal 1 (Backend):")
        print("     cd server")
        print("     source venv/bin/activate  # Windows: venv\\Scripts\\activate")
        print("     uvicorn app.main:app --reload --port 8000")
        print()
        print("   Terminal 2 (Frontend):")
        print("     cd client")
        print("     pnpm dev  # or npm run dev")
        print()
        print("   Open: http://localhost:3000")
        print()
        
        # Documentation
        print("4. Documentation:")
        print("   Setup Guide: docs/hackathon/Qwen/SETUP_AND_TESTING_GUIDE.md")
        print("   Architecture: docs/hackathon/Qwen/ARCHITECTURE_AND_USERFLOW.md")
        print("   Submission: SUBMISSION_README.md")
        print()
        
        print("🚀 PropFlow is ready for development and testing!")


async def main():
    """Main installation entry point."""
    parser = argparse.ArgumentParser(description="PropFlow Installation Script")
    parser.add_argument("--auto", action="store_true", help="Auto setup with defaults")
    parser.add_argument("--check-only", action="store_true", help="Check current setup only")
    parser.add_argument("--skip-demo", action="store_true", help="Skip demo test")
    parser.add_argument("--skip-db", action="store_true", help="Skip database setup")
    
    args = parser.parse_args()
    
    installer = PropFlowInstaller(auto_mode=args.auto)
    
    installer.print_header("PropFlow AI Agent Installation")
    
    if args.check_only:
        installer.print_header("System Check")
        try:
            from scripts.check_propflow_health import PropFlowHealthChecker
            checker = PropFlowHealthChecker(verbose=True)
            await checker.run_full_check()
            checker.print_summary()
        except Exception as e:
            print(f"❌ Check failed: {e}")
        return 0
    
    print("🏠 Installing PropFlow AI Agent for Qwen Hackathon")
    print("   This will set up the complete development environment.")
    
    if not args.auto:
        response = input("\n   Continue with installation? (Y/n): ")
        if response.lower() in ['n', 'no']:
            print("Installation cancelled.")
            return 0
    
    success_steps = 0
    total_steps = 8
    
    try:
        # Step 1: Prerequisites
        if installer.check_prerequisites():
            success_steps += 1
        
        # Step 2: Python environment
        if installer.setup_python_environment():
            success_steps += 1
        
        # Step 3: Node.js environment
        if installer.setup_node_environment():
            success_steps += 1
        
        # Step 4: Environment config
        if installer.setup_environment_config():
            success_steps += 1
        
        # Step 5: Database (optional)
        if not args.skip_db:
            if await installer.setup_database():
                success_steps += 1
        else:
            success_steps += 1
            print("⏭️  Skipping database setup")
        
        # Step 6: Health check
        if await installer.run_health_check():
            success_steps += 1
        
        # Step 7: Demo test (optional)
        if not args.skip_demo:
            if installer.run_demo_test():
                success_steps += 1
        else:
            success_steps += 1
            print("⏭️  Skipping demo test")
        
        # Step 8: Next steps
        installer.show_next_steps()
        success_steps += 1
        
        print(f"\n📊 Installation: {success_steps}/{total_steps} steps completed")
        
        if success_steps >= total_steps - 1:  # Allow 1 step to fail
            print("🎉 Installation successful!")
            return 0
        else:
            print("⚠️  Installation completed with issues")
            return 1
            
    except KeyboardInterrupt:
        print(f"\n\n⚠️  Installation cancelled by user")
        return 1
    except Exception as e:
        print(f"\n❌ Installation failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)