"""
Platform detection and management for cross-platform stealth browser.
"""

import os
import platform
import subprocess
from pathlib import Path
from enum import Enum
from dataclasses import dataclass


class Platform(Enum):
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"


class Architecture(Enum):
    X86_64 = "x86_64"
    ARM64 = "arm64"
    ARM32 = "arm32"


@dataclass
class PlatformInfo:
    platform: Platform
    architecture: Architecture
    platform_string: str     # "Win32", "MacIntel", "Linux x86_64"
    ua_platform: str         # "Windows", "macOS", "Linux"
    binary_name: str         # "jbium.exe", "jbium"
    lib_extension: str       # ".dll", ".so", ".dylib"
    font_system: str         # "directwrite", "fontconfig", "coretext"
    os_version: str
    
    @property
    def is_desktop(self) -> bool:
        return True
    
    @property
    def display_server(self) -> str:
        if self.platform == Platform.LINUX:
            return os.environ.get("XDG_SESSION_TYPE", "x11")
        return "native"


def detect_platform_info() -> PlatformInfo:
    """Detect current platform with all details"""
    
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    # Architecture
    if machine in ("x86_64", "amd64"):
        arch = Architecture.X86_64
    elif machine in ("arm64", "aarch64"):
        arch = Architecture.ARM64
    elif machine in ("arm", "armv7l"):
        arch = Architecture.ARM32
    else:
        arch = Architecture.X86_64  # Default
    
    if system == "windows":
        return PlatformInfo(
            platform=Platform.WINDOWS,
            architecture=arch,
            platform_string="Win32",
            ua_platform="Windows",
            binary_name="jbium.exe",
            lib_extension=".dll",
            font_system="directwrite",
            os_version=platform.version(),
        )
    
    elif system == "darwin":
        platform_str = "MacIntel" if arch == Architecture.X86_64 else "MacIntel"
        return PlatformInfo(
            platform=Platform.MACOS,
            architecture=arch,
            platform_string=platform_str,
            ua_platform="macOS",
            binary_name="jbium",
            lib_extension=".dylib",
            font_system="coretext",
            os_version=platform.mac_ver()[0],
        )
    
    elif system == "linux":
        return PlatformInfo(
            platform=Platform.LINUX,
            architecture=arch,
            platform_string="Linux x86_64" if arch == Architecture.X86_64 else "Linux arm64",
            ua_platform="Linux",
            binary_name="jbium",
            lib_extension=".so",
            font_system="fontconfig",
            os_version=platform.release(),
        )
    
    raise RuntimeError(f"Unsupported platform: {system}")


def find_browser_binary(
    custom_path: str = None,
    search_paths: list = None,
) -> Path:
    """
    Find the stealth browser binary for the current platform.
    
    Search order:
    1. Custom path (if provided)
    2. STEALTH_BROWSER_PATH env var
    3. Common install locations
    4. Current directory
    """
    
    info = detect_platform_info()
    
    if custom_path:
        path = Path(custom_path)
        if path.exists():
            return path
        raise FileNotFoundError(f"Binary not found at {custom_path}")
    
    # Environment variable
    env_path = os.environ.get("STEALTH_BROWSER_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path
    
    # Build search paths
    if search_paths is None:
        home = Path.home()
        
        search_paths = [
            # Project directory
            Path(__file__).parent.parent / "chrome" / info.binary_name,
            Path(__file__).parent.parent / info.binary_name,
            
            # Install locations
            home / ".local/share/jbium/bin" / info.binary_name,  # Linux
            home / ".local/share/jbium" / info.binary_name,
            home / "AppData/Roaming/Jbium" / info.binary_name,  # Windows
            home / "Library/Jbium/bin" / info.binary_name,  # macOS
            Path("/opt/jbium/bin/jbium"),  # Linux system
            Path("C:/Program Files/Jbium/jbium.exe"),  # Windows system
            Path("/Applications/Jbium.app/Contents/MacOS/jbium"),  # macOS
        ]
    
    for path in search_paths:
        path = Path(path)
        if path.exists():
            return path
    
    raise FileNotFoundError(
        f"Stealth browser binary ({info.binary_name}) not found.\n"
        f"Searched:\n" + "\n".join(f"  {p}" for p in search_paths)
    )


def get_platform_args(info: PlatformInfo) -> list:
    """Get platform-specific Chrome arguments"""
    
    args = []
    
    if info.platform == Platform.WINDOWS:
        args.extend([
            "--disable-features=msEdgeOOBE",
        ])
    elif info.platform == Platform.LINUX:
        args.extend([
            "--no-sandbox",  # Required in Docker/CI
            "--disable-dev-shm-usage",
        ])
    elif info.platform == Platform.MACOS:
        args.extend([
            "--disable-dev-shm-usage",
        ])
    
    return args


def setup_platform_fonts(info: PlatformInfo, font_dir: Path = None) -> dict:
    """
    Set up fonts for the platform.
    Returns environment variables needed.
    """
    
    env_vars = {}
    
    if info.platform == Platform.LINUX:
        # Use fontconfig
        if font_dir and font_dir.exists():
            cache_dir = Path.home() / ".cache" / "stealth-fonts"
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            font_config = f"""<?xml version="1.0"?>
<fontconfig>
  <dir>{font_dir}</dir>
  <cachedir>{cache_dir}</cachedir>
</fontconfig>"""
            
            (cache_dir / "fonts.conf").write_text(font_config)
            env_vars["FONTCONFIG_PATH"] = str(cache_dir)
            env_vars["FONTCONFIG_FILE"] = "fonts.conf"
    
    elif info.platform == Platform.WINDOWS:
        # DirectWrite uses system fonts automatically
        # For custom fonts, we'd need to register them
        pass
    
    elif info.platform == Platform.MACOS:
        # Core Text uses system fonts + ~/Library/Fonts
        # Could copy custom fonts there
        pass
    
    return env_vars
