#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Download GeoLite2 databases for GeoIP resolution
# ═══════════════════════════════════════════════════════════

set -euo pipefail

DATA_DIR="data/geoip"
GEOIP_LICENSE_KEY="${GEOIP_LICENSE_KEY:-}"

mkdir -p "$DATA_DIR"

echo "══════════════════════════════════════════════════════════"
echo "  Downloading GeoIP Database"
echo "══════════════════════════════════════════════════════════"

if [ -n "$GEOIP_LICENSE_KEY" ]; then
    # Using MaxMind license key (more accurate).
    #
    # This previously pointed at MaxMind's newer REST endpoint
    # (download.maxmind.com/geoip/databases/<edition>/download) with an
    # HTTP Basic Auth header built from the license key alone -- that
    # endpoint actually requires Basic Auth as account_id:license_key,
    # not license_key: with an empty password, so every request here
    # would 401. Switched to MaxMind's long-standing direct-download
    # endpoint instead, which only ever needed the license key as a
    # query param (https://dev.maxmind.com/geoip/updating-databases,
    # "Download by direct link") -- confirmed working with only a
    # license key, no account ID required.
    echo "  Using MaxMind license key..."

    # GeoLite2 City
    echo "  Downloading GeoLite2-City..."
    curl -sSL "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=${GEOIP_LICENSE_KEY}&suffix=tar.gz" \
        -o "$DATA_DIR/GeoLite2-City.tar.gz"

    tar -xzf "$DATA_DIR/GeoLite2-City.tar.gz" -C "$DATA_DIR" --strip-components=1 --wildcards '*.mmdb'
    rm -f "$DATA_DIR/GeoLite2-City.tar.gz"

    # GeoLite2 ASN
    echo "  Downloading GeoLite2-ASN..."
    curl -sSL "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-ASN&license_key=${GEOIP_LICENSE_KEY}&suffix=tar.gz" \
        -o "$DATA_DIR/GeoLite2-ASN.tar.gz"

    tar -xzf "$DATA_DIR/GeoLite2-ASN.tar.gz" -C "$DATA_DIR" --strip-components=1 --wildcards '*.mmdb'
    rm -f "$DATA_DIR/GeoLite2-ASN.tar.gz"

else
    # Using free DB-IP (no license needed). Accuracy caveat: DB-IP's
    # free "Lite" tier is intentionally less precise than MaxMind's
    # GeoLite2 (coarser city-level resolution, no VPN/hosting-provider
    # detection data) -- fine as a no-signup fallback, not a drop-in
    # equivalent.
    echo "  Using free DB-IP database (no license key)..."
    echo "  For better accuracy, set GEOIP_LICENSE_KEY environment variable"
    echo ""

    # DB-IP publishes one dated file per month at a URL keyed by
    # YYYY-MM (with a hyphen) -- the previous $(date +%Y%m) (no
    # hyphen) 404'd on every run, unconditionally, confirmed live.
    DBIP_MONTH="$(date +%Y-%m)"

    # DB-IP City Lite (curl, not wget -- consistent with the MaxMind
    # branch above, and doesn't add a second HTTP-client dependency)
    echo "  Downloading dbip-city-lite..."
    curl -sSL "https://download.db-ip.com/free/dbip-city-lite-${DBIP_MONTH}.mmdb.gz" \
        -o "$DATA_DIR/dbip-city-lite.mmdb.gz"
    gunzip -f "$DATA_DIR/dbip-city-lite.mmdb.gz"
    mv "$DATA_DIR/dbip-city-lite.mmdb" "$DATA_DIR/GeoLite2-City.mmdb"

    # DB-IP ASN Lite
    echo "  Downloading dbip-asn-lite..."
    curl -sSL "https://download.db-ip.com/free/dbip-asn-lite-${DBIP_MONTH}.mmdb.gz" \
        -o "$DATA_DIR/dbip-asn-lite.mmdb.gz"
    gunzip -f "$DATA_DIR/dbip-asn-lite.mmdb.gz"
    mv "$DATA_DIR/dbip-asn-lite.mmdb" "$DATA_DIR/GeoLite2-ASN.mmdb"
fi

echo ""
echo "  Files downloaded:"
ls -lh "$DATA_DIR/"
echo ""
echo "  ✅ GeoIP databases ready"
echo ""
echo "  Location: $DATA_DIR/"
echo "  Update monthly: bash scripts/download_geoip.sh"
