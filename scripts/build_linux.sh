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

# depot_tools' update_depot_tools refuses to run when $USER is
# literally the string "root" ("Running depot tools as root is sad.")
# and just exits 0 without doing anything — a check on $USER, not
# actual privilege. Harmless to set even when not root.
#
# Do NOT use VPYTHON_BYPASS for this instead — verified empirically
# that it makes vpython3 skip its own managed-interpreter selection
# and fall back to bare system `python3` (3.10 on Ubuntu 22.04),
# which is missing `enum.StrEnum` that depot_tools' own gclient.py
# now requires (Python 3.11+). That trades one failure for a worse,
# silent one deep in gclient's hooks.
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

    # `fetch` above synced all third_party/ DEPS against origin/main's
    # tip (a much newer Chromium). Switching src's own branch does NOT
    # touch those DEPS-managed directories — gclient sync must re-read
    # the DEPS file at the new HEAD to bring them in line. Verified
    # live: skipping this leaves third_party/angle new enough to use
    # "allowlist" naming while the pinned tag's root .gn still expects
    # the older "whitelist" name, and gn gen fails outright.
    log "  Re-syncing dependencies to match pinned version..."
    gclient sync --nohooks --no-history -D
fi

ok "Source ready ($(cat chrome/VERSION | head -4 | tr '\n' '.' | sed 's/\.$//'))"

# ── Step 3: Run hooks ──
log "Step 3/6: Running hooks..."

# gclient aborts entirely on the first failing hook, even optional
# test-only data — verified live that a shallow (--no-history)
# checkout hits this on the v8 wasm fuzzer corpus download, which has
# no bearing on actually building the browser. Warn instead of
# failing the whole script; a genuinely missing build dependency
# will surface as a ninja error instead.
if ! gclient runhooks; then
    log "  WARNING: gclient runhooks reported a failure — continuing." \
        "Commonly a non-essential DEPS hook (e.g. v8 fuzzer test data)" \
        "that a --no-history shallow checkout can't fetch."
fi
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
