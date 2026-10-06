#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════
Font Bundle Downloader
════════════════════════════════════════════════════════════

Downloads all required fonts for each platform bundle.
Fonts are free/open-source (SIL OFL 1.1 license).

Usage:
    python download_fonts.py                 # Download all platforms
    python download_fonts.py --platform windows
    python download_fonts.py --platform macos
    python download_fonts.py --platform linux
    python download_fonts.py --verify       # Check what's already downloaded
"""

import os
import sys
import hashlib
import argparse
import tarfile
import zipfile
import shutil
import json
from pathlib import Path
from typing import Dict, List, Optional
import urllib.request
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("font_downloader")


# ═════════════════════════════════════════════
# Download URLs
# ═════════════════════════════════════════════

# The URL table lives in packaging/src/jbium/font_urls.py — the single
# source of truth, imported here and by the pip package's own
# `jbium fetch-fonts` command, so a URL fix lands everywhere from one
# edit. Every URL there was verified live (HTTP 200 + sfnt magic
# bytes) before being written — this script's original inline URLs
# were mostly 404 (never worked at all, the same disease as the
# download_geoip.sh bug documented in CLAUDE.md), which is why the
# font bundles shipped manifest-only and the runtime font defense
# was dead on every box that ever ran it.

sys.path.insert(0, str(Path(__file__).parent.parent / "packaging" / "src"))
from jbium.font_urls import URLS, PLATFORM_FONTS  # noqa: E402


class FontDownloader:
    def __init__(self, fonts_root: Path):
        self.fonts_root = fonts_root
        self.temp_dir = fonts_root / ".downloads"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    def download_file(self, url: str, dest: Path) -> bool:
        """Download a single file"""
        
        try:
            logger.info(f"    Downloading: {url.split('/')[-1]}")
            urllib.request.urlretrieve(
                url, 
                dest,
                reporthook=self._progress
            )
            return True
        except Exception as e:
            logger.error(f"    ❌ Failed: {e}")
            return False
    
    def _progress(self, count, block_size, total_size):
        """Progress callback"""
        if total_size > 0:
            percent = min(int(count * block_size * 100 / total_size), 100)
            sys.stdout.write(f"\r    Progress: {percent}%")
            sys.stdout.flush()
    
    def download_group(self, group_name: str, dest_dir: Path) -> List[Path]:
        """Download a font group to a directory"""
        
        if group_name not in URLS:
            logger.warning(f"  ⚠️  Unknown font group: {group_name}")
            return []
        
        group = URLS[group_name]
        downloaded = []
        
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        if group["type"] == "direct":
            # Direct file downloads
            base_url = group["base_url"]
            
            for filename, path in group["files"].items():
                dest = dest_dir / filename
                
                # Skip if already exists
                if dest.exists():
                    logger.info(f"    ⏭️  Already exists: {filename}")
                    downloaded.append(dest)
                    continue
                
                url = f"{base_url}/{path}"
                print()  # New line before progress
                if self.download_file(url, dest):
                    downloaded.append(dest)
                    print(f"\n    ✅ {filename}")
                print()
        
        elif group["type"] in ("tar.gz", "zip", "tar.bz2"):
            # Archive download and extract
            url = group["url"]
            archive_name = url.split("/")[-1]
            archive_path = self.temp_dir / archive_name
            
            # Skip if all files already exist
            all_exist = all(
                (dest_dir / pattern).exists() 
                for pattern in group["extract_patterns"].values()
            )
            if all_exist:
                logger.info(f"    ⏭️  All files exist for {group_name}")
                return []
            
            # Download archive
            print()
            if not self.download_file(url, archive_path):
                return []
            print()
            
            # Extract specific files
            logger.info(f"    Extracting...")
            
            try:
                if group["type"] == "tar.gz":
                    with tarfile.open(archive_path, "r:gz") as tar:
                        for wanted_name, extract_as in group["extract_patterns"].items():
                            for member in tar.getmembers():
                                if member.name.endswith(wanted_name) or wanted_name in member.name:
                                    f = tar.extractfile(member)
                                    dest = dest_dir / extract_as
                                    with open(dest, "wb") as out:
                                        out.write(f.read())
                                    downloaded.append(dest)
                                    logger.info(f"    ✅ {extract_as}")
                                    break
                
                elif group["type"] == "tar.bz2":
                    with tarfile.open(archive_path, "r:bz2") as tar:
                        for wanted_name, extract_as in group["extract_patterns"].items():
                            for member in tar.getmembers():
                                if wanted_name in member.name:
                                    f = tar.extractfile(member)
                                    dest = dest_dir / extract_as
                                    with open(dest, "wb") as out:
                                        out.write(f.read())
                                    downloaded.append(dest)
                                    logger.info(f"    ✅ {extract_as}")
                                    break
                
                elif group["type"] == "zip":
                    with zipfile.ZipFile(archive_path, "r") as zf:
                        for wanted_name, extract_as in group["extract_patterns"].items():
                            for member in zf.namelist():
                                if wanted_name in member:
                                    data = zf.read(member)
                                    dest = dest_dir / extract_as
                                    dest.write_bytes(data)
                                    downloaded.append(dest)
                                    logger.info(f"    ✅ {extract_as}")
                                    break
                                    
            except Exception as e:
                logger.error(f"    ❌ Extraction failed: {e}")
            finally:
                # Clean up archive
                archive_path.unlink(missing_ok=True)
        
        return downloaded
    
    def download_platform(self, platform: str) -> Dict[str, int]:
        """Download all fonts for a platform"""
        
        platform_dir = self.fonts_root / platform
        
        if platform not in PLATFORM_FONTS:
            logger.error(f"Unknown platform: {platform}")
            return {}
        
        groups = PLATFORM_FONTS[platform]
        
        logger.info(f"Downloading fonts for {platform}...")
        logger.info(f"  Target: {platform_dir}")
        logger.info(f"  Groups: {len(groups)}")
        logger.info("")
        
        total_downloaded = 0
        total_skipped = 0
        total_failed = 0
        
        for group_name in groups:
            logger.info(f"  [{groups.index(group_name)+1}/{len(groups)}] {group_name}")
            
            files = self.download_group(group_name, platform_dir)
            
            if files:
                total_downloaded += len(files)
            else:
                # Check if already exists
                if group_name in URLS:
                    if "files" in URLS[group_name]:
                        expected = URLS[group_name]["files"].keys()
                    elif "extract_patterns" in URLS[group_name]:
                        expected = URLS[group_name]["extract_patterns"].values()
                    else:
                        expected = []
                    
                    existing = sum(
                        1 for f in expected 
                        if (platform_dir / f).exists()
                    )
                    if existing > 0:
                        total_skipped += existing
                    else:
                        total_failed += 1
        
        logger.info("")
        logger.info(f"  Summary:")
        logger.info(f"    Downloaded: {total_downloaded}")
        logger.info(f"    Already had: {total_skipped}")
        logger.info(f"    Failed: {total_failed}")
        
        return {
            "downloaded": total_downloaded,
            "skipped": total_skipped,
            "failed": total_failed,
        }
    
    def verify(self) -> Dict[str, Dict]:
        """Verify what fonts exist in each platform directory"""
        
        results = {}
        
        for platform in ["windows", "macos", "linux"]:
            platform_dir = self.fonts_root / platform
            
            if not platform_dir.exists():
                results[platform] = {
                    "exists": False,
                    "font_count": 0,
                    "size_mb": 0,
                    "missing": list(PLATFORM_FONTS.get(platform, []))
                }
                continue
            
            fonts = list(platform_dir.glob("*.ttf")) + list(platform_dir.glob("*.otf"))
            total_size = sum(f.stat().st_size for f in fonts)
            
            # Check which groups are complete
            present_groups = []
            missing_groups = []
            
            for group_name in PLATFORM_FONTS.get(platform, []):
                if group_name in URLS:
                    if "files" in URLS[group_name]:
                        expected = URLS[group_name]["files"].keys()
                    elif "extract_patterns" in URLS[group_name]:
                        expected = URLS[group_name]["extract_patterns"].values()
                    else:
                        expected = []
                    
                    existing = sum(
                        1 for f in expected
                        if (platform_dir / f).exists()
                    )
                    total_expected = len(expected)
                    
                    if existing == total_expected and total_expected > 0:
                        present_groups.append(group_name)
                    elif existing > 0:
                        present_groups.append(f"{group_name} (partial: {existing}/{total_expected})")
                    else:
                        missing_groups.append(group_name)
            
            results[platform] = {
                "exists": True,
                "font_count": len(fonts),
                "size_mb": round(total_size / 1024 / 1024, 1),
                "present_groups": present_groups,
                "missing_groups": missing_groups,
                "fonts": [f.name for f in sorted(fonts)],
            }
        
        return results
    
    def cleanup(self):
        """Remove temporary files"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


