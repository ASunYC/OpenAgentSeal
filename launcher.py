#!/usr/bin/env python3
"""
OpenAgent Standalone Launcher

新的架构：
1. AgentService 是核心服务，管理所有Agent
2. 托盘永远只有1个
3. 服务永远只有1个
4. Web和CLI不再共用Agent，各自独立

托盘菜单：
1. Open Web - 打开浏览器
2. New Agent - 创建新的后台Agent
3. New CLI Agent - 打开新终端创建CLI Agent
4. Open Service - 打开服务窗口
5. Help - 帮助文档
6. About - 关于
7. Exit - 退出
"""

import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

# Try to import tray dependencies
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

# Global instances
_tray_icon = None
_web_url = "http://127.0.0.1:9998"
_stop_event = threading.Event()
_agent_service = None

# Configuration
APP_NAME = "OpenAgent"
PACKAGE_NAME = "open_agent"
MIN_PYTHON_VERSION = (3, 9)


def get_user_app_dir() -> Path:
    r"""Get the user application directory for storing source code.
    
    Unified directory for all platforms:
    - Windows: C:\Users\<user>\.open-agent\
    - Linux/macOS: ~/.open-agent/
    """
    # 统一使用用户主目录下的 .open-agent
    return Path.home() / ".open-agent"


def get_log_file() -> Path:
    """Get the log file path."""
    log_dir = get_user_app_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return log_dir / f"launcher_{timestamp}.log"


# Paths
if getattr(sys, 'frozen', False):
    EXE_PATH = Path(sys.executable).absolute()
    EXE_DIR = EXE_PATH.parent
    BUNDLE_DIR = Path(sys._MEIPASS)
    IS_FROZEN = True
else:
    EXE_PATH = Path(__file__).absolute()
    EXE_DIR = Path(__file__).parent
    BUNDLE_DIR = Path(__file__).parent
    IS_FROZEN = False

# User app directory
APP_DIR = get_user_app_dir()
OPENAGENT_DIR = APP_DIR

# All directories are relative to OpenAgent directory
SOURCE_DIR = OPENAGENT_DIR
CONFIG_DIR = OPENAGENT_DIR / "config"
SKILLS_DIR = OPENAGENT_DIR / "skills"
VERSION_FILE = OPENAGENT_DIR / "VERSION.md"

# Log file for tray mode
LOG_FILE = get_log_file()


class TrayLogger:
    """Logger that writes to file instead of console."""
    
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self._file = None
        self._lock = threading.Lock()
    
    def _open(self):
        if self._file is None:
            try:
                self._file = open(self.log_file, "a", encoding="utf-8")
            except Exception:
                pass
    
    def write(self, text: str):
        with self._lock:
            self._open()
            if self._file:
                try:
                    self._file.write(text)
                    self._file.flush()
                except Exception:
                    pass
    
    def flush(self):
        with self._lock:
            if self._file:
                try:
                    self._file.flush()
                except Exception:
                    pass
    
    def close(self):
        with self._lock:
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
    
    def isatty(self):
        return False


def setup_tray_logging():
    """Setup logging to file for tray mode."""
    global LOG_FILE
    logger = TrayLogger(LOG_FILE)
    sys.stdout = logger
    sys.stderr = logger
    print(f"\n{'=' * 60}")
    print(f"OpenAgent Launcher Started: {datetime.now()}")
    print(f"Log file: {LOG_FILE}")
    print(f"{'=' * 60}\n")


# ANSI color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    BRIGHT_CYAN = "\033[96m"


def print_header(title: str):
    """Print a formatted header."""
    print()
    print(f"{'=' * 60}")
    # Use ASCII-safe prefix to avoid encoding issues in packaged exe
    prefix = "[Agent] " if IS_FROZEN else "  🤖 "
    print(f"{prefix}{title}")
    print(f"{'=' * 60}")


def get_bundled_version() -> tuple:
    """Get version info from bundled VERSION.md."""
    version_file = BUNDLE_DIR / "VERSION.md"
    if not version_file.exists():
        return "V0.0.0", "", ""
    
    try:
        content = version_file.read_text(encoding="utf-8")
        version = "V0.0.0"
        date = ""
        changelog = ""
        
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("## Version:"):
                version = line.replace("## Version:", "").strip()
            elif line.startswith("## Release Date:"):
                date = line.replace("## Release Date:", "").strip()
            elif line.startswith("### "):
                idx = content.find(line)
                changelog = content[idx:].strip()
                break
        
        return version, date, changelog
    except Exception:
        return "V0.0.0", "", ""


