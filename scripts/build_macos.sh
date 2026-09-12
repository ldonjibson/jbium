#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Build Jbium on macOS
# Requires: macOS 13+, Xcode 15+, Python 3.8+, Git
# ═══════════════════════════════════════════════════════════

set -euo pipefail

# Resolve this script's own directory now, before any `cd` below moves us
# away from it — computing this later (e.g. relative to Chromium's source
# tree) silently resolves to the wrong place.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCHES_DIR="$SCRIPT_DIR/../patches"

CHROMIUM_DIR="$HOME/jbium/chromium"
OUTPUT_DIR="$CHROMIUM_DIR/src/out/Release"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[MAC BUILD]${NC} $*"; }
ok()   { echo -e "${CYAN}[MAC BUILD]${NC} ✅ $*"; }
err()  { echo -e "${RED}[MAC BUILD]${NC} ❌ $*"; exit 1; }

echo "════════════════════════════════════════════════════════════"
echo "  Building Jbium (macOS)"
echo "════════════════════════════════════════════════════════════"

# ── Step 1: Check prerequisites ──
log "Step 1/6: Checking prerequisites..."

# Check macOS version
MAC_VERSION=$(sw_vers -productVersion)
log "  macOS: $MAC_VERSION"

# Check Xcode
if ! xcode-select -p &>/dev/null; then
    err "Xcode not installed. Install Xcode 15+ from App Store."
fi

XCODE_VERSION=$(xcodebuild -version | head -1 | awk '{print $2}')
log "  Xcode: $XCODE_VERSION"

# Check architecture
ARCH=$(uname -m)
log "  Architecture: $ARCH"

# Install depot_tools
if [ ! -d "$HOME/depot_tools" ]; then
    log "  Installing depot_tools..."
    git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git "$HOME/depot_tools"
fi

export PATH="$HOME/depot_tools:$PATH"

# depot_tools' update_depot_tools refuses to run when $USER is
# literally the string "root" ("Running depot tools as root is sad.")
# and just exits 0 without doing anything — a check on $USER, not
# actual privilege. Harmless to set even when not root.
#
# Do NOT use VPYTHON_BYPASS for this instead — verified empirically
# that it makes vpython3 skip its own managed-interpreter selection
# and fall back to bare system `python3`, which can be missing
# `enum.StrEnum` that depot_tools' own gclient.py now requires
# (Python 3.11+). That trades one failure for a worse, silent one
# deep in gclient's hooks.
if [ "$USER" = "root" ]; then
    export USER="${SUDO_USER:-jbium-builder}"
fi

# A freshly cloned depot_tools hasn't bootstrapped its vendored
# python3/vpython3 toolchain yet — `fetch`/`gclient sync` fail with
# "python3_bin_reldir.txt not found" until something triggers that
# bootstrap. Verified empirically: `gclient --version` does NOT trigger
# it, and `update_depot_tools` doesn't reliably either (it can exit 0
# without ever creating python3_bin_reldir.txt) — `ensure_bootstrap`
# is depot_tools' own script for exactly this and is the one that
# actually works.
"$HOME/depot_tools/ensure_bootstrap"

ok "Prerequisites OK"

# ── Step 2: Fetch source ──
log "Step 2/6: Fetching Chromium source..."

mkdir -p "$CHROMIUM_DIR"
cd "$CHROMIUM_DIR"

if [ ! -d "src" ]; then
    fetch --no-history --nohooks chromium
fi

cd "$CHROMIUM_DIR/src"

