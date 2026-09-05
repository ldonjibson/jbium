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
    # Using MaxMind license key (more accurate)
    echo "  Using MaxMind license key..."
    
    # GeoLite2 City
    echo "  Downloading GeoLite2-City..."
    curl -sSL "https://download.maxmind.com/geoip/databases/GeoLite2-City/download?suffix=tar.gz" \
        -H "Authorization: Basic $(echo -n "${GEOIP_LICENSE_KEY}:" | base64)" \
        -o "$DATA_DIR/GeoLite2-City.tar.gz"
    
    tar -xzf "$DATA_DIR/GeoLite2-City.tar.gz" -C "$DATA_DIR" --strip-components=1
    rm -f "$DATA_DIR/GeoLite2-City.tar.gz"
    
    # GeoLite2 ASN
    echo "  Downloading GeoLite2-ASN..."
    curl -sSL "https://download.maxmind.com/geoip/databases/GeoLite2-ASN/download?suffix=tar.gz" \
        -H "Authorization: Basic $(echo -n "${GEOIP_LICENSE_KEY}:" | base64)" \
        -o "$DATA_DIR/GeoLite2-ASN.tar.gz"
    
    tar -xzf "$DATA_DIR/GeoLite2-ASN.tar.gz" -C "$DATA_DIR" --strip-components=1
    rm -f "$DATA_DIR/GeoLite2-ASN.tar.gz"

else
    # Using free DB-IP (no license needed)
    echo "  Using free DB-IP database (no license key)..."
    echo "  For better accuracy, set GEOIP_LICENSE_KEY environment variable"
    echo ""
    
    # DB-IP City Lite
    echo "  Downloading dbip-city-lite..."
    wget -q "https://download.db-ip.com/free/dbip-city-lite-$(date +%Y%m).mmdb.gz" \
        -O "$DATA_DIR/dbip-city-lite.mmdb.gz"
    gunzip -f "$DATA_DIR/dbip-city-lite.mmdb.gz"
    mv "$DATA_DIR/dbip-city-lite.mmdb" "$DATA_DIR/GeoLite2-City.mmdb"
    
    # DB-IP ASN Lite
    echo "  Downloading dbip-asn-lite..."
    wget -q "https://download.db-ip.com/free/dbip-asn-lite-$(date +%Y%m).mmdb.gz" \
        -O "$DATA_DIR/dbip-asn-lite.mmdb.gz"
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