def get_installed_version() -> tuple:
    """Get version info from installed VERSION.md."""
    if not VERSION_FILE.exists():
        return "V0.0.0", "", ""
    
    try:
        content = VERSION_FILE.read_text(encoding="utf-8")
        version = "V0.0.0"
        date = ""
        changelog = ""
        
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("## Version:"):
                version = line.replace("## Version:", "").strip()
            elif line.startswith("## Release Date:"):
                date = line.replace("## Release Date:", "").strip()
            elif line.startswith("### "):
                idx = content.find(line)
                changelog = content[idx:].strip()
                break
        
        return version, date, changelog
    except Exception:
        return "V0.0.0", "", ""


def extract_resources() -> tuple:
    """Extract embedded resources to OpenAgent directory."""
    print(f"\nSetting up {APP_NAME} directory...")
    print(f"Target: {OPENAGENT_DIR}")
    print(f"Bundle dir (sys._MEIPASS): {BUNDLE_DIR}")
    
    updated_items = []
    is_first_install = False
    
    if not OPENAGENT_DIR.exists():
        OPENAGENT_DIR.mkdir(parents=True)
        print(f"Created {APP_NAME} directory")
        is_first_install = True
    else:
        print(f"{APP_NAME} directory exists")
    
    # IMPORTANT: Clean up old source directory FIRST to prevent ImportError
    # This must be done BEFORE any import from the source directory
    target_src = OPENAGENT_DIR / "open_agent"
    if target_src.exists():
        print(f"Removing old open_agent/ directory...")
        shutil.rmtree(target_src)
        print(f"Old open_agent/ removed")
    
    bundled_config = BUNDLE_DIR / "config"
    bundled_skills = BUNDLE_DIR / "skills"
    bundled_pyproject = BUNDLE_DIR / "pyproject.toml"
    bundled_uv_lock = BUNDLE_DIR / "uv.lock"
    bundled_src = BUNDLE_DIR / "open_agent"
    bundled_version = BUNDLE_DIR / "VERSION.md"
    
    # Debug: Check what's in the bundle
    print(f"\n[DEBUG] Bundle contents check:")
    print(f"  - bundled_src exists: {bundled_src.exists()}")
    if bundled_src.exists():
        print(f"  - bundled_src path: {bundled_src}")
        # Check for static files
        static_dir = bundled_src / "app" / "static"
        print(f"  - static_dir exists: {static_dir.exists()}")
        if static_dir.exists():
            static_files = list(static_dir.rglob("*"))
            print(f"  - static files count: {len([f for f in static_files if f.is_file()])}")
            index_html = static_dir / "index.html"
            print(f"  - index.html exists: {index_html.exists()}")
    
    # Copy VERSION.md
    if bundled_version.exists():
        old_version, old_date, _ = get_installed_version()
        shutil.copy2(bundled_version, VERSION_FILE)
        new_version, new_date, _ = get_bundled_version()
        
        if is_first_install:
            print(f"Installed: {new_version} ({new_date})")
            updated_items.append(f"VERSION.md: {new_version}")
        elif old_version != new_version:
            print(f"Updated: {old_version} -> {new_version}")
            updated_items.append(f"VERSION.md: {old_version} -> {new_version}")
        else:
            print(f"VERSION.md: {new_version} (unchanged)")
    
    # Copy config
    if bundled_config.exists():
        if not CONFIG_DIR.exists():
            shutil.copytree(bundled_config, CONFIG_DIR)
            print(f"Created: config/")
            updated_items.append("config/ (new)")
        else:
            print(f"config/ (exists, preserved)")
    
    # Copy skills
    if bundled_skills.exists():
        if not SKILLS_DIR.exists():
            shutil.copytree(bundled_skills, SKILLS_DIR)
            print(f"Created: skills/")
            updated_items.append("skills/ (new)")
        else:
            print(f"skills/ (exists, preserved)")
    
    # Copy pyproject.toml
    if bundled_pyproject.exists():
        target = OPENAGENT_DIR / "pyproject.toml"
        shutil.copy2(bundled_pyproject, target)
        print(f"Updated: pyproject.toml")
        updated_items.append("pyproject.toml")
    
    # Copy uv.lock
    if bundled_uv_lock.exists():
        target = OPENAGENT_DIR / "uv.lock"
        shutil.copy2(bundled_uv_lock, target)
        print(f"Updated: uv.lock")
        updated_items.append("uv.lock")
    
    # Copy source code (including static files)
    if bundled_src.exists():
        target_src = OPENAGENT_DIR / "open_agent"
        
        if target_src.exists():
            shutil.rmtree(target_src)
        shutil.copytree(bundled_src, target_src)
        print(f"Updated: open_agent/")
        updated_items.append("open_agent/")
        
        # Verify static files were copied
        static_target = target_src / "app" / "static"
        if static_target.exists():
            static_files = list(static_target.rglob("*"))
            print(f"[DEBUG] Copied static files: {len([f for f in static_files if f.is_file()])}")
        else:
            print(f"[WARNING] Static directory not found after copy: {static_target}")
    else:
        print(f"[ERROR] bundled_src does not exist: {bundled_src}")
    
    # Note: We do NOT clean .pyc files here because our source code IS .pyc files!
    # Only clean __pycache__ directories (which contain old cached .pyc files)
    pyc_cleaned = 0
    for pycache in OPENAGENT_DIR.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache)
            pyc_cleaned += 1
        except Exception:
            pass
    if pyc_cleaned > 0:
        print(f"Cleaned {pyc_cleaned} __pycache__ directories")
    
    return True, updated_items


