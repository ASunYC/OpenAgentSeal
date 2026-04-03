#!/usr/bin/env python3
"""
Open Agent Launcher - Cross-platform launcher with automatic dependency management

This launcher:
1. Checks Python version
2. Detects environment (conda or non-conda)
3. Installs uv appropriately:
   - conda: Use official installer (PowerShell/curl), then uv sync
   - non-conda: pip install uv, then install dependencies
4. Runs the application with Web UI

Usage:
    python run.py              # Run with Web UI + CLI
    python run.py --cli-only   # Run CLI only (no Web UI)
    python run.py --web-only   # Run Web UI only (no CLI)
    python run.py --install    # Install dependencies only
    python run.py --task "..." # Run with a task
    python run.py --no-browser # Don't open browser automatically
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Minimum Python version
MIN_PYTHON_VERSION = (3, 9)

# Project configuration
PROJECT_NAME = "open-agent"
PACKAGE_NAME = "open_agent"

# Paths
PROJECT_ROOT = Path(__file__).parent.absolute()
VENV_DIR = PROJECT_ROOT / ".venv"
CONFIG_DIR = PROJECT_ROOT / PACKAGE_NAME / "config"


def check_python_version() -> bool:
    """Check if Python version meets minimum requirement."""
    version = sys.version_info[:2]
    if version < MIN_PYTHON_VERSION:
        print(f"❌ Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}+ is required")
        print(f"   Current version: {version[0]}.{version[1]}")
        return False
    print(f"✅ Python {version[0]}.{version[1]} detected")
    return True


def is_conda_installed() -> bool:
    """Check if conda is installed on the system."""
    # Check if conda command is available
    conda_path = shutil.which("conda")
    if conda_path:
        return True
    
    # Check environment variables
    if os.environ.get('CONDA_PREFIX') or os.environ.get('CONDA_EXE'):
        return True
    
    return False


def is_uv_installed() -> bool:
    """Check if uv is installed (either as command or Python module)."""
    # Check if uv command is available
    uv_path = shutil.which("uv")
    if uv_path:
        return True
    
    # Check if uv is available as Python module
    try:
        result = subprocess.run(
            [sys.executable, "-m", "uv", "--version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def install_uv_conda() -> bool:
    """Install uv using official installer for conda environment."""
    print("\n📦 Installing uv via official installer...")
    
    system = platform.system()
    
    try:
        if system == "Windows":
            # PowerShell installer for Windows
            print("   Running: irm https://astral.sh/uv/install.ps1 | iex")
            result = subprocess.run(
                ["powershell", "-Command", "irm https://astral.sh/uv/install.ps1 | iex"],
                capture_output=True,
                text=True,
            )
        else:
            # curl installer for Linux/macOS
            print("   Running: curl -LsSf https://astral.sh/uv/install.sh | sh")
            result = subprocess.run(
                "curl -LsSf https://astral.sh/uv/install.sh | sh",
                shell=True,
                capture_output=True,
                text=True,
                executable="/bin/bash",
            )
        
        if result.returncode == 0:
            print("✅ uv installed successfully via official installer")
            print("⚠️  You may need to restart your terminal for uv to be available")
            return True
        else:
            print(f"⚠️  Official installer returned: {result.stderr}")
            return False
    except Exception as e:
        print(f"⚠️  Official installer failed: {e}")
        return False


def install_uv_pip() -> bool:
    """Install uv using pip for non-conda environment."""
    print("\n📦 Installing uv via pip...")
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "uv"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("✅ uv installed successfully via pip")
            return True
        else:
            print(f"⚠️  pip install failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"⚠️  pip install failed: {e}")
        return False


def uv_sync() -> bool:
    """Run uv sync to install dependencies."""
    print("\n📦 Running uv sync...")
    
    try:
        # Check if uv command is available
        uv_cmd = "uv"
        
        # If uv command not found, try python -m uv
        if not shutil.which("uv"):
            uv_cmd = [sys.executable, "-m", "uv"]
        else:
            uv_cmd = ["uv"]
        
        result = subprocess.run(
            uv_cmd + ["sync"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        
        if result.returncode == 0:
            print("✅ Dependencies installed via uv sync")
            return True
        else:
            print(f"⚠️  uv sync failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"⚠️  uv sync failed: {e}")
        return False


def pip_install() -> bool:
    """Install dependencies using pip as fallback."""
    print("\n📦 Installing dependencies via pip...")
    
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if not pyproject.exists():
        print(f"❌ pyproject.toml not found: {pyproject}")
        return False
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "--prefer-binary"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        
        if result.returncode == 0:
            print("✅ Dependencies installed via pip")
            return True
        else:
            print(f"⚠️  pip install failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"⚠️  pip install failed: {e}")
        return False


def check_config() -> bool:
    """Check if config file exists, create from example if needed.
    
    Note: API key is no longer checked here - it's loaded from user's 
    model selection (open_agent.json) at runtime.
    """
    config_file = CONFIG_DIR / "config.yaml"
    config_example = CONFIG_DIR / "config-example.yaml"
    
    if not config_file.exists():
        if config_example.exists():
            print(f"\n⚠️  Config file not found: {config_file}")
            print("   Creating from example...")
            shutil.copy(config_example, config_file)
            print(f"✅ Created: {config_file}")
            print(f"   Config location: {config_file}")
            return True
        else:
            print(f"\n❌ Config files not found in: {CONFIG_DIR}")
            return False
    
    return True


def get_venv_python() -> Path:
    """Get Python executable from .venv if it exists."""
    if VENV_DIR.exists():
        if platform.system() == "Windows":
            return VENV_DIR / "Scripts" / "python.exe"
        else:
            return VENV_DIR / "bin" / "python"
    return Path(sys.executable)


def run_application(args: list = None, mode: str = "unified", open_browser: bool = True) -> int:
    """Run the open-agent application.
    
    Args:
        args: Additional command line arguments
        mode: Running mode - "unified" (CLI + Web UI in same process), "cli" (CLI only), or "web" (Web UI only)
        open_browser: Whether to open browser for web UI
    """
    import threading
    import time
    import webbrowser
    import asyncio
    
    python_exe = get_venv_python()
    
    print("\n" + "=" * 50)
    print("🚀 Starting Open Agent...")
    print(f"   Mode: {mode.upper()}")
    print("=" * 50 + "\n")
    
    if mode == "web":
        # Web only mode (no CLI interaction)
        cmd = [str(python_exe), "-m", PACKAGE_NAME, "--web-only"]
        if not open_browser:
            cmd.append("--no-browser")
        if args:
            cmd.extend(args)
        
        try:
            return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode
        except KeyboardInterrupt:
            print("\n\n👋 Interrupted by user")
            return 0
        except Exception as e:
            print(f"\n❌ Failed to run: {e}")
            return 1
    
    elif mode == "cli":
        # CLI only mode (no Web UI)
        cmd = [str(python_exe), "-m", PACKAGE_NAME, "--cli-only"]
        if args:
            cmd.extend(args)
        
        try:
            return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode
        except KeyboardInterrupt:
            print("\n\n👋 Interrupted by user")
            return 0
        except Exception as e:
            print(f"\n❌ Failed to run: {e}")
            return 1
    
    else:  # mode == "unified" (default: CLI + Web UI in same process)
        # Unified mode: CLI and Web UI share the same process and AgentService
        # This allows CLI-created agents to be visible in Web UI
        
        print("🚀 Starting Open Agent (Unified Mode)...")
        print("   CLI: Interactive terminal")
        print("   Web UI: Background service (shared AgentService)")
        print()
        
        # Import and run in the same process
        try:
            # Add project root to path
            if str(PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT))
            
            # Parse workspace from args
            workspace = str(Path.cwd())
            task = None
            skip_model_selection = True  # Default to using config
            
            i = 0
            while i < len(args):
                if args[i] == "--workspace" and i + 1 < len(args):
                    workspace = args[i + 1]
                    i += 2
                elif args[i] == "--task" and i + 1 < len(args):
                    task = args[i + 1]
                    i += 2
                elif args[i] == "--config":
                    skip_model_selection = True
                    i += 1
                else:
                    i += 1
            
            # Import the unified runner
            from open_agent.cli import run_unified
            
            # Run unified mode (CLI + Web UI in same process)
            return asyncio.run(run_unified(
                workspace_dir=Path(workspace),
                task=task,
                skip_model_selection=skip_model_selection,
                open_browser=open_browser,
            ))
            
        except KeyboardInterrupt:
            print("\n\n👋 Interrupted by user")
            return 0
        except Exception as e:
            print(f"\n❌ Failed to run: {e}")
            import traceback
            traceback.print_exc()
            return 1


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Open Agent Launcher - Auto dependency management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--install", "-i",
        action="store_true",
        help="Install dependencies only, don't run",
    )
    parser.add_argument(
        "--task", "-t",
        type=str,
        help="Run with a specific task (non-interactive)",
    )
    parser.add_argument(
        "--workspace", "-w",
        type=str,
        help="Workspace directory",
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Skip dependency check/install",
    )
    parser.add_argument(
        "--cli-only",
        action="store_true",
        help="Run CLI only (no Web UI)",
    )
    parser.add_argument(
        "--web-only",
        action="store_true",
        help="Run Web UI only (no CLI)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser automatically when Web UI starts",
    )
    parser.add_argument(
        "--tray",
        action="store_true",
        help="Run as system tray daemon (background mode)",
    )
    
    args, unknown_args = parser.parse_known_args()
    
    print("=" * 50)
    print(f"[Launcher] {PROJECT_NAME.title()}")
    print(f"Platform: {platform.system()} ({platform.machine()})")
    print(f"Python: {sys.version.split()[0]}")
    print("=" * 50)
    
    # Check Python version
    if not check_python_version():
        return 1
    
    # Skip dependency management if requested
    if not args.skip_deps:
        # Check if uv is already installed
        uv_installed = is_uv_installed()
        
        if not uv_installed:
            # Detect conda and install uv accordingly
            has_conda = is_conda_installed()
            
            if has_conda:
                print("🔍 Detected conda installation")
                print("   Installing uv via official installer...")
                if not install_uv_conda():
                    print("❌ Failed to install uv")
                    print("   Please install manually and run again")
                    return 1
            else:
                print("🔍 No conda detected")
                print("   Installing uv via pip...")
                if not install_uv_pip():
                    print("❌ Failed to install uv")
                    print("   Please install manually: pip install uv")
                    return 1
        else:
            print("✅ uv is already installed")
        
        # Run uv sync for all environments
        if not uv_sync():
            print("⚠️  uv sync failed, falling back to pip...")
            if not pip_install():
                print("❌ Failed to install dependencies")
                return 1
    
    # Install-only mode
    if args.install:
        print("\n✅ Dependencies installed successfully!")
        return 0
    
    # Check config
    check_config()
    
    # Build run arguments
    run_args = []
    # Default to using config file (skip model selection)
    run_args.append("--config")
    if args.task:
        run_args.extend(["--task", args.task])
    if args.workspace:
        run_args.extend(["--workspace", args.workspace])
    run_args.extend(unknown_args)
    
    # Handle tray mode
    if args.tray:
        try:
            from open_agent.tray import run_tray_app
            workspace = args.workspace or str(Path.cwd())
            run_tray_app(
                host="127.0.0.1",
                port=9998,
                workspace_dir=workspace,
            )
            return 0
        except ImportError as e:
            print(f"❌ Failed to import tray module: {e}")
            print("   Please install: pip install pystray pillow")
            return 1
    
    # Determine running mode
    # Default: Unified mode (CLI + Web UI in same process)
    if args.web_only:
        mode = "web"
    elif args.cli_only:
        mode = "cli"
    else:
        mode = "unified"  # Default to unified mode (CLI + Web UI shared AgentService)
    
    open_browser = not args.no_browser
    
    # Run application
    return run_application(run_args, mode=mode, open_browser=open_browser)


if __name__ == "__main__":
    sys.exit(main())