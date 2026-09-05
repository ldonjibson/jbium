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

URLS = {
    # ── Liberation Fonts (Arial/Times/Courier compatible) ──
    "liberation": {
        "url": "https://github.com/liberationfonts/liberation-fonts/releases/download/2.1.5/liberation-fonts-ttf-2.1.5.tar.gz",
        "type": "tar.gz",
        "extract_patterns": {
            "LiberationSans-Regular.ttf": "LiberationSans-Regular.ttf",
            "LiberationSans-Bold.ttf": "LiberationSans-Bold.ttf",
            "LiberationSans-Italic.ttf": "LiberationSans-Italic.ttf",
            "LiberationSans-BoldItalic.ttf": "LiberationSans-BoldItalic.ttf",
            "LiberationSerif-Regular.ttf": "LiberationSerif-Regular.ttf",
            "LiberationSerif-Bold.ttf": "LiberationSerif-Bold.ttf",
            "LiberationMono-Regular.ttf": "LiberationMono-Regular.ttf",
            "LiberationMono-Bold.ttf": "LiberationMono-Bold.ttf",
        }
    },
    
    # ── Carlito (Calibri-compatible) ──
    "carlito": {
        "url": "https://github.com/googlefonts/carlito/releases/download/1.103/Carlito.zip",
        "type": "zip",
        "extract_patterns": {
            "Carlito-Regular.ttf": "Carlito-Regular.ttf",
            "Carlito-Bold.ttf": "Carlito-Bold.ttf",
            "Carlito-Italic.ttf": "Carlito-Italic.ttf",
            "Carlito-BoldItalic.ttf": "Carlito-BoldItalic.ttf",
        }
    },
    
    # ── Caladea (Cambria-compatible) ──
    "caladea": {
        "url": "https://github.com/huertatipografica/Caladea/releases/download/v1.0.2/caladea.zip",
        "type": "zip",
        "extract_patterns": {
            "Caladea-Regular.ttf": "Caladea-Regular.ttf",
            "Caladea-Bold.ttf": "Caladea-Bold.ttf",
        }
    },
    
    # ── Noto Sans (base) ──
    "noto_sans": {
        "base_url": "https://github.com/notofonts/noto-fonts/raw/main",
        "type": "direct",
        "files": {
            "NotoSans-Regular.ttf": "noto-core/NotoSans/NotoSans-Regular.ttf",
            "NotoSans-Bold.ttf": "noto-core/NotoSans/NotoSans-Bold.ttf",
            "NotoSans-Italic.ttf": "noto-core/NotoSans/NotoSans-Italic.ttf",
            "NotoSans-Medium.ttf": "noto-core/NotoSans/NotoSans-Medium.ttf",
            "NotoSans-Light.ttf": "noto-core/NotoSans/NotoSans-Light.ttf",
        }
    },
    
    # ── Noto Serif ──
    "noto_serif": {
        "base_url": "https://github.com/notofonts/noto-fonts/raw/main",
        "type": "direct",
        "files": {
            "NotoSerif-Regular.ttf": "noto-core/NotoSerif/NotoSerif-Regular.ttf",
            "NotoSerif-Bold.ttf": "noto-core/NotoSerif/NotoSerif-Bold.ttf",
        }
    },
    
    # ── Noto Mono ──
    "noto_mono": {
        "base_url": "https://github.com/notofonts/noto-fonts/raw/main",
        "type": "direct",
        "files": {
            "NotoMono-Regular.ttf": "noto-core/NotoMono/NotoMono-Regular.ttf",
        }
    },
    
    # ── Noto Sans JP (Japanese) ──
    "noto_sans_jp": {
        "base_url": "https://github.com/notofonts/noto-cjk/raw/main/Sans",
        "type": "direct",
        "files": {
            "NotoSansJP-Regular.ttf": "OTF/Japanese/NotoSansCJKjp-Regular.otf",
            "NotoSansJP-Bold.ttf": "OTF/Japanese/NotoSansCJKjp-Bold.otf",
        },
        "note": "Actual Noto Sans JP from Google Fonts is preferred"
    },
    
    # ── Noto Sans KR (Korean) ──
    "noto_sans_kr": {
        "base_url": "https://github.com/notofonts/noto-cjk/raw/main/Sans",
        "type": "direct",
        "files": {
            "NotoSansKR-Regular.ttf": "OTF/Korean/NotoSansCJKkr-Regular.otf",
            "NotoSansKR-Bold.ttf": "OTF/Korean/NotoSansCJKkr-Bold.otf",
        }
    },
    
    # ── Noto Sans SC (Simplified Chinese) ──
    "noto_sans_sc": {
        "base_url": "https://github.com/notofonts/noto-cjk/raw/main/Sans",
        "type": "direct",
        "files": {
            "NotoSansSC-Regular.ttf": "OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf",
            "NotoSansSC-Bold.ttf": "OTF/SimplifiedChinese/NotoSansCJKsc-Bold.otf",
        }
    },
    
    # ── Noto Sans TC (Traditional Chinese) ──
    "noto_sans_tc": {
        "base_url": "https://github.com/notofonts/noto-cjk/raw/main/Sans",
        "type": "direct",
        "files": {
            "NotoSansTC-Regular.ttf": "OTF/TraditionalChinese/NotoSansCJKtc-Regular.otf",
        }
    },
    
    # ── Noto Sans Arabic ──
    "noto_sans_arabic": {
        "base_url": "https://github.com/notofonts/noto-fonts/raw/main",
        "type": "direct",
        "files": {
            "NotoSansArabic-Regular.ttf": "noto-arabic/NotoSansArabic/NotoSansArabic-Regular.ttf",
        }
    },
    
    # ── DejaVu (classic Linux) ──
    "dejavu": {
        "url": "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.tar.bz2",
        "type": "tar.bz2",
        "extract_patterns": {
            "DejaVuSans.ttf": "dejavu-fonts-ttf-2.37/ttf/DejaVuSans.ttf",
            "DejaVuSans-Bold.ttf": "dejavu-fonts-ttf-2.37/ttf/DejaVuSans-Bold.ttf",
            "DejaVuSansMono.ttf": "dejavu-fonts-ttf-2.37/ttf/DejaVuSansMono.ttf",
            "DejaVuSansMono-Bold.ttf": "dejavu-fonts-ttf-2.37/ttf/DejaVuSansMono-Bold.ttf",
            "DejaVuSerif.ttf": "dejavu-fonts-ttf-2.37/ttf/DejaVuSerif.ttf",
            "DejaVuSerif-Bold.ttf": "dejavu-fonts-ttf-2.37/ttf/DejaVuSerif-Bold.ttf",
        }
    },
    
    # ── Ubuntu Font ──
    "ubuntu_font": {
        "url": "https://assets.ubuntu.com/v1/f35b1f89-ubuntu-font-family-0.83.zip",
        "type": "zip",
        "extract_patterns": {
            "Ubuntu-Regular.ttf": "ubuntu-font-family-0.83/Ubuntu-R.ttf",
            "Ubuntu-Bold.ttf": "ubuntu-font-family-0.83/Ubuntu-B.ttf",
            "UbuntuMono-Regular.ttf": "ubuntu-font-family-0.83/UbuntuMono-R.ttf",
        }
    },
    
    # ── Gelasio (Georgia-compatible) ──
    "gelasio": {
        "base_url": "https://github.com/EbenSorkin/Gelasio/raw/master/fonts/ttf",
        "type": "direct",
        "files": {
            "Gelasio-Regular.ttf": "Gelasio-Regular.ttf",
            "Gelasio-Bold.ttf": "Gelasio-Bold.ttf",
        }
    },
    
    # ── EB Garamond ──
    "eb_garamond": {
        "url": "https://github.com/octaviopardo/EBGaramond12/archive/refs/heads/master.zip",
        "type": "zip",
        "extract_patterns": {
            "EBGaramond-Regular.ttf": "EBGaramond12-master/fonts/ttf/EBGaramond12-Regular.ttf",
        }
    },
}


# ═════════════════════════════════════════════
# Platform Requirements
# ═════════════════════════════════════════════

PLATFORM_FONTS = {
    "windows": [
        "liberation",
        "carlito",
        "caladea",
        "noto_sans",
        "noto_serif",
        "noto_mono",
        "noto_sans_jp",
        "noto_sans_kr",
        "noto_sans_sc",
        "noto_sans_tc",
        "noto_sans_arabic",
        "dejavu",
        "gelasio",
    ],
    "macos": [
        "noto_sans",
        "noto_serif",
        "noto_mono",
        "liberation",
        "dejavu",
        "noto_sans_jp",
        "noto_sans_kr",
        "noto_sans_sc",
        "noto_sans_tc",
        "eb_garamond",
        "gelasio",
    ],
    "linux": [
        "noto_sans",
        "noto_serif",
        "noto_mono",
        "dejavu",
        "liberation",
        "ubuntu_font",
        "noto_sans_jp",
        "noto_sans_kr",
        "noto_sans_sc",
        "noto_sans_arabic",
    ],
}


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
