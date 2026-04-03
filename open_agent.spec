# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for open_agent

This builds a standalone launcher executable that:
1. Compiles source to bytecode (.pyc) for protection
2. Contains embedded bytecode (open_agent/)
3. Contains embedded resources (config/, skills/)
4. On first run, extracts to hidden user app directory
5. Installs dependencies via uv
6. Runs the application

Usage:
    python build.py

Output:
    dist/agent.exe (Windows) or dist/agent (Linux/macOS)
"""

import sys
import platform
from pathlib import Path

# Get the project root directory
PROJECT_ROOT = Path(SPECPATH).absolute()

# Use bytecode directory for protected source code
BYTECODE_DIR = PROJECT_ROOT / "build" / "bytecode"
OPEN_AGENT_DIR = BYTECODE_DIR / "open_agent"

# Fallback to source if bytecode not available (for development)
if not OPEN_AGENT_DIR.exists():
    OPEN_AGENT_DIR = PROJECT_ROOT / "open_agent"

# Determine the executable name based on platform
# Using "OpenAgentSeal" as the executable name
if sys.platform == "win32":
    exe_name = "OpenAgentSeal"
elif sys.platform == "darwin":
    exe_name = "OpenAgentSeal"
else:
    exe_name = "OpenAgentSeal"

# Icon file path
icon_path = PROJECT_ROOT / "icon.ico"

block_cipher = None

# Collect SSL DLLs for conda environments on Windows
binaries = []
if sys.platform == "win32":
    import os
    ssl_dll_names = ['libssl-3-x64.dll', 'libssl-1_1-x64.dll', 
                     'libcrypto-3-x64.dll', 'libcrypto-1_1-x64.dll']
    
    # Check conda environment
    conda_prefix = os.environ.get('CONDA_PREFIX')
    if conda_prefix:
        conda_bin = Path(conda_prefix) / 'Library' / 'bin'
        for dll_name in ssl_dll_names:
            dll_path = conda_bin / dll_name
            if dll_path.exists():
                binaries.append((str(dll_path), '.'))
                print(f"Adding SSL DLL: {dll_path}")
    
    # Check Python directory
    python_dir = Path(sys.executable).parent
    for dll_name in ssl_dll_names:
        dll_path = python_dir / dll_name
        if dll_path.exists():
            binaries.append((str(dll_path), '.'))
            print(f"Adding SSL DLL: {dll_path}")

# Data files to embed
# Collect open_agent source files, excluding config/ and skills/ subdirectories
# because they are packaged separately at root level
def collect_open_agent_files(src_dir, dest_prefix, excludes):
    """Collect files from directory, excluding specified subdirectories."""
    result = []
    src_path = Path(src_dir)
    if not src_path.exists():
        print(f"[WARNING] Source directory does not exist: {src_path}")
        return result
    
    print(f"[INFO] Collecting files from: {src_path}")
    file_count = 0
    for file_path in src_path.rglob("*"):
        if file_path.is_file():
            # Check if file is in excluded directory
            rel_parts = file_path.relative_to(src_path).parts
            if any(excl in rel_parts for excl in excludes):
                continue
            
            # Create destination path
            rel_path = file_path.relative_to(src_path)
            dest_path = f"{dest_prefix}/{rel_path}"
            result.append((str(file_path), f"{dest_prefix}/{rel_path.parent}"))
            file_count += 1
    
    print(f"[INFO] Collected {file_count} files from {src_path}")
    return result

# Collect open_agent source files (excluding config, skills, __pycache__)
# Note: app/static is NOT excluded, so it will be included in the package
open_agent_datas = collect_open_agent_files(
    OPEN_AGENT_DIR, 
    "open_agent", 
    ["config", "skills", "__pycache__"]
)

# Check if static files are included
static_files = [d for d in open_agent_datas if "static" in d[1]]
print(f"[INFO] Static files in open_agent_datas: {len(static_files)}")
for sf in static_files[:5]:  # Show first 5
    print(f"  - {sf[0]} -> {sf[1]}")

datas = [
    # Embed config directory at root level (not inside open_agent/)
    (str(PROJECT_ROOT / "open_agent" / "config"), "config"),
    
    # Embed skills directory at root level (not inside open_agent/)
    (str(PROJECT_ROOT / "open_agent" / "skills"), "skills"),
    
    # NOTE: Static web files are now included via open_agent_datas from bytecode directory
    # Do NOT add duplicate entry here to avoid conflicts
    
    # Embed pyproject.toml and uv.lock for dependency resolution
    (str(PROJECT_ROOT / "pyproject.toml"), "."),
    (str(PROJECT_ROOT / "uv.lock"), "."),
    
    # Embed LICENSE file
    (str(PROJECT_ROOT / "LICENSE"), "."),
    
    # Embed VERSION.md for version tracking and updates
    (str(PROJECT_ROOT / "VERSION.md"), "."),
] + open_agent_datas

# Print datas summary
print(f"[INFO] Total datas entries: {len(datas)}")

# Analysis - entry point is launcher.py
a = Analysis(
    [str(PROJECT_ROOT / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,  # Includes open_agent source (without config/skills), config/, skills/, and other files
    hiddenimports=[
        # Standard library
        "argparse",
        "os",
        "pathlib",
        "platform",
        "shutil",
        "subprocess",
        "sys",
        "threading",
        "time",
        "datetime",
        "webbrowser",
        "queue",
        # GUI console (tkinter)
        "tkinter",
        "tkinter.ttk",
        "tkinter.scrolledtext",
        # Tray dependencies
        "pystray",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        # Windows API
        "ctypes",
        "ctypes.wintypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy packages that launcher doesn't need
        # (they will be installed by uv sync)
        # Note: PIL is needed for tray icon, don't exclude
        # Note: tkinter is needed for GUI console, don't exclude
        "matplotlib",
        "numpy",
        "pandas",
        "cv2",
        "torch",
        "tensorflow",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Remove duplicate entries
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Create the executable
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disable UPX to avoid issues
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Use GUI mode for better tray integration
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)

# Print build info
print(f"\n{'=' * 50}")
print(f"Building open_agent launcher for {sys.platform}")
print(f"{'=' * 50}")
print(f"Entry point: launcher.py")
print(f"Embedded source: open_agent/")
print(f"Embedded config: config/")
print(f"Embedded skills: skills/")
print(f"Output: dist/{exe_name}.exe" if sys.platform == "win32" else f"Output: dist/{exe_name}")
print(f"{'=' * 50}\n")