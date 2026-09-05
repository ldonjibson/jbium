#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Build Jbium on Linux
# Requires: Ubuntu 22.04+, Clang, Python 3.8+, Git
# (see setup.sh for the full build-host provisioning)
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
log()  { echo -e "${CYAN}[LINUX BUILD]${NC} $*"; }
ok()   { echo -e "${GREEN}[LINUX BUILD]${NC} ✅ $*"; }
err()  { echo -e "${RED}[LINUX BUILD]${NC} ❌ $*"; exit 1; }

echo "════════════════════════════════════════════════════════════"
echo "  Building Jbium (Linux)"
echo "════════════════════════════════════════════════════════════"

# ── Step 1: Check prerequisites ──
log "Step 1/6: Checking prerequisites..."

ARCH=$(uname -m)
log "  Architecture: $ARCH"

if ! command -v clang &>/dev/null; then
    err "Clang not found. Run scripts/setup.sh first."
fi

if [ ! -d "$HOME/depot_tools" ]; then
    log "  Installing depot_tools..."
    git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git "$HOME/depot_tools"
fi

export PATH="$HOME/depot_tools:$PATH"
ok "Prerequisites OK"

# ── Step 2: Fetch source ──
log "Step 2/6: Fetching Chromium source..."

mkdir -p "$CHROMIUM_DIR"
cd "$CHROMIUM_DIR"

if [ ! -d "src" ]; then
    fetch --no-history --nohooks chromium
fi

cd "$CHROMIUM_DIR/src"
ok "Source ready"

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

    for patch_dir in "$PATCHES_DIR"/0*/; do
        if [ -f "$patch_dir/apply.sh" ]; then
            log "  Applying: $(basename "$patch_dir")"
            bash "$patch_dir/apply.sh"
        fi
    done

    date > "$PATCH_MARKER"
    ok "Patches applied"
fi

ok "Patches applied"

# ── Step 5: Configure build ──
log "Step 5/6: Configuring build..."

mkdir -p out/Release
cp "$SCRIPT_DIR/../config/args_linux.gn" out/Release/args.gn
echo "target_cpu = \"$([ "$ARCH" = "aarch64" ] && echo arm64 || echo x64)\"" >> out/Release/args.gn

gn gen out/Release
ok "Build configured"

# ── Step 6: Build ──
log "Step 6/6: Building..."

TOTAL_RAM_GB=$(free -g | awk '/Mem:/ {print $2}')
CORES=$(nproc)
NUM_JOBS=$CORES
if [ "$TOTAL_RAM_GB" -lt 64 ]; then
    NUM_JOBS=$(( TOTAL_RAM_GB / 2 ))
fi
log "  Using $NUM_JOBS parallel jobs (cores: $CORES, RAM: ${TOTAL_RAM_GB}GB)"

ninja -C out/Release chrome -j"$NUM_JOBS"

log "Renaming binary: chrome -> jbium"
mv "$OUTPUT_DIR/chrome" "$OUTPUT_DIR/jbium"

echo "════════════════════════════════════════════════════════════"
ok "Build Complete!"
echo "════════════════════════════════════════════════════════════"
echo "  Binary: $OUTPUT_DIR/jbium"
echo "  Size: $(du -sh "$OUTPUT_DIR/jbium" | cut -f1)"
echo ""

log "Stripping binary..."
strip --strip-all "$OUTPUT_DIR/jbium"
ok "Stripped size: $(du -sh "$OUTPUT_DIR/jbium" | cut -f1)"

# ── Package a portable bundle ──
log "Packaging portable bundle..."

BUNDLE_DIR="$OUTPUT_DIR/jbium-linux-$([ "$ARCH" = "aarch64" ] && echo arm64 || echo x64)"
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR"

cp "$OUTPUT_DIR/jbium" "$BUNDLE_DIR/"
cp "$OUTPUT_DIR"/*.pak "$BUNDLE_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR"/*.so "$BUNDLE_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR/icudtl.dat" "$BUNDLE_DIR/" 2>/dev/null || true

tar -czf "$BUNDLE_DIR.tar.gz" -C "$OUTPUT_DIR" "$(basename "$BUNDLE_DIR")"
rm -rf "$BUNDLE_DIR"

ok "Bundle: $BUNDLE_DIR.tar.gz ($(du -sh "$BUNDLE_DIR.tar.gz" | cut -f1))"
echo ""
echo "Next: scripts/package_all.py to build the full multi-platform installer,"
echo "      or scripts/upload_s3.py to publish this build."
echo ""