# ═════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Download font bundles for stealth browser"
    )
    parser.add_argument(
        "--platform", type=str, choices=["windows", "macos", "linux"],
        help="Download for specific platform only"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Download for all platforms"
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Check what's already downloaded"
    )
    parser.add_argument(
        "--fonts-dir", type=str, default=None,
        help="Custom fonts root directory"
    )
    
    args = parser.parse_args()
    
    # Determine fonts root
    script_dir = Path(__file__).parent
    fonts_root = Path(args.fonts_dir) if args.fonts_dir else script_dir
    
    downloader = FontDownloader(fonts_root)
    
    if args.verify:
        # Verify mode
        results = downloader.verify()
        
        print("\n" + "═" * 60)
        print("  Font Bundle Status")
        print("═" * 60)
        
        for platform, info in results.items():
            print(f"\n  {platform.upper()}:")
            if not info["exists"]:
                print(f"    ❌ Directory not found")
            else:
                status = "✅" if not info["missing_groups"] else "⚠️"
                print(f"    {status} {info['font_count']} fonts ({info['size_mb']} MB)")
                
                if info.get("present_groups"):
                    print(f"    Present: {', '.join(info['present_groups'])}")
                if info.get("missing_groups"):
                    print(f"    Missing: {', '.join(info['missing_groups'])}")
        
        print("\n" + "═" * 60)
        return
    
    # Download mode
    platforms = []
    if args.platform:
        platforms = [args.platform]
    elif args.all:
        platforms = ["windows", "macos", "linux"]
    else:
        # Download all by default
        platforms = ["windows", "macos", "linux"]
    
    print("═" * 60)
    print("  Jbium Font Downloader")
    print("═" * 60)
    print()
    
    for platform in platforms:
        downloader.download_platform(platform)
    
    downloader.cleanup()
    
    print("\n" + "═" * 60)
    print("  ✅ Complete!")
    print("═" * 60)


if __name__ == "__main__":
    main()
