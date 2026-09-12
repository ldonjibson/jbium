#!/bin/bash
# scripts/apply_all.sh
# Apply all patches in order

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCHES_DIR="$SCRIPT_DIR/../patches"

export CHROMIUM_SRC="${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"
cd "$CHROMIUM_SRC"

echo "════════════════════════════════════════════"
echo "  Applying Stealth Patches"
echo "════════════════════════════════════════════"

for patch_dir in "$PATCHES_DIR"/0*/; do
    patch_name=$(basename "$patch_dir")
    
    if [ -f "$patch_dir/apply.sh" ]; then
        echo "  Applying: $patch_name"
        bash "$patch_dir/apply.sh"
        echo "  ✅ $patch_name applied"
        echo ""
    fi
done

echo "════════════════════════════════════════════"
echo "  All patches applied!"
echo "  Now rebuild with: ninja -C out/Release chrome -j$(nproc)"
echo "════════════════════════════════════════════"
