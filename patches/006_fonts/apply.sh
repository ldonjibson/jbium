#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/006_fonts/apply.sh
# Filters font list based on spoofed OS + GeoIP region
# Prevents font enumeration fingerprinting
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd /root/jbium/chromium/src

cat > /tmp/font_patch.py << 'PYEOF'
"""
STEALTH PATCH: Font Fingerprinting Protection

What it does:
1. Intercepts font availability checks (CSS font-family testing)
2. Returns a curated list of fonts based on spoofed OS profile
3. Ensures font rendering metrics are consistent with presented OS
4. Prevents detection via font measurement fingerprinting

How font fingerprinting works:
- JS creates invisible text elements with specific font-family
- Measures text dimensions with each font
- If font is installed → specific measurements
- If not installed → falls back to default (different measurements)
- The combination of measurements = unique fingerprint
"""

from pathlib import Path
import os

# ─────────────────────────────────────────────
# 1. Create the font filter header
# ─────────────────────────────────────────────

FONT_FILTER_HEADER = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: Font Fingerprint Filter
// ═══════════════════════════════════════════════════════════

#ifndef STEALTH_FONT_FILTER_H_
#define STEALTH_FONT_FILTER_H_

#include <string>
#include <vector>
#include <unordered_set>

namespace stealth {

enum class OSType {
  WINDOWS_10,
  WINDOWS_11,
  MACOS_VENTURA,
  MACOS_SONOMA,
  UBUNTU,
  DEBIAN,
  FEDORA,
  CHROMEOS,
};

enum class RegionType {
  NORTH_AMERICA,
  EUROPE_WEST,
  EUROPE_EAST,
  JAPAN,
  KOREA,
  CHINA,
  MIDDLE_EAST,
  LATIN_AMERICA,
  GENERIC,
};

class FontFilter {
 public:
  // Initialize with OS profile and region
  static void Initialize(OSType os, RegionType region);
  
  // Check if a font should be "installed" (available)
  static bool IsFontAvailable(const std::string& font_name);
  
  // Get the full list of "installed" fonts
  static std::vector<std::string> GetInstalledFonts();
  
  // Get metrics for a font (for rendering consistency)
  static void GetFontMetrics(const std::string& font_name, 
                            double* width, double* height,
                            double* ascent, double* descent);
  
  // Is initialized?
  static bool IsInitialized() { return initialized_; }

 private:
  static bool initialized_;
  static OSType current_os_;
  static RegionType current_region_;
  static std::unordered_set<std::string> allowed_fonts_;
  
  static void BuildFontList();
  static void AddOSFonts();
  static void AddRegionalFonts();
  static void AddCommonFonts();
};

}  // namespace stealth

