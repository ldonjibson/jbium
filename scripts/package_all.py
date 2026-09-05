#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════
Cross-Platform Package Builder
════════════════════════════════════════════════════════════

Creates platform-specific packages and a universal installer.
Each platform gets its own optimized binary, but the driver,
config, and launcher are shared.

Output structure:
  dist/
  ├── jbium-1.0.0-linux-x64.tar.gz
  ├── jbium-1.0.0-linux-arm64.tar.gz
  ├── jbium-1.0.0-windows-x64.zip
  ├── jbium-1.0.0-macos-x64.tar.gz
  ├── jbium-1.0.0-macos-arm64.tar.gz
  └── universal-installer.py  ← Single file installs on any OS
"""

import os
import sys
import json
import hashlib
import tarfile
import zipfile
import platform
import subprocess
import shutil
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


# ─────────────────────────────────────────────
# Platform definitions
# ─────────────────────────────────────────────

PLATFORMS = {
    "linux-x64": {
        "os": "linux",
        "arch": "x64",
        "binary_name": "jbium",
        "lib_ext": ".so",
        "archive_ext": "tar.gz",
        "build_dir": "out/Release-Linux-x64",
    },
    "linux-arm64": {
        "os": "linux",
        "arch": "arm64",
        "binary_name": "jbium",
        "lib_ext": ".so",
        "archive_ext": "tar.gz",
        "build_dir": "out/Release-Linux-arm64",
    },
    "windows-x64": {
        "os": "windows",
        "arch": "x64",
        "binary_name": "jbium.exe",
        "lib_ext": ".dll",
        "archive_ext": "zip",
        "build_dir": "out/Release-Win-x64",
    },
    "macos-x64": {
        "os": "macos",
        "arch": "x64",
        "binary_name": "jbium",
        "lib_ext": ".dylib",
        "archive_ext": "tar.gz",
        "build_dir": "out/Release-Mac-x64",
    },
    "macos-arm64": {
        "os": "macos",
        "arch": "arm64",
        "binary_name": "jbium",
        "lib_ext": ".dylib",
        "archive_ext": "tar.gz",
        "build_dir": "out/Release-Mac-arm64",
    },
}


class PackageBuilder:
    def __init__(self, project_root: Path, output_dir: Path):
        self.root = project_root
        self.output = output_dir
        self.output.mkdir(parents=True, exist_ok=True)
    
    def find_build(self, platform_name: str) -> Optional[Path]:
        """Find the build directory for a platform"""
        
        info = PLATFORMS[platform_name]
        build_dir = self.root / "builds" / platform_name
        
        if build_dir.exists():
            binary = build_dir / info["binary_name"]
            if binary.exists():
                return build_dir
        
        # Also check standard Chromium location
        chrome_src = Path(os.environ.get(
            "CHROMIUM_SRC", 
            str(Path.home() / "jbium" / "chromium" / "src")
        ))
        
        alt_dirs = [
            chrome_src / info["build_dir"],
            chrome_src / "out" / f"Release-{platform_name}",
            chrome_src / "out" / "Release",
        ]
        
        for d in alt_dirs:
            if (d / info["binary_name"]).exists():
                return d
        
        return None
    
    def package_platform(self, platform_name: str) -> Optional[Path]:
        """Package a single platform"""
        
        info = PLATFORMS[platform_name]
        build_dir = self.find_build(platform_name)
        
        if not build_dir:
            print(f"  ⚠️  No build found for {platform_name}, skipping")
            return None
        
        print(f"\n{'═' * 60}")
        print(f"  Packaging: {platform_name}")
        print(f"  Build dir: {build_dir}")
        print(f"{'═' * 60}")
        
        # Create staging directory
        staging = Path(f"/tmp/stealth-pkg-{platform_name}")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        
        # Copy binary
        binary_src = build_dir / info["binary_name"]
        binary_dst = staging / info["binary_name"]
        shutil.copy2(binary_src, binary_dst)
        
        if info["os"] != "windows":
            os.chmod(binary_dst, 0o755)
        
        # Copy resources
        resources = [
            "resources.pak", "natives_blob.bin", "snapshot_blob.bin",
            "v8_context_snapshot.bin", "icudtl.dat"
        ]
        for res in resources:
            res_path = build_dir / res
            if res_path.exists():
                shutil.copy2(res_path, staging / res)
        
        # Copy libraries
        for lib in build_dir.glob(f"*{info['lib_ext']}"):
            shutil.copy2(lib, staging / lib.name)
        
        # Copy locales
        locales_src = build_dir / "locales"
        if locales_src.exists():
            shutil.copytree(locales_src, staging / "locales")
        
        # Copy fonts for this platform
        fonts_src = self.root / "fonts" / info["os"]
        if fonts_src.exists():
            shutil.copytree(fonts_src, staging / "fonts")
        
        # Copy driver (same for all platforms)
        driver_src = self.root / "driver"
        if driver_src.exists():
            shutil.copytree(driver_src, staging / "driver")
        
        # Copy config (same for all platforms)
        config_src = self.root / "config"
        if config_src.exists():
            # Only copy JSON/YAML, not .gn files
            staging_config = staging / "config"
            staging_config.mkdir(exist_ok=True)
            for f in config_src.glob("*.json"):
                shutil.copy2(f, staging_config)
            for f in config_src.glob("*.yaml"):
                shutil.copy2(f, staging_config)
        
        # Copy launcher
        launcher_src = self.root / "launcher"
        if launcher_src.exists():
            shutil.copy2(
                launcher_src / "stealth_browser.py", 
                staging / "stealth_browser.py"
            )
            if info["os"] != "windows":
                shutil.copy2(
                    launcher_src / "jbium",
                    staging / "jbium"
                )
                os.chmod(staging / "jbium", 0o755)
            else:
                shutil.copy2(
                    launcher_src / "jbium.bat",
                    staging / "jbium.bat"
                )
        
        # Copy installer
        shutil.copy2(
            self.root / "launcher" / "install.py",
            staging / "install.py"
        )
        
        # Create manifest
        manifest = {
            "platform": platform_name,
            "os": info["os"],
            "arch": info["arch"],
            "binary": info["binary_name"],
            "created": datetime.now().isoformat(),
            "files": [str(f.relative_to(staging)) for f in staging.rglob("*") if f.is_file()],
        }
        
        # Get binary hash
        sha = hashlib.sha256(binary_dst.read_bytes()).hexdigest()
        manifest["sha256"] = sha
        
        # Binary size
        manifest["size_bytes"] = binary_dst.stat().st_size
        manifest["size_human"] = self._human_size(binary_dst.stat().st_size)
        
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2)
        )
        
        # Create archive
        version = os.environ.get("STEALTH_VERSION", "1.0.0")
        archive_name = f"jbium-{version}-{platform_name}.{info['archive_ext']}"
        archive_path = self.output / archive_name
        
        print(f"  Creating {archive_name}...")
        
        if info["archive_ext"] == "tar.gz":
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(staging, arcname="jbium")
        else:  # zip
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in staging.rglob("*"):
                    if f.is_file():
                        zf.write(f, f"jbium/{f.relative_to(staging)}")
        
        archive_size = self._human_size(archive_path.stat().st_size)
        print(f"  ✅ {archive_name} ({archive_size})")
        
        # Cleanup
        shutil.rmtree(staging)
        
        return archive_path
    
    def _human_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
    
    def create_universal_installer(self, packages: List[Path]):
        """Create a single installer that downloads the right platform package"""
        
        print(f"\n{'═' * 60}")
        print(f"  Creating Universal Installer")
        print(f"{'═' * 60}")
        
        # Collect checksums
        checksums = {}
        for pkg in packages:
            sha = hashlib.sha256(pkg.read_bytes()).hexdigest()
            checksums[pkg.name] = sha
        
        # Create installer
        installer_content = f'''#!/usr/bin/env python3
"""
Jbium — Universal Installer
Automatically detects platform and installs the correct build.
"""

import os
import sys
import platform
import hashlib
import tarfile
import zipfile
import urllib.request
from pathlib import Path

VERSION = "{os.environ.get("STEALTH_VERSION", "1.0.0")}"
DOWNLOAD_BASE = os.environ.get(
    "STEALTH_DOWNLOAD_URL", 
    "https://github.com/yourusername/jbium/releases/download/v{{VERSION}}"
).format(VERSION=VERSION)

CHECKSUMS = {json.dumps(checksums, indent=4)}

PLATFORM_MAP = {{
    ("windows", "x64"): "windows-x64",
    ("linux", "x64"): "linux-x64",
    ("linux", "arm64"): "linux-arm64",
    ("macos", "x64"): "macos-x64",
    ("macos", "arm64"): "macos-arm64",
}}

def detect():
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    if system == "windows":
        os_name = "windows"
    elif system == "darwin":
        os_name = "macos"
    elif system == "linux":
        os_name = "linux"
    
    if machine in ("x86_64", "amd64"):
        arch = "x64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = "x64"
    
    return os_name, arch

def download(url, dest):
    print(f"  Downloading: {{url}}")
    urllib.request.urlretrieve(url, dest)
    
def verify(path, expected_sha):
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return sha == expected_sha

def extract(archive, dest):
    if archive.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(dest)
    else:
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(dest)

def main():
    os_name, arch = detect()
    platform_key = (os_name, arch)
    
    if platform_key not in PLATFORM_MAP:
        print(f"Unsupported: {{os_name}}/{{arch}}")
        sys.exit(1)
    
    platform_name = PLATFORM_MAP[platform_key]
    archive_name = f"jbium-{{VERSION}}-{{platform_name}}"
    
    if platform_name.startswith("windows"):
        archive_name += ".zip"
    else:
        archive_name += ".tar.gz"
    
    url = f"{{DOWNLOAD_BASE}}/{{archive_name}}"
    
    print(f"Jbium v{{VERSION}}")
    print(f"Platform: {{os_name}}-{{arch}}")
    print(f"Package: {{archive_name}}")
    print()
    
    # Download
    download_path = Path.home() / ".cache" / "jbium" / archive_name
    download_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not download_path.exists():
        download(url, download_path)
    
    # Verify
    expected = CHECKSUMS.get(archive_name)
    if expected:
        print("  Verifying...", end=" ")
        if verify(download_path, expected):
            print("✅")
        else:
            print("❌ (checksum mismatch)")
            sys.exit(1)
    
    # Install
    install_dir = Path.home() / ".local" / "share" / "jbium"
    if os_name == "windows":
        install_dir = Path(os.environ.get("APPDATA", "")) / "Jbium"
    
    print(f"  Installing to {{install_dir}}...")
    extract(download_path, install_dir.parent)
    
    print(f"\\n✅ Installed!")
    print(f"Run with: python {{install_dir}}/stealth_browser.py")

if __name__ == "__main__":
    main()
'''
        
        installer_path = self.output / "universal_installer.py"
        installer_path.write_text(installer_content)
        os.chmod(installer_path, 0o755)
        
        print(f"  ✅ universal_installer.py created")
    
    def package_all(self, platforms: List[str] = None):
        """Package all available platforms"""
        
        if platforms is None:
            platforms = list(PLATFORMS.keys())
        
        print(f"\n{'═' * 60}")
        print(f"  Jbium — Cross-Platform Packaging")
        print(f"  Version: {os.environ.get('STEALTH_VERSION', '1.0.0')}")
        print(f"{'═' * 60}\n")
        
        built = []
        
        for platform_name in platforms:
            result = self.package_platform(platform_name)
            if result:
                built.append(result)
        
        if built:
            self.create_universal_installer(built)
            
            print(f"\n{'═' * 60}")
            print(f"  ✅ Packaging Complete!")
            print(f"{'═' * 60}")
            print(f"\n  Packages created:")
            for pkg in built:
                print(f"    {pkg.name} ({self._human_size(pkg.stat().st_size)})")
            print(f"    universal_installer.py")
            print(f"\n  Location: {self.output}/")
        else:
            print(f"\n  ❌ No builds found to package!")
            print(f"  Run the build scripts first:")
            print(f"    scripts/build_linux.sh")
            print(f"    scripts/build_windows.bat")
            print(f"    scripts/build_macos.sh")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package Jbium")
    parser.add_argument(
        "--platforms", nargs="+",
        help="Platforms to package (default: all available)"
    )
    parser.add_argument(
        "--output", type=str, default="dist",
        help="Output directory"
    )
    parser.add_argument(
        "--version", type=str, default="1.0.0",
        help="Version string"
    )
    
    args = parser.parse_args()
    
    # Set version
    os.environ["STEALTH_VERSION"] = args.version
    
    # Determine project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # Output directory
    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir
    
    # Build
    builder = PackageBuilder(project_root, output_dir)
    builder.package_all(args.platforms)
