"""
Jbium — Browser Driver
==============================

Python driver for controlling the stealth Chromium browser.

Usage:
    from jbium import Jbium
    from jbium.device_generator import DeviceGenerator
    from jbium.geoip_resolver import GeoIPResolver
"""

__version__ = "1.0.0"
__all__ = [
    "Jbium",
    "DeviceGenerator",
    "GeoIPResolver",
    "FingerprintManager",
    "PlatformInfo",
]

# Convenience imports
from jbium.stealth_browser import Jbium
from jbium.device_generator import DeviceGenerator
from jbium.geoip_resolver import GeoIPResolver
from jbium.fingerprint_manager import FingerprintManager
from jbium.platform_detect import PlatformInfo, detect_platform_info
