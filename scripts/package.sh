#!/bin/bash
# ═══════════════════════════════════════════════════════════
# package.sh — Package Jbium Build
# ═══════════════════════════════════════════════════════════
# Collects all runtime files, strips debug info,
# creates a versioned tarball with checksums and manifest.
#
# Usage:
#   bash scripts/package.sh                    # Package current build
#   bash scripts/package.sh --upload          # Package + upload to S3
#   bash scripts/package.sh --output /custom  # Custom output dir
# ═══════════════════════════════════════════════════════════

set -euo pipefail

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

BUILD_DIR="/root/jbium/chromium/src/out/Release"
OUTPUT_DIR="/root/packages"
CHROMIUM_SRC="/root/jbium/chromium/src"

# Version info
CHROMIUM_VERSION=$(cat "$CHROMIUM_SRC/chrome/VERSION" | \
    head -4 | tr '\n' '.' | sed 's/\.$//')
BUILD_DATE=$(date +%Y%m%d)
BUILD_TIME=$(date +%H%M%S)
PACKAGE_VERSION="${BUILD_DATE}-${BUILD_TIME}"
ARCHIVE_NAME="jbium-${PACKAGE_VERSION}.tar.gz"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${CYAN}[PKG]${NC} $*"; }
ok()   { echo -e "${GREEN}[PKG]${NC} ✅ $*"; }
warn() { echo -e "${YELLOW}[PKG]${NC} ⚠️  $*"; }
err()  { echo -e "${RED}[PKG]${NC} ❌ $*"; exit 1; }

# ─────────────────────────────────────────────
# Parse arguments
# ─────────────────────────────────────────────

UPLOAD=false

for arg in "$@"; do
    case $arg in
        --upload)
            UPLOAD=true
            shift
            ;;
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --no-strip)
            NO_STRIP=true
            shift
            ;;
    esac
done

echo "════════════════════════════════════════════════════════════"
echo -e "${BOLD}  Jbium — Packaging${NC}"
echo "════════════════════════════════════════════════════════════"
echo ""
log "Build directory: $BUILD_DIR"
log "Output:         $OUTPUT_DIR"
log "Version:        $CHROMIUM_VERSION"
log "Package ID:     $PACKAGE_VERSION"
echo ""

# ─────────────────────────────────────────────
# Step 0: Verify build exists
# ─────────────────────────────────────────────

log "Step 0: Verifying build..."

if [ ! -f "$BUILD_DIR/jbium" ]; then
    err "jbium binary not found at $BUILD_DIR/jbium"
fi

BINARY_SIZE=$(du -sh "$BUILD_DIR/jbium" | cut -f1)
log "  Binary found: $BINARY_SIZE"

# Check if binary is executable
if [ ! -x "$BUILD_DIR/jbium" ]; then
    warn "Binary is not executable, fixing..."
    chmod +x "$BUILD_DIR/jbium"
fi

ok "Build verified"

# ─────────────────────────────────────────────
# Step 1: Strip debug symbols
# ─────────────────────────────────────────────

log "Step 1: Stripping binary..."

PRE_STRIP_SIZE=$(stat -c%s "$BUILD_DIR/jbium")

if [ "${NO_STRIP:-false}" != "true" ]; then
    # Strip debug info but keep symbols needed for stack traces
    strip --strip-debug "$BUILD_DIR/jbium" 2>/dev/null || \
        strip -S "$BUILD_DIR/jbium" 2>/dev/null || \
        warn "Could not strip binary (may already be stripped)"

    POST_STRIP_SIZE=$(stat -c%s "$BUILD_DIR/jbium")
    SAVED_MB=$(( (PRE_STRIP_SIZE - POST_STRIP_SIZE) / 1024 / 1024 ))

    if [ "$SAVED_MB" -gt 0 ]; then
        ok "Stripped ${SAVED_MB}MB of debug symbols"
    else
        ok "Binary already stripped"
    fi
else
    warn "Skipping strip (--no-strip)"
fi

# ─────────────────────────────────────────────
# Step 2: Create staging directory
# ─────────────────────────────────────────────

