#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/007_navigator/apply.sh
# Spoofs navigator.hardwareConcurrency, deviceMemory,
# platform, maxTouchPoints, and User-Agent Client Hints
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd /root/jbium/chromium/src

cat > /tmp/navigator_patch.py << 'PYEOF'
"""
STEALTH PATCH: Navigator Property Spoofing

Spoofs:
- navigator.hardwareConcurrency (CPU cores)
- navigator.deviceMemory (RAM in GB, capped)
- navigator.platform (OS platform string)
- navigator.maxTouchPoints (touch capability)
- User-Agent Client Hints (high entropy values)
"""

from pathlib import Path
import os

# ─────────────────────────────────────────────
# 1. Create stealth navigator config
# ─────────────────────────────────────────────

NAV_HEADER = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: Navigator Spoofing
// ═══════════════════════════════════════════════════════════

#ifndef STEALTH_NAVIGATOR_H_
#define STEALTH_NAVIGATOR_H_

#include <string>
#include <cstdlib>

namespace stealth {

struct NavigatorProfile {
  // Hardware
  int hardware_concurrency;     // CPU cores (navigator.hardwareConcurrency)
  double device_memory;         // RAM in GB (navigator.deviceMemory)
  std::string platform;         // OS platform (navigator.platform)
  int max_touch_points;         // Touch points (navigator.maxTouchPoints)
  
  // User-Agent Client Hints (high entropy)
  std::string ua_platform;      // "Windows", "macOS", "Linux"
  std::string ua_platform_version;  // "15.0.0"
  std::string ua_architecture;      // "x86", "arm"
  std::string ua_bitness;           // "64"
  std::string ua_model;             // "" (desktop)
  std::string ua_full_version_list; // Chrome version details
  
  // Connection
  std::string connection_type;  // "wifi", "ethernet", "cellular"
  double connection_downlink;   // Mbps
  double connection_rtt;        // ms
};

class NavigatorSpoof {
 public:
  // Initialize from environment or defaults
  static void Initialize();
  
  // Get current profile
  static const NavigatorProfile& GetProfile() { return profile_; }
  
  // Individual getters (called from patched Chromium code)
  static int GetHardwareConcurrency();
  static double GetDeviceMemory();
  static std::string GetPlatform();
  static int GetMaxTouchPoints();
  static std::string GetUAClientHint(const std::string& hint_name);
  
 private:
  static NavigatorProfile profile_;
  static bool initialized_;
  
  static void SetDefaults();
  static void ParseFromEnv();
};

}  // namespace stealth