def show_update_info(updated_items: list, is_first_install: bool = False):
    """Show update information and changelog."""
    new_version, new_date, changelog = get_bundled_version()
    
    if is_first_install:
        print(f"\n{'=' * 60}")
        print(f"Welcome to {APP_NAME}!")
        print(f"{'=' * 60}")
        print(f"Version: {new_version}")
        print(f"Date: {new_date}")
        return
    
    if not updated_items:
        print(f"\nNo updates needed, already at latest version")
        return
    
    print(f"\n{'=' * 60}")
    print(f"Updated to {new_version}")
    print(f"{'=' * 60}")
    
    print(f"\nUpdated files:")
    for item in updated_items:
        print(f"  - {item}")


def find_conda_python() -> Path:
    """Find conda's default Python executable."""
    if os.environ.get('CONDA_PREFIX'):
        conda_prefix = Path(os.environ['CONDA_PREFIX'])
        if platform.system() == "Windows":
            python_exe = conda_prefix / "python.exe"
        else:
            python_exe = conda_prefix / "bin" / "python"
        if python_exe.exists():
            print(f"Found conda Python (current env): {python_exe}")
            return python_exe
    
    conda_exe = os.environ.get('CONDA_EXE')
    if conda_exe:
        conda_dir = Path(conda_exe).parent.parent
        if platform.system() == "Windows":
            python_exe = conda_dir / "python.exe"
            if python_exe.exists():
                print(f"Found conda Python: {python_exe}")
                return python_exe
    
    conda_path = shutil.which("conda")
    if conda_path:
        conda_dir = Path(conda_path).parent.parent
        if platform.system() == "Windows":
            python_exe = conda_dir / "python.exe"
            if python_exe.exists():
                print(f"Found conda Python: {python_exe}")
                return python_exe
    
    common_paths = []
    if platform.system() == "Windows":
        common_paths = [
            Path(os.environ.get('USERPROFILE', '')) / "anaconda3" / "python.exe",
            Path(os.environ.get('USERPROFILE', '')) / "miniconda3" / "python.exe",
            Path("C:/ProgramData/anaconda3/python.exe"),
            Path("C:/ProgramData/miniconda3/python.exe"),
        ]
    elif platform.system() == "Darwin":
        common_paths = [
            Path.home() / "anaconda3" / "bin" / "python",
            Path.home() / "miniconda3" / "bin" / "python",
            Path("/opt/anaconda3/bin/python"),
            Path("/opt/miniconda3/bin/python"),
        ]
    else:
        common_paths = [
            Path.home() / "anaconda3" / "bin" / "python",
            Path.home() / "miniconda3" / "bin" / "python",
            Path("/opt/anaconda3/bin/python"),
            Path("/opt/miniconda3/bin/python"),
        ]
    
    for python_exe in common_paths:
        if python_exe.exists():
            print(f"Found conda Python: {python_exe}")
            return python_exe
    
    return None


def find_system_python() -> Path:
    """Find system Python executable (not conda)."""
    for name in ["python3", "python"]:
        path = shutil.which(name)
        if path:
            python_exe = Path(path)
            if "conda" not in str(python_exe).lower():
                print(f"Found system Python: {python_exe}")
                return python_exe
    
    return None