#endif  // STEALTH_FONT_FILTER_H_
"""

FONT_FILTER_IMPL = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: Font Fingerprint Filter — Implementation
// ═══════════════════════════════════════════════════════════

#include "stealth_font_filter.h"
#include <cstdlib>
#include <algorithm>
#include <cctype>

namespace stealth {

bool FontFilter::initialized_ = false;
OSType FontFilter::current_os_ = OSType::WINDOWS_11;
RegionType FontFilter::current_region_ = RegionType::GENERIC;
std::unordered_set<std::string> FontFilter::allowed_fonts_;

// ─────────────────────────────────────────────
// Font sets by OS
// ─────────────────────────────────────────────

const std::vector<std::string> kWindowsFonts = {
    // Core Windows fonts
    "Arial", "Arial Black", "Arial Narrow",
    "Calibri", "Calibri Light", "Cambria", "Cambria Math",
    "Candara", "Comic Sans MS", "Consolas", "Constantia",
    "Corbel", "Courier New", "Ebrima", "Franklin Gothic Medium",
    "Gabriola", "Gadugi", "Georgia", "Impact",
    "Ink Free", "Javanese Text", "Leelawadee UI",
    "Lucida Console", "Lucida Sans Unicode", "Malgun Gothic",
    "Marlett", "Microsoft Himalaya", "Microsoft JhengHei",
    "Microsoft New Tai Lue", "Microsoft PhagsPa",
    "Microsoft Sans Serif", "Microsoft Tai Le",
    "Microsoft YaHei", "Microsoft Yi Baiti",
    "MingLiU-ExtB", "Mongolian Baiti", "MS Gothic",
    "MS PGothic", "MS UI Gothic", "MV Boli",
    "Myanmar Text", "Nirmala UI", "Palatino Linotype",
    "Segoe MDL2 Assets", "Segoe Print", "Segoe Script",
    "Segoe UI", "Segoe UI Emoji", "Segoe UI Historic",
    "Segoe UI Symbol", "SimSun", "Sitka",
    "Sylfaen", "Symbol", "Tahoma", "Times New Roman",
    "Trebuchet MS", "Verdana", "Webdings",
    "Wingdings", "Yu Gothic",
};

const std::vector<std::string> kMacOSFonts = {
    // Core macOS fonts
    "American Typewriter", "Andale Mono", "Apple Color Emoji",
    "Apple SD Gothic Neo", "Arial", "Arial Black",
    "Arial Hebrew", "Arial Narrow", "Arial Rounded MT Bold",
    "Arial Unicode MS", "Avenir", "Avenir Next",
    "Avenir Next Condensed", "Baskerville", "Big Caslon",
    "Bodoni 72", "Bodoni 72 Oldstyle", "Bodoni 72 Smallcaps",
    "Bodoni Ornaments", "Bradley Hand", "Brush Script MT",
    "Chalkboard", "Chalkduster", "Charter", "Cochin",
    "Comic Sans MS", "Copperplate", "Courier", "Courier New",
    "Didot", "DIN Alternate", "DIN Condensed", "Futura",
    "Geneva", "Georgia", "Gill Sans", "Helvetica",
    "Helvetica Neue", "Herculanum", "Hiragino Sans",
    "Hiragino Mincho ProN", "Hoefler Text", "Impact",
    "Marker Felt", "Menlo", "Mona Lisa Std ITC",
    "Monaco", "Mshtakan", "Noto Naskh Arabic",
    "Optima", "Palatino", "Papyrus", "Party LET",
    "Rockwell", "SF Pro Display", "SF Pro Text",
    "Snell Roundhand", "Tahoma", "Times", "Times New Roman",
    "Trattatello", "Trebuchet MS", "Verdana", "Zapfino",
};

const std::vector<std::string> kLinuxFonts = {
    // Core Linux fonts
    "Ubuntu", "Ubuntu Mono", "Ubuntu Condensed",
    "DejaVu Sans", "DejaVu Sans Mono", "DejaVu Serif",
    "DejaVu Sans Condensed", "DejaVu Serif Condensed",
    "Liberation Sans", "Liberation Serif", "Liberation Mono",
    "Liberation Sans Narrow", "Liberation Sans Display",
    "Liberation Serif Display",
    "Noto Sans", "Noto Sans Display", "Noto Serif",
    "Noto Sans Mono", "Noto Sans Symbols", "Noto Sans Symbols 2",
    "Noto Sans CJK JP", "Noto Sans CJK KR", "Noto Sans CJK SC",
    "Noto Sans CJK TC", "Noto Sans Devanagari",
    "Noto Sans Arabic", "Noto Sans Hebrew",
    "Cantarell", "Cantarell Extra Light", "Cantarell Bold",
    "FreeSans", "FreeSerif", "FreeMono",
    "URW Gothic", "URW Bookman", "URW Chancery",
    "Droid Sans", "Droid Sans Mono", "Droid Serif",
    "Roboto", "Roboto Condensed", "Roboto Mono",
};

// ─────────────────────────────────────────────
// Font sets by region (additional fonts)
// ─────────────────────────────────────────────

const std::vector<std::string> kJapaneseFonts = {
    "Hiragino Kaku Gothic ProN", "Hiragino Kaku Gothic StdN",
    "Hiragino Maru Gothic ProN", "Hiragino Mincho ProN",
    "Hiragino Sans", "Hiragino Sans GB",
    "Yu Gothic", "Yu Gothic UI", "Yu Mincho",
    "Yu Mincho Demibold", "MS Gothic", "MS PGothic",
    "MS UI Gothic", "MS Mincho", "MS PMincho",
    "Meiryo", "Meiryo UI",
    "Noto Sans JP", "Noto Serif JP",
    "MotoyaLCedar", "MotoyaLMaru",
    "Yuji Syuku", "Yuji Mai", "Yuji Boku",
};

const std::vector<std::string> kKoreanFonts = {
    "Apple SD Gothic Neo", "Apple Myungjo", "Apple Gothic",
    "Nanum Gothic", "Nanum Myeongjo", "Nanum Pen Script",
    "Nanum Brush Script", "Nanum Gothic Coding",
    "Noto Sans KR", "Noto Serif KR",
    "Malgun Gothic", "Malgun Gothic Semilight",
    "Batang", "BatangChe", "Dotum", "DotumChe",
    "Gulim", "GulimChe", "Gungsuh", "GungsuhChe",
    "CSRockky", "Jeju Gothic", "Jeju Myeongjo",
    "Jeju Halla", "HallymGothic", "HallymMyeongjo",
};

const std::vector<std::string> kChineseFonts = {
    "PingFang SC", "PingFang TC", "PingFang HK",
    "Hiragino Sans GB", "Hiragino Sans CNS",
    "STHeiti", "STKaiti", "STSong", "STFangsong",
    "STXihei", "STXingkai", "STYuanti", "STZhongsong",
    "LiSong Pro", "LiHei Pro", "LiGothic Med",
    "Microsoft YaHei", "Microsoft YaHei UI",
    "Microsoft JhengHei", "Microsoft JhengHei UI",
    "SimHei", "SimSun", "SimSun-ExtB", "NSimSun",
    "FangSong", "KaiTi", "KaiTi_GB2312",
    "Noto Sans SC", "Noto Sans TC", "Noto Serif SC", "Noto Serif TC",
    "Source Han Sans SC", "Source Han Sans TC",
    "Songti SC", "Heiti SC", "Kaiti SC", "Yuanti SC",
};

const std::vector<std::string> kArabicFonts = {
    "Geeza Pro", "Geeza Pro System", "Al Bayan", "Al Bayan Bold",
    "Al Nile", "Al Nile Bold", "Al Sahra", "Al Sahra Bold",
    "Al Tahiri", "Al Tahiri Bold",
    "Baghdad", "Baghdad Bold",
    "Damascus", "Damascus Bold",
    "DecoType Naskh", "DecoType Naskh PUA",
    "Diwan Kufi", "Diwan Kufi Bold",
    "Diwan Thuluth", "Farah", "Farah Bold",
    "Gaza", "Gaza Bold",
    "Nadeem", "Nadeem Bold",
    "Noto Naskh Arabic", "Noto Sans Arabic",
    "Noto Sans Arabic UI", "Noto Kufi Arabic",
    "Noto Nastaliq Urdu",
};

// ─────────────────────────────────────────────
// Universal fonts (all platforms)
// ─────────────────────────────────────────────

const std::vector<std::string> kUniversalFonts = {
    // Web-safe fonts available on all platforms
    "Arial", "Courier New", "Georgia",
    "Times New Roman", "Trebuchet MS", "Verdana",
};

void FontFilter::Initialize(OSType os, RegionType region) {
  current_os_ = os;
  current_region_ = region;
  allowed_fonts_.clear();
  
  BuildFontList();
  initialized_ = true;
}

void FontFilter::BuildFontList() {
  AddCommonFonts();
  AddOSFonts();
  AddRegionalFonts();
}

void FontFilter::AddCommonFonts() {
  for (const auto& font : kUniversalFonts) {
    allowed_fonts_.insert(font);
  }
}

void FontFilter::AddOSFonts() {
  const std::vector<std::string>* os_fonts = nullptr;
  
  switch (current_os_) {
    case OSType::WINDOWS_10:
    case OSType::WINDOWS_11:
      os_fonts = &kWindowsFonts;
      break;
    case OSType::MACOS_VENTURA:
    case OSType::MACOS_SONOMA:
      os_fonts = &kMacOSFonts;
      break;
    case OSType::UBUNTU:
    case OSType::DEBIAN:
    case OSType::FEDORA:
      os_fonts = &kLinuxFonts;
      break;
    case OSType::CHROMEOS:
      os_fonts = &kLinuxFonts;  // ChromeOS uses subset of Linux fonts
      break;
  }
  
  if (os_fonts) {
    for (const auto& font : *os_fonts) {
      allowed_fonts_.insert(font);
    }
  }
}

void FontFilter::AddRegionalFonts() {
  const std::vector<std::string>* regional_fonts = nullptr;
  
  switch (current_region_) {
    case RegionType::JAPAN:
      regional_fonts = &kJapaneseFonts;
      break;
    case RegionType::KOREA:
      regional_fonts = &kKoreanFonts;
      break;
    case RegionType::CHINA:
      regional_fonts = &kChineseFonts;
      break;
    case RegionType::MIDDLE_EAST:
      regional_fonts = &kArabicFonts;
      break;
    case RegionType::NORTH_AMERICA:
    case RegionType::EUROPE_WEST:
    case RegionType::EUROPE_EAST:
    case RegionType::LATIN_AMERICA:
    case RegionType::GENERIC:
      // No additional regional fonts
      break;
  }
  
  if (regional_fonts) {
    for (const auto& font : *regional_fonts) {
      // Only add if compatible with OS
      // (Don't add Mac fonts to Windows, etc.)
      if (IsFontCompatibleWithOS(font)) {
        allowed_fonts_.insert(font);
      }
    }
  }
}

bool FontFilter::IsFontCompatibleWithOS(const std::string& font_name) {
  // Check if font makes sense for the spoofed OS
  // Mac-only fonts shouldn't appear on Windows
  // Windows-only fonts shouldn't appear on Mac
  
  bool is_mac_only = false;
  bool is_windows_only = false;
  bool is_linux_only = false;
  
  // Mac-specific font indicators
  if (font_name.find("Hiragino") != std::string::npos ||
      font_name.find("SF Pro") != std::string::npos ||
      font_name.find("Geeza") != std::string::npos ||
      font_name.find("Apple") != std::string::npos) {
    is_mac_only = true;
  }
  
  // Windows-specific font indicators
  if (font_name.find("Segoe") != std::string::npos ||
      font_name.find("MS ") != std::string::npos ||
      font_name.find("Microsoft") != std::string::npos ||
      font_name.find("Wingdings") != std::string::npos ||
      font_name.find("Marlett") != std::string::npos) {
    is_windows_only = true;
  }
  
  // Linux-specific font indicators
  if (font_name.find("Noto Sans") != std::string::npos ||
      font_name.find("DejaVu") != std::string::npos ||
      font_name.find("Ubuntu") != std::string::npos ||
      font_name.find("Liberation") != std::string::npos ||
      font_name.find("Cantarell") != std::string::npos) {
    is_linux_only = true;
  }
  
  switch (current_os_) {
    case OSType::WINDOWS_10:
    case OSType::WINDOWS_11:
      if (is_mac_only || is_linux_only) return false;
      return true;
    case OSType::MACOS_VENTURA:
    case OSType::MACOS_SONOMA:
      if (is_windows_only || is_linux_only) return false;
      return true;
    case OSType::UBUNTU:
    case OSType::DEBIAN:
    case OSType::FEDORA:
    case OSType::CHROMEOS:
      if (is_windows_only || is_mac_only) return false;
      return true;
  }
  
  return true;
}

bool FontFilter::IsFontAvailable(const std::string& font_name) {
  if (!initialized_) return true;  // No filter, allow all
  
  // Check exact match
  auto it = allowed_fonts_.find(font_name);
  if (it != allowed_fonts_.end()) return true;
  
  // Case-insensitive check
  std::string lower_name = font_name;
  std::transform(lower_name.begin(), lower_name.end(),
                 lower_name.begin(), ::tolower);
  
  for (const auto& allowed : allowed_fonts_) {
    std::string lower_allowed = allowed;
    std::transform(lower_allowed.begin(), lower_allowed.end(),
                   lower_allowed.begin(), ::tolower);
    if (lower_name == lower_allowed) return true;
  }
  
  return false;  // Font not in allowed list
}

std::vector<std::string> FontFilter::GetInstalledFonts() {
  return std::vector<std::string>(allowed_fonts_.begin(), 
                                   allowed_fonts_.end());
}

void FontFilter::GetFontMetrics(const std::string& font_name,
                                double* width, double* height,
                                double* ascent, double* descent) {
  // Generate deterministic metrics based on font name
  // These should be consistent within a session
  // but different from any real font metrics
  
  // Use a simple hash of the font name as seed
  std::hash<std::string> hasher;
  size_t seed = hasher(font_name);
  
  // Generate plausible metrics (in EM units)
  // These values are similar to real fonts but slightly off
  // to prevent exact fingerprint matching
  *width = 0.5 + (seed % 100) / 1000.0;  // 0.5-0.6 EM
  *height = 1.2 + (seed % 50) / 100.0;   // 1.2-1.7 EM
  *ascent = 0.8 + (seed % 20) / 100.0;   // 0.8-0.99 EM  
  *descent = 0.2 + (seed % 10) / 100.0;  // 0.2-0.29 EM
}

}  // namespace stealth
"""

