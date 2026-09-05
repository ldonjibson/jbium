#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════
Jbium — Universal Installer
════════════════════════════════════════════════════════════

Installs the stealth browser for the current platform.
Works on: Windows, Linux, macOS

Usage:
    python install.py              # Install to default location
    python install.py --prefix DIR # Install to custom location
    python install.py --uninstall  # Remove installation
"""

import os
import sys
import platform
import shutil
import argparse
from pathlib import Path


# ─────────────────────────────────────────────
# Platform Detection
# ─────────────────────────────────────────────

def detect_platform():
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "macos"
    elif system == "linux":
        return "linux"
    raise RuntimeError(f"Unsupported: {system}")


def get_install_dir(platform_name: str, custom_prefix: str = None) -> Path:
    """Get default install directory for platform"""
    
    if custom_prefix:
        return Path(custom_prefix)
    
    if platform_name == "windows":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return appdata / "Jbium"
    
    elif platform_name == "macos":
        return Path.home() / "Library" / "Jbium"
    
    else:  # linux
        return Path.home() / ".local" / "share" / "jbium"


def get_bin_dir(platform_name: str, install_dir: Path) -> Path:
    """Get directory where executables are placed"""
    
    if platform_name == "windows":
        return install_dir  # Same directory on Windows
    
    else:
        return install_dir / "bin"


# ─────────────────────────────────────────────
# Install
# ─────────────────────────────────────────────

def install(source_dir: Path, install_dir: Path) -> bool:
    """Install stealth browser from source directory"""
    
    platform_name = detect_platform()
    binary_name = get_binary_name(platform_name)
    
    print(f"══════════════════════════════════════════════════════════")
    print(f"  Installing Jbium")
    print(f"══════════════════════════════════════════════════════════")
    print(f"  Platform: {platform_name}")
    print(f"  Source:   {source_dir}")
    print(f"  Target:   {install_dir}")
    print()
    
    # Create directories
    install_dir.mkdir(parents=True, exist_ok=True)
    bin_dir = get_bin_dir(platform_name, install_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy binary
    binary_source = None
    for candidate in [
        source_dir / "chrome" / binary_name,
        source_dir / binary_name,
        source_dir / platform_name / binary_name,
    ]:
        if candidate.exists():
            binary_source = candidate
            break
    
    if not binary_source:
        print(f"❌ Binary not found: {binary_name}")
        print(f"   Searched: {source_dir}")
        return False
    
    binary_dest = bin_dir / binary_name
    print(f"  Copying binary... ", end="", flush=True)
    shutil.copy2(binary_source, binary_dest)
    if platform_name != "windows":
        os.chmod(binary_dest, 0o755)
    print("✅")
    
    # Copy resources
    resources = ["resources.pak", "natives_blob.bin", "snapshot_blob.bin",
                 "v8_context_snapshot.bin", "icudtl.dat"]
    
    for res_name in resources:
        res_source = source_dir / "chrome" / res_name
        if not res_source.exists():
            res_source = source_dir / res_name
        
        if res_source.exists():
            print(f"  Copying {res_name}... ", end="", flush=True)
            shutil.copy2(res_source, bin_dir / res_name)
            print("✅")
    
    # Copy locales
    locales_dir = source_dir / "locales"
    if locales_dir.exists():
        print(f"  Copying locales... ", end="", flush=True)
        dest_locales = bin_dir / "locales"
        dest_locales.mkdir(exist_ok=True)
        for pak_file in locales_dir.glob("*.pak"):
            shutil.copy2(pak_file, dest_locales)
        print("✅")
    
    # Copy libraries
    lib_patterns = {
        "linux": ["*.so"],
        "windows": ["*.dll"],
        "macos": ["*.dylib"],
    }
    
    for pattern in lib_patterns[platform_name]:
        for lib in source_dir.glob(f"chrome/{pattern}"):
            print(f"  Copying {lib.name}... ", end="", flush=True)
            shutil.copy2(lib, bin_dir / lib.name)
            print("✅")
    
    # Copy fonts
    fonts_source = source_dir / "fonts" / platform_name
    if not fonts_source.exists():
        fonts_source = source_dir / "fonts"
    
    if fonts_source.exists() and any(fonts_source.iterdir()):
        fonts_dest = bin_dir / "fonts"
        fonts_dest.mkdir(exist_ok=True)
        print(f"  Copying fonts... ", end="", flush=True)
        shutil.copytree(fonts_source, fonts_dest, dirs_exist_ok=True)
        print("✅")
    
    # Copy launcher
    launcher_source = source_dir / "stealth_browser.py"
    if launcher_source.exists():
        print(f"  Installing launcher... ", end="", flush=True)
        launcher_dest = bin_dir / "stealth_browser.py"
        shutil.copy2(launcher_source, launcher_dest)
        print("✅")
    
    # Create platform-specific executable wrapper
    print(f"  Creating command... ", end="", flush=True)
    
    if platform_name == "windows":
        # Create .bat wrapper
        bat_content = f'''@echo off
setlocal
set SCRIPT_DIR=%~dp0
set PYTHON=python
where python >nul 2>&1 || set PYTHON=python3
%PYTHON% "%SCRIPT_DIR%stealth_browser.py" %*
endlocal
'''
        (bin_dir / "jbium.bat").write_text(bat_content)
        
        # Add to PATH
        add_to_path_windows(bin_dir)
        
    else:
        # Create shell wrapper
        sh_content = f'''#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
exec python3 "$SCRIPT_DIR/stealth_browser.py" "$@"
'''
        wrapper = bin_dir / "jbium"
        wrapper.write_text(sh_content)
        os.chmod(wrapper, 0o755)
        
        # Add to PATH
        add_to_path_unix(bin_dir)
    
    print("✅")
    
    # Copy driver and config
    for dir_name in ["driver", "config"]:
        src = source_dir / dir_name
        if src.exists():
            print(f"  Copying {dir_name}/... ", end="", flush=True)
            shutil.copytree(src, install_dir / dir_name, dirs_exist_ok=True)
            print("✅")
    
    # Verify
    print(f"\n  Verifying installation... ", end="", flush=True)
    
    if platform_name == "windows":
        verify_cmd = [str(binary_dest), "--version"]
    else:
        verify_cmd = [str(binary_dest), "--version"]
    
    try:
        import subprocess
        result = subprocess.run(
            verify_cmd, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print("✅")
            version = result.stdout.strip()
            print(f"  Browser: {version}")
        else:
            print("⚠️  (may still work)")
    except Exception:
        print("⚠️  (could not verify)")
    
    # Done
    print(f"\n══════════════════════════════════════════════════════════")
    print(f"  ✅ Installation Complete")
    print(f"══════════════════════════════════════════════════════════")
    print(f"\n  Location: {install_dir}")
    print(f"  Command:  jbium")
    print(f"\n  Usage:")
    print(f"    jbium [args...]")
    print(f"\n  Or with Python:")
    print(f"    from driver.stealth_browser import Jbium")
    print(f"    browser = Jbium()")
    print()
    
    return True


def get_binary_name(platform_name):
    if platform_name == "windows":
        return "jbium.exe"
    return "jbium"


def add_to_path_windows(directory: Path):
    """Add directory to Windows PATH"""
    
    import winreg
    
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_READ
        )
        current_path, _ = winreg.QueryValueEx(key, "Path")
        winreg.CloseKey(key)
    except FileNotFoundError:
        current_path = ""
    
    dir_str = str(directory)
    if dir_str not in current_path:
        new_path = f"{current_path};{dir_str}" if current_path else dir_str
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
        winreg.CloseKey(key)
        print(f"\n  Added to PATH: {dir_str}")
        print(f"  (Restart terminal to take effect)")


def add_to_path_unix(directory: Path):
    """Add directory to PATH on Unix systems"""
    
    shell = os.environ.get("SHELL", "/bin/bash")
    
    if "zsh" in shell:
        rc_file = Path.home() / ".zshrc"
    else:
        rc_file = Path.home() / ".bashrc"
    
    export_line = f'export PATH="$PATH:{directory}"'
    
    if rc_file.exists():
        content = rc_file.read_text()
        if str(directory) not in content:
            with open(rc_file, "a") as f:
                f.write(f"\n# Jbium\n{export_line}\n")
            print(f"\n  Added to PATH (via {rc_file})")
            print(f"  Run: source {rc_file}")


# ─────────────────────────────────────────────
# Uninstall
# ─────────────────────────────────────────────

def uninstall(install_dir: Path):
    """Remove stealth browser installation"""
    
    print(f"Removing Jbium from {install_dir}...")
    
    if install_dir.exists():
        shutil.rmtree(install_dir)
        print("  ✅ Removed")
    else:
        print("  ⚠️  Not found")
    
    # TODO: Remove from PATH


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jbium Installer")
    parser.add_argument("--prefix", type=str, help="Custom install directory")
    parser.add_argument("--uninstall", action="store_true", help="Remove installation")
    parser.add_argument("--source", type=str, default=".", help="Source directory")
    
    args = parser.parse_args()
    
    platform_name = detect_platform()
    install_dir = get_install_dir(platform_name, args.prefix)
    
    if args.uninstall:
        uninstall(install_dir)
    else:
        source_dir = Path(args.source).resolve()
        success = install(source_dir, install_dir)
        sys.exit(0 if success else 1)
