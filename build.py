#!/usr/bin/env python3
"""
Build script for OpenAgent standalone launcher

This script builds a single executable using PyInstaller that:
1. Compiles source code to bytecode (.pyc) for protection
2. Embeds all source code (open_agent/, config/, skills/)
3. Embeds VERSION.md for version tracking
4. On first run, extracts to hidden user app directory
5. Installs dependencies via uv
6. Runs the application

Usage:
    python build.py              # Build executable
    python build.py --clean      # Clean build first
    python build.py --version V1.0.1 --release "Fixed bug"  # Update version and build
"""

import argparse
import compileall
import io
import platform
import py_compile
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Fix Windows console encoding for Unicode characters (emoji)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).parent.absolute()
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
SPECFILE = PROJECT_ROOT / "open_agent.spec"
VERSION_FILE = PROJECT_ROOT / "VERSION.md"
BYTECODE_DIR = PROJECT_ROOT / "build" / "bytecode"
IS_WINDOWS = platform.system() == "Windows"


def build_frontend() -> bool:
    """Build Vue frontend.
    
    Returns:
        True if build succeeded, False otherwise
    """
    print("\n🌐 Building Vue frontend...")
    
    web_dir = PROJECT_ROOT / "open_agent" / "app" / "web"
    
    if not web_dir.exists():
        print("  ⚠️  Web directory not found, skipping frontend build")
        return True
    
    package_json = web_dir / "package.json"
    if not package_json.exists():
        print("  ⚠️  package.json not found, skipping frontend build")
        return True
    
    # Check if npm is available
    npm_cmd = shutil.which("npm")
    if not npm_cmd:
        print("  ⚠️  npm not found, skipping frontend build")
        return True
    
    # Install dependencies
    print("  📦 Installing npm dependencies...")
    result = subprocess.run(
        [npm_cmd, "install"],
        cwd=web_dir,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    
    if result.returncode != 0:
        print(f"  ⚠️  npm install failed: {result.stderr}")
        return False
    
    # Build frontend
    print("  🔨 Building Vue frontend...")
    result = subprocess.run(
        [npm_cmd, "run", "build"],
        cwd=web_dir,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    
    if result.returncode != 0:
        print(f"  ⚠️  npm build failed: {result.stderr}")
        return False
    
    # Verify output
    static_dir = PROJECT_ROOT / "open_agent" / "app" / "static"
    if static_dir.exists():
        files = list(static_dir.rglob("*"))
        print(f"  ✅ Frontend built successfully ({len([f for f in files if f.is_file()])} files)")
        return True
    else:
        print("  ⚠️  Static directory not found after build")
        return False


def compile_to_bytecode() -> Path:
    """Compile Python source files to bytecode for source protection.
    
    This function:
    1. Creates a temporary directory for bytecode
    2. Compiles all .py files to .pyc files
    3. Flattens the structure (removes __pycache__ nesting)
    
    Returns:
        Path to the bytecode directory
    """
    print("\n📦 Compiling source to bytecode for protection...")
    
    # Clean previous bytecode directory
    if BYTECODE_DIR.exists():
        shutil.rmtree(BYTECODE_DIR)
    BYTECODE_DIR.mkdir(parents=True)
    
    # IMPORTANT: Clean all __pycache__ directories FIRST to ensure fresh compilation
    # This is necessary because compileall.compile_dir() with force=True sometimes
    # doesn't properly recompile existing .pyc files (a known Python issue)
    source_dirs = ["open_agent"]
    for src_dir in source_dirs:
        src_path = PROJECT_ROOT / src_dir
        if src_path.exists():
            for pycache in src_path.rglob("__pycache__"):
                try:
                    shutil.rmtree(pycache)
                except Exception as e:
                    print(f"  ⚠️  Failed to remove {pycache}: {e}")
    print("  ✅ Cleaned __pycache__ directories for fresh compilation")
    
    # Directories to exclude from compilation (they are packaged separately)
    exclude_dirs = {"config", "skills", "__pycache__"}
    
    for src_dir in source_dirs:
        src_path = PROJECT_ROOT / src_dir
        if not src_path.exists():
            print(f"  ⚠️  Source directory not found: {src_dir}")
            continue
        
        # Compile all .py files in the directory
        # We'll filter out config/ and skills/ when copying .pyc files
        compileall.compile_dir(
            src_path,
            force=True,
            quiet=1,
            optimize=2,  # Optimization level 2 (remove docstrings and asserts)
        )
        
        # Copy .pyc files to bytecode directory with flattened structure
        # We need to handle both root-level and nested __pycache__ directories
        # Note: exclude_dirs does NOT include __pycache__ because .pyc files are IN __pycache__
        for pyc_file in src_path.rglob("*.pyc"):
            # Only process files in __pycache__ directories
            if "__pycache__" not in pyc_file.parts:
                continue
            
            # Skip files in excluded directories (config, skills)
            # Note: We check for config/skills in the path, not __pycache__
            if "config" in pyc_file.parts or "skills" in pyc_file.parts:
                continue
            
            # Get the relative path from source directory
            rel_path = pyc_file.relative_to(src_path)
            
            # Build the destination path by removing __pycache__ from the path
            # e.g., __pycache__/foo.cpython-311.pyc -> foo.pyc
            # e.g., subpkg/__pycache__/bar.cpython-311.pyc -> subpkg/bar.pyc
            parts = list(rel_path.parts)
            
            # Remove __pycache__ from parts
            while "__pycache__" in parts:
                idx = parts.index("__pycache__")
                parts.pop(idx)
            
            # Get the filename and extract module name (remove .cpython-XY suffix)
            filename = parts[-1]  # e.g., foo.cpython-311.pyc
            
            # Extract module name from pyc filename
            # Patterns: module.cpython-311.opt-2.pyc, module.cpython-311.pyc
            module_name = filename
            for suffix in [".cpython-310.opt-2.pyc", ".cpython-311.opt-2.pyc", 
                          ".cpython-310.pyc", ".cpython-311.pyc", ".pyc"]:
                if module_name.endswith(suffix):
                    module_name = module_name[:-len(suffix)]
                    break
            
            parts[-1] = f"{module_name}.pyc"
            
            # Build destination path
            dest_rel_path = Path(*parts)
            dest_file = BYTECODE_DIR / src_dir / dest_rel_path
            
            # Create parent directories and copy
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pyc_file, dest_file)
    
    # Copy non-Python files (excluding config/ and skills/ - they are packaged separately)
    # config/ and skills/ should be at the root level, not inside open_agent/
    exclude_dirs = {"config", "skills", "__pycache__"}
    
    for src_dir in source_dirs:
        src_path = PROJECT_ROOT / src_dir
        if not src_path.exists():
            continue
        
        for file_path in src_path.rglob("*"):
            if file_path.is_file() and not file_path.suffix == ".py" and not file_path.suffix == ".pyc":
                # Skip files in excluded directories (config, skills, __pycache__)
                if any(excluded in file_path.parts for excluded in exclude_dirs):
                    continue
                rel_path = file_path.relative_to(src_path)
                dest_path = BYTECODE_DIR / src_dir / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, dest_path)
    
    # Count compiled files
    pyc_count = len(list(BYTECODE_DIR.rglob("*.pyc")))
    other_count = len([f for f in BYTECODE_DIR.rglob("*") if f.is_file() and not f.suffix == ".pyc"])
    
    print(f"  ✅ Compiled {pyc_count} Python files to bytecode")
    print(f"  ✅ Copied {other_count} non-Python files")
    print(f"  📁 Bytecode directory: {BYTECODE_DIR}")
    
    return BYTECODE_DIR


