#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/007_navigator/apply.sh
# Spoofs navigator.platform, hardwareConcurrency, deviceMemory,
# maxTouchPoints (where present) and User-Agent Client Hints.
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd "${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"

cat > /tmp/navigator_patch.py << 'PYEOF'
"""
STEALTH PATCH: Navigator Property Spoofing

Spoofs:
- navigator.platform            (NavigatorID mixin AND the
                                  NavigatorBase::platform() override
                                  that desktop JS actually reaches)
- navigator.hardwareConcurrency (NavigatorConcurrentHardware mixin)
- navigator.deviceMemory         (NavigatorDeviceMemory mixin)
- navigator.maxTouchPoints       (NavigatorEvents::maxTouchPoints,
                                  core/events/navigator_events.cc —
                                  the getter, per its IDL's
                                  [ImplementedAs=NavigatorEvents])
- User-Agent Client Hints        (brands / fullVersionList / platform /
                                  platformVersion / architecture /
                                  model / bitness / uaFullVersion)

Design notes:

1. Header-only state. The spoof state lives in function-local
   base::NoDestructor statics inside stealth_navigator.h. There is no
   stealth_navigator.cc on purpose: the patched files belong to
   existing build targets, and new .cc files would require BUILD.gn
   edits (and otherwise produce undefined-symbol errors at link
   time). NoDestructor also keeps -Wglobal-constructors and
   -Wexit-time-destructors silent under -Werror. Function-local statics
   inside inline functions are ODR-merged, so every translation unit
   shares one profile.

2. Effective targets. navigator.platform is served by
   NavigatorBase::platform() on desktop (Navigator::platform() and
   WorkerNavigator both funnel through it), so spoofing only the
   NavigatorID mixin would be dead code. Both are patched.

3. Client hints are spoofed at the Set*() boundary the embedder
   uses to populate the object, so brands(), platform(),
   getHighEntropyValues() and toJSON() all stay consistent without
   touching their bodies. getHighEntropyValues() therefore needs no
   patch at all.
"""

from pathlib import Path

STEALTH_INCLUDE = (
    '#include "third_party/blink/renderer/platform/stealth/'
    'stealth_navigator.h"'
)

# ─────────────────────────────────────────────
# 1. Header-only navigator spoof state
# ─────────────────────────────────────────────

NAV_HEADER = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: Navigator Spoofing (header-only)
// ═══════════════════════════════════════════════════════════
//
// Header-only by design: call sites live in targets that already
// exist in the build graph, so no BUILD.gn changes are needed.
// All state is held in function-local base::NoDestructor statics,
// which avoids -Wglobal-constructors and -Wexit-time-destructors
// under -Werror. Function-local statics inside inline functions
// are ODR-merged, so every translation unit shares one profile.

#ifndef STEALTH_NAVIGATOR_H_
#define STEALTH_NAVIGATOR_H_

#include <algorithm>
#include <cstdlib>
#include <string>
#include <utility>
#include <vector>

#include "base/no_destructor.h"

namespace stealth {

struct NavigatorProfile {
  // Hardware
  int hardware_concurrency = 8;  // navigator.hardwareConcurrency
  double device_memory = 8.0;    // navigator.deviceMemory (GB)
  std::string platform = "Win32";  // navigator.platform
  int max_touch_points = 0;      // navigator.maxTouchPoints

  // User-Agent Client Hints (high entropy)
  std::string ua_platform = "Windows";        // "Windows", "macOS", "Linux"
  std::string ua_platform_version = "15.0.0";
  std::string ua_architecture = "x86";
  std::string ua_bitness = "64";
  std::string ua_model;  // "" (desktop)
};

using BrandEntry = std::pair<std::string, std::string>;
using BrandList = std::vector<BrandEntry>;

class NavigatorSpoof {
 public:
  // Session profile (initialized once, on first use, from the
  // environment the jbium driver sets before launch).
  static const NavigatorProfile& GetProfile() {
    static const base::NoDestructor<NavigatorProfile> profile(MakeProfile());
    return *profile;
  }

  static int GetHardwareConcurrency() {
    return GetProfile().hardware_concurrency;
  }

  static double GetDeviceMemory() {
    return GetProfile().device_memory;
  }

  static const std::string& GetPlatform() { return GetProfile().platform; }

  static int GetMaxTouchPoints() { return GetProfile().max_touch_points; }

  // navigator.userAgentData.brands — "major" brand versions. Defaults
  // mirror a stock Chrome install so the brand list stays consistent
  // with the --user-agent string the driver passes. Override with
  // STEALTH_UA_BRANDS="Name=8|Chromium=120|Google Chrome=120".
  static const BrandList& GetBrandEntries() {
    static const base::NoDestructor<BrandList> brands(ParseBrandList(
        std::getenv("STEALTH_UA_BRANDS"),
        {{"Not_A Brand", "8"},
         {"Chromium", "120"},
         {"Google Chrome", "120"}}));
    return *brands;
  }