log "Step 2: Creating package structure..."

STAGING_DIR=$(mktemp -d /tmp/stealth-pkg-XXXXXX)
mkdir -p "$STAGING_DIR"/{chrome,locales,fonts,driver,config}

# Track what we're including
MANIFEST_ITEMS=()

# ─────────────────────────────────────────────
# Step 3: Copy binary
# ─────────────────────────────────────────────

log "Step 3: Copying binary..."

cp "$BUILD_DIR/jbium" "$STAGING_DIR/chrome/jbium"
chmod +x "$STAGING_DIR/chrome/jbium"
MANIFEST_ITEMS+=("chrome/jbium")

BINARY_SIZE=$(du -sh "$STAGING_DIR/chrome/jbium" | cut -f1)
ok "  Binary: $BINARY_SIZE"

# Copy required libraries (non-system)
for lib in "$BUILD_DIR"/*.so; do
    [ -f "$lib" ] || continue
    libname=$(basename "$lib")
    cp "$lib" "$STAGING_DIR/chrome/"
    MANIFEST_ITEMS+=("chrome/$libname")
    log "  Library: $libname ($(du -sh "$lib" | cut -f1))"
done

# ─────────────────────────────────────────────
# Step 4: Copy resources (.pak files)
# ─────────────────────────────────────────────

log "Step 4: Copying resources..."

# Main resources.pak (essential)
if [ -f "$BUILD_DIR/resources.pak" ]; then
    cp "$BUILD_DIR/resources.pak" "$STAGING_DIR/chrome/"
    MANIFEST_ITEMS+=("chrome/resources.pak")
    log "  resources.pak: $(du -sh "$BUILD_DIR/resources.pak" | cut -f1)"
fi

# V8 snapshots (essential)
for bin_file in natives_blob.bin snapshot_blob.bin v8_context_snapshot.bin; do
    if [ -f "$BUILD_DIR/$bin_file" ]; then
        cp "$BUILD_DIR/$bin_file" "$STAGING_DIR/chrome/"
        MANIFEST_ITEMS+=("chrome/$bin_file")
        log "  $bin_file: $(du -sh "$BUILD_DIR/$bin_file" | cut -f1)"
    fi
done

# ICU data (essential for locale support)
if [ -f "$BUILD_DIR/icudtl.dat" ]; then
    cp "$BUILD_DIR/icudtl.dat" "$STAGING_DIR/chrome/"
    MANIFEST_ITEMS+=("chrome/icudtl.dat")
    log "  icudtl.dat: $(du -sh "$BUILD_DIR/icudtl.dat" | cut -f1)"
fi

ok "Resources copied"

# ─────────────────────────────────────────────
# Step 5: Copy locales
# ─────────────────────────────────────────────

log "Step 5: Copying locales..."

# Supported locales (matches config/locales.json)
SUPPORTED_LOCALES=("en-US" "en-GB" "ja" "de" "fr" "es" "pt-BR" "ko" "zh-CN" "it" "ru")

for locale in "${SUPPORTED_LOCALES[@]}"; do
    locale_file="$BUILD_DIR/locales/${locale}.pak"
    if [ -f "$locale_file" ]; then
        cp "$locale_file" "$STAGING_DIR/locales/"
        MANIFEST_ITEMS+=("locales/${locale}.pak")
    fi
done

LOCALE_COUNT=$(ls "$STAGING_DIR/locales/" | wc -l)
ok "  Copied $LOCALE_COUNT locale files"

# ─────────────────────────────────────────────
# Step 6: Bundle fonts (if available)
# ─────────────────────────────────────────────

log "Step 6: Bundling fonts..."

FONT_SOURCE="/root/jbium/chromium/src/out/Release/fonts"
SYSTEM_FONT_DIR="/usr/share/fonts/truetype"

# Check for bundled fonts
if [ -d "$FONT_SOURCE" ] && [ "$(ls -A "$FONT_SOURCE" 2>/dev/null)" ]; then
    log "  Using build fonts..."
    cp "$FONT_SOURCE"/*.ttf "$STAGING_DIR/fonts/" 2>/dev/null || true
elif [ -d "/root/jbium/fonts" ]; then
    log "  Using project fonts..."
    cp /root/jbium/fonts/*.ttf "$STAGING_DIR/fonts/" 2>/dev/null || true
else
    # Download essential fonts (Noto Sans for basic coverage)
    log "  Downloading essential fonts..."
    
    mkdir -p "$STAGING_DIR/fonts"
    
    # Noto Sans (Latin, covers en/de/fr/es/it)
    wget -q -O "$STAGING_DIR/fonts/NotoSans-Regular.ttf" \
        "https://github.com/notofonts/noto-fonts/raw/main/noto-core/NotoSans/NotoSans-Regular.ttf" \
        2>/dev/null || warn "Could not download NotoSans-Regular"
    
    # Noto Sans JP (Japanese)
    wget -q -O "$STAGING_DIR/fonts/NotoSansJP-Regular.ttf" \
        "https://github.com/notofonts/noto-fonts/raw/main/noto-cjk/NotoSansJP/NotoSansJP-Regular.ttf" \
        2>/dev/null || warn "Could not download NotoSansJP"
    
    # Noto Sans KR (Korean)
    wget -q -O "$STAGING_DIR/fonts/NotoSansKR-Regular.ttf" \
        "https://github.com/notofonts/noto-fonts/raw/main/noto-cjk/NotoSansKR/NotoSansKR-Regular.ttf" \
        2>/dev/null || warn "Could not download NotoSansKR"
fi

FONT_COUNT=$(ls "$STAGING_DIR/fonts/" 2>/dev/null | wc -l)
if [ "$FONT_COUNT" -gt 0 ]; then
    ok "  Bundled $FONT_COUNT font files"
    # Add all fonts to manifest
    for font in "$STAGING_DIR/fonts"/*; do
        [ -f "$font" ] && MANIFEST_ITEMS+=("fonts/$(basename "$font")")
    done
else
    warn "  No fonts bundled (system fonts will be used)"
fi

# ─────────────────────────────────────────────
# Step 7: Copy driver and config
# ─────────────────────────────────────────────

log "Step 7: Copying driver and configuration..."

DRIVER_DIR="/root/jbium/driver"
CONFIG_DIR="/root/jbium/config"

# Driver (Python files)
if [ -d "$DRIVER_DIR" ]; then
    cp "$DRIVER_DIR"/*.py "$STAGING_DIR/driver/"
    MANIFEST_ITEMS+=("driver/")
    log "  Driver: $(ls "$STAGING_DIR/driver/" | wc -l) files"
fi

# Config files
if [ -d "$CONFIG_DIR" ]; then
    for config_file in "$CONFIG_DIR"/*.json "$CONFIG_DIR"/*.yaml; do
        [ -f "$config_file" ] || continue
        cp "$config_file" "$STAGING_DIR/config/"
        MANIFEST_ITEMS+=("config/$(basename "$config_file")")
    done
    log "  Config: $(ls "$STAGING_DIR/config/" | wc -l) files"
fi

ok "Driver and config copied"

# ─────────────────────────────────────────────
# Step 8: Create launcher script
# ─────────────────────────────────────────────

log "Step 8: Creating launcher script..."

cat > "$STAGING_DIR/jbium" << 'LAUNCHER_EOF'
#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Jbium Launcher
# ═══════════════════════════════════════════════════════════
# Launches the stealth Chromium with proper paths.
#
# Usage:
#   ./jbium [chrome args...]
#
# Environment variables (set by driver):
#   STEALTH_* variables control fingerprint behavior
# ═══════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHROME_DIR="$SCRIPT_DIR/chrome"
FONT_DIR="$SCRIPT_DIR/fonts"

# Required paths
export CHROME_PATH="$CHROME_DIR/jbium"
export FONTCONFIG_PATH="${FONTCONFIG_PATH:-$FONT_DIR}"

# Create fontconfig cache
export FONTCONFIG_CACHE="/tmp/.fontconfig-$$"
mkdir -p "$FONTCONFIG_CACHE"

# Essential arguments
ESSENTIAL_ARGS=(
    "--no-first-run"
    "--no-default-browser-check"
    "--disable-background-timer-throttling"
    "--disable-backgrounding-occluded-windows"
    "--disable-renderer-backgrounding"
    "--disable-background-networking"
    "--disable-client-side-phishing-detection"
    "--disable-default-apps"
    "--disable-features=site-per-process,Translate,MediaRouter"
    "--disable-hang-monitor"
    "--disable-prompt-on-repost"
    "--disable-sync"
    "--metrics-recording-only"
    "--no-pings"
    "--password-store=basic"
    "--use-mock-keychain"
    "--no-sandbox"  # Required in Docker/CI environments
)

# Font configuration (if bundled fonts exist)
if [ -d "$FONT_DIR" ] && [ "$(ls -A "$FONT_DIR" 2>/dev/null)" ]; then
    # Create fontconfig config
    mkdir -p "$FONTCONFIG_CACHE"
    cat > "$FONTCONFIG_CACHE/fonts.conf" << 'FC_EOF'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>BINDIR</dir>
  <cachedir>CACHEDIR</cachedir>
  <match target="pattern">
    <test qual="any" name="family">
      <string>sans-serif</string>
    </test>
    <edit name="family" mode="assign" binding="same">
      <string>Noto Sans</string>
    </edit>
  </match>
</fontconfig>
FC_EOF
    # Substitute paths
    sed -i "s|BINDIR|$FONT_DIR|g" "$FONTCONFIG_CACHE/fonts.conf"
    sed -i "s|CACHEDIR|$FONTCONFIG_CACHE|g" "$FONTCONFIG_CACHE/fonts.conf"
    
    # Also add to essential args
    ESSENTIAL_ARGS+=("--font-render-hinting=none")
fi

# Launch
exec "$CHROME_PATH" \
    "${ESSENTIAL_ARGS[@]}" \
    "$@"
LAUNCHER_EOF

chmod +x "$STAGING_DIR/jbium"
MANIFEST_ITEMS+=("jbium")
ok "Launcher script created"

# ─────────────────────────────────────────────
# Step 9: Create install script
# ─────────────────────────────────────────────

cat > "$STAGING_DIR/install.sh" << 'INSTALL_EOF'
#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Jbium — Installer
# ═══════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "════════════════════════════════════════════════════════════"
echo "  Installing Jbium"
echo "════════════════════════════════════════════════════════════"

# Installation directory
INSTALL_DIR="${1:-/opt/jbium}"
sudo mkdir -p "$INSTALL_DIR"

# Copy files
echo "  Copying to $INSTALL_DIR..."
sudo cp -r "$SCRIPT_DIR"/{chrome,locales,fonts} "$INSTALL_DIR/" 2>/dev/null || true
sudo cp "$SCRIPT_DIR/jbium" "$INSTALL_DIR/"

# Symlink
if [ -w /usr/local/bin ]; then
    sudo ln -sf "$INSTALL_DIR/jbium" /usr/local/bin/jbium
    echo "  ✅ Installed: /usr/local/bin/jbium"
else
    echo "  ✅ Installed: $INSTALL_DIR/jbium"
fi

# Verify
if "$INSTALL_DIR/chrome/jbium" --version 2>/dev/null; then
    echo "  ✅ Installation verified"
else
    echo "  ⚠️  Could not verify installation"
fi

echo ""
echo "  Usage:"
echo "    jbium [args...]"
echo ""
echo "  Or with Python driver:"
echo "    from driver.stealth_browser import Jbium"
echo "    browser = Jbium()"
echo ""

INSTALL_EOF

chmod +x "$STAGING_DIR/install.sh"
MANIFEST_ITEMS+=("install.sh")

# ─────────────────────────────────────────────
# Step 10: Create uninstall script
# ─────────────────────────────────────────────

cat > "$STAGING_DIR/uninstall.sh" << 'UNINSTALL_EOF'
#!/bin/bash
INSTALL_DIR="${1:-/opt/jbium}"

echo "Removing Jbium..."

sudo rm -f /usr/local/bin/jbium
sudo rm -rf "$INSTALL_DIR"

echo "✅ Uninstalled"
UNINSTALL_EOF

chmod +x "$STAGING_DIR/uninstall.sh"
MANIFEST_ITEMS+=("uninstall.sh")

# ─────────────────────────────────────────────
# Step 11: Create manifest.json
# ─────────────────────────────────────────────

log "Step 9: Creating manifest..."

# Calculate total sizes
BINARY_SHA=$(sha256sum "$STAGING_DIR/chrome/jbium" | cut -d' ' -f1)

cat > "$STAGING_DIR/manifest.json" << MANIFESTEOF
{
  "name": "jbium",
  "version": "$PACKAGE_VERSION",
  "chromium_version": "$CHROMIUM_VERSION",
  "build_date": "$(date -I)",
  "build_time": "$(date '+%H:%M:%S')",
  "binary_sha256": "$BINARY_SHA",
  "binary_size_bytes": $(stat -c%s "$STAGING_DIR/chrome/jbium"),
  "binary_size_human": "$(du -sh "$STAGING_DIR/chrome/jbium" | cut -f1)",
  "locales_included": $LOCALE_COUNT,
  "fonts_included": $FONT_COUNT,
  "patches_applied": [
    "001_automation",
    "002_cdp",
    "003_tls",
    "004_canvas",
    "005_webgl",
    "006_fonts",
    "007_navigator",
    "008_geoip",
    "009_plugins",
    "010_misc"
  ],
  "files": [
$(printf '    "%s"' "${MANIFEST_ITEMS[@]:0:1}"
for item in "${MANIFEST_ITEMS[@]:1}"; do
    printf ',\n    "%s"' "$item"
done
printf '\n')
  ],
  "features": {
    "pdf_viewer": true,
    "proprietary_codecs": true,
    "webrtc": true,
    "canvas_noise": true,
    "webgl_spoofing": true,
    "font_filtering": true,
    "geoip_consistency": true,
    "webrtc_leak_prevention": true
  },
  "requirements": {
    "min_ram": "4GB",
    "min_disk": "500MB",
    "os": "Linux (glibc 2.28+)",
    "display": "X11 (or headless mode)"
  }
}
MANIFESTEOF

ok "Manifest created"

# ─────────────────────────────────────────────
# Step 12: Create archive
# ─────────────────────────────────────────────

log "Step 10: Creating archive..."

mkdir -p "$OUTPUT_DIR"

ARCHIVE_PATH="$OUTPUT_DIR/$ARCHIVE_NAME"

# Create tarball with progress
cd "$STAGING_DIR"

tar -czf "$ARCHIVE_PATH" \
    --exclude='.fontconfig-*' \
    --transform "s|^\.|jbium|" \
    . \
    2>/dev/null

# Alternative if --transform not supported
if [ ! -s "$ARCHIVE_PATH" ]; then
    rm -f "$ARCHIVE_PATH"
    # Simple approach: just tar from staging dir
    tar -C "$STAGING_DIR" -czf "$ARCHIVE_PATH" .
fi

ARCHIVE_SIZE=$(du -sh "$ARCHIVE_PATH" | cut -f1)
ARCHIVE_SHA=$(sha256sum "$ARCHIVE_PATH" | cut -d' ' -f1)

ok "Archive: $ARCHIVE_NAME ($ARCHIVE_SIZE)"

# ─────────────────────────────────────────────
# Step 13: Create checksum file
# ─────────────────────────────────────────────

cat > "$OUTPUT_DIR/$ARCHIVE_NAME.sha256" << SHAEOF
$ARCHIVE_SHA  $ARCHIVE_NAME
SHAEOF

ok "Checksum: $ARCHIVE_NAME.sha256"

# ─────────────────────────────────────────────
# Step 14: Update "latest" pointer
# ─────────────────────────────────────────────

log "Step 11: Updating latest..."

LATEST_PATH="$OUTPUT_DIR/latest.tar.gz"
cp "$ARCHIVE_PATH" "$LATEST_PATH"

# Also update latest manifest
cp "$STAGING_DIR/manifest.json" "$OUTPUT_DIR/latest-manifest.json"

ok "Latest pointer updated"

# ─────────────────────────────────────────────
# Step 15: Print summary
# ─────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════════════════════"
echo -e "${BOLD}  ✅ Package Complete${NC}"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  Version:      $PACKAGE_VERSION"
echo "  Chromium:     $CHROMIUM_VERSION"
echo "  Archive:      $ARCHIVE_NAME"
echo "  Size:         $ARCHIVE_SIZE"
echo "  Location:     $OUTPUT_DIR/"
echo "  SHA-256:      ${ARCHIVE_SHA:0:32}..."
echo ""
echo "  Contents:"
echo "    chrome/jbium          $(du -sh "$STAGING_DIR/chrome/jbium" | cut -f1)"
echo "    chrome/*.pak           $(ls "$STAGING_DIR/chrome/"*.pak 2>/dev/null | wc -l) files"
echo "    chrome/*.bin           $(ls "$STAGING_DIR/chrome/"*.bin 2>/dev/null | wc -l) files"
echo "    chrome/icudtl.dat      $(du -sh "$STAGING_DIR/chrome/icudtl.dat" 2>/dev/null | cut -f1 || echo 'N/A')"
echo "    locales/               $LOCALE_COUNT locale files"
echo "    fonts/                  $FONT_COUNT font files"
echo "    driver/                $(ls "$STAGING_DIR/driver/" 2>/dev/null | wc -l) Python files"
echo "    config/                $(ls "$STAGING_DIR/config/" 2>/dev/null | wc -l) config files"
echo "    jbium        Launcher script"
echo "    install.sh             Installer script"
echo "    uninstall.sh           Uninstaller script"
echo "    manifest.json          Package metadata"
echo ""

# ─────────────────────────────────────────────
# Step 16: Upload (optional)
# ─────────────────────────────────────────────

if [ "$UPLOAD" = true ]; then
    log "Step 12: Uploading to S3..."
    
    S3_BUCKET="${S3_BUCKET:-your-bucket-name}"
    S3_PREFIX="${S3_PREFIX:-jbium}"
    AWS_REGION="${AWS_REGION:-us-east-1}"
    
    # Upload archive
    aws s3 cp "$ARCHIVE_PATH" \
        "s3://$S3_BUCKET/$S3_PREFIX/$ARCHIVE_NAME" \
        --region "$AWS_REGION" > /dev/null
    ok "  Uploaded: $ARCHIVE_NAME"
    
    # Upload checksum
    aws s3 cp "$OUTPUT_DIR/$ARCHIVE_NAME.sha256" \
        "s3://$S3_BUCKET/$S3_PREFIX/$ARCHIVE_NAME.sha256" \
        --region "$AWS_REGION" > /dev/null
    ok "  Uploaded: checksum"
    
    # Upload manifest
    aws s3 cp "$STAGING_DIR/manifest.json" \
        "s3://$S3_BUCKET/$S3_PREFIX/manifest-$PACKAGE_VERSION.json" \
        --region "$AWS_REGION" > /dev/null
    ok "  Uploaded: manifest"
    
    # Update latest
    aws s3 cp "$ARCHIVE_PATH" \
        "s3://$S3_BUCKET/$S3_PREFIX/latest.tar.gz" \
        --region "$AWS_REGION" > /dev/null
    aws s3 cp "$STAGING_DIR/manifest.json" \
        "s3://$S3_BUCKET/$S3_PREFIX/latest-manifest.json" \
        --region "$AWS_REGION" > /dev/null
    ok "  Updated latest pointer"
    
    echo ""
    echo "  S3 Location:"
    echo "    s3://$S3_BUCKET/$S3_PREFIX/$ARCHIVE_NAME"
fi

# ─────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────

rm -rf "$STAGING_DIR"

echo "════════════════════════════════════════════════════════════"

# List output directory
echo ""
echo "  Output directory contents:"
ls -lah "$OUTPUT_DIR/" | tail -5
echo ""