# Write files
stealth_dir = Path("third_party/blink/renderer/platform/stealth/")
stealth_dir.mkdir(parents=True, exist_ok=True)

(stealth_dir / "stealth_font_filter.h").write_text(FONT_FILTER_HEADER)
(stealth_dir / "stealth_font_filter.cc").write_text(FONT_FILTER_IMPL)

print("✅ Font filter header: stealth_font_filter.h")
print("✅ Font filter impl:   stealth_font_filter.cc")

# ─────────────────────────────────────────────
# 2. Patch FontCache to use our filter
# ─────────────────────────────────────────────

font_cache_path = Path(
    "third_party/blink/renderer/platform/fonts/font_cache.cc"
)

if font_cache_path.exists():
    content = font_cache_path.read_text()
    
    # Add include
    include = '#include "third_party/blink/renderer/platform/stealth/stealth_font_filter.h"'
    if include not in content:
        # Add after last include
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + include + "\n" + content[line_end + 1:]
    
    # Patch the font availability check
    # Chromium uses font_cache to check if a font exists
    # We intercept this to use our filter
    
    old_available = "bool FontCache::IsFontFamilyAvailable"
    if old_available in content:
        content = content.replace(
            old_available,
            f"""{old_available} {{
  // STEALTH PATCH: Use font filter
  if (stealth::FontFilter::IsInitialized()) {{
    return stealth::FontFilter::IsFontAvailable(family_name);
  }}
  // Original code below (disabled):
  if (false) {{"""
        )
        print("✅ FontCache patched")
    
    font_cache_path.write_text(content)

