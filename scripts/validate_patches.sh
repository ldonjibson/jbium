#!/bin/bash
# ═════════════════════════════════════════════════════════════
# Validate that all patches were applied cleanly
#
# Markers below match the CURRENT patch architecture
# (patches/001-010/apply.sh): body replacements of real functions
# plus header-only stealth helpers under
# third_party/blink/renderer/platform/stealth/.
# ═════════════════════════════════════════════════════════════

set -euo pipefail

CHROMIUM_SRC="${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"

if [ ! -d "$CHROMIUM_SRC" ]; then
    echo "❌ Chromium source not found at: $CHROMIUM_SRC"
    echo "   Set CHROMIUM_SRC to your checkout path."
    exit 1
fi

cd "$CHROMIUM_SRC"

echo "══════════════════════════════════════════════════════════"
echo "  Validating Stealth Patches"
echo "══════════════════════════════════════════════════════════"
echo ""

PASS=0
FAIL=0
WARN=0

# ─────────────────────────────────────────────
check_patch() {
    # name | file | grep pattern | required (yes/no)
    local name="$1"
    local file="$2"
    local grep_pattern="$3"
    local required="${4:-yes}"

    if [ ! -f "$file" ]; then
        if [ "$required" = "no" ]; then
            echo "  ⏭️  $name: $file not in this tree (optional)"
        else
            echo "  ❌ $name: File not found: $file"
            ((FAIL++))
        fi
        return
    fi

    if grep -q "$grep_pattern" "$file" 2>/dev/null; then
        echo "  ✅ $name"
        ((PASS++))
    else
        echo "  ⚠️  $name: marker '$grep_pattern' not found in $file"
        ((WARN++))
    fi
}

check_header() {
    local name="$1"
    local file="$2"
    if [ -f "$file" ]; then
        echo "  ✅ $name"
        ((PASS++))
    else
        echo "  ❌ $name: $file not found"
        ((FAIL++))
    fi
}

# ─────────────────────────────────────────────
echo "001: Automation Hiding"
check_patch "001 navigator.webdriver = false" \
    "third_party/blink/renderer/core/frame/navigator.cc" \
    "STEALTH PATCH"
check_patch "001 automation infobar suppressed" \
    "chrome/browser/ui/startup/automation_infobar_delegate.cc" \
    "STEALTH PATCH"

echo ""
echo "002: CDP Traces — verification-only patch (no source markers)"

echo ""
echo "003: TLS Fingerprint"
check_patch "003 TLS" \
    "net/ssl/ssl_config.cc" \
    "STEALTH"

echo ""
echo "004: Canvas Noise"
check_header "004 stealth_canvas_noise.h" \
    "third_party/blink/renderer/platform/stealth/stealth_canvas_noise.h"
check_patch "004 GetImage() readback wrapped" \
    "third_party/blink/renderer/modules/canvas/canvas2d/canvas_rendering_context_2d.cc" \
    "stealth::CanvasNoise"

echo ""
echo "005: WebGL Spoofing"
check_header "005 stealth_webgl.h" \
    "third_party/blink/renderer/platform/stealth/stealth_webgl.h"
check_patch "005 WebGL1 GPU strings wrapped" \
    "third_party/blink/renderer/modules/webgl/webgl_rendering_context_base.cc" \
    "stealth::GPUSpoof"
check_patch "005 WebGL2 GPU strings wrapped" \
    "third_party/blink/renderer/modules/webgl/webgl2_rendering_context_base.cc" \
    "stealth::GPUSpoof"

echo ""
echo "006: Fonts — verification-only patch (defense = bundled fonts + fontconfig)"

echo ""
echo "007: Navigator Spoofing"
check_header "007 stealth_navigator.h" \
    "third_party/blink/renderer/platform/stealth/stealth_navigator.h"
check_patch "007 NavigatorBase::platform" \
    "third_party/blink/renderer/core/frame/navigator_base.cc" \
    "STEALTH PATCH"
check_patch "007 hardwareConcurrency" \
    "third_party/blink/renderer/core/frame/navigator_concurrent_hardware.cc" \
    "STEALTH PATCH"
check_patch "007 deviceMemory" \
    "third_party/blink/renderer/core/frame/navigator_device_memory.cc" \
    "STEALTH PATCH"
check_patch "007 UA-CH brands/platform" \
    "third_party/blink/renderer/core/frame/navigator_ua_data.cc" \
    "STEALTH PATCH"

echo ""
echo "008: GeoIP Consistency"
check_patch "008 navigator.languages" \
    "third_party/blink/renderer/core/frame/navigator_language.cc" \
    "STEALTH PATCH"
check_patch "008 Accept-Language header" \
    "net/http/http_util.cc" \
    "STEALTH PATCH"

echo ""
echo "009: Plugin Consistency"
check_patch "009 DOMPluginArray::length pinned" \
    "third_party/blink/renderer/modules/plugins/dom_plugin_array.cc" \
    "STEALTH PATCH"

echo ""
echo "010: Misc (Battery, WebRTC, Media)"
check_header "010 stealth_battery.h" \
    "third_party/blink/renderer/platform/stealth/stealth_battery.h"
check_patch "010 battery getters spoofed" \
    "third_party/blink/renderer/modules/battery/battery_manager.cc" \
    "stealth::BatterySpoof"

echo ""
echo "011: AudioContext Noise — helper-only, not wired up (expected)"
check_header "011 stealth_audio_noise.h" \
    "third_party/blink/renderer/platform/stealth/stealth_audio_noise.h"
echo "  ℹ️  No source file check here on purpose: nothing consumes this"
echo "     header yet — see patches/011_audio/apply.sh for why."

# ─────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════"
echo "  Validation Results"
echo "══════════════════════════════════════════════════════════"
echo "  Passed:    $PASS"
echo "  Warnings:  $WARN"
echo "  Failed:    $FAIL"
echo "══════════════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "  ❌ Some patches failed validation."
    echo "  Run: bash scripts/reset_patches.sh   # restore + re-apply"
    exit 1
fi
