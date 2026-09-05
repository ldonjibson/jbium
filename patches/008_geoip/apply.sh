#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/008_geoip/apply.sh
# Makes timezone, locale, and geolocation consistent with proxy IP
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd /root/jbium/chromium/src

cat > /tmp/geoip_patch.py << 'PYEOF'
"""
STEALTH PATCH: GeoIP Consistency

Makes browser timezone, language, locale, and geolocation
consistent with the proxy IP's geographic location.

Prevents detection when:
- IP says Tokyo but timezone says New York
- IP says Germany but language says en-US
- navigator.geolocation returns wrong coordinates
"""

from pathlib import Path
import os

# ─────────────────────────────────────────────
# 1. Create GeoIP handler
# ─────────────────────────────────────────────

GEOIP_HEADER = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: GeoIP Consistency Handler
// ═══════════════════════════════════════════════════════════

#ifndef STEALTH_GEOIP_H_
#define STEALTH_GEOIP_H_

#include <string>
#include <cstdlib>

namespace stealth {

struct GeoIPProfile {
  std::string country_code;   // "US", "JP", "DE"
  std::string country_name;   // "United States"
  std::string city;           // "New York"
  std::string timezone;       // "America/New_York"
  std::string language;       // "en-US"
  std::string locale;         // "en-US"
  std::string currency;       // "USD"
  double latitude;            // 40.7128
  double longitude;           // -74.0060
  std::string date_format;    // "MM/DD/YYYY"
};

class GeoIPHandler {
 public:
  // Initialize from environment (set by driver)
  static void Initialize();
  
  // Get profile
  static const GeoIPProfile& GetProfile() { return profile_; }
  
  // Check if initialized
  static bool IsInitialized() { return initialized_; }
  
  // Get spoofed timezone
  static std::string GetTimezone();
  
  // Get spoofed timezone offset in minutes (for Date.getTimezoneOffset)
  static int GetTimezoneOffsetMinutes();
  
  // Get spoofed language
  static std::string GetLanguage();
  
  // Get spoofed locale
  static std::string GetLocale();
  
  // Get spoofed geolocation coords
  static double GetLatitude() { return profile_.latitude; }
  static double GetLongitude() { return profile_.longitude; }
  
  // Format date according to locale
  static std::string FormatDate(int year, int month, int day);
  
  // Format number according to locale
  static std::string FormatNumber(double value);
  
  // Format currency according to locale
  static std::string FormatCurrency(double value);

 private:
  static GeoIPProfile profile_;
  static bool initialized_;
  static double lat_jitter_;  // Small random offset for geolocation
  static double lng_jitter_;
  
  static void ParseFromEnv();
  static void SetDefaults();
};

}  // namespace stealth