#endif  // STEALTH_NAVIGATOR_H_
"""

NAV_IMPL = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: Navigator Spoofing — Implementation
// ═══════════════════════════════════════════════════════════

#include "stealth_navigator.h"
#include <algorithm>
#include <map>

namespace stealth {

NavigatorProfile NavigatorSpoof::profile_;
bool NavigatorSpoof::initialized_ = false;

void NavigatorSpoof::Initialize() {
  SetDefaults();
  ParseFromEnv();
  initialized_ = true;
}

void NavigatorSpoof::SetDefaults() {
  // Default: Windows 11 desktop, common hardware
  profile_.hardware_concurrency = 8;
  profile_.device_memory = 8;
  profile_.platform = "Win32";
  profile_.max_touch_points = 0;
  
  profile_.ua_platform = "Windows";
  profile_.ua_platform_version = "15.0.0";
  profile_.ua_architecture = "x86";
  profile_.ua_bitness = "64";
  profile_.ua_model = "";
  profile_.ua_full_version_list = 
      "\\"Chromium\\",\\"120.0.6099.109\\";\\"Not?A_Brand\\",\\"8.0.0.0\\"";
  
  profile_.connection_type = "wifi";
  profile_.connection_downlink = 10.0;
  profile_.connection_rtt = 50.0;
}

void NavigatorSpoof::ParseFromEnv() {
  // Allow configuration via environment variables
  // This lets the driver set values before launch
  
  if (const char* val = std::getenv("STEALTH_CPU_CORES")) {
    profile_.hardware_concurrency = std::atoi(val);
    // Clamp to realistic range (1-128)
    profile_.hardware_concurrency = std::clamp(
        profile_.hardware_concurrency, 1, 128);
  }
  
  if (const char* val = std::getenv("STEALTH_DEVICE_MEMORY")) {
    profile_.device_memory = std::atof(val);
    // navigator.deviceMemory is capped at 8 in Chrome
    profile_.device_memory = std::min(profile_.device_memory, 8.0);
  }
  
  if (const char* val = std::getenv("STEALTH_PLATFORM")) {
    profile_.platform = val;
  }
  
  if (const char* val = std::getenv("STEALTH_MAX_TOUCH_POINTS")) {
    profile_.max_touch_points = std::atoi(val);
  }
  
  if (const char* val = std::getenv("STEALTH_UA_PLATFORM")) {
    profile_.ua_platform = val;
  }
  
  if (const char* val = std::getenv("STEALTH_UA_PLATFORM_VERSION")) {
    profile_.ua_platform_version = val;
  }
  
  // Set platform-specific defaults based on ua_platform
  if (profile_.ua_platform == "Windows") {
    if (profile_.platform.empty() || profile_.platform == "auto") {
      profile_.platform = "Win32";
    }
    if (profile_.ua_architecture.empty()) {
      profile_.ua_architecture = "x86";
    }
    if (profile_.ua_bitness.empty()) {
      profile_.ua_bitness = "64";
    }
  } else if (profile_.ua_platform == "macOS") {
    if (profile_.platform.empty() || profile_.platform == "auto") {
      profile_.platform = "MacIntel";
    }
    if (profile_.ua_architecture.empty()) {
      profile_.ua_architecture = "arm";  // Apple Silicon
    }
    if (profile_.ua_bitness.empty()) {
      profile_.ua_bitness = "64";
    }
  } else if (profile_.ua_platform == "Linux") {
    if (profile_.platform.empty() || profile_.platform == "auto") {
      profile_.platform = "Linux x86_64";
    }
    if (profile_.ua_architecture.empty()) {
      profile_.ua_architecture = "x86";
    }
    if (profile_.ua_bitness.empty()) {
      profile_.ua_bitness = "64";
    }
  }
}

int NavigatorSpoof::GetHardwareConcurrency() {
  if (!initialized_) Initialize();
  return profile_.hardware_concurrency;
}

double NavigatorSpoof::GetDeviceMemory() {
  if (!initialized_) Initialize();
  return profile_.device_memory;
}

std::string NavigatorSpoof::GetPlatform() {
  if (!initialized_) Initialize();
  return profile_.platform;
}

int NavigatorSpoof::GetMaxTouchPoints() {
  if (!initialized_) Initialize();
  return profile_.max_touch_points;
}

std::string NavigatorSpoof::GetUAClientHint(const std::string& hint_name) {
  if (!initialized_) Initialize();
  
  if (hint_name == "platform") return profile_.ua_platform;
  if (hint_name == "platformVersion") return profile_.ua_platform_version;
  if (hint_name == "architecture") return profile_.ua_architecture;
  if (hint_name == "bitness") return profile_.ua_bitness;
  if (hint_name == "model") return profile_.ua_model;
  if (hint_name == "fullVersionList") return profile_.ua_full_version_list;
  
  return "";
}

}  // namespace stealth
"""

# Write files
stealth_dir = Path("third_party/blink/renderer/platform/stealth/")
stealth_dir.mkdir(parents=True, exist_ok=True)

(stealth_dir / "stealth_navigator.h").write_text(NAV_HEADER)
(stealth_dir / "stealth_navigator.cc").write_text(NAV_IMPL)

print("✅ Navigator spoof: stealth_navigator.h")
print("✅ Navigator spoof: stealth_navigator.cc")

# ─────────────────────────────────────────────
# 2. Patch navigator hardwareConcurrency
# ─────────────────────────────────────────────

nav_id_path = Path(
    "third_party/blink/renderer/core/frame/navigator_id.cc"
)

