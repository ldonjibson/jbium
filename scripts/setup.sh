#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# setup.sh — Jbium Build Environment
# Run on: Vast.ai Ubuntu 22.04 instance (48+ cores, 128GB+ RAM)
# Time: ~30-45 minutes (mostly source download)
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Logging
LOG="/root/setup.log"
log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $*" | tee -a "$LOG"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" | tee -a "$LOG"; exit 1; }
ok()   { echo -e "${GREEN}[OK]${NC} $*" | tee -a "$LOG"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*" | tee -a "$LOG"; }

echo "═════════════════════════════════════════════════════════════════"
echo "  Jbium Build Environment Setup"
echo "═════════════════════════════════════════════════════════════════"

# ───────────────────────────────────────────────────────────────
# 0. Hardware check
# ───────────────────────────────────────────────────────────────
log "Checking hardware..."

CORES=$(nproc)
RAM_GB=$(free -g | awk '/Mem:/ {print $2}')
DISK_GB=$(df -BG /root | awk 'NR==2 {print $4}' | tr -d 'G')

log "  CPU: $(grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)"
log "  Cores: $CORES"
log "  RAM: ${RAM_GB}GB"
log "  Free disk: ${DISK_GB}GB"

if [ "$CORES" -lt 16 ]; then
    warn "Only $CORES cores — build will be slow (16+ recommended)"
fi
if [ "$RAM_GB" -lt 32 ]; then
    err "Need at least 32GB RAM (have ${RAM_GB}GB). Add swap and retry, or use larger instance."
fi
if [ "$DISK_GB" -lt 150 ]; then
    err "Need at least 150GB free disk (have ${DISK_GB}GB)"
fi
ok "Hardware sufficient"

# ───────────────────────────────────────────────────────────────
# 1. System update + base packages
# ───────────────────────────────────────────────────────────────
log "Step 1/9: System packages..."

apt-get update -qq 2>/dev/null
apt-get install -y -qq \
    git curl wget unzip zip \
    build-essential \
    cmake \
    ninja-build \
    pkg-config \
    python3 python3-pip python3-dev python3-setuptools \
    perl bison flex gperf \
    clang lld llvm \
    nodejs npm \
    htop tmux \
    awscli \
    rsync \
    > /dev/null 2>&1

ok "Base packages installed"

# ───────────────────────────────────────────────────────────────
# 2. Chromium build dependencies
# ───────────────────────────────────────────────────────────────
log "Step 2/9: Chromium build dependencies..."

apt-get install -y -qq \
    libasound2-dev \
    libatk1.0-dev \
    libatk-bridge2.0-dev \
    libatspi2.0-dev \
    libcairo2-dev \
    libcups2-dev \
    libdrm-dev \
    libgbm-dev \
    libglib2.0-dev \
    libgtk-3-dev \
    libnss3-dev \
    libpango1.0-dev \
    libx11-xcb-dev \
    libxcomposite-dev \
    libxcursor-dev \
    libxdamage-dev \
    libxext-dev \
    libxfixes-dev \
    libxi-dev \
    libxkbcommon-dev \
    libxrandr-dev \
    libxshmfence-dev \
    libxtst-dev \
    libdbus-1-dev \
    libdrm-dev \
    libgbm-dev \
    libffi-dev \
    > /dev/null 2>&1

ok "Chromium dependencies installed"

# ───────────────────────────────────────────────────────────────
# 3. depot_tools
# ───────────────────────────────────────────────────────────────
log "Step 3/9: Installing depot_tools..."

if [ ! -d "/opt/depot_tools" ]; then
    git clone -q https://chromium.googlesource.com/chromium/tools/depot_tools.git /opt/depot_tools
fi

# Add to PATH for all users
echo 'export PATH="/opt/depot_tools:$PATH"' > /etc/profile.d/depot_tools.sh
echo 'export PATH="/opt/depot_tools:$PATH"' >> /root/.bashrc
export PATH="/opt/depot_tools:$PATH"

# Disable depot_tools metrics (no Google telemetry)
echo 'export DEPOT_TOOLS_METRICS=0' >> /root/.bashrc
echo 'export DEPOT_TOOLS_UPDATE=0' >> /root/.bashrc

ok "depot_tools installed at /opt/depot_tools"

# ───────────────────────────────────────────────────────────────
# 4. Git configuration
# ───────────────────────────────────────────────────────────────
log "Step 4/9: Configuring git..."

git config --global http.postBuffer 524288000
git config --global core.compression 0
git config --global user.email "builder@stealth.local"
git config --global user.name "Stealth Builder"
git config --global color.ui auto
git config --global init.defaultBranch main

ok "Git configured"

# ───────────────────────────────────────────────────────────────
# 5. Fetch Chromium source
# ───────────────────────────────────────────────────────────────
log "Step 5/9: Fetching Chromium source (this takes ~15-20 min)..."

CHROMIUM_DIR="/root/jbium/chromium"
mkdir -p "$CHROMIUM_DIR"
cd "$CHROMIUM_DIR"

if [ ! -d "src" ]; then
    # Fetch without history (smaller, faster)
    fetch --no-history --nohooks chromium 2>&1 | \
        while IFS= read -r line; do
            echo -n "\r  Downloading... $line" | tail -c 80 >&2
        done
    echo ""
fi

cd "$CHROMIUM_DIR/src"

# Pin to a stable version
CHROMIUM_VERSION="120.0.6099.224"
git checkout "tags/$CHROMIUM_VERSION" -b "jbium-$CHROMIUM_VERSION" 2>/dev/null || \
    warn "Could not checkout $CHROMIUM_VERSION, using current"

CHROMIUM_ACTUAL=$(cat chrome/VERSION | head -4 | tr '\n' '.' | sed 's/\.$//')
ok "Chromium source ready (version: $CHROMIUM_ACTUAL)"

# ───────────────────────────────────────────────────────────────
# 6. Run hooks (downloads third-party deps)
# ───────────────────────────────────────────────────────────────
log "Step 6/9: Running gclient hooks (~10-15 min)..."

gclient runhooks 2>&1 | grep -E "(Running|Still)" | tail -5
ok "Hooks completed"

# ───────────────────────────────────────────────────────────────
# 7. Create project structure
# ───────────────────────────────────────────────────────────────
log "Step 7/9: Creating project structure..."

PROJECT_DIR="/root/jbium"
mkdir -p "$PROJECT_DIR"/{patches,scripts,driver,fingerprints,tests,config}

# ───────────────────────────────────────────────────────────────
# 8. Configure GN build
# ───────────────────────────────────────────────────────────────
log "Step 8/9: Configuring build..."

mkdir -p out/Release
cat > out/Release/args.gn << 'EOF'
# ═════════════════════════════════════════════
# Jbium — Build Configuration
# ═════════════════════════════════════════════

# Build type
is_debug = false
is_official_build = true
is_component_build = false

# Optimization
symbol_level = 0
strip_debug_info = true
optimize_for_size = true
use_thin_lto = true
thin_lto_enable_optimizations = true
is_cfi = true

# Compiler
is_clang = true
use_lld = true

# No Google branding
is_chrome_branded = false
google_api_key = ""
google_default_client_id = ""
google_default_client_secret = ""

# ═════════════════════════════════════════════
# FINGERPRINT CONSISTENCY (KEEP)
# ═════════════════════════════════════════════
enable_pdf = true
enable_plugins = true
enable_mime_type_detection = true
proprietary_codecs = true
ffmpeg_branding = "Chrome"
enable_webrtc = true
rtc_use_h264 = true
enable_media_stream = true
enable_screen_capture = true
enable_web_speech = true
enable_speech_synthesis = true
enable_service_worker = true
enable_gamepad = true
enable_web_midi = true
enable_battery_status_api = true
enable_web_bluetooth = true
enable_webxr = true
enable_navigator_stored_client_hints = true

# ═════════════════════════════════════════════
# REMOVE BLOAT
# ═════════════════════════════════════════════
safe_browsing_mode = 0
enable_signin = false
enable_browser_signin = false
enable_one_click_signin = false
enable_sync = false
enable_google_now = false
enable_voice_search = false
enable_web_store = false
enable_cloud_print = false
enable_print_preview = false
enable_basic_printing = false
enable_media_router = false
enable_dial_media_route_provider = false
enable_remoting = false
enable_update_flows = false
use_crashpad = false
enable_crash_reporting = false
enable_metrics = false
enable_metrics_reporting = false
enable_policy = false
enable_spellcheck = false
enable_accessibility_ui = false
enable_notification_ui = false
enable_nacl = false
enable_nacl_nonsfi = false
enable_apps = false
enable_app_list = false

# ═════════════════════════════════════════════
# PLATFORM
# ═════════════════════════════════════════════
use_udev = true
use_alsa = true
use_pulseaudio = false
use_cairo = true
use_glib = true
use_gtk = true
use_ozone = true
ozone_platform_x11 = true
use_system_minilibc = false
EOF

# Generate build files
gn gen out/Release 2>&1 | tail -1
ok "Build configured"

# ───────────────────────────────────────────────────────────────
# 9. Create helper scripts
# ───────────────────────────────────────────────────────────────
log "Step 9/9: Creating build scripts..."

# Build script
cat > "$PROJECT_DIR/scripts/build.sh" << 'BUILDEOF'
#!/bin/bash
set -euo pipefail

cd /root/jbium/chromium/src

CORES=$(nproc)
RAM_GB=$(free -g | awk '/Mem:/ {print $2}')

if [ "$RAM_GB" -lt 64 ]; then
    NUM_JOBS=$(( CORES * 3 / 4 ))
else
    NUM_JOBS=$CORES
fi

echo "══════════════════════════════════════════"
echo "  Building Jbium"
echo "  Cores: $CORES | Jobs: $NUM_JOBS"
echo "  Started: $(date)"
echo "══════════════════════════════════════════"

ninja -C out/Release chrome -j$NUM_JOBS
mv out/Release/chrome out/Release/jbium

echo "══════════════════════════════════════════"
echo "  ✅ Build complete: $(date)"
echo "  Binary: $(du -sh out/Release/jbium)"
echo "══════════════════════════════════════════"
BUILDEOF
chmod +x "$PROJECT_DIR/scripts/build.sh"

# Package script
cat > "$PROJECT_DIR/scripts/package.sh" << 'PKGEOF'
#!/bin/bash
set -euo pipefail

cd /root/jbium/chromium/src/out/Release

echo "Packaging build..."

tar -czf /root/jbium-$(date +%Y%m%d-%H%M%S).tar.gz \
    jbium \
    *.pak \
    *.bin \
    *.dat \
    *.so \
    2>/dev/null || true

LATEST=$(ls -t /root/jbium-*.tar.gz | head -1)
echo "Package: $LATEST"
echo "Size: $(du -sh $LATEST)"
PKGEOF
chmod +x "$PROJECT_DIR/scripts/package.sh"

ok "Scripts created"

# ───────────────────────────────────────────────────────────────
# Summary
# ───────────────────────────────────────────────────────────────
echo ""
echo "═════════════════════════════════════════════════════════════════"
echo "  ✅ SETUP COMPLETE"
echo "═════════════════════════════════════════════════════════════════"
echo ""
echo "  Chromium source:  /root/jbium/chromium/src"
echo "  Build output:     /root/jbium/chromium/src/out/Release"
echo "  Project dir:      /root/jbium"
echo ""
echo "  Next steps:"
echo "  1. Test build:     /root/jbium/scripts/build.sh"
echo "  2. Connect VS Code (see instructions)"
echo "  3. Apply stealth patches"
echo ""
echo "  First build will take ~2-4 hours"
echo "  Subsequent builds: 5-30 minutes (incremental)"
echo "═════════════════════════════════════════════════════════════════"