def find_python() -> tuple:
    """Find the best available Python executable."""
    print(f"\nSearching for Python...")
    
    conda_python = find_conda_python()
    if conda_python:
        return conda_python, True
    
    system_python = find_system_python()
    if system_python:
        return system_python, False
    
    print(f"No Python found on system")
    return None, False


def check_python_version(python_exe: Path) -> bool:
    """Check if Python version meets minimum requirement."""
    try:
        result = subprocess.run(
            [str(python_exe), "--version"],
            capture_output=True,
            text=True,
        )
        version_str = result.stdout.strip() or result.stderr.strip()
        print(f"Python version: {version_str}")
        
        parts = version_str.split()
        if len(parts) >= 2:
            version_parts = parts[1].split(".")
            major = int(version_parts[0])
            minor = int(version_parts[1]) if len(version_parts) > 1 else 0
            
            if (major, minor) >= MIN_PYTHON_VERSION:
                return True
            else:
                print(f"Python {major}.{minor} is below minimum {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}")
                return False
    except Exception as e:
        print(f"Failed to check Python version: {e}")
        return False


def is_uv_installed(python_exe: Path) -> bool:
    """Check if uv is installed."""
    try:
        if shutil.which("uv"):
            return True
        
        result = subprocess.run(
            [str(python_exe), "-m", "uv", "--version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def install_uv(python_exe: Path, is_conda: bool) -> bool:
    """Install uv using the best method."""
    print(f"\nInstalling uv...")
    
    if is_conda:
        system = platform.system()
        
        try:
            if system == "Windows":
                print("Using official installer for Windows...")
                result = subprocess.run(
                    ["powershell", "-Command", "irm https://astral.sh/uv/install.ps1 | iex"],
                    capture_output=True,
                    text=True,
                )
            else:
                print("Using official installer for Unix...")
                result = subprocess.run(
                    "curl -LsSf https://astral.sh/uv/install.sh | sh",
                    shell=True,
                    capture_output=True,
                    text=True,
                    executable="/bin/bash",
                )
            
            if result.returncode == 0:
                print(f"uv installed via official installer")
                uv_path = shutil.which("uv")
                if uv_path:
                    print(f"uv location: {uv_path}")
                    return True
        except Exception as e:
            print(f"Official installer failed: {e}")
    
    print("Installing uv via pip...")
    try:
        result = subprocess.run(
            [str(python_exe), "-m", "pip", "install", "uv"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"uv installed via pip")
            return True
        print(f"pip install failed: {result.stderr}")
    except Exception as e:
        print(f"pip install failed: {e}")
    
    return False


def find_uv_executable(python_exe: Path) -> str:
    """Find uv executable or return python -m uv."""
    uv_path = shutil.which("uv")
    if uv_path:
        return uv_path
    
    if platform.system() == "Windows":
        local_uv = Path.home() / ".local" / "bin" / "uv.exe"
    else:
        local_uv = Path.home() / ".local" / "bin" / "uv"
    
    if local_uv.exists():
        return str(local_uv)
    
    return f"{python_exe} -m uv"


def check_venv_exists() -> bool:
    """Check if .venv exists and has required packages."""
    venv_dir = OPENAGENT_DIR / ".venv"
    if not venv_dir.exists():
        return False
    
    if platform.system() == "Windows":
        site_packages = venv_dir / "Lib" / "site-packages"
    else:
        lib_dir = venv_dir / "lib"
        if not lib_dir.exists():
            return False
        for item in lib_dir.iterdir():
            if item.is_dir() and item.name.startswith("python"):
                site_packages = item / "site-packages"
                break
        else:
            return False
    
    if not site_packages.exists():
        return False
    
    key_packages = ["tiktoken", "prompt_toolkit", "httpx", "pydantic"]
    for pkg in key_packages:
        if not (site_packages / pkg).exists() and not (site_packages / (pkg.replace("-", "_"))).exists():
            return False
    
    return True


def uv_sync(python_exe: Path, force: bool = False) -> bool:
    """Run uv sync to install dependencies."""
    if not force and check_venv_exists():
        print(f"\nDependencies already installed (.venv exists)")
        return True
    
    print(f"\nInstalling dependencies...")
    
    pyproject_path = OPENAGENT_DIR / "pyproject.toml"
    if not pyproject_path.exists():
        print(f"pyproject.toml not found at: {pyproject_path}")
        return False
    
    uv_cmd_str = find_uv_executable(python_exe)
    print(f"Using: {uv_cmd_str}")
    
    if " -m " in uv_cmd_str:
        parts = uv_cmd_str.split(" -m ")
        uv_cmd = [parts[0], "-m", "uv"]
    else:
        uv_cmd = [uv_cmd_str]
    
    try:
        print("Running uv sync (this may take a moment on first run)...")
        
        result = subprocess.run(
            uv_cmd + ["sync", "--python", str(python_exe)],
            cwd=str(OPENAGENT_DIR),
        )
        
        if result.returncode == 0:
            print(f"Dependencies installed")
            return True
        
        print("Retrying with auto-detection...")
        result = subprocess.run(
            uv_cmd + ["sync"],
            cwd=str(OPENAGENT_DIR),
        )
        
        if result.returncode == 0:
            print(f"Dependencies installed")
            return True
        
        print(f"uv sync failed with return code: {result.returncode}")
        return False
    except Exception as e:
        print(f"uv sync failed: {e}")
        return False


def check_config() -> bool:
    """Check if config file exists."""
    config_file = CONFIG_DIR / "config.yaml"
    config_example = CONFIG_DIR / "config-example.yaml"
    
    if not config_file.exists():
        if config_example.exists():
            shutil.copy(config_example, config_file)
            print(f"Created config from example: {config_file}")
    
    return True


def get_venv_python() -> Path:
    """Get Python from .venv if exists."""
    venv_dir = OPENAGENT_DIR / ".venv"
    if venv_dir.exists():
        if platform.system() == "Windows":
            return venv_dir / "Scripts" / "python.exe"
        else:
            return venv_dir / "bin" / "python"
    return Path(sys.executable)


# ==================== 新架构 ====================

def setup_venv_environment():
    """Setup Python to use the venv's site-packages when running from frozen exe."""
    if not IS_FROZEN:
        return True
    
    print(f"[VENV] Setting up venv environment...")
    
    venv_dir = OPENAGENT_DIR / ".venv"
    if not venv_dir.exists():
        print(f"ERROR: .venv not found at {venv_dir}")
        return False
    
    print(f"[VENV] Found .venv at: {venv_dir}")
    
    # Get site-packages path
    if platform.system() == "Windows":
        site_packages = venv_dir / "Lib" / "site-packages"
        venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        lib_dir = venv_dir / "lib"
        site_packages = None
        for item in lib_dir.iterdir():
            if item.is_dir() and item.name.startswith("python"):
                site_packages = item / "site-packages"
                break
        venv_python = venv_dir / "bin" / "python"
    
    if not site_packages or not site_packages.exists():
        print(f"ERROR: site-packages not found in venv: {site_packages}")
        return False
    
    print(f"[VENV] Found site-packages: {site_packages}")
    
    # Add venv's site-packages to sys.path
    site_packages_str = str(site_packages)
    if site_packages_str not in sys.path:
        sys.path.insert(0, site_packages_str)
        print(f"[VENV] Added to sys.path: {site_packages_str}")
    
    # Set PYTHONTABSPATH to help with imports
    os.environ["PYTHONPATH"] = str(SOURCE_DIR) + os.pathsep + site_packages_str
    
    # Verify key packages can be imported
    try:
        import tiktoken
        print(f"[VENV] tiktoken imported successfully")
    except ImportError as e:
        print(f"[VENV] ERROR: Failed to import tiktoken: {e}")
        return False
    
    print(f"[VENV] Environment setup complete!")
    return True


def run_application_service(host: str = "127.0.0.1", port: int = 9998, open_browser: bool = True):
    """运行AgentService - 新架构的核心入口
    
    这是新的主入口，启动AgentService来管理所有Agent。
    Web和CLI不再共用Agent，各自独立。
    """
    global _web_url, _agent_service
    _web_url = f"http://{host}:{port}"
    
    # 设置环境变量
    os.environ["OPEN_AGENT_CONFIG_DIR"] = str(CONFIG_DIR)
    os.environ["OPEN_AGENT_SKILLS_DIR"] = str(SKILLS_DIR)
    
    print(f"\n{'=' * 60}")
    print(f"Starting {APP_NAME} Service...")
    print(f"Web UI: {_web_url}")
    print(f"{'=' * 60}\n")
    
    # Setup venv environment for frozen exe
    if IS_FROZEN:
        if not setup_venv_environment():
            print("Failed to setup venv environment")
            return
    
    # 添加源码目录到Python路径
    sys.path.insert(0, str(SOURCE_DIR))
    
    # 初始化AgentService
    from open_agent.agent_service import init_agent_service
    _agent_service = init_agent_service(
        host=host,
        port=port,
        workspace_dir=str(SOURCE_DIR),
    )
    
    # 启动托盘
    if TRAY_AVAILABLE:
        from open_agent.tray import start_tray
        start_tray(
            host=host,
            port=port,
            workspace_dir=str(SOURCE_DIR),
            on_exit=stop_application,
        )
        print("[OK] System tray started")
    
    # 启动服务（包含Web服务器）
    try:
        print("Starting web server...")
        _agent_service.start(open_browser=open_browser)
        print(f"[OK] Web server started at {_web_url}")
        if open_browser:
            print("Opening browser...")
    except Exception as e:
        print(f"[ERROR] Failed to start web server: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 保持运行
    try:
        while _agent_service._running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        stop_application()


def stop_application():
    """停止应用程序"""
    global _agent_service
    
    print("Stopping application...")
    
    if _agent_service:
        _agent_service.stop()
    
    # 停止托盘
    if TRAY_AVAILABLE:
        from open_agent.tray import stop_tray
        stop_tray()
    
    print("Application stopped")


def run_cli_only(workspace_dir: Path = None):
    """运行纯CLI模式（不启动Web服务）"""
    os.environ["OPEN_AGENT_CONFIG_DIR"] = str(CONFIG_DIR)
    os.environ["OPEN_AGENT_SKILLS_DIR"] = str(SKILLS_DIR)
    
    sys.path.insert(0, str(SOURCE_DIR))
    
    # 运行CLI
    from open_agent.cli import main
    sys.argv = ["open-agent", "--cli-only"]
    if workspace_dir:
        sys.argv.extend(["--workspace", str(workspace_dir)])
    main()


# ==================== 主函数 ====================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description=f"{APP_NAME} Launcher")
    parser.add_argument("--install", "-i", action="store_true", help="Install deps only")
    parser.add_argument("--update-deps", "-u", action="store_true", help="Force update dependencies")
    parser.add_argument("--skip-deps", action="store_true", help="Skip dep check")
    parser.add_argument("--port", "-p", type=int, default=9998, help="Web UI port")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Web UI host")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")
    parser.add_argument("--cli", action="store_true", help="Use console mode (show terminal)")
    parser.add_argument("--cli-only", action="store_true", help="Run CLI only (no Web UI)")
    parser.add_argument("--version", "-v", action="version", version=f"{APP_NAME} 1.0.0")
    
    args, unknown = parser.parse_known_args()
    
    # 检查是否使用托盘模式
    use_tray = IS_FROZEN and not args.cli and not args.cli_only
    
    if use_tray:
        setup_tray_logging()
    
    print_header(f"{APP_NAME} Launcher")
    print(f"Platform: {platform.system()} ({platform.machine()})")
    
    if IS_FROZEN:
        print(f"Mode: Packaged executable")
        print(f"Exe: {EXE_PATH}")
        print(f"Target: {OPENAGENT_DIR}")
        if use_tray:
            print(f"Tray Mode: Enabled")
    else:
        print(f"Mode: Development")
    
    # 提取资源
    is_first_install = not OPENAGENT_DIR.exists()
    updated_items = []
    
    if IS_FROZEN:
        success, updated_items = extract_resources()
        if not success:
            print(f"Failed to extract resources")
            return 1
        
        show_update_info(updated_items, is_first_install)
    
    # 查找Python
    python_exe, is_conda = find_python()
    
    if python_exe is None:
        print(f"\nNo Python found!")
        return 1
    
    if is_conda:
        print(f"Using conda Python: {python_exe}")
    else:
        print(f"Using system Python: {python_exe}")
    
    # 检查Python版本
    if not check_python_version(python_exe):
        print(f"Python version may be too old, continuing anyway...")
    
    # 安装依赖
    if not args.skip_deps:
        if not is_uv_installed(python_exe):
            if not install_uv(python_exe, is_conda):
                print(f"Failed to install uv")
                return 1
        else:
            print(f"\nuv is already installed")
        
        if not uv_sync(python_exe, force=args.update_deps):
            print(f"Failed to install dependencies")
            return 1
    
    if args.update_deps and args.install:
        print(f"\nDependencies updated!")
        return 0
    
    if args.install:
        print(f"\nInstallation complete!")
        print(f"Config: {CONFIG_DIR}")
        print(f"Skills: {SKILLS_DIR}")
        return 0
    
    check_config()
    
    # CLI only mode
    if args.cli_only:
        run_cli_only()
        return 0
    
    # 运行应用服务
    try:
        run_application_service(
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 0
    
    return 0


if __name__ == "__main__":
    sys.exit(main())