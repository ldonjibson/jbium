#!/bin/bash
# scripts/auto_build.sh
# Watches for changes and rebuilds automatically

set -euo pipefail

PATCHES_DIR="/root/jbium/patches"
CHROMIUM_DIR="/root/jbium/chromium/src"
LAST_HASH_FILE="/root/.last_patch_hash"

# Get current state hash of all patch files
get_current_hash() {
    find "$PATCHES_DIR" -type f -name "*.sh" -o -name "*.py" -o -name "*.patch" | \
        sort | xargs cat 2>/dev/null | sha256sum | cut -d' ' -f1
}

# Build function
do_build() {
    echo "$(date '+%H:%M:%S') [BUILD] Starting build..."
    
    cd "$CHROMIUM_DIR"
    
    CORES=$(nproc)
    NUM_JOBS=$CORES
    
    # Incremental build (fast if only some files changed)
    # ninja automatically detects what changed
    if ninja -C out/Release chrome -j$NUM_JOBS 2>&1 | tail -5; then
        echo "$(date '+%H:%M:%S') [BUILD] ✅ Success!"

        # Package
        cd out/Release
        mv -f chrome jbium
        tar -czf /root/jbium-latest.tar.gz \
            jbium *.pak *.bin *.dat 2>/dev/null || true

        echo "$(date '+%H:%M:%S') [BUILD] Packaged: $(du -sh /root/jbium-latest.tar.gz)"
        
        # Update hash
        get_current_hash > "$LAST_HASH_FILE"
        
        return 0
    else
        echo "$(date '+%H:%M:%S') [BUILD] ❌ Build failed!"
        return 1
    fi
}

echo "════════════════════════════════════════════"
echo "  Auto-Build Watcher Started"
echo "  Watching: $PATCHES_DIR"
echo "  Press Ctrl+C to stop"
echo "════════════════════════════════════════════"

# Main loop
while true; do
    CURRENT_HASH=$(get_current_hash)
    LAST_HASH=$(cat "$LAST_HASH_FILE" 2>/dev/null || echo "none")
    
    if [ "$CURRENT_HASH" != "$LAST_HASH" ]; then
        echo "$(date '+%H:%M:%S') [WATCH] Change detected!"
        do_build
    fi
    
    sleep 5  # Check every 5 seconds
done