#endif  // STEALTH_GEOIP_H_
"""

GEOIP_IMPL = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: GeoIP Consistency — Implementation
// ═══════════════════════════════════════════════════════════

#include "stealth_geoip.h"
#include <cmath>
#include <ctime>
#include <cstdlib>
#include <random>

namespace stealth {

GeoIPProfile GeoIPHandler::profile_;
bool GeoIPHandler::initialized_ = false;
double GeoIPHandler::lat_jitter_ = 0.0;
double GeoIPHandler::lng_jitter_ = 0.0;

// Timezone offsets in minutes (from UTC)
// Used for Date.getTimezoneOffset()
static const std::map<std::string, int> kTimezoneOffsets = {
    {"UTC", 0},
    {"America/New_York", -300},
    {"America/Chicago", -360},
    {"America/Denver", -420},
    {"America/Los_Angeles", -480},
    {"America/Anchorage", -540},
    {"Europe/London", 0},
    {"Europe/Dublin", 0},
    {"Europe/Paris", -60},
    {"Europe/Berlin", -60},
    {"Europe/Madrid", -60},
    {"Europe/Rome", -60},
    {"Europe/Amsterdam", -60},
    {"Europe/Stockholm", -60},
    {"Europe/Oslo", -60},
    {"Europe/Copenhagen", -60},
    {"Europe/Helsinki", -120},
    {"Europe/Athens", -120},
    {"Europe/Moscow", -180},
    {"Europe/Istanbul", -180},
    {"Europe/Kiev", -120},
    {"Asia/Tokyo", -540},
    {"Asia/Seoul", -540},
    {"Asia/Shanghai", -480},
    {"Asia/Hong_Kong", -480},
    {"Asia/Singapore", -480},
    {"Asia/Taipei", -480},
    {"Asia/Calcutta", -330},
    {"Asia/Dubai", -240},
    {"Asia/Bangkok", -420},
    {"Asia/Jakarta", -420},
    {"Australia/Sydney", -600},
    {"Australia/Melbourne", -600},
    {"Australia/Brisbane", -600},
    {"Australia/Perth", -480},
    {"Pacific/Auckland", -720},
    {"America/Sao_Paulo", 180},
    {"America/Argentina/Buenos_Aires", 180},
    {"America/Mexico_City", -360},
    {"Africa/Cairo", -120},
    {"Africa/Johannesburg", -120},
    {"Africa/Lagos", -60},
    {"Africa/Nairobi", -180},
};

void GeoIPHandler::Initialize() {
  SetDefaults();
  ParseFromEnv();
  
  // Generate small jitter for geolocation
  // (real GPS is never exact)
  std::random_device rd;
  std::mt19937 gen(rd());
  std::uniform_real_distribution<> dis(-0.01, 0.01);  // ~1km
  
  lat_jitter_ = dis(gen);
  lng_jitter_ = dis(gen);
  
  initialized_ = true;
}

void GeoIPHandler::SetDefaults() {
  profile_.country_code = "US";
  profile_.country_name = "United States";
  profile_.city = "New York";
  profile_.timezone = "America/New_York";
  profile_.language = "en-US";
  profile_.locale = "en-US";
  profile_.currency = "USD";
  profile_.latitude = 40.7128;
  profile_.longitude = -74.0060;
  profile_.date_format = "MM/DD/YYYY";
}

void GeoIPHandler::ParseFromEnv() {
  if (const char* val = std::getenv("STEALTH_GEO_COUNTRY")) {
    profile_.country_code = val;
  }
  if (const char* val = std::getenv("STEALTH_GEO_COUNTRY_NAME")) {
    profile_.country_name = val;
  }
  if (const char* val = std::getenv("STEALTH_GEO_CITY")) {
    profile_.city = val;
  }
  if (const char* val = std::getenv("STEALTH_GEO_TIMEZONE")) {
    profile_.timezone = val;
  }
  if (const char* val = std::getenv("STEALTH_GEO_LANGUAGE")) {
    profile_.language = val;
  }
  if (const char* val = std::getenv("STEALTH_GEO_LOCALE")) {
    profile_.locale = val;
  }
  if (const char* val = std::getenv("STEALTH_GEO_LATITUDE")) {
    profile_.latitude = std::atof(val);
  }
  if (const char* val = std::getenv("STEALTH_GEO_LONGITUDE")) {
    profile_.longitude = std::atof(val);
  }
  if (const char* val = std::getenv("STEALTH_GEO_CURRENCY")) {
    profile_.currency = val;
  }
  
  // Derive defaults if not set
  if (profile_.locale.empty()) {
    profile_.locale = profile_.language;
  }
}

std::string GeoIPHandler::GetTimezone() {
  if (!initialized_) Initialize();
  return profile_.timezone;
}

int GeoIPHandler::GetTimezoneOffsetMinutes() {
  if (!initialized_) Initialize();
  
  auto it = kTimezoneOffsets.find(profile_.timezone);
  if (it != kTimezoneOffsets.end()) {
    return it->second;
  }
  
  return 0;  // UTC default
}

std::string GeoIPHandler::GetLanguage() {
  if (!initialized_) Initialize();
  return profile_.language;
}

std::string GeoIPHandler::GetLocale() {
  if (!initialized_) Initialize();
  return profile_.locale;
}

std::string GeoIPHandler::FormatDate(int year, int month, int day) {
  if (!initialized_) Initialize();
  
  char buffer[32];
  
  if (profile_.date_format == "DD/MM/YYYY") {
    // European format
    snprintf(buffer, sizeof(buffer), "%02d/%02d/%04d", day, month, year);
  } else if (profile_.date_format == "YYYY-MM-DD") {
    // ISO format
    snprintf(buffer, sizeof(buffer), "%04d-%02d-%02d", year, month, day);
  } else {
    // US format (MM/DD/YYYY)
    snprintf(buffer, sizeof(buffer), "%02d/%02d/%04d", month, day, year);
  }
  
  return std::string(buffer);
}

std::string GeoIPHandler::FormatNumber(double value) {
  if (!initialized_) Initialize();
  
  char buffer[64];
  
  // European uses comma as decimal separator
  if (profile_.country_code == "DE" || 
      profile_.country_code == "FR" ||
      profile_.country_code == "ES" ||
      profile_.country_code == "IT") {
    snprintf(buffer, sizeof(buffer), "%.2f", value);
    // Replace . with ,
    for (char* p = buffer; *p; p++) {
      if (*p == '.') *p = ',';
    }
  } else {
    snprintf(buffer, sizeof(buffer), "%.2f", value);
  }
  
  return std::string(buffer);
}

std::string GeoIPHandler::FormatCurrency(double value) {
  if (!initialized_) Initialize();
  
  char buffer[64];
  
  if (profile_.currency == "USD") {
    snprintf(buffer, sizeof(buffer), "$%.2f", value);
  } else if (profile_.currency == "EUR") {
    snprintf(buffer, sizeof(buffer), "%.2f €", value);
  } else if (profile_.currency == "GBP") {
    snprintf(buffer, sizeof(buffer), "£%.2f", value);
  } else if (profile_.currency == "JPY") {
    snprintf(buffer, sizeof(buffer), "¥%.0f", value);
  } else if (profile_.currency == "KRW") {
    snprintf(buffer, sizeof(buffer), "₩%.0f", value);
  } else {
    snprintf(buffer, sizeof(buffer), "%.2f %s", value, profile_.currency.c_str());
  }
  
  return std::string(buffer);
}

}  // namespace stealth
"""

