#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Validate that all patches were applied cleanly
# ═══════════════════════════════════════════════════════════

set -euo pipefail

CHROMIUM_SRC="${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"

if [ ! -d "$CHROMIUM_SRC" ]; then
    echo "❌ Chromium source not found at: $CHROMIUM_SRC"
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
    local name="$1"
    local file="$2"
    local grep_pattern="$3"
    
    if [ ! -f "$file" ]; then
        echo "  ❌ $name: File not found: $file"
        ((FAIL++))
        return
    fi
    
    if grep -q "$grep_pattern" "$file" 2>/dev/null; then
        echo "  ✅ $name"
        ((PASS++))
    else
        echo "  ⚠️  $name: Patch marker not found in $file"
        ((WARN++))
    fi
}

# ─────────────────────────────────────────────
echo "001: Automation Detection"
check_patch "001_automation" \
    "content/renderer/renderer_main_frame.cc" \
    "STEALTH"

echo ""
echo "002: CDP Traces"
check_patch "002_cdp" \
    "content/browser/devtools/protocol/runtime_handler.cc" \
    "STEALTH"

echo ""
echo "003: TLS Fingerprint"
check_patch "003_tls" \
    "net/ssl/ssl_config.cc" \
    "STEALTH"

echo ""
echo "004: Canvas Noise"
if [ -f "third_party/blink/renderer/platform/stealth/stealth_canvas_noise.h" ]; then
    echo "  ✅ 004_canvas"
    ((PASS++))
else
    echo "  ❌ 004_canvas: stealth_canvas_noise.h not found"
    ((FAIL++))
fi

echo ""
echo "005: WebGL Spoofing"
check_patch "005_webgl" \
    "third_party/blink/renderer/modules/webgl/webgl_rendering_context_base.cc" \
    "STEALTH"

echo ""
echo "006: Font Filtering"
if [ -f "third_party/blink/renderer/platform/stealth/stealth_font_filter.h" ]; then
    echo "  ✅ 006_fonts"
    ((PASS++))
else
    echo "  ❌ 006_fonts: stealth_font_filter.h not found"
    ((FAIL++))
fi

echo ""
echo "007: Navigator Spoofing"
if [ -f "third_party/blink/renderer/platform/stealth/stealth_navigator.h" ]; then
    echo "  ✅ 007_navigator"
    ((PASS++))
else
    echo "  ❌ 007_navigator: stealth_navigator.h not found"
    ((FAIL++))
fi

echo ""
echo "008: GeoIP Consistency"
if [ -f "third_party/blink/renderer/platform/stealth/stealth_geoip.h" ]; then
    echo "  ✅ 008_geoip"
    ((PASS++))
else
    echo "  ❌ 008_geoip: stealth_geoip.h not found"
    ((FAIL++))
fi

echo ""
echo "009: Plugin Consistency"
check_patch "009_plugins" \
    "third_party/blink/renderer/modules/plugins/dom_plugin_array.cc" \
    "STEALTH"

echo ""
echo "010: Misc (WebRTC, Battery, Media)"
check_patch "010_misc" \
    "third_party/blink/renderer/modules/peerconnection/rtc_peer_connection.cc" \
    "STEALTH"

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
    echo "  Run: bash patches/apply_all.sh"
    exit 1
fi