  // Same list with full versions (ch-ua-full-version-list).
  static const BrandList& GetFullBrandEntries() {
    static const base::NoDestructor<BrandList> brands(ParseBrandList(
        std::getenv("STEALTH_UA_FULL_BRANDS"),
        {{"Not_A Brand", "8.0.0.0"},
         {"Chromium", "120.0.6099.109"},
         {"Google Chrome", "120.0.6099.109"}}));
    return *brands;
  }

 private:
  static NavigatorProfile MakeProfile() {
    NavigatorProfile p;
    if (const char* val = std::getenv("STEALTH_CPU_CORES")) {
      // Clamp to a realistic range (1-128).
      p.hardware_concurrency = std::clamp(std::atoi(val), 1, 128);
    }
    if (const char* val = std::getenv("STEALTH_DEVICE_MEMORY")) {
      // navigator.deviceMemory is capped at 8 in stock Chrome.
      p.device_memory = std::min(std::atof(val), 8.0);
    }
    if (const char* val = std::getenv("STEALTH_PLATFORM")) {
      if (*val) {
        p.platform = val;
      }
    }
    if (const char* val = std::getenv("STEALTH_MAX_TOUCH_POINTS")) {
      p.max_touch_points = std::atoi(val);
    }
    if (const char* val = std::getenv("STEALTH_UA_PLATFORM")) {
      if (*val) {
        p.ua_platform = val;
      }
    }
    if (const char* val = std::getenv("STEALTH_UA_PLATFORM_VERSION")) {
      if (*val) {
        p.ua_platform_version = val;
      }
    }
    if (const char* val = std::getenv("STEALTH_UA_ARCHITECTURE")) {
      if (*val) {
        p.ua_architecture = val;
      }
    }
    if (const char* val = std::getenv("STEALTH_UA_BITNESS")) {
      if (*val) {
        p.ua_bitness = val;
      }
    }
    if (const char* val = std::getenv("STEALTH_UA_MODEL")) {
      p.ua_model = val;
    }

    // Platform-consistent defaults when only the platform name is set.
    if (p.ua_platform == "Windows") {
      if (p.platform.empty() || p.platform == "auto") {
        p.platform = "Win32";
      }
    } else if (p.ua_platform == "macOS") {
      if (p.platform.empty() || p.platform == "auto") {
        p.platform = "MacIntel";
      }
      if (p.ua_architecture.empty()) {
        p.ua_architecture = "arm";
      }
    } else if (p.ua_platform == "Linux") {
      if (p.platform.empty() || p.platform == "auto") {
        p.platform = "Linux x86_64";
      }
    }
    return p;
  }

  static BrandList ParseBrandList(const char* env_value, BrandList fallback) {
    if (!env_value || !*env_value) {
      return fallback;
    }
    BrandList result;
    const std::string spec(env_value);
    size_t start = 0;
    while (true) {
      const size_t bar = spec.find('|', start);
      const std::string item = spec.substr(
          start, (bar == std::string::npos ? spec.size() : bar) - start);
      const size_t eq = item.find('=');
      if (eq != std::string::npos && eq + 1 < item.size()) {
        result.emplace_back(item.substr(0, eq), item.substr(eq + 1));
      }
      if (bar == std::string::npos) {
        break;
      }
      start = bar + 1;
    }
    return result.empty() ? fallback : result;
  }
};

}  // namespace stealth