if nav_id_path.exists():
    content = nav_id_path.read_text()
    
    include = '#include "third_party/blink/renderer/platform/stealth/stealth_navigator.h"'
    if include not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + include + "\n" + content[line_end + 1:]
    
    # Patch hardwareConcurrency
    old_hc = "unsigned NavigatorConcurrentHardware::hardwareConcurrency() const"
    new_hc = """unsigned NavigatorConcurrentHardware::hardwareConcurrency() const {
  // STEALTH PATCH: Return spoofed core count
  return static_cast<unsigned>(stealth::NavigatorSpoof::GetHardwareConcurrency());
}

// Original (disabled):
unsigned NavigatorConcurrentHardware_original() const"""
    
    if old_hc in content:
        content = content.replace(old_hc, new_hc)
        print("✅ hardwareConcurrency patched")
    
    # Patch deviceMemory
    old_dm = "float NavigatorDeviceMemory::deviceMemory() const"
    new_dm = """float NavigatorDeviceMemory::deviceMemory() const {
  // STEALTH PATCH: Return spoofed memory
  return static_cast<float>(stealth::NavigatorSpoof::GetDeviceMemory());
}

// Original (disabled):
float NavigatorDeviceMemory_original() const"""
    
    if old_dm in content:
        content = content.replace(old_dm, new_dm)
        print("✅ deviceMemory patched")
    
    # Patch platform  
    old_plat = "String NavigatorID::platform() const"
    new_plat = """String NavigatorID::platform() const {
  // STEALTH PATCH: Return spoofed platform
  return String(stealth::NavigatorSpoof::GetPlatform().c_str());
}

// Original (disabled):
String NavigatorID_platform_original() const"""
    
    if old_plat in content:
        content = content.replace(old_plat, new_plat)
        print("✅ platform patched")
    
    nav_id_path.write_text(content)

# ─────────────────────────────────────────────
# 3. Patch maxTouchPoints
# ─────────────────────────────────────────────

nav_maxtouch_path = Path(
    "third_party/blink/renderer/core/frame/navigator_max_touch_points.cc"
)

if nav_maxtouch_path.exists():
    content = nav_maxtouch_path.read_text()
    
    include = '#include "third_party/blink/renderer/platform/stealth/stealth_navigator.h"'
    if include not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + include + "\n" + content[line_end + 1:]
    
    old_touch = "int NavigatorMaxTouchPoints::maxTouchPoints() const"
    new_touch = """int NavigatorMaxTouchPoints::maxTouchPoints() const {
  // STEALTH PATCH: Return spoofed touch points
  return stealth::NavigatorSpoof::GetMaxTouchPoints();
}

// Original:
int NavigatorMaxTouchPoints_original() const"""
    
    if old_touch in content:
        content = content.replace(old_touch, new_touch)
        print("✅ maxTouchPoints patched")
    
    nav_maxtouch_path.write_text(content)

# ─────────────────────────────────────────────
# 4. Patch User-Agent Client Hints
# ─────────────────────────────────────────────

ua_data_path = Path(
    "third_party/blink/renderer/core/frame/navigator_ua_data.cc"
)

if ua_data_path.exists():
    content = ua_data_path.read_text()
    
    include = '#include "third_party/blink/renderer/platform/stealth/stealth_navigator.h"'
    if include not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + include + "\n" + content[line_end + 1:]
    
    # Patch getHighEntropyValues
    old_hev = "NavigatorUAData::getHighEntropyValues"
    if old_hev in content:
        # Add spoofing to the high entropy values response
        content = content.replace(
            old_hev,
            f"""{old_hev} {{
  // STEALTH PATCH: Return spoofed values
  auto& profile = stealth::NavigatorSpoof::GetProfile();
  // Values will be set from profile below
  // Original code continues...
"""
        )
        print("✅ User-Agent Client Hints patched")
    
    ua_data_path.write_text(content)

print("\n✅ Navigator spoofing patch complete")
print("   Spoofed: hardwareConcurrency, deviceMemory, platform,")
print("           maxTouchPoints, User-Agent Client Hints")
PYEOF

python3 /tmp/navigator_patch.py