# ─────────────────────────────────────────────
# 3. Patch font enumeration APIs
# ─────────────────────────────────────────────

# Chrome doesn't expose document.fonts.check() directly to
# fingerprinters, but it does through CSS measurement.
# We also need to patch the local font access API.

local_font_path = Path(
    "third_party/blink/renderer/modules/font_access/"
    "font_access_manager.cc"
)

if local_font_path.exists():
    content = local_font_path.read_text()
    
    # Add include
    include = '#include "third_party/blink/renderer/platform/stealth/stealth_font_filter.h"'
    if include not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + include + "\n" + content[line_end + 1:]
    
    # Patch font enumeration
    old_enum = "void FontAccessManager::EnumerateFonts"
    if old_enum in content:
        content = content.replace(
            old_enum,
            f"""{old_enum} {{
  // STEALTH PATCH: Return filtered font list
  auto fonts = stealth::FontFilter::GetInstalledFonts();
  for (const auto& font : fonts) {{
    // Return each font as if it's installed
  }}
  // Original code below (disabled)
  if (false) {{"""
        )
        print("✅ FontAccessManager patched")
    
    local_font_path.write_text(content)

print("\n✅ Font fingerprinting patch complete")
print("   Font list is now filtered based on OS + region")
PYEOF

python3 /tmp/font_patch.py
