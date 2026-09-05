#!/bin/bash
# build.sh
# Run on the AWS instance after setup

set -euo pipefail

# Determine optimal parallel jobs
# Rule: jobs = cores, but limit by RAM
TOTAL_RAM_GB=$(free -g | awk '/Mem:/ {print $2}')
CORES=$(nproc)

if [ "$TOTAL_RAM_GB" -lt 64 ]; then
    # RAM-constrained
    NUM_JOBS=$(( TOTAL_RAM_GB / 2 ))
    echo "⚠️  RAM-limited: using $NUM_JOBS jobs (RAM: ${TOTAL_RAM_GB}GB)"
else
    # CPU-bound
    NUM_JOBS=$CORES
    echo "✅ CPU-bound: using $NUM_JOBS jobs (Cores: $CORES, RAM: ${TOTAL_RAM_GB}GB)"
fi

echo "══════════════════════════════════════════════════"
echo "  Building Jbium"
echo "  Jobs: $NUM_JOBS"
echo "  Started: $(date)"
echo "══════════════════════════════════════════════════"

cd /home/ubuntu/jbium/chromium/src

# Build with progress
ninja -C out/Release chrome -j$NUM_JOBS 2>&1 | while IFS= read -r line; do
    # Show progress every 100 lines
    echo "$line"
done

echo "══════════════════════════════════════════════════"
echo "  Build completed: $(date)"
echo "══════════════════════════════════════════════════"

# Rename binary
echo "Renaming binary: chrome -> jbium"
mv out/Release/chrome out/Release/jbium

# Report binary size
echo "Binary size:"
du -sh out/Release/jbium
du -sh out/Release/

# Strip binary for production
echo "Stripping binary..."
strip --strip-all out/Release/jbium
echo "Stripped size:"
du -sh out/Release/jbium