#endif  // STEALTH_NAVIGATOR_H_
"""

stealth_dir = Path("third_party/blink/renderer/platform/stealth/")
stealth_dir.mkdir(parents=True, exist_ok=True)
(stealth_dir / "stealth_navigator.h").write_text(NAV_HEADER)
# NOTE: no stealth_navigator.cc anymore — see design notes above.
print("✅ Navigator spoof: stealth_navigator.h (header-only)")

# ─────────────────────────────────────────────
# Helpers: brace-aware source patching
#
# Naive str.replace() on a function *signature* leaves the original
# body dangling under a renamed, non-member "_original" signature
# (invalid C++, and -Wunreachable-code-aggressive/-Werror rejects
# dead code besides). These helpers instead find the real matching
# brace so a whole function body can be replaced cleanly, even when
# the signature spans multiple lines.
# ─────────────────────────────────────────────

def _find_body_open_brace(content, marker):
    """Return the index of the '{' that opens the function body whose
    signature contains `marker`, skipping the parameter list first so
    multi-line signatures work."""
    idx = content.find(marker)
    if idx == -1:
        return -1
    paren_idx = content.find("(", idx)
    if paren_idx == -1:
        return -1
    depth = 0
    i = paren_idx
    n = len(content)
    while i < n:
        c = content[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                i += 1
                break
        i += 1
    while i < n and content[i] != "{":
        i += 1
    return i if i < n else -1


def replace_function_body(content, marker, new_body):
    """Replace the entire body of the function identified by `marker`
    with `new_body`, discarding the original body via brace matching."""
    brace_idx = _find_body_open_brace(content, marker)
    if brace_idx == -1:
        return content, False
    depth = 0
    i = brace_idx
    n = len(content)
    while i < n:
        c = content[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                i += 1
                break
        i += 1
    new_content = content[:brace_idx] + "{\n" + new_body + "\n}" + content[i:]
    return new_content, True


def add_include(content, include):
    if include in content:
        return content
    last_include = content.rfind("#include")
    line_end = content.find("\n", last_include)
    return content[:line_end + 1] + include + "\n" + content[line_end + 1:]


def patch_bodies(rel_path, include, replacements, note):
    """Apply several whole-body replacements to one file.

    replacements: list of (marker, new_body) tuples.
    """
    path = Path(rel_path)
    if not path.exists():
        print(f"⚠️  {rel_path} not found — skipped ({note})")
        return
    content = path.read_text()
    if "STEALTH PATCH" in content:
        print(f"⏭️  {rel_path} already patched — skipped")
        return
    content = add_include(content, include)
    applied = 0
    for marker, new_body in replacements:
        content, ok = replace_function_body(content, marker, new_body)
        if ok:
            applied += 1
        else:
            print(f"⚠️  {rel_path}: marker not found: {marker.strip()}")
    if applied:
        path.write_text(content)
        print(f"✅ {rel_path}: {applied}/{len(replacements)} targets patched")
    else:
        print(f"⚠️  {rel_path}: nothing patched ({note})")


# ─────────────────────────────────────────────
# 2. navigator.platform
#
# NavigatorID::platform() is the mixin fallback, but desktop JS reads
# go through NavigatorBase::platform() (Navigator::platform() and
# WorkerNavigator both delegate to it), so both must be patched.
# ─────────────────────────────────────────────

patch_bodies(
    "third_party/blink/renderer/core/frame/navigator_id.cc",
    STEALTH_INCLUDE,
    [(
        "String NavigatorID::platform() const",
        "  // STEALTH PATCH: navigator.platform — session-profile value.\n"
        "  return String::FromUtf8(stealth::NavigatorSpoof::GetPlatform());",
    )],
    "platform mixin",
)

patch_bodies(
    "third_party/blink/renderer/core/execution_context/navigator_base.cc",
    '#include <cstdlib>',
    [(
        "String NavigatorBase::platform() const",
        "  // STEALTH PATCH: navigator.platform for both window and worker\n"
        "  // navigators — this override is the one JavaScript actually\n"
        "  // reaches. Fall back to the native reduced-platform value\n"
        "  // when no spoof is configured.\n"
        "  const char* spoofed = std::getenv(\"STEALTH_PLATFORM\");\n"
        "  if (spoofed && *spoofed) {\n"
        "    return String::FromUtf8(spoofed);\n"
        "  }\n"
        "  return GetReducedNavigatorPlatform();",
    )],
    "platform override actually reached by JS",
)

# ─────────────────────────────────────────────
# 3. navigator.hardwareConcurrency / deviceMemory
# ─────────────────────────────────────────────

patch_bodies(
    "third_party/blink/renderer/core/frame/navigator_concurrent_hardware.cc",
    STEALTH_INCLUDE,
    [(
        "unsigned NavigatorConcurrentHardware::hardwareConcurrency() const",
        "  // STEALTH PATCH: navigator.hardwareConcurrency —\n"
        "  // session-profile core count.\n"
        "  return static_cast<unsigned>(\n"
        "      stealth::NavigatorSpoof::GetHardwareConcurrency());",
    )],
    "hardwareConcurrency",
)

patch_bodies(
    "third_party/blink/renderer/core/frame/navigator_device_memory.cc",
    STEALTH_INCLUDE,
    [(
        "float NavigatorDeviceMemory::deviceMemory() const",
        "  // STEALTH PATCH: navigator.deviceMemory — session-profile\n"
        "  // value in GB, capped at 8 exactly like stock Chrome.\n"
        "  return static_cast<float>(stealth::NavigatorSpoof::GetDeviceMemory());",
    )],
    "deviceMemory",
)

# ─────────────────────────────────────────────
# 4. navigator.maxTouchPoints
#
# IDL says [ImplementedAs=NavigatorEvents] — the getter lives in
# navigator_events.cc (core/events/), not a dedicated
# navigator_max_touch_points.cc file. Verified against the actually
# pinned Chromium tree; confirmed present there as:
#   int32_t NavigatorEvents::maxTouchPoints(Navigator& navigator)
# ─────────────────────────────────────────────

patch_bodies(
    "third_party/blink/renderer/core/events/navigator_events.cc",
    STEALTH_INCLUDE,
    [(
        "int32_t NavigatorEvents::maxTouchPoints(Navigator& navigator)",
        "  // STEALTH PATCH: navigator.maxTouchPoints —\n"
        "  // session-profile touch support.\n"
        "  (void)navigator;\n"
        "  return stealth::NavigatorSpoof::GetMaxTouchPoints();",
    )],
    "maxTouchPoints",
)

# ─────────────────────────────────────────────
# 5. User-Agent Client Hints
#
# Spoofed at the Set*() boundary the embedder uses to populate
# navigator.userAgentData. Every reader (brands(), platform(),
# getHighEntropyValues(), toJSON()) then serves the spoofed data
# with no further patches, and getHighEntropyValues() itself keeps
# its original, valid body.
# ─────────────────────────────────────────────

PROLOGUE = (
    "  // STEALTH PATCH: session-profile value (see stealth_navigator.h).\n"
    "  const auto& profile = stealth::NavigatorSpoof::GetProfile();\n"
)

patch_bodies(
    "third_party/blink/renderer/core/frame/navigator_ua_data.cc",
    STEALTH_INCLUDE,
    [
        (
            "NavigatorUAData::SetBrandVersionList",
            "  // STEALTH PATCH: install the profile's brand list so\n"
            "  // navigator.userAgentData.brands matches the spoofed\n"
            "  // --user-agent string; fall back to the embedder's list\n"
            "  // when no profile is configured.\n"
            "  const auto& spoofed = stealth::NavigatorSpoof::GetBrandEntries();\n"
            "  if (!spoofed.empty()) {\n"
            "    for (const auto& entry : spoofed) {\n"
            "      AddBrandVersion(String::FromUtf8(entry.first),\n"
            "                      String::FromUtf8(entry.second));\n"
            "    }\n"
            "    return;\n"
            "  }\n"
            "  for (const auto& brand_version : brand_version_list) {\n"
            "    AddBrandVersion(String::FromUtf8(brand_version.brand),\n"
            "                    String::FromUtf8(brand_version.version));\n"
            "  }",
        ),
        (
            "NavigatorUAData::SetFullVersionList",
            "  // STEALTH PATCH: same as SetBrandVersionList, for the\n"
            "  // full (major.minor.build.patch) brand versions returned\n"
            "  // by getHighEntropyValues(['fullVersionList']).\n"
            "  const auto& spoofed =\n"
            "      stealth::NavigatorSpoof::GetFullBrandEntries();\n"
            "  if (!spoofed.empty()) {\n"
            "    for (const auto& entry : spoofed) {\n"
            "      AddBrandFullVersion(String::FromUtf8(entry.first),\n"
            "                          String::FromUtf8(entry.second));\n"
            "    }\n"
            "    return;\n"
            "  }\n"
            "  for (const auto& brand_version : full_version_list) {\n"
            "    AddBrandFullVersion(String::FromUtf8(brand_version.brand),\n"
            "                        String::FromUtf8(brand_version.version));\n"
            "  }",
        ),
        (
            "NavigatorUAData::SetPlatform",
            PROLOGUE
            + "  platform_ = String::FromUtf8(profile.ua_platform);\n"
            "  platform_version_ =\n"
            "      String::FromUtf8(profile.ua_platform_version);",
        ),
        (
            "NavigatorUAData::SetArchitecture",
            PROLOGUE + "  architecture_ = String::FromUtf8(profile.ua_architecture);",
        ),
        (
            "NavigatorUAData::SetModel",
            PROLOGUE + "  model_ = String::FromUtf8(profile.ua_model);",
        ),
        (
            "NavigatorUAData::SetUAFullVersion",
            "  // STEALTH PATCH: derive the full version from the profile's\n"
            "  // brand list so it matches the spoofed --user-agent string.\n"
            "  const auto& full = stealth::NavigatorSpoof::GetFullBrandEntries();\n"
            "  ua_full_version_ = full.empty()\n"
            "                           ? ua_full_version\n"
            "                           : String::FromUtf8(full.back().second);",
        ),
        (
            "NavigatorUAData::SetBitness",
            PROLOGUE + "  bitness_ = String::FromUtf8(profile.ua_bitness);",
        ),
    ],
    "User-Agent Client Hints",
)

print("\n✅ Navigator spoofing patch complete")
print("   Spoofed: platform, hardwareConcurrency, deviceMemory,")
print("           maxTouchPoints, UA Client Hints")
PYEOF

PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
"$PYTHON_BIN" /tmp/navigator_patch.py
