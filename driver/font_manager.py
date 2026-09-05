"""
════════════════════════════════════════════════════════════
Font Manager
════════════════════════════════════════════════════════════

Resolves the font profile a launch should use (STEALTH_FONT_OS /
STEALTH_FONT_REGION, consumed by Patch 006 — see
patches/006_fonts/apply.sh) from a device's spoofed OS and the
session's geo profile, and verifies that the font files declared
in fonts/<platform>/manifest.json are actually present on disk
before the browser starts.

On Linux it also writes the fontconfig pointing at the bundled
font directory, mirroring the inline logic in
launcher/stealth_browser.py and
driver/platform_detect.py.setup_platform_fonts().
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Device OS (DeviceProfile.os / PlatformInfo.ua_platform) -> STEALTH_FONT_OS.
# Keys are matched as substrings, so "Windows 11" and "Windows" both hit.
OS_FONT_MAP = {
    "Windows": "WINDOWS_11",
    "macOS": "MACOS_SONOMA",
    "Linux": "UBUNTU",
}

# Country code -> STEALTH_FONT_REGION. Anything not listed falls back to
# the generic Western font set.
REGION_FONT_MAP = {
    "JP": "JAPAN",
    "KR": "KOREA",
    "CN": "CHINA",
    "TW": "CHINA",
    "HK": "CHINA",
    "SG": "CHINA",
    "SA": "ARABIC",
    "AE": "ARABIC",
    "EG": "ARABIC",
    "QA": "ARABIC",
    "RU": "CYRILLIC",
    "UA": "CYRILLIC",
    "BY": "CYRILLIC",
    "IN": "INDIC",
    "PK": "INDIC",
    "TH": "INDIC",
}

DEFAULT_FONT_OS = "WINDOWS_11"
DEFAULT_FONT_REGION = "GENERIC"

# STEALTH_FONT_OS -> the fonts/<dir>/manifest.json this OS bundle lives in.
PLATFORM_DIRS = {
    "WINDOWS_11": "windows",
    "WINDOWS_10": "windows",
    "MACOS_SONOMA": "macos",
    "MACOS_VENTURA": "macos",
    "UBUNTU": "linux",
    "DEBIAN": "linux",
}


@dataclass
class FontProfile:
    """Resolved font configuration for a single launch."""

    font_os: str
    font_region: str
    platform_dir: str
    font_files: List[str] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.missing_files

    def to_env(self) -> Dict[str, str]:
        return {
            "STEALTH_FONT_OS": self.font_os,
            "STEALTH_FONT_REGION": self.font_region,
        }


class FontManager:
    """
    Loads the bundled font manifests (fonts/<platform>/manifest.json)
    and resolves the STEALTH_FONT_OS / STEALTH_FONT_REGION pair a
    session should launch with, so it always lines up with a font
    bundle that's actually on disk — a mismatch here is a fingerprint
    inconsistency (Patch 006 reports fonts for an OS the bundle can't
    back up).
    """

    def __init__(self, fonts_root: Optional[str] = None):
        self.fonts_root = (
            Path(fonts_root) if fonts_root
            else Path(__file__).parent.parent / "fonts"
        )
        self._manifests: Dict[str, dict] = {}
        self._load_manifests()

    def _load_manifests(self):
        for platform_dir in ("windows", "macos", "linux"):
            manifest_path = self.fonts_root / platform_dir / "manifest.json"

            if manifest_path.exists():
                with open(manifest_path) as f:
                    self._manifests[platform_dir] = json.load(f)
                logger.info(f"Loaded font manifest: {platform_dir}")
            else:
                self._manifests[platform_dir] = {}
                logger.warning(f"Font manifest missing: {manifest_path}")

    def get_manifest(self, platform_dir: str) -> dict:
        """Raw manifest for 'windows' / 'macos' / 'linux'."""
        return self._manifests.get(platform_dir, {})

    def resolve(
        self,
        os_name: str,
        country_code: Optional[str] = None,
    ) -> FontProfile:
        """
        Resolve the font profile for a device OS + geo country.

        Args:
            os_name: e.g. DeviceProfile.os ("Windows 11") or
                PlatformInfo.ua_platform ("Windows" / "macOS" / "Linux")
            country_code: geo profile's country_code, or None for generic

        Returns:
            FontProfile with STEALTH_FONT_OS/REGION plus a bundle
            completeness check against the manifest.
        """

        font_os = DEFAULT_FONT_OS
        for name, mapped in OS_FONT_MAP.items():
            if name.lower() in (os_name or "").lower():
                font_os = mapped
                break

        font_region = REGION_FONT_MAP.get(
            (country_code or "").upper(), DEFAULT_FONT_REGION
        )

        platform_dir = PLATFORM_DIRS.get(font_os, "linux")
        font_files, missing_files = self._check_bundle(platform_dir)

        profile = FontProfile(
            font_os=font_os,
            font_region=font_region,
            platform_dir=platform_dir,
            font_files=font_files,
            missing_files=missing_files,
        )

        if not profile.is_complete:
            logger.warning(
                f"Font bundle incomplete for {platform_dir}: "
                f"{len(missing_files)} file(s) missing — run "
                f"'python fonts/download_fonts.py --platform {platform_dir}'"
            )

        return profile

    def _check_bundle(self, platform_dir: str) -> Tuple[List[str], List[str]]:
        """Cross-check the manifest's declared files against disk."""

        manifest = self.get_manifest(platform_dir)
        fonts_dir = self.fonts_root / platform_dir

        all_files: List[str] = []
        missing: List[str] = []

        for font_group in manifest.get("fonts", {}).values():
            for filename in font_group.get("files", []):
                all_files.append(filename)
                if not (fonts_dir / filename).exists():
                    missing.append(filename)

        return all_files, missing

    def fontconfig_env(
        self,
        profile: FontProfile,
        cache_dir: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Linux only: write a fonts.conf pointing at the bundled font
        directory and return the FONTCONFIG_* env vars to export.
        Windows (DirectWrite) and macOS (Core Text) use the system
        font store directly, so this is a no-op there.
        """

        if profile.platform_dir != "linux":
            return {}

        font_dir = self.fonts_root / "linux"
        cache_path = (
            Path(cache_dir) if cache_dir
            else Path.home() / ".cache" / "jbium" / "fonts"
        )
        cache_path.mkdir(parents=True, exist_ok=True)

        config = f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{font_dir.resolve()}</dir>
  <cachedir>{cache_path.resolve()}</cachedir>
</fontconfig>"""

        (cache_path / "fonts.conf").write_text(config)

        return {
            "FONTCONFIG_PATH": str(cache_path),
            "FONTCONFIG_FILE": "fonts.conf",
        }

    def build_env(
        self,
        os_name: str,
        country_code: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ) -> Dict[str, str]:
        """Resolve a profile and return every env var a launch needs."""

        profile = self.resolve(os_name, country_code)
        env = profile.to_env()
        env.update(self.fontconfig_env(profile, cache_dir))
        return env

    def verify_all(self) -> Dict[str, Dict]:
        """Bundle-completeness summary for every platform, for quick_check-style tooling."""

        results = {}

        for platform_dir in ("windows", "macos", "linux"):
            files, missing = self._check_bundle(platform_dir)
            results[platform_dir] = {
                "total": len(files),
                "missing": missing,
                "complete": not missing,
            }

        return results
