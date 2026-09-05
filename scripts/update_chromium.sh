#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Update Chromium source and re-apply patches
# ═══════════════════════════════════════════════════════════

set -euo pipefail

# Resolve this script's own directory now, before the `cd` below moves us
# into the Chromium source tree — computing it after that `cd` silently
# resolves relative to the wrong place.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CHROMIUM_DIR="${CHROMIUM_DIR:-$HOME/jbium/chromium}"
CHROMIUM_SRC="$CHROMIUM_DIR/src"
NEW_VERSION="${1:-}"

cd "$CHROMIUM_SRC"

echo "══════════════════════════════════════════════════════════"
echo "  Updating Chromium Source"
echo "══════════════════════════════════════════════════════════"

# Get current version
CURRENT_VERSION=$(cat chrome/VERSION | head -4 | tr '\n' '.' | sed 's/\.$//')
echo "  Current version: $CURRENT_VERSION"

# Fetch updates
echo "  Fetching upstream..."
git fetch origin

if [ -n "$NEW_VERSION" ]; then
    echo "  Checking out: $NEW_VERSION"
    git checkout "tags/$NEW_VERSION" -b "jbium-$NEW_VERSION"
else
    echo "  Pulling latest..."
    git pull origin main
fi

NEW_VERSION_ACTUAL=$(cat chrome/VERSION | head -4 | tr '\n' '.' | sed 's/\.$//')
echo "  New version: $NEW_VERSION_ACTUAL"

# Run hooks
echo "  Running hooks..."
gclient runhooks

# Re-apply patches
echo "  Re-applying patches..."
bash "$SCRIPT_DIR/../patches/apply_all.sh"

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  ✅ Updated to $NEW_VERSION_ACTUAL"
echo "  ⚠️  Rebuild required: ninja -C out/Release chrome"
echo "══════════════════════════════════════════════════════════"