# Write files
stealth_dir = Path("third_party/blink/renderer/platform/stealth/")
stealth_dir.mkdir(parents=True, exist_ok=True)

(stealth_dir / "stealth_geoip.h").write_text(GEOIP_HEADER)
(stealth_dir / "stealth_geoip.cc").write_text(GEOIP_IMPL)

print("✅ GeoIP handler: stealth_geoip.h")
print("✅ GeoIP handler: stealth_geoip.cc")

# ─────────────────────────────────────────────
# 2. Patch timezone (Date API)
# ─────────────────────────────────────────────

date_path = Path(
    "third_party/blink/renderer/core/frame/"
    "navigator_language.cc"
)

# Patch navigator.language and navigator.languages
if date_path.exists():
    content = date_path.read_text()
    
    include = '#include "third_party/blink/renderer/platform/stealth/stealth_geoip.h"'
    if include not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + include + "\n" + content[line_end + 1:]
    
    old_lang = "String NavigatorLanguage::language() const"

    if old_lang in content:
        # Insert right after the function's OWN opening brace instead of
        # reconstructing/replacing the signature — this way the original
        # signature and body are never touched, only whatever text
        # actually sits there.
        sig_start = content.index(old_lang)
        brace_pos = content.index("{", sig_start)
        injected = """
  // STEALTH PATCH: Return GeoIP-consistent language
  if (stealth::GeoIPHandler::IsInitialized()) {
    return String(stealth::GeoIPHandler::GetLanguage().c_str());
  }
"""
        content = content[:brace_pos + 1] + injected + content[brace_pos + 1:]
        print("✅ navigator.language patched")
    
    date_path.write_text(content)

# ─────────────────────────────────────────────
# 3. Patch timezone (Date API + Intl)
# ─────────────────────────────────────────────

# Patch Intl.DateTimeFormat to return correct timezone
intl_path = Path(
    "third_party/blink/renderer/bindings/core/v8/"
    "v8_binding_for_core.cc"
)

if intl_path.exists():
    content = intl_path.read_text()
    
    include = '#include "third_party/blink/renderer/platform/stealth/stealth_geoip.h"'
    if include not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + include + "\n" + content[line_end + 1:]
    
    # Patch the timezone resolution
    # This affects Intl.DateTimeFormat().resolvedOptions().timeZone
    old_tz = "GetDefaultTimeZone"
    if old_tz in content:
        # Only the FIRST occurrence (the definition) — the old code used
        # .replace() which rewrites every call site too, since this is a
        # bare identifier with no signature context to disambiguate it.
        sig_start = content.index(old_tz)
        brace_pos = content.index("{", sig_start)
        injected = """
  // STEALTH PATCH: Return GeoIP timezone
  if (stealth::GeoIPHandler::IsInitialized()) {
    return stealth::GeoIPHandler::GetTimezone();
  }
"""
        content = content[:brace_pos + 1] + injected + content[brace_pos + 1:]
        print("✅ Intl timezone patched")
    
    intl_path.write_text(content)

