#!/bin/bash
# Resume after the 429-killed gclient sync: retry the sync with
# backoff, then hooks, patches, arm64 args, gn gen, and the build.
set -uo pipefail
export PATH=/opt/depot_tools:$PATH
export USER=${SUDO_USER:-jbium-builder}
export DEPOT_TOOLS_METRICS=0
LOG=/root/setup-run.log
log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

cd /root/jbium/chromium/src

# 1. gclient sync with retries (429 = transient rate limit)
for attempt in 1 2 3 4 5 6; do
    log "Resume: gclient sync attempt $attempt..."
    if gclient sync --nohooks --no-history -D >> "$LOG" 2>&1; then
        log "Resume: sync OK on attempt $attempt"
        break
    fi
    if [ "$attempt" -eq 6 ]; then
        log "Resume: sync FAILED after 6 attempts -- stopping"
        exit 1
    fi
    wait_min=$((attempt * 2))
    log "Resume: sync attempt $attempt failed (likely 429) -- sleeping ${wait_min}m"
    sleep $((wait_min * 60))
done

# 2. Hooks (same tolerance as setup.sh: warn, don't die)
if [ -f third_party/node/node_modules.tar.gz.sha1 ]; then
    rm -rf third_party/node/node_modules
fi
log "Resume: running gclient runhooks..."
if ! gclient runhooks >> "$LOG" 2>&1; then
    log "Resume: runhooks reported a failure (commonly a non-essential DEPS hook on --no-history checkouts); continuing"
fi
log "Resume: hooks done"

# 3. Apply all jbium patches
log "Resume: applying patches 001-011..."
rm -f /root/apply.log
if ! bash /root/jbium/scripts/apply_all.sh > /root/apply.log 2>&1; then
    log "Resume: apply_all.sh FAILED -- see /root/apply.log"
    exit 1
fi
log "Resume: patches applied (see /root/apply.log)"

# 4. arm64 args + gn gen
log "Resume: writing arm64 args.gn + gn gen..."
if ! bash /root/apply-arm64-args.sh >> "$LOG" 2>&1; then
    log "Resume: gn gen FAILED"
    exit 1
fi
log "Resume: gn gen done (arm64)"

# 5. Build
log "Resume: starting ninja build (arm64 cross-compile)..."
mkdir -p /root/jbium/build-logs
ninja -C out/Release chrome -j 76 > /root/jbium/build-logs/build.log 2>&1
BUILD_RC=$?
if [ "$BUILD_RC" -ne 0 ]; then
    log "Resume: BUILD FAILED (rc=$BUILD_RC) -- see /root/jbium/build-logs/build.log"
    exit 1
fi
log "Resume: BUILD COMPLETE"
cd out/Release && mv chrome jbium 2>/dev/null
file jbium | tee -a "$LOG"
du -sh jbium | tee -a "$LOG"
log "Resume: ALL DONE"