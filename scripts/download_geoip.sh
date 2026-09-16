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
    # Using the free git.io/GeoLite.mmdb mirror (no license needed) --
    # git.io shortlinks to github.com/P3TERX/GeoLite.mmdb's
    # daily-updated release mirror of MaxMind's real GeoLite2 databases.
    # Replaced the previous DB-IP fallback: DB-IP needed a guessed
    # YYYY-MM dated URL (already bit us once with a wrong date format)
    # and its Cloudflare-fronted host blocks non-browser User-Agents on
    # some clients. This mirror serves the real GeoLite2 data directly,
    # no date-guessing, no signup. Verified live (2026-09-16): both
    # links 301 straight to a working .mmdb download.
    echo "  Using free GeoLite2 mirror (no license key)..."
    echo "  For better accuracy/freshness, set GEOIP_LICENSE_KEY environment variable"
    echo ""

    echo "  Downloading GeoLite2-City..."
    curl -sSL "https://git.io/GeoLite2-City.mmdb" -o "$DATA_DIR/GeoLite2-City.mmdb"

    echo "  Downloading GeoLite2-ASN..."
    curl -sSL "https://git.io/GeoLite2-ASN.mmdb" -o "$DATA_DIR/GeoLite2-ASN.mmdb"
fi

echo ""
echo "  Files downloaded:"
ls -lh "$DATA_DIR/"
echo ""
echo "  ✅ GeoIP databases ready"
echo ""
echo "  Location: $DATA_DIR/"
echo "  Update monthly: bash scripts/download_geoip.sh"