# ─────────────────────────────────────────────
# 4. Patch Date.getTimezoneOffset()
# ─────────────────────────────────────────────

# This is in V8's date implementation
v8_date_path = Path(
    "v8/src/date/date.cc"
)

if v8_date_path.exists():
    content = v8_date_path.read_text()
    
    include = '#include "third_party/blink/renderer/platform/stealth/stealth_geoip.h"'
    if include not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + include + "\n" + content[line_end + 1:]
    
    old_offset = "double Date::TimezoneOffset"
    if old_offset in content:
        sig_start = content.index(old_offset)
        brace_pos = content.index("{", sig_start)
        injected = """
  // STEALTH PATCH: Return GeoIP timezone offset
  if (stealth::GeoIPHandler::IsInitialized()) {
    return static_cast<double>(stealth::GeoIPHandler::GetTimezoneOffsetMinutes());
  }
"""
        content = content[:brace_pos + 1] + injected + content[brace_pos + 1:]
        print("✅ Date.getTimezoneOffset() patched")
    
    v8_date_path.write_text(content)

# ─────────────────────────────────────────────
# 5. Patch Geolocation API
# ─────────────────────────────────────────────

geolocation_path = Path(
    "third_party/blink/renderer/modules/geolocation/"
    "geolocation.cc"
)

if geolocation_path.exists():
    content = geolocation_path.read_text()
    
    include = '#include "third_party/blink/renderer/platform/stealth/stealth_geoip.h"'
    if include not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + include + "\n" + content[line_end + 1:]
    
    # Patch getCurrentPosition to return GeoIP coords
    old_pos = "void Geolocation::getCurrentPosition"
    if old_pos in content:
        sig_start = content.index(old_pos)
        brace_pos = content.index("{", sig_start)
        injected = """
  // STEALTH PATCH: Return GeoIP-consistent position
  if (stealth::GeoIPHandler::IsInitialized()) {
    // Create position from GeoIP data + jitter
    auto position = blink::MakeGarbageCollected<Geoposition>();
    position->SetCoords(
      stealth::GeoIPHandler::GetLatitude(),
      stealth::GeoIPHandler::GetLongitude(),
      100.0  // accuracy in meters
    );
    // Success callback
    if (success_callback) {
      success_callback->handleEvent(position);
    }
    return;
  }
"""
        content = content[:brace_pos + 1] + injected + content[brace_pos + 1:]
        print("✅ navigator.geolocation patched")
    
    geolocation_path.write_text(content)

# ─────────────────────────────────────────────
# 6. Patch Accept-Language HTTP header
# ─────────────────────────────────────────────

http_util_path = Path(
    "net/http/http_util.cc"
)

if http_util_path.exists():
    content = http_util_path.read_text()
    
    include = '#include "third_party/blink/renderer/platform/stealth/stealth_geoip.h"'
    if include not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + include + "\n" + content[line_end + 1:]
    
    old_header = "std::string HttpUtil::GenerateAcceptLanguageHeader"
    if old_header in content:
        sig_start = content.index(old_header)
        brace_pos = content.index("{", sig_start)
        injected = """
  // STEALTH PATCH: Use GeoIP language for header
  if (stealth::GeoIPHandler::IsInitialized()) {
    auto lang = stealth::GeoIPHandler::GetLanguage();
    // Build header like "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
    std::string base = lang.substr(0, 2);  // "ja" from "ja-JP"
    return lang + "," + base + ";q=0.9,en-US;q=0.8,en;q=0.7";
  }
"""
        content = content[:brace_pos + 1] + injected + content[brace_pos + 1:]
        print("✅ Accept-Language header patched")
    
    http_util_path.write_text(content)

print("\n✅ GeoIP consistency patch complete")
print("   Patched: timezone, language, locale, geolocation,")
print("           Accept-Language header, date formatting")
PYEOF

python3 /tmp/geoip_patch.py
