"""
Jbium — Browser Driver
==============================

Python driver for controlling the stealth Chromium browser.

Usage:
    from driver.stealth_browser import Jbium
    from driver.device_generator import DeviceGenerator
    from driver.geoip_resolver import GeoIPResolver
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
from driver.stealth_browser import Jbium
from driver.device_generator import DeviceGenerator
from driver.geoip_resolver import GeoIPResolver
from driver.fingerprint_manager import FingerprintManager
from driver.platform_detect import PlatformInfo, detect_platform_info