def get_current_version() -> tuple[str, str]:
    """Get current version from VERSION.md.
    
    Returns:
        Tuple of (version, date)
    """
    if not VERSION_FILE.exists():
        return "V0.0.0", ""
    
    try:
        content = VERSION_FILE.read_text(encoding="utf-8")
        version = "V0.0.0"
        date = ""
        
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("## Version:"):
                version = line.replace("## Version:", "").strip()
            elif line.startswith("## Release Date:"):
                date = line.replace("## Release Date:", "").strip()
        
        return version, date
    except Exception:
        return "V0.0.0", ""


def update_version(new_version: str, release_notes: list[str] = None):
    """Update VERSION.md with new version and release notes.
    
    Args:
        new_version: New version string (e.g., "V1.0.1")
        release_notes: List of release notes for this version
    """
    current_version, _ = get_current_version()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Build changelog entry
    changelog_entry = f"### {new_version} ({today})\n"
    if release_notes:
        for note in release_notes:
            changelog_entry += f"- {note}\n"
    else:
        changelog_entry += "- Updated\n"
    
    # Read existing content
    if VERSION_FILE.exists():
        content = VERSION_FILE.read_text(encoding="utf-8")
    else:
        content = """# OpenAgent Version Info

## Version: V0.0.0

## Release Date: 

## Changelog

"""
    
    # Update version and date
    content = re.sub(
        r"## Version:.*",
        f"## Version: {new_version}",
        content
    )
    content = re.sub(
        r"## Release Date:.*",
        f"## Release Date: {today}",
        content
    )
    
    # Add new changelog entry after "## Changelog"
    if "## Changelog" in content:
        parts = content.split("## Changelog", 1)
        content = parts[0] + "## Changelog\n\n" + changelog_entry + parts[1].lstrip()
    
    VERSION_FILE.write_text(content, encoding="utf-8")
    print(f"✅ Updated version: {current_version} → {new_version}")
    print(f"   Date: {today}")


def parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse version string to tuple."""
    version_str = version_str.lstrip("Vv")
    parts = version_str.split(".")
    major = int(parts[0]) if len(parts) > 0 else 0
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0
    return (major, minor, patch)


def increment_version(current: str, increment: str) -> str:
    """Increment version by major, minor, or patch.
    
    Args:
        current: Current version string
        increment: "major", "minor", or "patch"
    
    Returns:
        New version string
    """
    major, minor, patch = parse_version(current)
    
    if increment == "major":
        major += 1
        minor = 0
        patch = 0
    elif increment == "minor":
        minor += 1
        patch = 0
    else:  # patch
        patch += 1
    
    return f"V{major}.{minor}.{patch}"


def main():
    parser = argparse.ArgumentParser(
        description="Build OpenAgent standalone launcher executable",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python build.py                          # Build executable
    python build.py --clean                  # Clean build first
    python build.py --version V1.0.1         # Set version and build
    python build.py --minor                  # Increment minor version and build
    python build.py --patch --release "Fix"  # Increment patch with note

The built executable will:
1. Extract to OpenAgent directory (sibling to exe)
2. Check version and show changelog on update
3. Install uv and dependencies automatically
4. Run the OpenAgent application
        """
    )
    parser.add_argument("--clean", action="store_true", help="Clean build and dist directories first")
    parser.add_argument("--version", "-v", type=str, help="Set specific version (e.g., V1.0.1)")
    parser.add_argument("--major", action="store_true", help="Increment major version (V1.0.0 -> V2.0.0)")
    parser.add_argument("--minor", action="store_true", help="Increment minor version (V1.0.0 -> V1.1.0)")
    parser.add_argument("--patch", action="store_true", help="Increment patch version (V1.0.0 -> V1.0.1)")
    parser.add_argument("--release", "-r", type=str, action="append", help="Release note (can be used multiple times)")
    parser.add_argument("--show-version", action="store_true", help="Show current version and exit")
    args = parser.parse_args()
    
    # Show version and exit
    if args.show_version:
        current, date = get_current_version()
        print(f"Current version: {current}")
        if date:
            print(f"Release date: {date}")
        return 0
    
    print("=" * 60)
    print("  OpenAgent Build Script")
    print("=" * 60)
    print(f"Platform: {platform.system()}")
    print(f"Python: {sys.version.split()[0]}")
    
    # Show current version
    current_version, current_date = get_current_version()
    print(f"Version: {current_version} ({current_date})")
    print("=" * 60)
    
    # Handle version update
    if args.version:
        update_version(args.version, args.release)
    elif args.major:
        new_version = increment_version(current_version, "major")
        update_version(new_version, args.release)
    elif args.minor:
        new_version = increment_version(current_version, "minor")
        update_version(new_version, args.release)
    elif args.patch:
        new_version = increment_version(current_version, "patch")
        update_version(new_version, args.release)
    
    # Clean if requested
    if args.clean:
        print("\nCleaning...")
        for d in [BUILD_DIR, DIST_DIR]:
            if d.exists():
                try:
                    shutil.rmtree(d)
                    print(f"  Removed {d.name}/")
                except PermissionError:
                    print(f"  ⚠️  Cannot remove {d.name}/ (in use), skipping...")
                except Exception as e:
                    print(f"  ⚠️  Error removing {d.name}/: {e}")
    
    # Install pyinstaller if needed
    try:
        import PyInstaller
        print(f"\n✅ PyInstaller installed")
    except ImportError:
        print("\nInstalling PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
    
    # Build Vue frontend first
    if not build_frontend():
        print("  ⚠️  Frontend build failed, continuing with build...")
    
    # Compile source to bytecode for protection
    compile_to_bytecode()
    
    # Build
    print("\nBuilding standalone launcher...")
    cmd = [sys.executable, "-m", "PyInstaller", str(SPECFILE), "--clean", "--noconfirm"]
    
    result = subprocess.run(cmd)
    
    if result.returncode != 0:
        print("\n❌ Build failed!")
        return 1
    
    # Verify output
    if IS_WINDOWS:
        exe_path = DIST_DIR / "OpenAgentSeal.exe"
    else:
        exe_path = DIST_DIR / "OpenAgentSeal"
    
    if exe_path.exists():
        size = exe_path.stat().st_size / (1024 * 1024)
        print("\n" + "=" * 50)
        print("✅ Build successful!")
        print("=" * 50)
        print(f"\nExecutable: {exe_path}")
        print(f"Size: {size:.1f} MB")
        print(f"\nHow it works:")
        print(f"  1. First run: extracts source code to user app directory")
        print(f"     - Windows: %APPDATA%\\open-agent\\")
        print(f"     - Linux/macOS: ~/.open-agent/")
        print(f"  2. Installs uv package manager (if not installed)")
        print(f"  3. Runs 'uv sync' to install dependencies")
        print(f"  4. Starts open_agent application")
        print(f"\nUsage:")
        if IS_WINDOWS:
            print(f"  {exe_path}              # Run interactively")
            print(f"  {exe_path} --install    # Install dependencies only")
            print(f"  {exe_path} --task \"...\" # Run with a task")
        else:
            print(f"  ./{exe_path.name}              # Run interactively")
            print(f"  ./{exe_path.name} --install    # Install dependencies only")
            print(f"  ./{exe_path.name} --task \"...\" # Run with a task")
        print("")
    else:
        print(f"\n❌ Executable not found: {exe_path}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())