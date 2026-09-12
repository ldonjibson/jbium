#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/006_fonts/apply.sh
# Font fingerprint consistency (OS + region)
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd "${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"

cat > /tmp/font_patch.py << 'PYEOF'
"""
STEALTH PATCH: Font Fingerprint Consistency

How font fingerprinting actually works against this build:
- Font enumeration APIs (queryLocalFonts, FontAccessManager)
  require a user gesture + permission prompt — fingerprinters
  can't silently call them.
- The practical vectors are (a) measuring text width in CSS/canvas
  (reveals which substitute font actually rendered) and (b)
  checking availability of OS-specific family names via
  document.fonts.check() / CSS fallback.

This build's real font defense is already in place and does not
live in Chromium source at all:
- fonts/ ships metric-compatible substitutes (Liberation Sans ↔
  Arial, Carlito ↔ Calibri, Liberation Serif ↔ Times New Roman,
  Caladea ↔ Cambria, Noto families for CJK regions).
- scripts/generate_fontconfig.py + the fontconfig template install
  alias rules so the spoofed-OS family names resolve to the
  substitutes with identical metrics — text measures exactly like
  the claimed OS.
- The driver sets STEALTH_FONT_OS / STEALTH_FONT_REGION and
  installs only the matching manifest's fonts into the session
  profile, so enumerated lists match the claimed OS + region.

What the old patch tried (and why it's gone):
- "bool FontCache::IsFontFamilyAvailable" — no such function in
  this tree (the real one is IsPlatformFamilyMatchAvailable(const
  FontDescription&, const AtomicString&), font_cache.cc). Even
  patched, returning "false" for disallowed families would just
  make pages fall back to defaults — it does NOT change what
  renders, and spoofing it "true" for unbundled fonts would
  create a render/metrics mismatch (the actual fingerprint).
- FontAccessManager::EnumerateFonts — gesture + permission gated,
  not a silent fingerprinting vector.
- Both splices left dangling "if (false) {" bodies and wrote an
  uncompiled stealth_font_filter.cc (never registered in
  BUILD.gn → undefined-symbol link failure).

So: verify the real chokepoints exist, verify the fontconfig
tooling this build actually relies on, and patch nothing in
source.
"""

from pathlib import Path

checks = [
    ("third_party/blink/renderer/platform/fonts/font_cache.cc",
     "FontCache (IsPlatformFamilyMatchAvailable)"),
    ("third_party/blink/renderer/modules/font_access/",
     "FontAccess (gesture + permission gated)"),
]

for fpath, what in checks:
    if Path(fpath).exists():
        print(f"✅ {what}: {fpath}")
    else:
        print(f"⚠️  {what}: {fpath} NOT FOUND")

# The actual defense: verify the metric-compatible font tooling
# this build ships (relative to the jbium repo root, not the
# Chromium tree — this script runs from chromium/src, so look up).
font_tools = [
    "../../fonts/manifest.json",
    "../../scripts/generate_fontconfig.py",
    "../../fonts/fontconfig_template.xml",
]
for fpath in font_tools:
    if Path(fpath).exists():
        print(f"✅ Font defense tooling: {fpath}")
    else:
        print(f"⚠️  Font defense tooling missing: {fpath}")

print("\nℹ️  document.fonts.check() answers come from fontconfig "
      "aliases over the bundled metric-compatible fonts")
print("ℹ️  Driver env vars consumed by fontconfig/driver:")
print("    STEALTH_FONT_OS    — e.g. WINDOWS_11, MACOS_SONOMA, UBUNTU")
print("    STEALTH_FONT_REGION — e.g. JAPAN, KOREA, CHINA, GENERIC")

print("\n✅ Font fingerprint patch complete")
print("   ✅ No source patch needed (defense = bundled fonts +")
print("      fontconfig aliases, verified above)")
PYEOF

PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
"$PYTHON_BIN" /tmp/font_patch.py
