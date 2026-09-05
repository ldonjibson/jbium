#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════
Jbium — Universal Launcher
════════════════════════════════════════════════════════════

Cross-platform launcher for Jbium.
Detects OS and launches the correct binary.

Works on: Windows, Linux, macOS
Requires: Python 3.8+

Usage:
    python stealth_browser.py [chrome_args...]
    
    # Or after installation:
    jbium [chrome_args...]
"""

import os
import sys
import platform
import subprocess
import shutil
from pathlib import Path


# ─────────────────────────────────────────────
# Platform Detection
# ─────────────────────────────────────────────

def detect_platform() -> str:
    """Detect current platform and return canonical name"""
    
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "macos"
    elif system == "linux":
        return "linux"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def get_binary_name(platform_name: str) -> str:
    """Get the binary name for the platform"""
    
    if platform_name == "windows":
        return "jbium.exe"
    else:
        return "jbium"


def find_browser_binary() -> Path:
    """Find the stealth browser binary for current platform"""
    
    platform_name = detect_platform()
    binary_name = get_binary_name(platform_name)
    
    # Search paths (in order of priority)
    script_dir = Path(__file__).parent
    
    search_paths = [
        # Same directory as launcher
        script_dir / "chrome" / binary_name,
        script_dir / binary_name,
        
        # Platform subdirectory
        script_dir / "chrome" / platform_name / binary_name,
        script_dir / platform_name / binary_name,
        
        # Standard install locations
        Path.home() / ".jbium" / "chrome" / binary_name,
        Path("/opt/jbium/chrome") / binary_name,  # Linux
        Path("C:/Program Files/Jbium/chrome") / binary_name,  # Windows
        Path("/Applications/Jbium.app/Contents/MacOS/jbium"),  # macOS
        
        # Environment variable override
        Path(os.environ.get("STEALTH_BROWSER_PATH", "")) if os.environ.get("STEALTH_BROWSER_PATH") else None,
    ]
    
    for path in search_paths:
        if path and path.exists():
            return path
    
    raise FileNotFoundError(
        f"Stealth browser binary not found for {platform_name}.\n"
        f"Searched:\n" + "\n".join(f"  {p}" for p in search_paths if p)
    )


# ─────────────────────────────────────────────
# Font Configuration
# ─────────────────────────────────────────────

def setup_fonts(platform_name: str) -> dict:
    """
    Set up font environment for the platform.
    Returns environment variables to set.
    """
    
    env_vars = {}
    script_dir = Path(__file__).parent
    font_dir = script_dir / "fonts" / platform_name
    
    if not font_dir.exists():
        font_dir = script_dir / "fonts"
    
    if font_dir.exists() and any(font_dir.iterdir()):
        if platform_name == "linux":
            # Linux uses fontconfig
            cache_dir = Path.home() / ".cache" / "stealth-fonts"
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            # Create fontconfig config
            font_config = f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{font_dir}</dir>
  <cachedir>{cache_dir}</cachedir>
  <match target="pattern">
    <test qual="any" name="family">
      <string>sans-serif</string>
    </test>
    <edit name="family" mode="assign" binding="same">
      <string>Noto Sans</string>
    </edit>
  </match>
</fontconfig>"""
            
            config_path = cache_dir / "fonts.conf"
            config_path.write_text(font_config)
            
            env_vars["FONTCONFIG_PATH"] = str(cache_dir)
            env_vars["FONTCONFIG_FILE"] = "fonts.conf"
            
        elif platform_name == "windows":
            # Windows uses DirectWrite — it automatically finds system fonts
            # For custom fonts, we'd need to register them
            # For now, system fonts work
            pass
            
        elif platform_name == "macos":
            # macOS uses Core Text — it finds fonts in ~/Library/Fonts
            # Copy custom fonts there or use system fonts
            pass
    
    return env_vars


# ─────────────────────────────────────────────
# Essential Arguments
# ─────────────────────────────────────────────

def get_essential_args(platform_name: str) -> list:
    """Get essential Chrome arguments for the platform"""
    
    # Common args (all platforms)
    args = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-networking",
        "--disable-client-side-phishing-detection",
        "--disable-default-apps",
        "--disable-features=site-per-process,Translate,MediaRouter",
        "--disable-hang-monitor",
        "--disable-prompt-on-repost",
        "--disable-sync",
        "--metrics-recording-only",
        "--no-pings",
        "--password-store=basic",
    ]
    
    # Platform-specific
    if platform_name == "linux":
        args.extend([
            "--use-mock-keychain",
            "--no-sandbox",  # Required in Docker/CI
        ])
        
    elif platform_name == "windows":
        args.extend([
            "--use-mock-keychain",
            "--disable-features=msEdgeOOBE",
        ])
        
    elif platform_name == "macos":
        args.extend([
            "--use-mock-keychain",
        ])
    
    return args


# ─────────────────────────────────────────────
# Main Launcher
# ─────────────────────────────────────────────

def launch(extra_args: list = None) -> int:
    """Launch the stealth browser"""
    
    # Detect platform
    platform_name = detect_platform()
    
    # Find binary
    binary_path = find_browser_binary()
    
    # Setup fonts
    font_env = setup_fonts(platform_name)
    
    # Build args
    args = [str(binary_path)]
    args.extend(get_essential_args(platform_name))
    
    if extra_args:
        args.extend(extra_args)
    
    # Prepare environment
    env = os.environ.copy()
    env.update(font_env)
    
    # Launch
    print(f"Launching Jbium ({platform_name})...")
    print(f"  Binary: {binary_path}")
    
    try:
        process = subprocess.Popen(
            args,
            env=env,
        )
        process.wait()
        return process.returncode
    except KeyboardInterrupt:
        print("\nShutting down...")
        process.terminate()
        return 0
    except Exception as e:
        print(f"Error launching browser: {e}", file=sys.stderr)
        return 1


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    sys.exit(launch(sys.argv[1:]))
