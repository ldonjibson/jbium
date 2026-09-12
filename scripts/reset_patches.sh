#!/bin/bash
# ═════════════════════════════════════════════════════════════
# scripts/reset_patches.sh
# Restore all patch-touched Chromium files to pristine, then
# re-apply the current (fixed) patch set.
#
# Why this exists: the build tree was previously patched by an
# older, broken version of the apply.sh scripts (naive signature
# replacement producing invalid C++: _original free functions
# with const qualifiers, stray braces, dangling if(false){ bodies,
# and renderer_main_frame.cc overwritten with a stub). The fixed
# scripts skip already-patched files, so re-running them alone
# cannot repair a tree mangled by the old versions. This script
# git-restores every file any patch touches, removes the stealth
# helper headers, and re-applies everything cleanly.
# ═════════════════════════════════════════════════════════════

set -euo pipefail

CHROMIUM_SRC="${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"
PATCHES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/patches"

if [ ! -d "$CHROMIUM_SRC" ]; then
    echo "❌ Chromium source not found at $CHROMIUM_SRC"
    echo "   Set CHROMIUM_SRC to your checkout path."
    exit 1
fi

cd "$CHROMIUM_SRC"

# ─────────────────────────────────────────────
# Every file/version any patch script touches.
# Keep in sync with patches/*/apply.sh.
# ─────────────────────────────────────────────
TOUCHED_FILES=(
    # 001_automation
    "third_party/blink/renderer/core/frame/navigator.cc"
    "chrome/browser/ui/startup/automation_infobar_delegate.cc"
    "content/renderer/renderer_main_frame.cc"   # old patch overwrote it

    # 002_cdp — verification only, no source edits

    # 004_canvas
    "third_party/blink/renderer/modules/canvas/canvas2d/canvas_rendering_context_2d.cc"

    # 005_webgl
    "third_party/blink/renderer/modules/webgl/webgl_rendering_context_base.cc"
    "third_party/blink/renderer/modules/webgl/webgl2_rendering_context_base.cc"

    # 006_fonts — verification only, no source edits

    # 007_navigator
    "third_party/blink/renderer/core/frame/navigator_id.cc"
    "third_party/blink/renderer/core/frame/navigator_base.cc"
    "third_party/blink/renderer/core/frame/navigator_concurrent_hardware.cc"
    "third_party/blink/renderer/core/frame/navigator_device_memory.cc"
    "third_party/blink/renderer/core/frame/navigator_max_touch_points.cc"
    "third_party/blink/renderer/modules/navigatorcontentutils/navigator_content_utils.cc"  # legacy path, skip if absent
    "third_party/blink/renderer/core/frame/navigator_ua_data.cc"
    "third_party/blink/renderer/core/frame/navigator_ua_data.h"

    # 008_geoip
    "third_party/blink/renderer/core/frame/navigator_language.cc"
    "net/http/http_util.cc"
    # old broken 008 also touched these; restore them too
    "third_party/blink/renderer/modules/geolocation/geolocation.cc"
    "v8/src/date/date.cc"
    "third_party/blink/renderer/bindings/core/v8/v8_binding_for_core.cc"

    # 009_plugins
    "third_party/blink/renderer/modules/plugins/dom_plugin_array.cc"
    "third_party/blink/renderer/core/frame/dom_mime_type_array.cc"

    # 010_misc
    "third_party/blink/renderer/modules/battery/battery_manager.cc"
    "third_party/blink/renderer/core/html/media/html_media_element.cc"
)

restored=0
missing=0
for f in "${TOUCHED_FILES[@]}"; do
    if [ -e "$f" ]; then
        git checkout -- "$f" 2>/dev/null || {
            echo "⚠️  could not restore $f (not git-tracked?)"
            continue
        }
        restored=$((restored + 1))
    else
        missing=$((missing + 1))
    fi
done
echo "✅ Restored $restored patched file(s) to pristine ($missing not present in this tree — fine)"

# ─────────────────────────────────────────────
# Remove stealth helper headers (they are rewritten by the
# current patch scripts, but drop any stale ones first).
# ─────────────────────────────────────────────
STEALTH_DIR="third_party/blink/renderer/platform/stealth"
if [ -d "$STEALTH_DIR" ]; then
    find "$STEALTH_DIR" -type f -delete
    echo "✅ Cleared $STEALTH_DIR (stale headers removed)"
fi

# ─────────────────────────────────────────────
# Re-apply the current patch set.
# ─────────────────────────────────────────────
echo ""
echo "── Re-applying patches from $PATCHES_DIR ──"
bash "$PATCHES_DIR/apply_all.sh"

echo ""
echo "✅ Reset complete: pristine sources + current patches"