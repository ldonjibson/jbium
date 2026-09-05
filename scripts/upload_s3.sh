#!/bin/bash
# scripts/upload_s3.sh

set -euo pipefail

# ─────────────────────────────────────────
# Configure these:
# ─────────────────────────────────────────
S3_BUCKET="your-bucket-name"
S3_PREFIX="jbium"
AWS_REGION="us-east-1"
# ─────────────────────────────────────────

# Check if build exists
BUILD_DIR="/root/jbium/chromium/src/out/Release"
if [ ! -f "$BUILD_DIR/jbium" ]; then
    echo "❌ No build found. Run build first."
    exit 1
fi

# Create versioned package
VERSION=$(date +%Y%m%d-%H%M%S)
ARCHIVE_NAME="jbium-${VERSION}.tar.gz"

echo "Packaging build..."
cd "$BUILD_DIR"
tar -czf "/tmp/$ARCHIVE_NAME" \
    jbium \
    *.pak \
    *.bin \
    *.dat \
    *.so \
    2>/dev/null || true

SIZE=$(du -sh "/tmp/$ARCHIVE_NAME" | cut -f1)
echo "Archive: $ARCHIVE_NAME ($SIZE)"

# Upload to S3
echo "Uploading to S3..."
aws s3 cp "/tmp/$ARCHIVE_NAME" \
    "s3://$S3_BUCKET/$S3_PREFIX/$ARCHIVE_NAME" \
    --region "$AWS_REGION"

# Also update "latest" pointer
echo "Updating latest..."
aws s3 cp "/tmp/$ARCHIVE_NAME" \
    "s3://$S3_BUCKET/$S3_PREFIX/latest.tar.gz" \
    --region "$AWS_REGION"

# Create a manifest
cat > /tmp/manifest.json << EOF
{
  "version": "$VERSION",
  "date": "$(date -I)",
  "size": "$SIZE",
  "chromium_version": "$(cat /root/jbium/chromium/src/chrome/VERSION | head -4 | tr '\n' '.' | sed 's/\.$//')",
  "patches_applied": $(ls /root/jbium/patches/ | wc -l),
  "download": "s3://$S3_BUCKET/$S3_PREFIX/$ARCHIVE_NAME"
}
EOF

aws s3 cp /tmp/manifest.json \
    "s3://$S3_BUCKET/$S3_PREFIX/manifest.json" \
    --region "$AWS_REGION"

echo ""
echo "════════════════════════════════════════"
echo "  ✅ Uploaded to S3"
echo "  Bucket: s3://$S3_BUCKET/$S3_PREFIX/"
echo "  File: $ARCHIVE_NAME"
echo "  Size: $SIZE"
echo "════════════════════════════════════════"

# Cleanup
rm -f "/tmp/$ARCHIVE_NAME"
