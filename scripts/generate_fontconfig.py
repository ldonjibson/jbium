#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════
Fontconfig Template Generator
════════════════════════════════════════════════════════════

Takes the fontconfig_template.xml and generates a customized
fonts.conf for a specific platform/region combination.

Called by the stealth browser launcher at runtime.
"""

import os
import re
import sys
import argparse
from pathlib import Path
from typing import Dict, Tuple


# ═════════════════════════════════════════════
# Platform configurations
# ═════════════════════════════════════════════

PLATFORM_CONFIGS = {
    "windows_10": {
        "spoof_mode": "windows",
        "dpi": 96,
        "rendering": "windows",
        "description": "Windows 10 font environment",
    },
    "windows_11": {
        "spoof_mode": "windows",
        "dpi": 96,
        "rendering": "windows",
        "description": "Windows 11 font environment",
    },
    "macos_ventura": {
        "spoof_mode": "macos",
        "dpi": 144,  # Retina
        "rendering": "macos",
        "description": "macOS Ventura font environment",
    },
    "macos_sonoma": {
        "spoof_mode": "macos",
        "dpi": 144,  # Retina
        "rendering": "macos",
        "description": "macOS Sonoma font environment",
    },
    "ubuntu": {
        "spoof_mode": "linux",
        "dpi": 96,
        "rendering": "linux",
        "description": "Ubuntu Linux font environment",
    },
    "debian": {
        "spoof_mode": "linux",
        "dpi": 96,
        "rendering": "linux",
        "description": "Debian Linux font environment",
    },
}

# ═════════════════════════════════════════════
# Region configurations
# ═════════════════════════════════════════════

REGION_MAP = {
    # Generic (Western)
    "US": "generic",
    "GB": "generic",
    "DE": "generic",
    "FR": "generic",
    "ES": "generic",
    "IT": "generic",
    "NL": "generic",
    "SE": "generic",
    "NO": "generic",
    "DK": "generic",
    "FI": "generic",
    "PT": "generic",
    "BR": "generic",
    "MX": "generic",
    "CA": "generic",
    "AU": "generic",
    "NZ": "generic",
    
    # CJK
    "JP": "japan",
    "KR": "korea",
    "CN": "china",
    "TW": "china",
    "HK": "china",
    "SG": "china",
    
    # Arabic
    "SA": "arabic",
    "AE": "arabic",
    "EG": "arabic",
    "QA": "arabic",
    "KW": "arabic",
    "JO": "arabic",
    "MA": "arabic",
    "DZ": "arabic",
    
    # Cyrillic
    "RU": "cyrillic",
    "UA": "cyrillic",
    "BY": "cyrillic",
    "KZ": "cyrillic",
    
    # Indic
    "IN": "indic",
    "PK": "indic",
    "BD": "indic",
    "TH": "indic",
    "VN": "indic",
    "ID": "indic",
}


def generate_fontconfig(
    platform: str,
    region: str,
    font_dir: str,
    cache_dir: str,
    template_path: str = None,
    output_path: str = None,
) -> str:
    """
    Generate customized fonts.conf from template.
    
    Args:
        platform: Platform name (windows_11, macos_sonoma, ubuntu, etc.)
        region: Country code (US, JP, DE, etc.)
        font_dir: Path to bundled fonts
        cache_dir: Path to font cache
        template_path: Path to template (default: fonts/fontconfig_template.xml)
        output_path: Where to write the result
    
    Returns:
        Path to generated fonts.conf
    """
    
    # Find template
    if template_path is None:
        template_path = Path(__file__).parent.parent / "fonts" / "fontconfig_template.xml"
    
    template_path = Path(template_path)
    
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    
    # Read template
    content = template_path.read_text()
    
    # Get platform config
    if platform not in PLATFORM_CONFIGS:
        # Default to windows (most common)
        platform = "windows_11"
    
    config = PLATFORM_CONFIGS[platform]
    spoof_mode = config["spoof_mode"]
    
    # Get region
    region_type = REGION_MAP.get(region.upper(), "generic")
    
    # Get DPI
    # If environment overrides it, use that
    if os.environ.get("STEALTH_DPI"):
        dpi = os.environ.get("STEALTH_DPI")
    else:
        dpi = str(config["dpi"])
    
    # ── Basic substitutions ──
    
    content = content.replace("{{FONT_DIR}}", str(Path(font_dir).resolve()))
    content = content.replace("{{CACHE_DIR}}", str(Path(cache_dir).resolve()))
    content = content.replace("{{DPI}}", dpi)
    content = content.replace("{{PLATFORM}}", platform)
    content = content.replace("{{REGION}}", region_type)
    
    # ── Platform-specific sections ──
    # Enable/disable platform sections based on spoof mode
    
    if spoof_mode == "windows":
        # Enable Windows sections
        content = _enable_section(content, "PLATFORM_WINDOWS")
        content = _enable_section(content, "SPOOF_WINDOWS")
        
        # Disable other platform sections
        content = _disable_section(content, "PLATFORM_MACOS")
        content = _disable_section(content, "PLATFORM_LINUX")
        content = _disable_section(content, "SPOOF_MACOS")
        content = _disable_section(content, "SPOOF_LINUX")
    
    elif spoof_mode == "macos":
        # Enable macOS sections
        content = _enable_section(content, "PLATFORM_MACOS")
        content = _enable_section(content, "SPOOF_MACOS")
        
        # Disable others
        content = _disable_section(content, "PLATFORM_WINDOWS")
        content = _disable_section(content, "PLATFORM_LINUX")
        content = _disable_section(content, "SPOOF_WINDOWS")
        content = _disable_section(content, "SPOOF_LINUX")
    
    else:  # linux
        # Enable Linux sections
        content = _enable_section(content, "PLATFORM_LINUX")
        content = _enable_section(content, "SPOOF_LINUX")
        
        # Disable others
        content = _disable_section(content, "PLATFORM_WINDOWS")
        content = _disable_section(content, "PLATFORM_MACOS")
        content = _disable_section(content, "SPOOF_WINDOWS")
        content = _disable_section(content, "SPOOF_MACOS")
    
    # ── Region-specific sections ──
    
    # Enable the relevant region
    region_markers = [
        "REGION_GENERIC",
        "REGION_JAPAN", 
        "REGION_KOREA",
        "REGION_CHINA",
        "REGION_ARABIC",
    ]
    
    for marker in region_markers:
        if marker == f"REGION_{region_type.upper()}":
            content = _enable_section(content, marker)
        else:
            content = _disable_section(content, marker)
    
    # ── Clean up markers ──
    
    # Remove all remaining markers
    content = re.sub(
        r'<!-- \{\{[A-Z_]+(_START|_END)\}\} -->\s*\n?',
        '',
        content
    )
    
    # ── Write output ──
    
    if output_path is None:
        output_path = Path(cache_dir) / "fonts.conf"
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    output_path.write_text(content)
    
    return str(output_path)


def _enable_section(content: str, marker: str) -> str:
    """Enable a section by removing comment markers around it"""
    
    # Remove start marker (uncomment the section)
    content = content.replace(
        f"<!-- {{{marker}_START}}} -->",
        f"<!-- {marker}_START -->"  # Keep marker for later cleanup
    )
    
    # Remove end marker
    content = content.replace(
        f"<!-- {{{marker}_END}}} -->",
        f"<!-- {marker}_END -->"
    )
    
    # For sections that are fully commented out (<!-- ... -->),
    # we need to uncomment them
    
    # Pattern: find the section and uncomment it
    pattern = re.compile(
        rf'(<!--\s*{marker}_START\s*-->\s*\n)(.*?)(<!--\s*{marker}_END\s*-->)',
        re.DOTALL
    )
    
    match = pattern.search(content)
    if match:
        section_content = match.group(2)
        
        # Uncomment XML comments within the section
        # <!-- <tag> --> becomes <tag>
        # But be careful not to uncomment actual comments
        # This is tricky, so we use a simpler approach:
        # Just uncomment lines that start with <!-- and end with -->
        
        uncommented = []
        for line in section_content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('<!--') and stripped.endswith('-->') and len(stripped) > 8:
                # Check if it's a real comment or commented-out code
                inner = stripped[4:-3].strip()
                if inner.startswith('<') or inner.startswith('<match') or inner.startswith('<alias'):
                    # This is commented-out XML code, uncomment it
                    line = line.replace('<!--', '', 1)
                    line = line[::-1].replace('-->', '', 1)[::-1]
            uncommented.append(line)
        
        section_content = '\n'.join(uncommented)
        
        content = content[:match.start(2)] + section_content + content[match.end(2):]
    
    return content


def _disable_section(content: str, marker: str) -> str:
    """Disable a section by commenting it out"""
    
    # Pattern to find the section
    pattern = re.compile(
        rf'(<!--\s*{marker}_START\s*-->\s*\n)(.*?)(<!--\s*{marker}_END\s*-->)',
        re.DOTALL
    )
    
    def comment_out(match):
        section = match.group(2)
        # If already commented, leave as is
        if section.strip().startswith('<!--'):
            return match.group(0)
        
        # Comment it out
        commented = ""
        for line in section.split('\n'):
            if line.strip() and not line.strip().startswith('<!--'):
                commented += f"<!-- {line} -->\n"
            else:
                commented += line + "\n"
        
        return match.group(1) + commented + match.group(3)
    
    return pattern.sub(comment_out, content)


# ═════════════════════════════════════════════
# Font Bundling Helper
# ═════════════════════════════════════════════

BUNDLED_FONTS = {
    "windows": [
        # Metric-compatible fonts (needed to match Windows metrics)
        ("Liberation Sans", "LiberationSans-Regular.ttf"),
        ("Liberation Sans Bold", "LiberationSans-Bold.ttf"),
        ("Liberation Serif", "LiberationSerif-Regular.ttf"),
        ("Liberation Mono", "LiberationMono-Regular.ttf"),
        ("Carlito", "Carlito-Regular.ttf"),  # Calibri-compatible
        ("Caladea", "Caladea-Regular.ttf"),   # Cambria-compatible
        
        # Noto for broader coverage
        ("Noto Sans", "NotoSans-Regular.ttf"),
        ("Noto Sans JP", "NotoSansJP-Regular.ttf"),
        ("Noto Sans KR", "NotoSansKR-Regular.ttf"),
        ("Noto Sans SC", "NotoSansSC-Regular.ttf"),
        ("Noto Naskh Arabic", "NotoNaskhArabic-Regular.ttf"),
    ],
    "macos": [
        ("Noto Sans", "NotoSans-Regular.ttf"),
        ("Noto Sans JP", "NotoSansJP-Regular.ttf"),
        ("Noto Serif", "NotoSerif-Regular.ttf"),
    ],
    "linux": [
        ("Noto Sans", "NotoSans-Regular.ttf"),
        ("Noto Sans JP", "NotoSansJP-Regular.ttf"),
        ("DejaVu Sans", "DejaVuSans.ttf"),
        ("DejaVu Serif", "DejaVuSerif.ttf"),
        ("DejaVu Sans Mono", "DejaVuSansMono.ttf"),
        ("Liberation Sans", "LiberationSans-Regular.ttf"),
        ("Liberation Serif", "LiberationSerif-Regular.ttf"),
        ("Ubuntu", "Ubuntu-Regular.ttf"),
    ],
}


def download_fonts(platform: str, output_dir: str):
    """Download the recommended fonts for a platform"""
    
    import urllib.request
    import tarfile
    import zipfile
    
    fonts = BUNDLED_FONTS.get(platform, BUNDLED_FONTS["linux"])
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print(f"Downloading fonts for {platform}...")
    
    # Noto fonts from Google's GitHub
    NOTO_BASE = "https://github.com/notofonts/noto-fonts/raw/main"
    
    # Liberation fonts
    LIBERATION_URL = "https://github.com/liberationfonts/liberation-fonts/releases/download/2.1.5/liberation-fonts-ttf-2.1.5.tar.gz"
    
    # Carlito (Calibri-compatible)
    CARLITO_URL = "https://github.com/googlefonts/carlito/raw/main/fonts/ttf/Carlito-Regular.ttf"
    
    font_sources = {
        "Noto Sans": f"{NOTO_BASE}/noto-core/NotoSans/NotoSans-Regular.ttf",
        "Noto Sans JP": f"{NOTO_BASE}/noto-cjk/NotoSansJP/NotoSansJP-Regular.ttf",
        "Noto Sans KR": f"{NOTO_BASE}/noto-cjk/NotoSansKR/NotoSansKR-Regular.ttf",
        "Noto Sans SC": f"{NOTO_BASE}/noto-cjk/NotoSansSC/NotoSansSC-Regular.ttf",
        "Noto Naskh Arabic": f"{NOTO_BASE}/noto-arabic/NotoNaskhArabic/NotoNaskhArabic-Regular.ttf",
        "Liberation Sans": LIBERATION_URL,  # Archive
        "Carlito": CARLITO_URL,
    }
    
    for font_name, _ in fonts:
        if font_name in font_sources:
            url = font_sources[font_name]
            
            if url.endswith(".tar.gz"):
                # Download and extract archive
                archive_path = output_path / f"{font_name.replace(' ', '')}.tar.gz"
                print(f"  Downloading {font_name}...")
                urllib.request.urlretrieve(url, archive_path)
                
                with tarfile.open(archive_path, "r:gz") as tar:
                    for member in tar.getmembers():
                        if member.name.endswith(".ttf"):
                            f = tar.extractfile(member)
                            with open(output_path / Path(member.name).name, "wb") as out:
                                out.write(f.read())
                
                archive_path.unlink()
                
            else:
                # Direct TTF download
                print(f"  Downloading {font_name}...")
                dest = output_path / f"{font_name.replace(' ', '')}-Regular.ttf"
                try:
                    urllib.request.urlretrieve(url, dest)
                except Exception as e:
                    print(f"    ⚠️  Failed: {e}")
    
    print("  ✅ Fonts downloaded")


# ═════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate customized fontconfig for stealth browser"
    )
    parser.add_argument(
        "--platform", type=str, default="windows_11",
        choices=list(PLATFORM_CONFIGS.keys()),
        help="Platform to generate config for"
    )
    parser.add_argument(
        "--region", type=str, default="US",
        help="Country code for regional fonts"
    )
    parser.add_argument(
        "--font-dir", type=str, default="./fonts",
        help="Directory containing bundled fonts"
    )
    parser.add_argument(
        "--cache-dir", type=str, default=None,
        help="Cache directory (default: auto)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output file path (default: cache_dir/fonts.conf)"
    )
    parser.add_argument(
        "--download-fonts", action="store_true",
        help="Download bundled fonts for the platform"
    )
    
    args = parser.parse_args()
    
    # Download fonts if requested
    if args.download_fonts:
        download_fonts(args.platform, args.font_dir)
    
    # Determine cache directory
    if args.cache_dir is None:
        cache_dir = Path.home() / ".cache" / "jbium" / "fonts"
    else:
        cache_dir = Path(args.cache_dir)
    
    # Generate
    result = generate_fontconfig(
        platform=args.platform,
        region=args.region,
        font_dir=args.font_dir,
        cache_dir=str(cache_dir),
        template_path=None,
        output_path=args.output,
    )
    
    print(f"\n✅ Generated: {result}")
    print(f"   Platform: {args.platform}")
    print(f"   Region:   {args.region}")
    print(f"   Fonts:    {args.font_dir}")
    print(f"   Cache:    {cache_dir}")
    print(f"\nTo use with Chromium:")
    print(f"   export FONTCONFIG_PATH={cache_dir}")
    print(f"   export FONTCONFIG_FILE=fonts.conf")
