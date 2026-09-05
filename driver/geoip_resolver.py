"""
════════════════════════════════════════════════════════════
GeoIP Resolver
════════════════════════════════════════════════════════════

Resolves proxy IP addresses to geographic profiles.
Handles edge cases: VPNs, hosting providers, mobile carriers.
Provides fallback for unresolvable IPs.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List
import json

logger = logging.getLogger(__name__)

try:
    import geoip2.database
    HAS_GEOIP2 = True
except ImportError:
    HAS_GEOIP2 = False
    logger.warning("geoip2 not installed. Using fallback GeoIP resolver.")


class IPType(Enum):
    RESIDENTIAL = "residential"
    MOBILE = "mobile"
    DATACENTER = "datacenter"
    VPN = "vpn"
    HOSTING = "hosting"
    CDN = "cdn"
    TOR = "tor"
    UNKNOWN = "unknown"


@dataclass
class GeoProfile:
    """Complete geographic profile for an IP"""
    
    # Location
    country_code: str
    country_name: str
    city: str
    region: str
    latitude: float
    longitude: float
    
    # Cultural
    timezone: str
    language: str
    locale: str
    currency: str
    date_format: str
    
    # Technical
    ip_type: IPType
    asn: str
    isp: str
    organization: str
    
    # Fingerprint hints
    common_screen_resolutions: list
    common_fonts: list
    os_distribution: dict
    
    # Quality
    confidence: float
    fallback_used: bool = False


class GeoIPResolver:
    """
    Resolves IPs to GeoProfiles.
    
    Primary: MaxMind GeoLite2 (local, fast)
    Fallback: IPInfo API (if configured)
    Last resort: Smart defaults
    """
    
    def __init__(self, db_path: str = "./data/geoip/GeoLite2-City.mmdb"):
        self.db_path = Path(db_path)
        self._reader = None
        self._locale_data = self._load_locale_data()
        
        if HAS_GEOIP2 and self.db_path.exists():
            self._reader = geoip2.database.Reader(str(self.db_path))
            logger.info(f"GeoIP database loaded: {self.db_path}")
        else:
            logger.warning(f"GeoIP database not found: {self.db_path}")
            logger.warning("Using fallback resolution (less accurate)")
    
    def _load_locale_data(self) -> dict:
        """Load locale mappings from config"""
        
        locale_file = Path("config/locales.json")
        
        if locale_file.exists():
            with open(locale_file) as f:
                return json.load(f)
        
        # Minimal fallback
        return {
            "country_data": {
                "US": {
                    "name": "United States",
                    "primary_language": "en-US",
                    "timezone": "America/New_York",
                    "currency": "USD",
                    "date_format": "MM/DD/YYYY",
                    "os_distribution": {"Windows": 0.58, "macOS": 0.27, "Linux": 0.06},
                },
                "GB": {
                    "name": "United Kingdom",
                    "primary_language": "en-GB",
                    "timezone": "Europe/London",
                    "currency": "GBP",
                    "date_format": "DD/MM/YYYY",
                    "os_distribution": {"Windows": 0.65, "macOS": 0.22, "Linux": 0.07},
                },
            }
        }
    
    async def resolve(self, ip: str) -> GeoProfile:
        """
        Resolve IP to GeoProfile.
        
        Args:
            ip: The IP address to resolve
            
        Returns:
            Complete GeoProfile with location, language, timezone, etc.
        """
        
        # Validate IP
        if not self._is_valid_ip(ip):
            raise ValueError(f"Invalid IP: {ip}")
        
        # Try local database
        if self._reader:
            try:
                return self._resolve_local(ip)
            except Exception as e:
                logger.warning(f"Local GeoIP failed: {e}")
        
        # Fallback: IPInfo API
        try:
            return await self._resolve_api(ip)
        except Exception as e:
            logger.warning(f"API GeoIP failed: {e}")
        
        # Last resort: smart defaults
        return self._smart_defaults(ip)
    
    def _resolve_local(self, ip: str) -> GeoProfile:
        """Resolve using MaxMind GeoLite2"""
        
        response = self._reader.city(ip)
        
        country_code = response.country.iso_code
        if not country_code:
            raise ValueError(f"No country data for {ip}")
        
        # Get locale data
        locale_info = self._locale_data.get(
            "country_data", {}
        ).get(country_code, {})
        
        if not locale_info:
            # Use generic English data
            locale_info = {
                "name": response.country.name or "Unknown",
                "primary_language": "en-US",
                "timezone": response.location.time_zone or "UTC",
                "currency": "USD",
                "date_format": "MM/DD/YYYY",
                "os_distribution": {"Windows": 0.70, "macOS": 0.20, "Linux": 0.05},
            }
        
        # Classify IP type
        ip_type = self._classify_ip(ip, response)
        
        # Get geolocation from locale data if available
        geo_cities = locale_info.get("geolocation", {}).get("cities", [])
        if geo_cities:
            # Pick a city from the list (weighted by population)
            import random
            city_data = random.choice(geo_cities)
            city = city_data["name"]
            latitude = city_data["lat"]
            longitude = city_data["lng"]
            timezone = city_data.get("tz", locale_info.get("timezone", "UTC"))
        else:
            city = response.city.name or "Unknown"
            latitude = response.location.latitude or 0.0
            longitude = response.location.longitude or 0.0
            timezone = response.location.time_zone or locale_info.get("timezone", "UTC")
        
        return GeoProfile(
            country_code=country_code,
            country_name=locale_info.get("name", response.country.name),
            city=city,
            region=response.subdivisions.most_specific.name or "Unknown",
            latitude=latitude,
            longitude=longitude,
            timezone=timezone,
            language=locale_info.get("primary_language", "en-US"),
            locale=locale_info.get("primary_language", "en-US"),
            currency=locale_info.get("currency", "USD"),
            date_format=locale_info.get("date_format", "MM/DD/YYYY"),
            ip_type=ip_type,
            asn=f"AS{response.autonomous_system_number or 0}",
            isp=response.autonomous_system_organization or "Unknown",
            organization=response.traits.organization or "Unknown",
            common_screen_resolutions=locale_info.get("common_resolutions", []),
            common_fonts=locale_info.get("common_fonts", []),
            os_distribution=locale_info.get("os_distribution", {}),
            confidence=self._calculate_confidence(response),
        )
    
    async def _resolve_api(self, ip: str) -> GeoProfile:
        """Resolve using IPInfo API (fallback)"""
        
        import aiohttp
        
        # This requires an IPInfo API token
        # Get free one at: https://ipinfo.io/
        ipinfo_token = "YOUR_IPINFO_TOKEN"  # Configure this
        
        if ipinfo_token == "YOUR_IPINFO_TOKEN":
            raise RuntimeError("IPInfo token not configured")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://ipinfo.io/{ip}/json?token={ipinfo_token}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                data = await response.json()
        
        country_code = data.get("country", "US")
        locale_info = self._locale_data.get(
            "country_data", {}
        ).get(country_code, {})
        
        # Parse coordinates
        lat, lng = data.get("loc", "0,0").split(",")
        
        return GeoProfile(
            country_code=country_code,
            country_name=locale_info.get("name", data.get("country", "Unknown")),
            city=data.get("city", "Unknown"),
            region=data.get("region", "Unknown"),
            latitude=float(lat),
            longitude=float(lng),
            timezone=data.get("timezone", "UTC"),
            language=locale_info.get("primary_language", "en-US"),
            locale=locale_info.get("primary_language", "en-US"),
            currency=locale_info.get("currency", "USD"),
            date_format=locale_info.get("date_format", "MM/DD/YYYY"),
            ip_type=IPType.UNKNOWN,
            asn="Unknown",
            isp=data.get("org", "Unknown"),
            organization=data.get("org", "Unknown"),
            common_screen_resolutions=locale_info.get("common_resolutions", []),
            common_fonts=locale_info.get("common_fonts", []),
            os_distribution=locale_info.get("os_distribution", {}),
            confidence=0.8,
        )
    
    def _smart_defaults(self, ip: str) -> GeoProfile:
        """Generate safe defaults for unresolvable IP"""
        
        logger.warning(f"Using smart defaults for {ip}")
        
        return GeoProfile(
            country_code="US",
            country_name="United States",
            city="Unknown",
            region="Unknown",
            latitude=39.8283,
            longitude=-98.5795,
            timezone="America/Chicago",
            language="en-US",
            locale="en-US",
            currency="USD",
            date_format="MM/DD/YYYY",
            ip_type=IPType.UNKNOWN,
            asn="Unknown",
            isp="Unknown",
            organization="Unknown",
            common_screen_resolutions=[],
            common_fonts=[],
            os_distribution={"Windows": 0.70, "macOS": 0.20, "Linux": 0.05},
            confidence=0.3,
            fallback_used=True,
        )
    
    def _classify_ip(self, ip: str, response) -> IPType:
        """Classify the type of IP address"""
        
        org = (response.autonomous_system_organization or "").lower()
        
        # Known hosting providers
        hosting = [
            "amazon", "aws", "google", "microsoft", "azure",
            "digitalocean", "linode", "vultr", "ovh", "hetzner",
            "contabo", "choopa", "leaseweb", "softlayer",
        ]
        
        # Known VPN providers
        vpn = [
            "nordvpn", "expressvpn", "surfshark", "private internet",
            "cyberghost", "purevpn", "hidemyass", "ipvanish",
        ]
        
        # Known mobile carriers
        mobile = [
            "verizon", "at&t", "t-mobile", "sprint", "vodafone",
            "orange", "deutsche telekom", "telefonica", "ntt docomo",
        ]
        
        # Known CDN
        cdn = ["cloudflare", "akamai", "fastly", "cloudfront"]
        
        for kw in cdn:
            if kw in org:
                return IPType.CDN
        
        for kw in vpn:
            if kw in org:
                return IPType.VPN
        
        for kw in mobile:
            if kw in org:
                return IPType.MOBILE
        
        for kw in hosting:
            if kw in org:
                return IPType.DATACENTER
        
        return IPType.RESIDENTIAL
    
    def _calculate_confidence(self, response) -> float:
        """Calculate confidence in the GeoIP result"""
        
        confidence = 0.5
        
        if response.country.iso_code:
            confidence += 0.2
        if response.city.name:
            confidence += 0.1
        if response.location.latitude and response.location.longitude:
            confidence += 0.1
        if response.location.time_zone:
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _is_valid_ip(self, ip: str) -> bool:
        """Check if IP is valid and not private"""
        
        import ipaddress
        
        try:
            addr = ipaddress.ip_address(ip)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                return False
            return True
        except ValueError:
            return False