# Pin to the exact version the patches were written and verified
# against. `fetch --no-history` only grabs a shallow, depth-1 clone
# of origin/main's tip — it does NOT bring down tags, so the tag ref
# must be fetched explicitly, or the checked-out tree silently stays
# on whatever HEAD is (which drifts forward continuously and can be
# dozens of major versions newer, making every patch's source-text
# markers stop matching).
CHROMIUM_VERSION="120.0.6099.224"
if [ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" != "jbium-$CHROMIUM_VERSION" ]; then
    if git fetch --depth 1 origin "refs/tags/$CHROMIUM_VERSION:refs/tags/$CHROMIUM_VERSION" \
            && git checkout -B "jbium-$CHROMIUM_VERSION" "tags/$CHROMIUM_VERSION"; then
        :
    else
        err "Could not check out pinned Chromium $CHROMIUM_VERSION. Patches are written against this exact version — check network access to chromium.googlesource.com and retry."
    fi
fi

ok "Source ready ($(cat chrome/VERSION | head -4 | tr '\n' '.' | sed 's/\.$//'))"

# ── Step 3: Run hooks ──
log "Step 3/6: Running hooks..."

gclient runhooks
ok "Hooks complete"

# ── Step 4: Apply patches ──
# Patches aren't reliably idempotent (some match on a substring that's
# still present after being applied once), so re-running this on an
# already-patched checkout can corrupt files instead of being a no-op.
# Skip unless the checkout is fresh or the caller explicitly forces it.
PATCH_MARKER="$CHROMIUM_DIR/src/.jbium_patches_applied"

if [ -f "$PATCH_MARKER" ] && [ "${FORCE_PATCH:-0}" != "1" ]; then
    log "Step 4/6: Patches already applied (found $PATCH_MARKER) — skipping."
    log "  Re-apply with: FORCE_PATCH=1 bash $0"
else
    log "Step 4/6: Applying stealth patches..."

    export CHROMIUM_SRC="$CHROMIUM_DIR/src"
    for patch_dir in "$PATCHES_DIR"/0*/; do
        if [ -f "$patch_dir/apply.sh" ]; then
            log "  Applying: $(basename "$patch_dir")"
            bash "$patch_dir/apply.sh"
        fi
    done

    date > "$PATCH_MARKER"
    ok "Patches applied"
fi

# ── Step 5: Configure build ──
log "Step 5/6: Configuring build..."

mkdir -p out/Release
cp "$SCRIPT_DIR/../config/args_macos.gn" out/Release/args.gn

# Adjust for architecture
if [ "$ARCH" = "arm64" ]; then
    echo 'target_cpu = "arm64"' >> out/Release/args.gn
else
    echo 'target_cpu = "x64"' >> out/Release/args.gn
fi

gn gen out/Release
ok "Build configured"

# ── Step 6: Build ──
log "Step 6/6: Building..."

CORES=$(sysctl -n hw.ncpu)
log "  Using $CORES parallel jobs"
log "  Estimated time: $(( 200 / CORES )) hours"

ninja -C out/Release chrome -j$CORES

log "Renaming binary: chrome -> jbium"
mv "$OUTPUT_DIR/chrome" "$OUTPUT_DIR/jbium"

echo "════════════════════════════════════════════════════════════"
ok "Build Complete!"
echo "════════════════════════════════════════════════════════════"
echo "  Binary: $OUTPUT_DIR/jbium"
echo "  Size: $(du -sh $OUTPUT_DIR/jbium | cut -f1)"
echo ""

# Create .app bundle
log "Creating .app bundle..."

APP_DIR="$OUTPUT_DIR/Jbium.app"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

cp "$OUTPUT_DIR/jbium" "$APP_DIR/Contents/MacOS/jbium"
cp "$OUTPUT_DIR"/*.pak "$APP_DIR/Contents/MacOS/" 2>/dev/null || true
cp "$OUTPUT_DIR"/*.bin "$APP_DIR/Contents/MacOS/" 2>/dev/null || true
cp "$OUTPUT_DIR/icudtl.dat" "$APP_DIR/Contents/MacOS/" 2>/dev/null || true

# Create Info.plist
cat > "$APP_DIR/Contents/Info.plist" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>jbium</string>
    <key>CFBundleIdentifier</key>
    <string>com.jbium.browser</string>
    <key>CFBundleName</key>
    <string>Jbium</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST_EOF

ok "App bundle: $APP_DIR"
echo ""
