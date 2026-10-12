"""
════════════════════════════════════════════════════════════
Jbium Driver
════════════════════════════════════════════════════════════

Controls the stealth Chromium build. Handles:
- Proxy connection and rotation
- GeoIP resolution
- Fingerprint generation
- Browser launch with all stealth parameters
- Page navigation and interaction

Usage:
    from jbium import Jbium
    
    async with Jbium(proxy_url="http://user:pass@proxy:80") as browser:
        page = await browser.new_page()
        await page.goto("https://www.vrbo.com")
        content = await page.get_content()
"""

import asyncio
import json
import logging
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

# Local imports
from jbium.cdp_pipe import CDPPipeConnection, spawn_with_cdp_pipe
from jbium.fingerprint_manager import FingerprintManager
from jbium.geoip_resolver import GeoIPResolver, GeoProfile
from jbium.device_generator import DeviceGenerator, DeviceProfile, ua_brand_lists

logger = logging.getLogger(__name__)

# The installed package's own directory — packaged config/data files
# ship here (jbium/config/...), and must be resolved relative to this
# file rather than the caller's CWD, since a pip-installed package can
# be imported from any working directory.
_PACKAGE_DIR = Path(__file__).parent


# Chrome 120 desktop UI locales: build/config/locales.gni's
# all_chrome_locales minus extended_locales and pseudolocales.
_CHROME_UI_LOCALES = frozenset(
    "af am ar bg bn ca cs da de el en-GB en-US es es-419 et fa fi fil fr gu "
    "he hi hr hu id it ja kn ko lt lv ml mr ms nb nl pl pt-BR pt-PT ro ru sk "
    "sl sr sv sw ta te th tr uk ur vi zh-CN zh-TW".split()
)

# Default accept-languages Chrome ships per UI locale (IDS_ACCEPT_LANGUAGES
# in components/strings/components_locale_settings_*.xtb at
# 120.0.6099.224). UI locales without an entry use the en-US default.
# This is what a fresh Chrome install in that language reports as
# navigator.languages (verified against a stock Chrome for de, en-GB,
# es, ja, ko, zh-CN, ...).
_CHROME_DEFAULT_ACCEPT_LANGUAGES = {
    "en-US": "en-US,en",
    "am": "am,en-GB,en", "ar": "ar,en-US,en", "bg": "bg-BG,bg",
    "bn": "bn-IN,bn,en-US,en", "ca": "ca-ES,ca", "cs": "cs-CZ,cs",
    "da": "da-DK,da,en-US,en", "de": "de-DE,de,en-US,en", "el": "el-GR,el",
    "en-GB": "en-GB,en-US,en", "es": "es-ES,es", "es-419": "es-419,es",
    "et": "et-EE,et,en-US,en", "fa": "fa,en-US,en", "fi": "fi-FI,fi,en-US,en",
    "fil": "fil,fil-PH,tl,en-US,en", "fr": "fr-FR,fr,en-US,en",
    "gu": "gu-IN,gu,hi-IN,hi,en-US,en", "he": "he-IL,he,en-US,en",
    "hi": "hi-IN,hi,en-US,en", "hr": "hr-HR,hr,en-US,en", "hu": "hu-HU,hu,en-US,en",
    "id": "id-ID,id,en-US,en", "it": "it-IT,it,en-US,en", "ja": "ja,en-US,en",
    "kn": "kn-IN,kn,en-US,en", "ko": "ko-KR,ko,en-US,en", "lt": "lt,en-US,en,ru,pl",
    "lv": "lv-LV,lv,en-US,en", "ml": "ml-IN,ml,en-US,en",
    "mr": "mr-IN,mr,hi-IN,hi,en-US,en", "nb": "nb-NO,nb,no,nn,en-US,en",
    "nl": "nl-NL,nl,en-US,en", "pl": "pl-PL,pl,en-US,en", "pt-BR": "pt-BR,pt,en-US,en",
    "pt-PT": "pt-PT,pt,en-US,en", "ro": "ro-RO,ro,en-US,en", "ru": "ru-RU,ru,en-US,en",
    "sk": "sk-SK,sk,cs,en-US,en", "sl": "sl-SI,sl,en-GB,en", "sr": "sr-RS,sr,en-US,en",
    "sv": "sv-SE,sv,en-US,en", "sw": "sw,en-GB,en", "ta": "ta-IN,ta,en-US,en",
    "te": "te-IN,te,hi-IN,hi,en-US,en", "th": "th-TH,th", "tr": "tr-TR,tr,en-US,en",
    "uk": "uk-UA,uk,en-US,en", "vi": "vi-VN,vi,fr-FR,fr,en-US,en",
    "zh-CN": "zh-CN,zh", "zh-TW": "zh-TW,zh,en-US,en",
}


def chrome_ui_locale(locale: str) -> str:
    """
    The UI locale Chrome 120 picks for a requested locale — a port of
    ui/base/l10n/l10n_util.cc CheckAndResolveLocale (desktop), e.g.
    "ja-JP" -> "ja", "es-MX" -> "es-419", "en-AU" -> "en-GB",
    "zh-HK" -> "zh-TW"; en-US when nothing matches.
    """

    locale = locale.replace("_", "-")
    if locale in _CHROME_UI_LOCALES:
        return locale
    lang, _, region = locale.partition("-")
    lang, region = lang.lower(), region.lower()
    if region:
        if lang == "es" and region != "es":
            candidate = "es-419"
        elif lang == "pt" and region != "br":
            candidate = "pt-PT"
        elif lang == "zh":
            candidate = "zh-TW" if region in ("hk", "mo") else "zh-CN"
        elif lang == "en":
            candidate = "en-US" if region in ("lr", "ph") else "en-GB"
        else:
            candidate = lang
        if candidate in _CHROME_UI_LOCALES:
            return candidate
    aliases = {"en": "en-US", "iw": "he", "no": "nb", "pt": "pt-BR", "tl": "fil", "zh": "zh-CN"}
    return aliases.get(lang, lang if lang in _CHROME_UI_LOCALES else "en-US")


@dataclass
class StealthSession:
    """Complete stealth session configuration"""
    
    # Proxy
    proxy_url: str
    proxy_ip: str
    
    # GeoIP
    geo_profile: GeoProfile
    
    # Device
    device_profile: DeviceProfile
    
    # Browser
    browser_process: Optional[subprocess.Popen] = None
    # Always None: CDP runs over --remote-debugging-pipe, so there is no
    # DevTools WebSocket URL. Kept so existing callers don't break.
    ws_url: Optional[str] = None
    env_vars: Optional[Dict[str, str]] = None
    
    # Metadata
    session_id: str = ""
    created_at: float = 0.0


class Jbium:
    """
    High-level stealth browser controller.
    
    Handles the complete lifecycle:
    1. Resolve proxy → get exit IP
    2. GeoIP lookup on IP
    3. Generate matching device fingerprint
    4. Set environment variables
    5. Launch stealth Chromium
    6. Provide page interaction API
    """
    
    def __init__(
        self,
        config_path: str = None,
        browser_path: str = None,
    ):
        # Packaged defaults live inside the installed package itself
        # (jbium/config/...) — resolved relative to this file, not the
        # caller's CWD, since pip-installed code can be imported from
        # anywhere. An explicit config_path still overrides this.
        config_path = config_path or str(_PACKAGE_DIR / "config" / "settings.yaml")
        self.config = self._load_config(config_path)
        self.browser_path = browser_path or self._find_browser()
        
        # Managers
        self.geoip_resolver = GeoIPResolver(
            db_path=self.config.get("geoip", {}).get(
                "database_path", "./data/geoip/GeoLite2-City.mmdb"
            ),
            asn_db_path=self.config.get("geoip", {}).get(
                "asn_database_path", "./data/geoip/GeoLite2-ASN.mmdb"
            ),
        )
        self.fingerprint_manager = FingerprintManager()
        self.device_generator = DeviceGenerator(
            templates_path=str(_PACKAGE_DIR / "config" / "fingerprints.json")
        )
        
        # State
        self._session: Optional[StealthSession] = None
        self._browser_process: Optional[subprocess.Popen] = None
        self._pages: List["StealthPage"] = []
        self._proxy_auth_extension_dir: Optional[str] = None
        self._user_data_dir: Optional[str] = None
        self._xvfb_process: Optional[subprocess.Popen] = None
        self._fontconfig_dir: Optional[str] = None

        # CDP transport: --remote-debugging-pipe (see driver/cdp_pipe.py).
        # No TCP debugging port exists unless launch(expose_cdp_port=True)
        # explicitly asks for one, in which case _debug_port holds it.
        self._conn: Optional[CDPPipeConnection] = None
        self._debug_port: Optional[int] = None

        logger.info("Jbium initialized")
        logger.info(f"  Browser: {self.browser_path}")
        logger.info(f"  Config: {config_path}")
    
    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────
    
    async def launch(
        self,
        proxy_url: str,
        headless: bool = False,
        fingerprint_profile: Optional[str] = None,
        geoip_override: Optional[Dict] = None,
        extensions: Optional[List[str]] = None,
        fingerprint_overrides: Optional[Dict[str, str]] = None,
        expose_cdp_port: bool = False,
    ) -> StealthSession:
        """
        Launch stealth browser with complete configuration.

        Args:
            proxy_url: Proxy URL (http://user:pass@host:port)
            headless: Run without UI (false recommended for DataDome)
            fingerprint_profile: Optional specific device template name
            geoip_override: Optional manual GeoIP data
            extensions: Optional list of unpacked extension directory paths
                to load at startup. Chrome extensions are unreliable under
                --headless=new, so these are ignored (with a warning) when
                headless=True rather than silently loading nothing.
            fingerprint_overrides: Optional STEALTH_* env var overrides,
                applied after the generated profile — e.g.
                {"STEALTH_GPU_VENDOR": "Custom Vendor Inc."} to force one
                property without hand-building a whole device template.
            expose_cdp_port: The driver itself always talks to the browser
                over --remote-debugging-pipe, which no web page can reach.
                Set this only to ALSO open a TCP debugging port for an
                external CDP client (e.g. Playwright's connect_over_cdp).
                That port is reachable from page JavaScript
                (fetch('http://127.0.0.1:<port>/json/version')), so it
                makes the session detectable as automated — leave it off
                for anything stealth-sensitive.

        Returns:
            StealthSession with all configuration
        """
        
        logger.info("Launching stealth browser...")
        
        # Step 1: Get proxy exit IP
        proxy_ip = await self._get_proxy_ip(proxy_url)
        logger.info(f"  Proxy IP: {proxy_ip}")
        
        # Step 2: Resolve GeoIP
        if geoip_override:
            geo_profile = self._manual_geoip(geoip_override)
        else:
            geo_profile = await self.geoip_resolver.resolve(proxy_ip)
        
        logger.info(f"  Location: {geo_profile.city}, {geo_profile.country_name}")
        logger.info(f"  Timezone: {geo_profile.timezone}")
        logger.info(f"  Language: {geo_profile.language}")
        
        # Step 3: Generate device fingerprint
        device_profile = self.device_generator.generate(
            geo_profile,
            preferred_template=fingerprint_profile
        )
        
        logger.info(f"  Device: {device_profile.os} | {device_profile.cpu_model}")
        logger.info(f"  Screen: {device_profile.screen_width}x{device_profile.screen_height}")
        logger.info(f"  GPU: {device_profile.gpu_renderer}")
        
        # Step 4: Set environment variables
        env_vars = self._generate_env_vars(
            device_profile, geo_profile, proxy_url
        )

        # Explicit per-property overrides win over the generated profile —
        # applied last, after every STEALTH_* default is already set, so a
        # caller can force one property without regenerating a whole
        # device profile (e.g. fingerprint_overrides={"STEALTH_GPU_VENDOR":
        # "Custom Vendor Inc."}).
        if fingerprint_overrides:
            env_vars.update(fingerprint_overrides)

        if extensions and headless:
            logger.warning(
                "  extensions requested but headless=True — Chrome "
                "extensions are unreliable under --headless=new and will "
                "not be loaded"
            )
            extensions = None

        # Step 5: Launch browser
        session = StealthSession(
            proxy_url=proxy_url,
            proxy_ip=proxy_ip,
            geo_profile=geo_profile,
            device_profile=device_profile,
            env_vars=env_vars,
            session_id=f"session_{int(time.time() * 1000)}",
            created_at=time.time(),
        )

        self._session = session
        self._browser_process = await self._spawn_browser(
            proxy_url=proxy_url,
            headless=headless,
            env_vars=env_vars,
            device_profile=device_profile,
            geo_profile=geo_profile,
            extensions=extensions,
            expose_cdp_port=expose_cdp_port,
        )
        session.browser_process = self._browser_process

        # Step 6: Wait for the browser to answer on the CDP pipe
        await self._wait_for_browser_ready(device_profile)

        if expose_cdp_port:
            self._debug_port = await self._read_devtools_active_port()
            logger.warning(
                f"  CDP TCP port {self._debug_port} is open (expose_cdp_port=True) — "
                "any page can detect it; use only for external CDP tooling"
            )

        logger.info("  ✅ Browser launched")
        logger.info(f"  Session: {session.session_id}")
        
        return session
    
    def client_hints_override(self) -> Dict[str, Any]:
        """
        Params for CDP Emulation.setUserAgentOverride matching this
        session's profile. new_page() applies them automatically; pages
        opened by anything else (e.g. Playwright attached through
        launch(expose_cdp_port=True)) must send them once per page before
        navigating, or their Sec-CH-UA* headers report the real build.
        """

        if not self._session:
            raise RuntimeError("Browser is not running — call launch() first")
        return self._user_agent_override_params(self._session.device_profile)

    async def new_page(self) -> "StealthPage":
        """Create a new page/tab"""

        if not self._conn:
            raise RuntimeError("Browser is not running — call launch() first")

        # Create the tab, then attach to it as a flattened session so its
        # commands and events share the one debugging pipe (tagged with
        # sessionId) — the pipe equivalent of the old per-page
        # /devtools/page/<id> WebSocket.
        target = await self._cdp_command("Target.createTarget", {
            "url": "about:blank"
        })
        target_id = target["targetId"]
        attached = await self._cdp_command("Target.attachToTarget", {
            "targetId": target_id,
            "flatten": True,
        })

        page = StealthPage(
            browser=self,
            connection=self._conn,
            target_id=target_id,
            session_id=attached["sessionId"],
            session=self._session,
        )

        # User-Agent Client Hints for this page, before anything loads.
        # With --user-agent set, the browser process still builds the
        # Sec-CH-UA* request headers from the real build's metadata
        # (components/embedder_support/user_agent_utils.cc returns the
        # low-entropy defaults — real OS as Sec-CH-UA-Platform, the
        # Chromium-only brand list — and empty high-entropy values).
        # Patch 007 only rewrites the JS-side navigator.userAgentData,
        # so without this the headers contradict the UA string and JS.
        # Emulation.setUserAgentOverride with userAgentMetadata replaces
        # both the headers and navigator.userAgentData for this target
        # (emulation_handler.cc ApplyUserAgentMetadataOverrides).
        # A failure here is fatal: a page with mismatched Client Hints
        # is worse than no page.
        if self._session:
            try:
                await page._command(
                    "Emulation.setUserAgentOverride", self.client_hints_override()
                )
            except Exception:
                await page.close()
                try:
                    await self._cdp_command("Target.closeTarget", {"targetId": target_id})
                except Exception:
                    pass
                raise

        # Geolocation override (replaces the old in-source patch):
        # serve the GeoIP profile's coordinates (with per-session
        # jitter) instead of any real location. CDP's
        # Emulation.setGeolocationOverride covers
        # navigator.geolocation consistently.
        #
        # Sent through page._command() (not a raw page_ws.send())
        # so the response is read and matched by the same id
        # counter every other command on this page uses — a raw
        # send with a hardcoded id would leave its response
        # unread on the socket, where it could be picked up by
        # the next real command as a false match.
        if self._session and getattr(self._session, "geo_profile", None):
            geo = self._session.geo_profile
            jitter_lat = random.uniform(-0.05, 0.05)
            jitter_lng = random.uniform(-0.05, 0.05)
            try:
                await page._command("Emulation.setGeolocationOverride", {
                    "latitude": round(geo.latitude + jitter_lat, 6),
                    "longitude": round(geo.longitude + jitter_lng, 6),
                    "accuracy": 100,
                })
                logger.debug(f"  Geolocation override: "
                             f"{geo.latitude + jitter_lat:.4f}, "
                             f"{geo.longitude + jitter_lng:.4f}")
            except Exception as e:
                logger.warning(f"  Geolocation override failed: {e}")

        self._pages.append(page)
        return page
    
    async def close(self):
        """Clean shutdown"""
        
        logger.info("Shutting down stealth browser...")
        
        # Close all pages
        for page in self._pages:
            try:
                await page.close()
            except Exception as e:
                logger.warning(f"Error closing page: {e}")
        self._pages = []

        # Closing our end of the debugging pipe is the browser's signal
        # to shut down cleanly (devtools_pipe_handler.cc treats EOF on its
        # command pipe as the client disconnecting). Give it a few
        # seconds, then fall back to terminate/kill.
        if self._conn:
            self._conn.close()
            self._conn = None

        process = self._browser_process
        if process:
            loop = asyncio.get_running_loop()
            for stop in (None, process.terminate, process.kill):
                if stop:
                    stop()
                try:
                    await loop.run_in_executor(None, process.wait, 5)
                    break
                except subprocess.TimeoutExpired:
                    continue
            self._browser_process = None
        self._debug_port = None

        # Stop this session's virtual display (after the browser, which
        # is still connected to it until it exits).
        xvfb = self._xvfb_process
        if xvfb:
            xvfb.terminate()
            try:
                await asyncio.get_running_loop().run_in_executor(None, xvfb.wait, 5)
            except subprocess.TimeoutExpired:
                xvfb.kill()
            self._xvfb_process = None

        # Remove the temporary proxy-auth extension directory, if one was
        # generated for this session (contains the proxy password on disk).
        if self._proxy_auth_extension_dir:
            shutil.rmtree(self._proxy_auth_extension_dir, ignore_errors=True)
            self._proxy_auth_extension_dir = None

        # Remove the throwaway profile (cookies, cache, local storage) —
        # it is uniquely named per launch and never reused.
        if self._user_data_dir:
            shutil.rmtree(self._user_data_dir, ignore_errors=True)
            self._user_data_dir = None

        # Remove this session's private fontconfig directory (it holds
        # only the generated fonts.conf and fontconfig's cache; the font
        # files themselves live in the shared bundle).
        if self._fontconfig_dir:
            shutil.rmtree(self._fontconfig_dir, ignore_errors=True)
            self._fontconfig_dir = None

        logger.info("  ✅ Browser shut down")
    
    # ─────────────────────────────────────────────
    # Context manager support
    # ─────────────────────────────────────────────
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    # ─────────────────────────────────────────────
    # Internal methods
    # ─────────────────────────────────────────────
    
    def _load_config(self, config_path: str) -> dict:
        """Load YAML configuration"""
        
        import yaml
        
        config_file = Path(config_path)
        if config_file.exists():
            with open(config_file, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        
        # Defaults — binary_path empty means "auto-detect" via
        # jbium.platform_detect.find_browser_binary() (see _find_browser).
        return {
            "browser": {
                "binary_path": "",
                "headless": False,
            },
            "proxy": {
                "provider": "webshare",
                "endpoint": "p.webshare.io",
                "port": 80,
                "username_prefix": os.environ.get("STEALTH_WEBSHARE_USERNAME", ""),
                "password": os.environ.get("STEALTH_WEBSHARE_PASSWORD", ""),
            },
            "geoip": {
                "enabled": True,
                "database_path": "./data/geoip/GeoLite2-City.mmdb",
            },
            "anti_detection": {
                "filter_webrtc": True,
                "spoof_battery": True,
                "canvas_noise": True,
                "webgl_spoof": True,
                "font_filter": True,
            },
        }
    
    def _find_browser(self) -> str:
        """Find the stealth browser binary (cross-platform: Windows/macOS/Linux)"""

        # Check config first, but only if it actually points at a real file —
        # a stale/default configured path should fall through to the
        # cross-platform search below rather than hard-failing.
        configured = self.config.get("browser", {}).get("binary_path")
        if configured and Path(configured).exists():
            return configured

        from jbium.platform_detect import find_browser_binary

        try:
            return str(find_browser_binary())
        except FileNotFoundError:
            raise FileNotFoundError(
                "Stealth browser binary not found. Run `jbium fetch` to "
                "download it, or set binary_path in config if you built "
                "it yourself."
            )
    
    async def _get_proxy_ip(self, proxy_url: str) -> str:
        """Get the actual exit IP of the proxy"""
        
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://ipv4.webshare.io/",
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    ip = (await response.text()).strip()
                    # Validate IP format
                    parts = ip.split(".")
                    if len(parts) == 4:
                        return ip
        except Exception as e:
            logger.warning(f"Could not get proxy IP: {e}")
        
        raise RuntimeError(f"Failed to get proxy IP for {proxy_url}")
    
    def _manual_geoip(self, override: Dict) -> GeoProfile:
        """Create GeoProfile from manual override data"""
        
        return GeoProfile(
            country_code=override.get("country_code", "US"),
            country_name=override.get("country_name", "United States"),
            city=override.get("city", "Unknown"),
            region=override.get("region", "Unknown"),
            latitude=override.get("latitude", 39.8283),
            longitude=override.get("longitude", -98.5795),
            timezone=override.get("timezone", "America/New_York"),
            language=override.get("language", "en-US"),
            locale=override.get("locale", "en-US"),
            currency=override.get("currency", "USD"),
            date_format=override.get("date_format", "MM/DD/YYYY"),
            ip_type=override.get("ip_type", "residential"),
            asn=override.get("asn", "Unknown"),
            isp=override.get("isp", "Unknown"),
            organization=override.get("organization", "Unknown"),
            common_screen_resolutions=override.get("common_resolutions", []),
            common_fonts=override.get("common_fonts", []),
            os_distribution=override.get("os_distribution", {}),
            confidence=override.get("confidence", 1.0),
        )
    
    def _generate_env_vars(
        self,
        device: DeviceProfile,
        geo: GeoProfile,
        proxy_url: str,
    ) -> Dict[str, str]:
        """
        Generate the environment variables the stealth Chromium build
        reads via getenv(). Only variables some patch actually reads are
        set (verified against patches/*/apply.sh) — see
        packaging/API.md for the full table.
        """

        env_vars = {}

        # ── Navigator + UA Client Hints (Patch 007) ──
        env_vars["STEALTH_CPU_CORES"] = str(device.cpu_cores)
        env_vars["STEALTH_DEVICE_MEMORY"] = str(device.ram_gb)
        env_vars["STEALTH_PLATFORM"] = device.platform
        env_vars["STEALTH_MAX_TOUCH_POINTS"] = str(
            10 if device.touch_support else 0
        )
        env_vars["STEALTH_UA_PLATFORM"] = device.ua_platform
        env_vars["STEALTH_UA_PLATFORM_VERSION"] = device.ua_platform_version
        # Without these the patch serves the build machine's real values
        # (e.g. "x86" for an Apple Silicon profile).
        env_vars["STEALTH_UA_ARCHITECTURE"] = device.architecture
        env_vars["STEALTH_UA_BITNESS"] = device.bitness
        env_vars["STEALTH_UA_MODEL"] = ""  # desktop devices report no model
        # Brand lists derived from the exact version the User-Agent
        # string claims. Binaries built before the patch-007 fix carry a
        # hard-coded 120.0.6099.109 fallback that would contradict a .224
        # UA; setting these always wins over the fallback.
        brands, full_brands = ua_brand_lists(self._chrome_full_version(device))
        env_vars["STEALTH_UA_BRANDS"] = "|".join(f"{b}={v}" for b, v in brands)
        env_vars["STEALTH_UA_FULL_BRANDS"] = "|".join(f"{b}={v}" for b, v in full_brands)

        # ── Languages (Patch 008) ──
        # A plain comma-separated list: patch 008 splits it on commas for
        # navigator.languages (Blink's ParseAndSanitize does not strip
        # ";q=" parameters) and appends its own descending q-values for
        # the Accept-Language header.
        env_vars["STEALTH_GEO_LANGUAGES"] = ",".join(self._accept_languages(geo))

        # Timezone: TZ is honored by libc/ICU/V8 Date directly, keeping
        # getTimezoneOffset(), Intl, and date formatting consistent with
        # the proxy IP's location (replaces the old v8 source patch).
        env_vars["TZ"] = geo.timezone

        # ── Noise seeds ──
        # Canvas noise (Patch 004). The audio seed is read by Patch 011's
        # helper, which is deliberately not wired in yet (see its
        # docstring). No patch reads a WebGL seed — 005 only swaps the
        # GPU strings below — so none is set.
        env_vars["STEALTH_CANVAS_SEED"] = str(device.canvas_seed)
        env_vars["STEALTH_AUDIO_SEED"] = str(device.audio_seed)

        # ── GPU strings (Patch 005) ──
        # Unmasked vendor/renderer, in the exact form Chrome 120 reports
        # them for the profile's OS (see config/fingerprints.json).
        # STEALTH_GPU_VERSION / STEALTH_GPU_GLSL_VERSION are deliberately
        # NOT set: Chrome's WebGL VERSION / SHADING_LANGUAGE_VERSION inner
        # strings are fixed constants ("OpenGL ES 2.0 Chromium" /
        # "OpenGL ES GLSL ES 1.0 Chromium", 3.0 for WebGL2 —
        # gpu/command_buffer/service/gl_utils.cc), the same on every
        # machine, so the real values are already the right ones.
        env_vars["STEALTH_GPU_VENDOR"] = device.gpu_vendor
        env_vars["STEALTH_GPU_RENDERER"] = device.gpu_renderer

        # ── Font profile (consumed by the fontconfig tooling, Patch 006) ──
        # Keyed on ua_platform ("Windows"/"macOS"/"Linux"): the Linux
        # templates' os field is "Ubuntu 22.04", so matching on device.os
        # left Linux profiles without a font profile at all.
        os_font_map = {
            "Windows": "WINDOWS_11",
            "macOS": "MACOS_SONOMA",
            "Linux": "UBUNTU",
        }
        if device.ua_platform in os_font_map:
            env_vars["STEALTH_FONT_OS"] = os_font_map[device.ua_platform]

        # Map region to font region
        region_font_map = {
            "JP": "JAPAN",
            "KR": "KOREA",
            "CN": "CHINA",
            "TW": "CHINA",
        }
        if geo.country_code in region_font_map:
            env_vars["STEALTH_FONT_REGION"] = region_font_map[geo.country_code]
        else:
            env_vars["STEALTH_FONT_REGION"] = "GENERIC"
        
        # ── WebRTC ──
        # Nothing to set here: no patch reads an env var for WebRTC.
        # ICE-candidate filtering is the --webrtc-ip-handling-policy
        # switch added in _spawn_browser.

        # ── Battery API (Patch 010) ──
        # Deliberately NOT set. Patch 010's getters return their
        # hardcoded constants (chargingTime=1800, dischargingTime=14400)
        # whenever either var is present, *regardless of charging state*
        # -- a spec violation (the Battery Status spec requires
        # dischargingTime=Infinity while charging, and vice versa) that
        # any script can flag in one line, and the identical constants
        # across every jbium session ever built are a cross-session
        # cluster signature. Unset, the patch passes the real readings
        # through: on a battery-less server that's the desktop-AC profile
        # (level=1, charging=true, chargingTime=0,
        # dischargingTime=Infinity) -- spec-consistent, and exactly what
        # every real desktop Chrome reports. Verified live (2026-10-06):
        # setting these vars produced the spec FAIL; leaving them unset
        # produces the desktop-AC values.
        # Patch 010's constant-return design needs the rebuild to fix
        # properly (see patches/010_misc/apply.sh); until then, the
        # real-readings passthrough is the safer default. Callers can
        # still force a spoof via launch(fingerprint_overrides=...).

        return env_vars

    def _chrome_full_version(self, device: DeviceProfile) -> str:
        """The full Chrome version the profile's User-Agent string claims."""

        if device.chrome_full_version:
            return device.chrome_full_version
        # Profiles built without chrome_full_version (e.g. by hand):
        # recover it from the UA string itself.
        marker = "Chrome/"
        idx = device.user_agent.find(marker)
        if idx == -1:
            raise ValueError(f"Cannot determine Chrome version from UA: {device.user_agent!r}")
        return device.user_agent[idx + len(marker):].split(" ", 1)[0]

    @staticmethod
    def _ui_locale(geo: GeoProfile) -> str:
        """Chrome UI locale for the profile's primary language (e.g. "ja-JP" -> "ja")."""

        return chrome_ui_locale(geo.locale or geo.language or "en-US")

    @staticmethod
    def _accept_languages(geo: GeoProfile) -> List[str]:
        """
        The profile's language list, most preferred first: exactly what a
        fresh Chrome install in that UI language reports (e.g.
        de-DE,de,en-US,en; en-GB,en-US,en; ja,en-US,en; en-US,en), so
        navigator.languages, Accept-Language and the UI locale that
        drives Intl all agree the way they do on a real install.
        """

        default = _CHROME_DEFAULT_ACCEPT_LANGUAGES.get(
            Jbium._ui_locale(geo), _CHROME_DEFAULT_ACCEPT_LANGUAGES["en-US"]
        )
        return default.split(",")

    def _user_agent_override_params(self, device: DeviceProfile) -> Dict[str, Any]:
        """
        Emulation.setUserAgentOverride params that make the Sec-CH-UA*
        request headers and navigator.userAgentData match the profile
        (the same values patch 007 serves from the env vars above).
        acceptLanguage is omitted on purpose: patch 008 already makes the
        Accept-Language header match navigator.languages.
        """

        brands, full_brands = ua_brand_lists(self._chrome_full_version(device))
        return {
            "userAgent": device.user_agent,
            "platform": device.platform,
            "userAgentMetadata": {
                "brands": [{"brand": b, "version": v} for b, v in brands],
                "fullVersionList": [{"brand": b, "version": v} for b, v in full_brands],
                "fullVersion": self._chrome_full_version(device),
                "platform": device.ua_platform,
                "platformVersion": device.ua_platform_version,
                "architecture": device.architecture,
                "model": "",
                "mobile": False,
                "bitness": device.bitness,
                "wow64": False,
            },
        }

    async def _spawn_browser(
        self,
        proxy_url: str,
        headless: bool,
        env_vars: Dict[str, str],
        device_profile: DeviceProfile,
        geo_profile: GeoProfile,
        extensions: Optional[List[str]] = None,
        expose_cdp_port: bool = False,
    ) -> subprocess.Popen:
        """Launch the stealth Chromium process"""

        # Build command line args
        args = [self.browser_path]

        # Chrome refuses to start as root at all without --no-sandbox
        # ("Running as root without --no-sandbox is not supported",
        # zygote_host_impl_linux.cc). Beyond that, the SUID sandbox helper
        # (chrome-sandbox) only works if it's owned root:root with the
        # setuid bit set, which a plain tar-extracted release archive
        # never sets up -- and even non-root users hit a hard "No usable
        # sandbox!" FATAL crash on cloud VMs/containers whose kernel
        # doesn't allow unprivileged user namespaces (verified live on a
        # non-root Ubuntu EC2 box). Auto-detect rather than relying on
        # someone remembering to add it to config/settings.yaml's
        # extra_args: an earlier fix this session only hand-edited one
        # box's local copy and never made it into source, so a fresh
        # install on a new box hit the exact same crash again -- so
        # always disable the sandbox rather than gating on root only.
        args.append("--no-sandbox")

        # User-Agent
        args.append(f"--user-agent={device_profile.user_agent}")

        # Window size (use device screen size)
        if not headless:
            args.append(f"--window-size={device_profile.screen_width},{device_profile.screen_height}")

        # Screen size / pixel ratio (Linux, headed). No patch spoofs
        # screen.*: the page sees the X display the browser runs on, which
        # on a server is typically Xvfb's 1280x1024 default. Give each
        # session its own Xvfb sized to the profile's physical resolution
        # and force the profile's device pixel ratio, so screen.width/
        # height, devicePixelRatio, colorDepth and the matching CSS media
        # queries all report the profile. (availWidth/availHeight equal
        # the screen size: there is no desktop panel on a bare Xvfb.)
        virtual_display = None
        if (
            not headless
            and sys.platform.startswith("linux")
            and self.config.get("browser", {}).get("virtual_display", True)
        ):
            virtual_display = await self._start_virtual_display(device_profile)
            if virtual_display:
                args.append(f"--force-device-scale-factor={device_profile.device_pixel_ratio:g}")
                args.append("--window-position=0,0")
        if (
            not headless
            and sys.platform.startswith("linux")
            and not virtual_display
            and not os.environ.get("DISPLAY")
            and not os.environ.get("WAYLAND_DISPLAY")
        ):
            # Otherwise the browser exits at once with only "Missing X
            # server or $DISPLAY" on stderr.
            raise RuntimeError(
                "Headed launch on Linux needs a display, and none is available: "
                "$DISPLAY is unset and no virtual display was started. Install "
                "Xvfb (apt-get install xvfb) so the driver can start one per "
                "session, run under xvfb-run, or launch with headless=True."
            )

        # Headless (careful — use our custom headless mode)
        if headless:
            args.append("--headless=new")  # New headless mode (less detectable)
            args.append("--disable-gpu")

        # WebRTC IP leak prevention. Patch 010's own docstring says this is
        # "handled via driver flags" rather than a renderer patch (WebRTC's
        # ICE candidate plumbing lives in the browser process, so patching
        # Blink wouldn't touch it) — but the flag was never actually added
        # here, only an env var (STEALTH_FILTER_WEBRTC) that no C++ code
        # reads. Confirmed live: a CreepJS run leaked this box's real
        # public IP through host/srflx ICE candidates despite a working
        # proxy.
        #
        # First attempt used --force-webrtc-ip-handling-policy — wrong
        # switch. Verified against this box's own pinned Chromium source:
        # that one (content/public/common/content_switches.cc) is only
        # ever read by content_shell (content/shell/browser/shell.cc), a
        # test harness, not the real `chrome` target we build. The real
        # browser maps a *different* command-line switch,
        # chrome::switches::kWebRtcIPHandlingPolicy = "webrtc-ip-handling-
        # policy" (chrome/common/chrome_switches.cc), through
        # ChromeCommandLinePrefStore into the kWebRTCIPHandlingPolicy
        # pref, which chrome/browser/renderer_preferences_util.cc then
        # copies into RendererPreferences for the actual PeerConnection
        # code to enforce. The value string itself,
        # "disable_non_proxied_udp" (permit only proxied UDP, so no
        # local/public interface IP is ever surfaced as a candidate), was
        # already correct per
        # third_party/blink/common/peerconnection/webrtc_ip_handling_policy.cc
        # — only the flag name was wrong.
        if self.config.get("browser", {}).get("filter_webrtc", True):
            args.append("--webrtc-ip-handling-policy=disable_non_proxied_udp")

        # Proxy — Chrome's --proxy-server flag takes a bare scheme://host:port
        # and doesn't understand embedded user:pass@ credentials; a URL with
        # userinfo in it fails Chrome's proxy-server parsing outright and
        # surfaces later as net::ERR_NO_SUPPORTED_PROXIES on first navigation
        # (found live: launch() and new_page() both succeed since neither
        # touches the proxy, only goto() actually routes traffic through it).
        # Credentials for an authenticated proxy have to be supplied a
        # different way — see _build_proxy_auth_extension below.
        parsed_proxy = urlsplit(proxy_url)
        if parsed_proxy.username:
            stripped_netloc = parsed_proxy.hostname or ""
            if parsed_proxy.port:
                stripped_netloc += f":{parsed_proxy.port}"
            proxy_server_value = urlunsplit((
                parsed_proxy.scheme, stripped_netloc, parsed_proxy.path,
                parsed_proxy.query, parsed_proxy.fragment,
            ))
        else:
            proxy_server_value = proxy_url
        args.append(f"--proxy-server={proxy_server_value}")

        # Extensions — both flags are needed together: --load-extension
        # alone is silently ignored under Chrome's automation-controlled
        # startup path unless paired with --disable-extensions-except
        # naming the same directories.
        extensions = list(extensions) if extensions else []

        if parsed_proxy.username:
            if headless:
                # --headless=new loads MV2 extensions unreliably (same
                # reason launch() already refuses caller-supplied
                # extensions under headless), so an authenticated proxy
                # can silently fail to authenticate here. Surfacing that
                # now is more useful than a confusing ERR_TUNNEL/407 later.
                logger.warning(
                    "  Proxy has embedded credentials but headless=True — "
                    "the auth extension is unreliable under --headless=new "
                    "and the proxy may fail to authenticate"
                )
            auth_extension_dir = self._build_proxy_auth_extension(
                parsed_proxy.username, parsed_proxy.password or ""
            )
            self._proxy_auth_extension_dir = auth_extension_dir
            extensions.append(auth_extension_dir)

        if extensions:
            paths = ",".join(str(Path(p).resolve()) for p in extensions)
            args.append(f"--disable-extensions-except={paths}")
            args.append(f"--load-extension={paths}")
        
        # User data directory (fresh) — tempfile.gettempdir() resolves to
        # %TEMP% on Windows and /tmp on Linux/macOS, unlike a hardcoded
        # "/tmp/..." path which isn't valid on native Windows.
        #
        # int(time.time()) only has 1-second resolution -- confirmed live
        # running concurrent launches: two Jbium.launch() calls landing in
        # the same wall-clock second got the *identical* user-data-dir.
        # Chrome's single-instance-per-profile lock then made the second
        # process silently forward its request to the first ("Opening in
        # existing browser session", exit code 0) and exit without ever
        # opening its own CDP debug port -- which _wait_for_browser_ready
        # then dutifully timed out waiting for, 30 seconds later, with no
        # indication of the real cause. uuid4 makes a collision virtually
        # impossible regardless of how many launches happen in the same
        # instant.
        user_data_dir = str(
            Path(tempfile.gettempdir()) / f"stealth-profile-{uuid.uuid4().hex}"
        )
        args.append(f"--user-data-dir={user_data_dir}")
        self._user_data_dir = user_data_dir

        # CDP transport: a pipe on fds 3/4 instead of a TCP port, so there
        # is no local HTTP/WebSocket endpoint a page could probe (see
        # driver/cdp_pipe.py).
        args.append("--remote-debugging-pipe")

        # No field-trial testing config. Non-Chrome-branded builds apply
        # testing/variations/fieldtrial_testing_config.json (917 studies in
        # the pinned tree) by default, even with is_official_build=true
        # (components/variations/BUILD.gn fieldtrial_testing_enabled). Real
        # Chrome gets only its server-assigned slice of experiments, so
        # "every experiment on at once" is itself a fingerprint -- visibly on
        # the wire, where the HTTP2 study adds a GREASE SETTINGS entry
        # (e.g. 64026:...) that stable Chrome doesn't send on its first
        # connection. Builds with disable_fieldtrial_testing_config=true
        # (config/args_*.gn) don't need this; it's harmless there.
        args.append("--disable-field-trial-config")
        if expose_cdp_port:
            # Explicit opt-in only (launch() docstring). Port 0 lets the
            # browser pick a free port and record it in
            # <user-data-dir>/DevToolsActivePort.
            args.append("--remote-debugging-port=0")

        # UI locale = the profile's primary language. It decides the
        # renderer's ICU default locale, i.e. what
        # Intl.DateTimeFormat().resolvedOptions().locale and
        # toLocaleString() use; leaving it at the host's locale while
        # navigator.language says e.g. "de-DE" is a direct mismatch.
        # Windows/macOS take --lang; on Linux the browser ignores --lang
        # and reads LANGUAGE/LC_*/LANG through glib instead
        # (ui/base/l10n/l10n_util.cc, GetApplicationLocaleInternalNonMac).
        ui_locale = self._ui_locale(geo_profile)
        args.append(f"--lang={ui_locale}")
        self._warn_if_locale_missing(ui_locale)

        # Software WebGL fallback on GPU-less machines needs SwiftShader's
        # Vulkan ICD manifest next to the binary (see _ensure_swiftshader_icd).
        self._ensure_swiftshader_icd()

        # Anti-detection args
        extra_args = list(self.config.get("browser", {}).get("extra_args", []))
        port_args = [a for a in extra_args if a.startswith("--remote-debugging-")]
        if port_args:
            logger.warning(
                f"  Ignoring {port_args} from config extra_args — the driver uses "
                "--remote-debugging-pipe; pass expose_cdp_port=True to launch() "
                "if an external CDP port is really needed"
            )
            extra_args = [a for a in extra_args if a not in port_args]
        args.extend(extra_args)

        # Environment: start from the caller's environment minus anything
        # that would override or contradict this session's profile —
        # stale STEALTH_* values (including the proxy credentials, which
        # the browser has no use for) and locale/timezone variables —
        # then apply this session's values.
        env = {
            k: v for k, v in os.environ.items()
            if not k.upper().startswith("STEALTH_") and k.upper() not in ("TZ", "LANGUAGE")
        }
        env.update(env_vars)
        if sys.platform.startswith("linux"):
            # glib's format uses "_" ("en_GB", "es_419"); Chrome maps it
            # back to the same UI locale.
            env["LANGUAGE"] = ui_locale.replace("-", "_")
        if virtual_display:
            env["DISPLAY"] = virtual_display
            env.pop("WAYLAND_DISPLAY", None)  # keep Chrome on the X11 display

        # Font defense. Nothing compiled in reads STEALTH_FONT_OS/REGION
        # (patch 006 is verify-only), so the *runtime* font defense is
        # entirely here: a private fontconfig that exposes only the
        # claimed OS's font bundle and aliases each Windows/macOS family
        # to its metric-compatible substitute. Without this the page
        # measures the host's fonts (typically one single DejaVu
        # fallback for every family — verified live: all 12 Windows core
        # families measured the identical width), which is a hard
        # fingerprint violation no UA spoofing can cover. fontconfig is
        # Linux's font stack — Windows (DirectWrite) and macOS (Core
        # Text) use the OS font store, where this is a no-op.
        if sys.platform.startswith("linux"):
            font_env = self._setup_session_fonts(device_profile, env_vars)
            env.update(font_env)

        logger.info(f"  Launching: {' '.join(args[:5])}...")
        logger.debug(f"  Full command: {' '.join(args)}")
        logger.debug(f"  ENV vars: {env_vars}")

        # Spawn with the CDP pipe on the child's fds 3/4
        process, pipe_read_fd, pipe_write_fd = spawn_with_cdp_pipe(args, env)
        self._conn = CDPPipeConnection(pipe_read_fd, pipe_write_fd)

        # Drain stdout/stderr continuously on background threads instead
        # of leaving them as unread pipes -- an unread PIPE fills its OS
        # buffer (~64KB) once the process writes enough (Chrome is very
        # noisy on stderr: GPU/Vulkan errors, policy-logger lines, etc.,
        # seen repeatedly in real runs), at which point the child blocks
        # on its own write() call. Keeping just the tail also gives
        # _wait_for_browser_ready something real to report on failure
        # instead of a bare "did not become ready".
        self._browser_stderr_tail = deque(maxlen=60)

        def _drain(pipe):
            try:
                for line in iter(pipe.readline, b""):
                    self._browser_stderr_tail.append(line.decode(errors="replace").rstrip())
            except Exception:
                pass

        threading.Thread(target=_drain, args=(process.stdout,), daemon=True).start()
        threading.Thread(target=_drain, args=(process.stderr,), daemon=True).start()

        return process

    def _setup_session_fonts(
        self,
        device: DeviceProfile,
        env_vars: Dict[str, str],
        fonts_root: Optional[Path] = None,
    ) -> Dict[str, str]:
        """
        Write a per-session fontconfig so the page measures the claimed
        OS's fonts, and return the FONTCONFIG_* env vars pointing at it.
        Returns {} (browser uses the host's own config) when fonts aren't
        installed or the claimed OS has no bundle. Only meaningful on
        Linux (fontconfig); the caller gates on that — the file-writing
        itself is platform-neutral so it stays unit-testable.

        Why this exists (verified live, 2026-10-06, on the Jenkins box):
        with no fontconfig override, every font family a "Windows"
        profile promised measured the identical width — the page fell
        back to one host font for all of them — and host-only families
        (DejaVu) resolved while the UA claimed Windows. Both are hard
        tells no UA spoofing covers.

        The aliases map each claimed-OS family to its metric-compatible
        substitute (Arial->Liberation Sans, Calibri->Carlito, ...), the
        same pairs fonts/<platform>/manifest.json documents. Only the
        claimed OS's own bundle directory is exposed, plus the host's
        system dirs AFTER the substitutes, so an alias never shadows a
        bundled font but pages with unusual fallback chains still
        render — while the host's own config stays out entirely via
        FONTCONFIG_PATH (no <include> of /etc/fonts), so an empty or
        incomplete bundle cannot leak host-only families the way the
        old broken launchers did.
        """

        font_os = env_vars.get("STEALTH_FONT_OS")
        platform_dir = {
            "WINDOWS_11": "windows", "WINDOWS_10": "windows",
            "MACOS_SONOMA": "macos", "MACOS_VENTURA": "macos",
            "UBUNTU": "linux", "DEBIAN": "linux",
        }.get(font_os)
        if not platform_dir:
            logger.warning(f"  No font bundle for STEALTH_FONT_OS={font_os!r} — using host fonts")
            return {}

        # Packaged fonts: a single shared pool of font files at
        # jbium/fonts/ (the same font file is used by several claimed
        # OSes — Noto Sans backs Windows, macOS and Linux claims alike —
        # so one deduplicated pool saves ~2/3 of the installed size vs
        # per-platform copies), with the per-OS alias sets living in
        # jbium/fonts/<platform>/manifest.json. Installed by
        # `jbium fetch-fonts`, or shipped as package-data at build time.
        fonts_root = fonts_root or _PACKAGE_DIR / "fonts"
        font_dir = fonts_root / platform_dir
        font_file_dir = font_dir if any(font_dir.glob("*.tt[fc]")) else fonts_root
        if not font_file_dir.is_dir() or not any(font_file_dir.glob("*.tt[fc]")):
            # The manifest ships; the font files don't until someone
            # runs `jbium fetch-fonts` (or the repo's
            # fonts/download_fonts.py). Missing fonts with a private
            # fontconfig would render *nothing*, which is worse than the
            # host's real fonts.
            logger.warning(
                f"  Font pool empty at {fonts_root} — no fontconfig override. "
                "Run 'jbium fetch-fonts' to install the fonts; "
                "until then the page sees the host's fonts"
            )
            return {}

        cache_path = Path(tempfile.gettempdir()) / f"jbium-fonts-{uuid.uuid4().hex}"
        cache_path.mkdir(parents=True, exist_ok=True)
        self._fontconfig_dir = cache_path

        # Real aliases from the manifest: claimed family -> the
        # substitute font's real family name, as a HARD pattern rewrite
        # (<match target="pattern"> + prepend with strong binding)
        # rather than <alias><accept>. Two earlier live runs showed
        # <accept> is not reliable here: it fired for families whose
        # target had a static face in the pool (Arial->Liberation Sans
        # worked) and silently fell through for others (Consolas,
        # Georgia, Segoe UI all landed on fontconfig's generic default
        # instead of their substitutes -- 2026-10-07 run, every miss
        # measuring one identical default width). A prepend/strong rule
        # replaces the requested family outright, so every claimed
        # name resolves exactly where the manifest says, independent of
        # what fontconfig's generic machinery would do with the name.
        aliases_xml = ""
        alias_pairs = []
        manifest_path = font_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for group in manifest.get("fonts", {}).values():
                target = group.get("family")
                if not target:
                    continue
                for claimed in group.get("substitutes_for", []):
                    aliases_xml += (
                        f"  <match target=\"pattern\">\n"
                        f"    <test qual=\"any\" name=\"family\">\n"
                        f"      <string>{claimed}</string>\n"
                        f"    </test>\n"
                        f"    <edit name=\"family\" mode=\"prepend\" binding=\"strong\">\n"
                        f"      <string>{target}</string>\n"
                        f"    </edit>\n"
                        f"  </match>\n"
                    )
                    alias_pairs.append((claimed, target))
        except (OSError, ValueError) as e:
            # A broken manifest shouldn't take the whole launch down --
            # bundle fonts still load via <dir> without aliases.
            logger.warning(f"  Could not read {manifest_path} ({e}) — fonts.conf written without family aliases")

        # The claimed OS's manifest decides which pool files the session
        # exposes. selectfont/acceptfont rules turned out to be the
        # wrong tool (verified live 2026-10-12: fontconfig globs take
        # only * and ?, so *.tt[fc] matched nothing, and accept rules
        # are additive — nothing was actually hidden, and the negative
        # probe correctly refused to certify it). The deterministic
        # approach: a per-session directory of symlinks to exactly the
        # manifest-referenced files, and that directory is the ONLY
        # <dir>. Unreferenced families are not "rejected" — they are
        # simply not present. Symlinks (not copies) so the pool stays
        # deduplicated on disk; the whole directory is removed in
        # close() along with the fontconfig dir.
        referenced = set()
        try:
            for group in manifest.get("fonts", {}).values():
                for fname in group.get("files", []):
                    referenced.add(fname)
        except NameError:
            referenced = set()  # manifest unreadable; no symlinks

        # Files live either in the per-platform dir (repo layout) or
        # flat in the shared pool (pip layout); resolve each name
        # against both.
        def _pool_file(fname: str) -> Optional[Path]:
            for candidate in (font_dir / fname, fonts_root / fname):
                if candidate.exists():
                    return candidate
            return None

        session_font_dir = cache_path / "fonts"
        session_font_dir.mkdir(parents=True, exist_ok=True)
        linked = 0
        for fname in sorted(referenced):
            src = _pool_file(fname)
            if src is not None:
                os.symlink(src.resolve(), session_font_dir / fname)
                linked += 1
        if not linked:
            logger.warning(
                f"  No manifest-referenced font files found in {fonts_root} — "
                "no fontconfig override (page sees the host's fonts). "
                "Reinstall the wheel or run 'jbium fetch-fonts'."
            )
            shutil.rmtree(cache_path, ignore_errors=True)
            self._fontconfig_dir = None
            return {}

        config = f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir>{session_font_dir.resolve()}</dir>
  <cachedir>{(cache_path / "cache").resolve()}</cachedir>
{aliases_xml}</fontconfig>
"""
        (cache_path / "fonts.conf").write_text(config, encoding="utf-8")

        # Verify EVERY alias against fc-match before trusting the
        # session. The 2026-10-07 live run showed one sample probe is
        # not enough: 'Arial' verified fine while Consolas/Georgia/
        # Segoe UI silently fell through to the generic default.
        # Per-alias verification means the launch log states exactly
        # which families resolve where, and a bad config falls back to
        # host fonts instead of half-working.
        verify_env = {
            **os.environ,
            "FONTCONFIG_PATH": str(cache_path),
            "FONTCONFIG_FILE": "fonts.conf",
        }
        n_aliases = len(alias_pairs)
        try:
            bad = []
            for claimed, target in alias_pairs:
                probe = subprocess.run(
                    ["fc-match", "-f", "%{family}", claimed],
                    env=verify_env,
                    capture_output=True, text=True, timeout=15,
                )
                resolved_family = probe.stdout.strip()
                # A hard rewrite must land the requested name on the
                # substitute's family (fc-match reports the matched
                # font's own family name).
                if probe.returncode != 0 or resolved_family != target:
                    bad.append(f"{claimed!r}->{resolved_family!r} (want {target!r})")
            # Negative probe: a family whose file the claimed manifest
            # does NOT reference must not resolve to that file — with
            # the symlink-pool layout, its file simply is not in <dir>,
            # so fc-match must land on a *referenced* file (or nothing).
            # Keyed by platform_dir's actual lowercase values, with a
            # safe fallback list (the 1.2.1 regression: a capitalized-
            # key mismatch returned None and crashed verification).
            hidden_candidates = {
                "windows": ["Ubuntu", "DejaVu Sans", "DejaVu Sans Mono"],
                "macos": ["Ubuntu", "DejaVu Sans", "DejaVu Serif"],
            }.get(platform_dir) or ["Ubuntu", "DejaVu Sans"]
            for hidden_family in hidden_candidates:
                probe = subprocess.run(
                    ["fc-match", "-f", "%{file}", hidden_family],
                    env=verify_env,
                    capture_output=True, text=True, timeout=15,
                )
                matched_file = probe.stdout.strip()
                # The hidden family must not resolve to an
                # unreferenced pool file.
                matched_name = Path(matched_file).name
                if matched_file and matched_name not in referenced:
                    bad.append(
                        f"hidden family {hidden_family!r} resolves to {matched_name!r}"
                    )
                break  # one negative probe is enough per launch
            if bad:
                raise RuntimeError("; ".join(bad[:5]) + (" ..." if len(bad) > 5 else ""))
            sample = alias_pairs[0] if alias_pairs else ("sans-serif", "sans-serif")
            logger.info(f"  Font profile (driver fontconfig v3/symlink-pool): {platform_dir} claim, "
                        f"{n_aliases} hard aliases + {linked} linked fonts, "
                        f"all {n_aliases} verified via fc-match "
                        f"({sample[0]!r} -> {sample[1]!r})")
        except FileNotFoundError:
            logger.info(f"  Font profile (driver fontconfig v3/symlink-pool): {platform_dir} claim "
                        f"({n_aliases} hard aliases, {linked} linked fonts) "
                        "via private fontconfig (fc-match not installed; aliases unverified)")
        except Exception as e:
            logger.warning(
                f"  Private fontconfig fails alias verification ({e}) — "
                "falling back to the host's fonts. Check that the bundle's "
                "manifest 'family' names match the fonts' real names."
            )
            shutil.rmtree(cache_path, ignore_errors=True)
            self._fontconfig_dir = None
            return {}

        return {
            "FONTCONFIG_PATH": str(cache_path),
            "FONTCONFIG_FILE": "fonts.conf",
        }

    async def _start_virtual_display(self, device: DeviceProfile, timeout: float = 10) -> Optional[str]:
        """
        Start a private Xvfb sized to the profile's physical resolution
        (CSS size x device pixel ratio, e.g. 1728x1117 @2x -> 3456x2234)
        and return its DISPLAY value, or None if Xvfb isn't installed or
        didn't start (the browser then uses the inherited DISPLAY, and a
        warning says the screen size won't match the profile).

        -displayfd lets Xvfb pick a free display number itself and report
        it, so concurrent sessions can't collide on a number.
        """

        xvfb = shutil.which("Xvfb")
        if not xvfb:
            logger.warning(
                "  Xvfb not found — screen size will be the inherited display's, "
                "not the profile's (install the xvfb package)"
            )
            return None

        width = round(device.screen_width * device.device_pixel_ratio)
        height = round(device.screen_height * device.device_pixel_ratio)
        read_fd, write_fd = os.pipe()
        try:
            process = subprocess.Popen(
                [xvfb, "-displayfd", str(write_fd), "-screen", "0",
                 f"{width}x{height}x{device.color_depth}", "-nolisten", "tcp"],
                pass_fds=(write_fd,),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            os.close(read_fd)
            logger.warning(f"  Could not start Xvfb ({e}) — using the inherited display")
            return None
        finally:
            os.close(write_fd)

        def _read_display_number() -> str:
            # Xvfb writes "<number>\n" once it accepts connections; EOF
            # without a number means it exited.
            data = b""
            while not data.endswith(b"\n"):
                chunk = os.read(read_fd, 64)
                if not chunk:
                    break
                data += chunk
            return data.decode(errors="replace").strip()

        read_future = asyncio.get_running_loop().run_in_executor(None, _read_display_number)
        try:
            number = await asyncio.wait_for(asyncio.shield(read_future), timeout=timeout)
        except asyncio.TimeoutError:
            # Kill Xvfb so the blocked read sees EOF, and let it finish
            # before closing its fd (never close an fd another thread is
            # still reading).
            process.kill()
            await read_future
            number = ""
        os.close(read_fd)

        if not number.isdigit():
            process.kill()
            process.wait()
            logger.warning("  Xvfb did not start — using the inherited display")
            return None

        self._xvfb_process = process
        logger.info(
            f"  Virtual display :{number} at {width}x{height}x{device.color_depth} "
            f"(screen {device.screen_width}x{device.screen_height} @ {device.device_pixel_ratio:g}x)"
        )
        return f":{number}"

    # SwiftShader's Vulkan driver per platform, and the ICD manifest the
    # build writes next to it (third_party/swiftshader/src/Vulkan/BUILD.gn
    # "icd_file" + vk_swiftshader_icd.json.tmpl at the pinned revision).
    _SWIFTSHADER_LIBS = {
        "linux": "./libvk_swiftshader.so",
        "darwin": "./libvk_swiftshader.dylib",
        "win32": ".\\vk_swiftshader.dll",
    }

    def _ensure_swiftshader_icd(self):
        """
        Make sure vk_swiftshader_icd.json sits next to the browser binary.

        With no usable GPU (servers, VMs, Xvfb), Chrome renders WebGL with
        ANGLE on SwiftShader's software Vulkan driver, and ANGLE points the
        Vulkan loader at <binary dir>/vk_swiftshader_icd.json to find it.
        Without that manifest the loader finds no driver, reports no
        VK_KHR_surface, the GPU process exits, and pages get no WebGL at
        all -- a strong tell, since real Chrome always has it. Release
        archives packaged before this fix copied libvk_swiftshader.so but
        not the manifest, so write it here if it's missing.
        """

        platform_key = "linux" if sys.platform.startswith("linux") else sys.platform
        library_path = self._SWIFTSHADER_LIBS.get(platform_key)
        if not library_path:
            return
        bin_dir = Path(self.browser_path).parent
        library = bin_dir / library_path.lstrip(".\\/")
        manifest = bin_dir / "vk_swiftshader_icd.json"
        if not library.exists() or manifest.exists():
            return
        content = json.dumps({
            "file_format_version": "1.0.0",
            "ICD": {"library_path": library_path, "api_version": "1.0.5"},
        }, indent=2) + "\n"
        try:
            manifest.write_text(content)
            logger.info(f"  Wrote missing SwiftShader ICD manifest: {manifest}")
        except OSError as e:
            logger.warning(
                f"  {manifest} is missing and could not be written ({e}) — "
                "WebGL will be unavailable on machines without a GPU"
            )

    def _warn_if_locale_missing(self, ui_locale: str):
        """
        Warn when the binary ships no .pak for the UI locale. The browser
        then falls back to en-US, so Intl's default locale would disagree
        with navigator.languages. (scripts/package.sh copies a fixed
        subset of locales/*.pak.)
        """

        locales_dir = Path(self.browser_path).parent / "locales"
        if not locales_dir.is_dir():
            return  # macOS bundles keep them in *.lproj; nothing to check
        if not (locales_dir / f"{ui_locale}.pak").exists():
            logger.warning(
                f"  No locales/{ui_locale}.pak next to the browser — it will fall "
                f"back to en-US and Intl's locale will not match navigator.languages"
            )

    def _build_proxy_auth_extension(self, username: str, password: str) -> str:
        """
        Write a temporary unpacked MV2 extension that answers the proxy's
        Basic-auth challenge via chrome.webRequest.onAuthRequired.

        Chrome has no --proxy-server flag support for embedded credentials
        (see _spawn_browser), and CDP's own Fetch.authRequired handling
        would require a concurrent event-listening loop this driver's
        current request/response CDP transport doesn't have — every
        _command()/_cdp_command() call blocks synchronously waiting for a
        matching response id, so an authRequired event arriving mid-wait
        would just be silently discarded, deadlocking the proxy handshake.
        A background-page extension sidesteps that entirely: Chrome
        resolves the challenge internally before any page-level CDP
        traffic is involved. MV2 (not MV3) is required — MV3 restricts
        blocking webRequest to policy-installed extensions, and Chrome
        120 still loads unpacked MV2 extensions given via --load-extension.
        """

        ext_dir = Path(tempfile.gettempdir()) / f"jbium-proxy-auth-{int(time.time() * 1000)}"
        ext_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "manifest_version": 2,
            "name": "jbium-proxy-auth",
            "version": "1.0",
            "permissions": ["webRequest", "webRequestBlocking", "<all_urls>"],
            "background": {"scripts": ["background.js"], "persistent": True},
        }
        (ext_dir / "manifest.json").write_text(json.dumps(manifest))

        # json.dumps escapes quotes/backslashes so the credentials can't
        # break out of the string literals they're embedded into below.
        #
        # extraInfoSpec is ["blocking"], not ["asyncBlocking"] — that means
        # the listener must return its BlockingResponse synchronously. A
        # callback-based signature (function(details, callback) {...}) is
        # only valid under "asyncBlocking"; under plain "blocking" the
        # callback argument is undefined, so invoking it throws inside the
        # listener, Chrome treats the event as unhandled, no credentials
        # are ever supplied, and the proxy handshake fails with
        # net::ERR_INVALID_AUTH_CREDENTIALS (caught live testing this).
        background_js = f"""
chrome.webRequest.onAuthRequired.addListener(
    function(details) {{
        return {{
            authCredentials: {{
                username: {json.dumps(username)},
                password: {json.dumps(password)}
            }}
        }};
    }},
    {{urls: ["<all_urls>"]}},
    ["blocking"]
);
"""
        (ext_dir / "background.js").write_text(background_js)

        logger.info("  Generated proxy-auth extension (credentials not passed on the command line)")

        return str(ext_dir)

    async def _wait_for_browser_ready(self, device_profile: DeviceProfile, timeout: int = 30):
        """Wait for the browser to answer on the CDP pipe, and check its version."""

        try:
            info = await self._conn.send("Browser.getVersion", timeout=timeout)
        except Exception as e:
            exit_code = self._browser_process.poll() if self._browser_process else None
            tail = "\n".join(self._browser_stderr_tail) if getattr(self, "_browser_stderr_tail", None) else "(no output captured)"
            raise RuntimeError(
                f"Browser did not become ready within timeout ({e}) "
                f"(process exit code: {exit_code!r} -- None means still running)\n"
                f"Last output:\n{tail}"
            ) from None

        product = info.get("product", "unknown")
        logger.info(f"  Browser version: {product}")

        # The UA string and Client Hints claim a specific version; if the
        # binary is a different build, JS feature detection and other
        # version-gated behavior will contradict that claim.
        claimed = self._chrome_full_version(device_profile)
        actual = product.split("/", 1)[-1]
        if actual != claimed:
            logger.warning(
                f"  Browser binary reports {product!r} but the profile claims Chrome "
                f"{claimed} — version-gated JS features will not match the "
                f"User-Agent / Client Hints (see config/fingerprints.json chrome_versions)"
            )

    async def _read_devtools_active_port(self, timeout: float = 10) -> int:
        """
        Port chosen by --remote-debugging-port=0, read from
        <user-data-dir>/DevToolsActivePort (first line). Only used when
        launch(expose_cdp_port=True).
        """

        port_file = Path(self._user_data_dir) / "DevToolsActivePort"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                first_line = port_file.read_text().splitlines()[0].strip()
                if first_line.isdigit():
                    return int(first_line)
            except (OSError, IndexError):
                pass
            await asyncio.sleep(0.1)
        raise RuntimeError(f"expose_cdp_port=True but {port_file} never appeared")

    async def _cdp_command(self, method: str, params: dict = None) -> dict:
        """Send a browser-level CDP command over the debugging pipe."""

        if not self._conn:
            raise RuntimeError("Browser is not running — call launch() first")
        return await self._conn.send(method, params, timeout=30, label="browser-level")


# Keys physically adjacent to each letter on a QWERTY layout — the
# source of most real single-character typos, used by
# StealthPage.type_text's typo simulation.
_QWERTY_ADJACENCY = {
    "a": "qwsz", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wsdr",
    "f": "drtgvc", "g": "ftyhbv", "h": "gyujnb", "i": "ujko", "j": "huikmn",
    "k": "jiolm", "l": "kop", "m": "njk", "n": "bhjm", "o": "iklp",
    "p": "ol", "q": "wa", "r": "edft", "s": "awedxz", "t": "rfgy",
    "u": "yhji", "v": "cfgb", "w": "qase", "x": "zsdc", "y": "tghu",
    "z": "asx",
}


class StealthPage:
    """
    Represents a single page/tab in the stealth browser.
    Provides navigation, content extraction, and interaction.
    """
    
    def __init__(
        self,
        browser: Jbium,
        connection: CDPPipeConnection,
        target_id: str,
        session_id: str,
        session: StealthSession,
    ):
        self.browser = browser
        self.target_id = target_id
        self.session_id = session_id
        self.session = session
        self._conn = connection
        self._closed = False

        # Unsolicited CDP events for this page (no "id", e.g.
        # Network.responseReceived) arrive on the shared debugging pipe
        # tagged with this page's sessionId; the connection routes them
        # to _dispatch_event, which fans them out to registered handlers.
        self._event_handlers: Dict[str, List] = {}
        connection.register_session(session_id, self._dispatch_event)

        # Network capture state, populated once enable_network_capture()
        # registers handlers: requestId -> in-flight request metadata,
        # resolved GraphQL bodies keyed by operationName, and any
        # wait_for_graphql_response() callers already waiting on one.
        self._network_enabled = False
        self._request_meta: Dict[str, Dict] = {}
        self._graphql_responses: Dict[str, Dict] = {}
        self._graphql_waiters: Dict[str, asyncio.Future] = {}

        # General in-flight request tracking (independent of GraphQL
        # tagging above) -- backs goto(wait_until="networkidle").
        self._inflight_requests: set = set()

        # Tracked cursor position, so mouse moves start from where the
        # "hand" actually is instead of teleporting in from nowhere.
        self._mouse_x = session.device_profile.screen_width * random.uniform(0.3, 0.7)
        self._mouse_y = session.device_profile.screen_height * random.uniform(0.3, 0.7)

        logger.info(f"New page created: {target_id}")
    
    def _dispatch_event(self, method: str, params: Dict):
        """Fan one CDP event out to the handlers registered for it."""

        if method == "Target.detachedFromTarget":
            self._closed = True
            return
        for handler in list(self._event_handlers.get(method, ())):
            try:
                handler(params)
            except Exception:
                logger.exception(f"Error in handler for {method}")

    def on(self, method: str, handler):
        """Register a callback for a raw CDP event method (e.g. 'Network.responseReceived')."""

        self._event_handlers.setdefault(method, []).append(handler)

    async def _command(self, method: str, params: dict = None) -> dict:
        """Send a CDP command to this page's session over the debugging pipe."""

        return await self._conn.send(
            method, params, session_id=self.session_id,
            timeout=30, label=f"page {self.target_id}",
        )

    # ─────────────────────────────────────────────
    # Network capture
    # ─────────────────────────────────────────────

    async def enable_network_capture(self):
        """
        Turn on Network domain events and start tracking GraphQL
        request/response pairs by operationName, so callers can await
        wait_for_graphql_response("SomeQuery") instead of relying on
        DOM state for data that only ever exists in a GraphQL payload
        (e.g. VRBO's 30-day pricing calendar). Idempotent.
        """

        if self._network_enabled:
            return

        self.on("Network.requestWillBeSent", self._on_request_will_be_sent)
        self.on("Network.responseReceived", self._on_response_received)
        self.on("Network.loadingFinished", self._on_loading_finished)
        self.on("Network.loadingFailed", self._on_loading_failed)

        # Separate, unconditional in-flight tracking (on() supports
        # multiple handlers per event) -- feeds _wait_for_network_idle,
        # independent of whether a given request ever gets tagged with a
        # GraphQL operationName.
        self.on("Network.requestWillBeSent", self._track_request_started)
        self.on("Network.loadingFinished", self._track_request_finished)
        self.on("Network.loadingFailed", self._track_request_finished)

        await self._command("Network.enable")
        self._network_enabled = True

    def _extract_operation_name(self, post_data: Optional[str]) -> Optional[str]:
        if not post_data:
            return None
        try:
            body = json.loads(post_data)
        except (ValueError, TypeError):
            return None
        if isinstance(body, list):
            # Batched GraphQL requests — only the first operation is
            # tracked, matching the single-query POSTs the ported
            # detail/pricing extraction actually sends.
            body = body[0] if body else {}
        return body.get("operationName") if isinstance(body, dict) else None

    def _on_request_will_be_sent(self, params: Dict):
        request = params.get("request", {})
        request_id = params["requestId"]
        post_data = request.get("postData")
        if post_data:
            self._tag_operation(request_id, post_data, request.get("url"))
        elif request.get("hasPostData"):
            # CDP omits postData inline above its own size threshold,
            # flagging hasPostData instead -- GraphQL variables (date
            # ranges, filters) can push a request over that, so without
            # this fallback a large-enough query would silently never
            # get matched to its response.
            asyncio.create_task(
                self._fetch_and_tag_operation(request_id, request.get("url"))
            )

    def _tag_operation(self, request_id: str, post_data: str, url: Optional[str]):
        operation_name = self._extract_operation_name(post_data)
        if operation_name:
            self._request_meta[request_id] = {
                "operation_name": operation_name,
                "url": url,
            }

    async def _fetch_and_tag_operation(self, request_id: str, url: Optional[str]):
        try:
            result = await self._command("Network.getRequestPostData", {"requestId": request_id})
        except Exception as e:
            logger.debug(f"Failed to fetch large postData for {request_id}: {e}")
            return
        self._tag_operation(request_id, result.get("postData", ""), url)

    def _track_request_started(self, params: Dict):
        self._inflight_requests.add(params["requestId"])

    def _track_request_finished(self, params: Dict):
        self._inflight_requests.discard(params["requestId"])

    async def _wait_for_network_idle(self, timeout: float, idle_for: float = 0.5):
        """
        Wait until no requests have been in flight for `idle_for` seconds
        (Playwright's own networkidle definition), or until `timeout`
        total seconds have elapsed.
        """

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._inflight_requests:
                await asyncio.sleep(idle_for)
                if not self._inflight_requests:
                    return
                continue
            await asyncio.sleep(0.1)
        logger.warning("  goto: networkidle wait timed out with requests still in flight")

    def _on_response_received(self, params: Dict):
        meta = self._request_meta.get(params["requestId"])
        if meta:
            meta["status"] = params.get("response", {}).get("status")

    def _on_loading_finished(self, params: Dict):
        meta = self._request_meta.pop(params["requestId"], None)
        if meta:
            asyncio.create_task(self._resolve_graphql_response(params["requestId"], meta))

    def _on_loading_failed(self, params: Dict):
        meta = self._request_meta.pop(params["requestId"], None)
        if meta:
            waiter = self._graphql_waiters.pop(meta["operation_name"], None)
            if waiter and not waiter.done():
                waiter.set_exception(RuntimeError(
                    f"Network request for {meta['operation_name']} failed: "
                    f"{params.get('errorText')}"
                ))

    async def _resolve_graphql_response(self, request_id: str, meta: Dict):
        try:
            result = await self._command("Network.getResponseBody", {"requestId": request_id})
        except Exception as e:
            logger.warning(f"Failed to fetch response body for {meta['operation_name']}: {e}")
            return

        body_text = result.get("body", "")
        if result.get("base64Encoded"):
            import base64
            body_text = base64.b64decode(body_text).decode("utf-8", errors="replace")

        try:
            body = json.loads(body_text)
        except ValueError:
            body = body_text

        record = {
            "operation_name": meta["operation_name"],
            "url": meta.get("url"),
            "status": meta.get("status"),
            "body": body,
        }
        self._graphql_responses[meta["operation_name"]] = record

        waiter = self._graphql_waiters.pop(meta["operation_name"], None)
        if waiter and not waiter.done():
            waiter.set_result(record)

    async def wait_for_graphql_response(self, operation_name: str, timeout: float = 30) -> Dict:
        """
        Wait for a GraphQL response matching `operation_name` (matched
        against the request body's own `operationName` field — the CDP
        equivalent of Playwright's page.on('response', ...) + JSON body
        inspection). Returns immediately if the response already
        arrived. Requires enable_network_capture() to have been called
        first (goto() does this automatically).
        """

        if operation_name in self._graphql_responses:
            return self._graphql_responses[operation_name]

        waiter = self._graphql_waiters.setdefault(
            operation_name, asyncio.get_running_loop().create_future()
        )
        return await asyncio.wait_for(waiter, timeout=timeout)

    def get_captured_graphql(self, operation_name: str) -> Optional[Dict]:
        """
        Non-blocking lookup of a GraphQL response that may already have
        arrived passively (e.g. off the initial page load), without
        opening a new wait. Returns None if it hasn't shown up (yet).
        """
        return self._graphql_responses.get(operation_name)

    async def goto(self, url: str, wait_until: str = "load", timeout: int = 30):
        """
        Navigate to URL and wait for `wait_until`:
          - "load" / "domcontentloaded": waits for the matching CDP Page
            lifecycle event (Page.loadEventFired / Page.domContentEventFired)
            via the reader loop's event dispatch.
          - "networkidle": waits until no requests have been in flight
            for 500ms (Playwright's own definition), up to `timeout`.

        A short settle delay always follows the wait, since the lifecycle
        event fires before client-side rendering has necessarily finished
        painting, and callers are typically about to read the DOM.
        """

        logger.info(f"  goto: {url}")

        wait_for_map = {
            "load": "Page.loadEventFired",
            "domcontentloaded": "Page.domContentEventFired",
        }

        await self._command("Page.enable")
        await self.enable_network_capture()

        load_fut = None
        method = wait_for_map.get(wait_until)
        if method:
            # Registered synchronously, before Page.navigate is even
            # sent, so there's no window where the real event could fire
            # before anything is listening for it.
            load_fut = asyncio.get_running_loop().create_future()

            def _on_load_event(params, fut=load_fut):
                if not fut.done():
                    fut.set_result(params)

            self.on(method, _on_load_event)

        result = await self._command("Page.navigate", {
            "url": url
        })

        if "errorText" in result:
            if method:
                handlers = self._event_handlers.get(method)
                if handlers and _on_load_event in handlers:
                    handlers.remove(_on_load_event)
            raise RuntimeError(f"Navigation failed: {result['errorText']}")

        if load_fut is not None:
            try:
                await asyncio.wait_for(load_fut, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"  goto: timed out waiting for {wait_until} on {url}")
            finally:
                handlers = self._event_handlers.get(method)
                if handlers and _on_load_event in handlers:
                    handlers.remove(_on_load_event)
        elif wait_until == "networkidle":
            await self._wait_for_network_idle(timeout)

        await asyncio.sleep(0.5)  # let client-side rendering settle

    async def get_content(self) -> str:
        """Get page HTML content"""
        
        result = await self._command("Runtime.evaluate", {
            "expression": "document.documentElement.outerHTML",
            "returnByValue": True,
        })
        
        return result.get("result", {}).get("value", "")
    
    async def get_title(self) -> str:
        """Get page title"""
        
        result = await self._command("Runtime.evaluate", {
            "expression": "document.title",
            "returnByValue": True,
        })
        
        return result.get("result", {}).get("value", "")
    
    async def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript in page"""
        
        result = await self._command("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        
        return result.get("result", {}).get("value")
    
    async def screenshot(self, filepath: str, full_page: bool = True):
        """
        Take a screenshot.

        full_page=True (default) captures the entire scrollable page via
        Page.getLayoutMetrics + a clip covering the full content size —
        plain Page.captureScreenshot with no clip only grabs the current
        viewport, which silently truncated CreepJS's report (its device/
        CPU/GPU section sits below the fold on a 1920x1080 viewport).
        """

        params = {"format": "png"}

        if full_page:
            metrics = await self._command("Page.getLayoutMetrics")
            content_size = metrics.get("cssContentSize") or metrics["contentSize"]
            params["clip"] = {
                "x": 0,
                "y": 0,
                "width": content_size["width"],
                "height": content_size["height"],
                "scale": 1,
            }
            params["captureBeyondViewport"] = True

        result = await self._command("Page.captureScreenshot", params)

        import base64
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(result["data"]))

        logger.info(f"  Screenshot saved: {filepath}")
    
    async def _get_element_box(self, selector: str) -> Optional[Dict[str, float]]:
        """Get an element's bounding box in viewport coordinates, or None if not found."""

        return await self.evaluate(f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {{x: r.x, y: r.y, width: r.width, height: r.height}};
            }})()
        """)

    @staticmethod
    def _curved_path(x1: float, y1: float, x2: float, y2: float, steps: int) -> List[tuple]:
        """
        Sample points along a slightly bowed quadratic curve rather than a
        straight line — a real hand doesn't move the mouse in a perfectly
        straight line, and constant-velocity straight-line movement is
        itself a well-known automation signal.
        """

        distance = math.hypot(x2 - x1, y2 - y1)
        bow = random.uniform(-0.25, 0.25) * distance
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2

        length = max(distance, 1e-6)
        # Unit vector perpendicular to the straight line, to offset the
        # control point sideways by `bow`.
        nx, ny = -(y2 - y1) / length, (x2 - x1) / length
        cx, cy = mx + nx * bow, my + ny * bow

        points = []
        for i in range(1, steps + 1):
            t = i / steps
            x = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * cx + t ** 2 * x2
            y = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cy + t ** 2 * y2
            points.append((x, y))
        return points

    async def move_mouse_to(self, x: float, y: float):
        """
        Move the mouse to (x, y) along a curved, variable-speed path using
        real Input domain events — CDP's Input events are dispatched
        through the browser's actual input pipeline, so they carry
        isTrusted=true, unlike a synthetic JS MouseEvent.
        """

        start_x, start_y = self._mouse_x, self._mouse_y
        distance = math.hypot(x - start_x, y - start_y)
        steps = max(6, min(40, int(distance / 12)))

        for px, py in self._curved_path(start_x, start_y, x, y, steps):
            await self._command("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": px,
                "y": py,
            })
            await asyncio.sleep(random.uniform(0.004, 0.02))

        self._mouse_x, self._mouse_y = x, y

    async def idle(self, duration: float):
        """
        Hold roughly still for `duration` seconds like a real user
        reading or waiting for a page to finish something, rather than
        going completely motionless — a browser that emits zero input
        events for many seconds (e.g. a bare `asyncio.sleep()` while
        waiting for an async page computation) is itself an unusual
        signal; real users make small, unconscious mouse corrections
        even while not actively doing anything. Jiggles are dispatched
        via move_mouse_to, so they're curved-path movements themselves,
        not instant jumps.
        """

        elapsed = 0.0
        while elapsed < duration:
            step = min(random.uniform(0.6, 2.0), duration - elapsed)
            await asyncio.sleep(step)
            elapsed += step

            if elapsed < duration and random.random() < 0.6:
                jitter_x = self._mouse_x + random.uniform(-8, 8)
                jitter_y = self._mouse_y + random.uniform(-8, 8)
                await self.move_mouse_to(jitter_x, jitter_y)

    async def click(self, selector: str):
        """
        Click an element like a user would: move the mouse there along a
        curved path, then press/release at a randomized point inside the
        element (never dead-center every time) with a human press duration.
        """

        box = await self._get_element_box(selector)
        if not box:
            logger.warning(f"click: element not found for selector {selector!r}")
            return

        target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
        target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)

        await self.move_mouse_to(target_x, target_y)
        await asyncio.sleep(random.uniform(0.03, 0.12))  # dwell before pressing

        await self._command("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": target_x, "y": target_y,
            "button": "left", "clickCount": 1,
        })
        await asyncio.sleep(random.uniform(0.04, 0.12))  # press duration
        await self._command("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": target_x, "y": target_y,
            "button": "left", "clickCount": 1,
        })

    async def drag_and_drop(self, source_selector: str, target_selector: str):
        """
        Drag one element onto another like a user would: press at a
        randomized point inside the source, move along a curved path
        with the button held (every intermediate move carries
        buttons=1, so dragover/dragenter handlers reading
        event.buttons see it as actually held down — not just pressed
        once and teleported), hover briefly over the target, then
        release. Real CDP Input events go through the browser's actual
        input pipeline, so a real HTML5 drag (draggable="true" +
        dragstart/dragover/drop) is triggered the same way a genuine
        mouse would, unlike dispatching synthetic DOM drag events
        directly from JS.
        """

        source_box = await self._get_element_box(source_selector)
        if not source_box:
            logger.warning(f"drag_and_drop: source not found for selector {source_selector!r}")
            return

        target_box = await self._get_element_box(target_selector)
        if not target_box:
            logger.warning(f"drag_and_drop: target not found for selector {target_selector!r}")
            return

        start_x = source_box["x"] + source_box["width"] * random.uniform(0.3, 0.7)
        start_y = source_box["y"] + source_box["height"] * random.uniform(0.3, 0.7)
        end_x = target_box["x"] + target_box["width"] * random.uniform(0.3, 0.7)
        end_y = target_box["y"] + target_box["height"] * random.uniform(0.3, 0.7)

        await self.move_mouse_to(start_x, start_y)
        await asyncio.sleep(random.uniform(0.03, 0.1))

        await self._command("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": start_x, "y": start_y,
            "button": "left", "clickCount": 1,
        })
        await asyncio.sleep(random.uniform(0.05, 0.12))

        distance = math.hypot(end_x - start_x, end_y - start_y)
        steps = max(10, min(60, int(distance / 10)))
        for px, py in self._curved_path(start_x, start_y, end_x, end_y, steps):
            await self._command("Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": px, "y": py,
                "button": "left", "buttons": 1,
            })
            await asyncio.sleep(random.uniform(0.008, 0.025))

        self._mouse_x, self._mouse_y = end_x, end_y
        await asyncio.sleep(random.uniform(0.05, 0.15))  # hover over target before releasing

        await self._command("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": end_x, "y": end_y,
            "button": "left", "clickCount": 1,
        })

    async def _send_char(self, char: str):
        """Dispatch one trusted printable-character key press."""

        await self._command("Input.dispatchKeyEvent", {
            "type": "keyDown", "text": char, "unmodifiedText": char, "key": char,
        })
        await asyncio.sleep(random.uniform(0.01, 0.04))
        await self._command("Input.dispatchKeyEvent", {
            "type": "keyUp", "text": char, "unmodifiedText": char, "key": char,
        })

    async def _send_backspace(self):
        """
        Dispatch a trusted Backspace press. Backspace has no associated
        text to insert, so — matching CDP's own convention for
        non-printable/control keys (the same one Puppeteer's key
        handling uses) — this is "rawKeyDown", not "keyDown", with the
        Windows virtual-key code Chromium's key handling actually keys
        off of for control keys, rather than the `text`/`key` string
        alone.
        """

        await self._command("Input.dispatchKeyEvent", {
            "type": "rawKeyDown", "key": "Backspace", "code": "Backspace",
            "windowsVirtualKeyCode": 8, "nativeVirtualKeyCode": 8,
        })
        await asyncio.sleep(random.uniform(0.01, 0.04))
        await self._command("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": "Backspace", "code": "Backspace",
            "windowsVirtualKeyCode": 8, "nativeVirtualKeyCode": 8,
        })

    async def type_text(self, selector: str, text: str, typo_rate: float = 0.04):
        """
        Type into a field like a user would: click it first to focus (real
        users don't teleport focus in), then dispatch trusted per-character
        key events with jittered inter-key delay and occasional longer
        pauses — a single .value= assignment is instant and untrusted.

        Occasionally (typo_rate, default 4% per alphabetic character)
        hits a key physically adjacent to the intended one on a QWERTY
        layout, pauses as if noticing, backspaces it, then continues
        with the correct character — perfectly clean, instant typing
        is itself an automation tell.
        """

        await self.click(selector)
        await asyncio.sleep(random.uniform(0.1, 0.3))

        for char in text:
            if char.isalpha() and random.random() < typo_rate:
                adjacent = _QWERTY_ADJACENCY.get(char.lower())
                if adjacent:
                    typo_char = random.choice(adjacent)
                    if char.isupper():
                        typo_char = typo_char.upper()
                    await self._send_char(typo_char)
                    await asyncio.sleep(random.uniform(0.08, 0.22))  # notice the mistake
                    await self._send_backspace()
                    await asyncio.sleep(random.uniform(0.05, 0.15))

            await self._send_char(char)

            delay = random.uniform(0.05, 0.18)
            if random.random() < 0.08:
                delay += random.uniform(0.2, 0.5)  # occasional "thinking" pause
            await asyncio.sleep(delay)

    async def wheel(self, delta_x: float, delta_y: float):
        """
        Dispatch a single mouse-wheel tick at the current cursor position
        — the same underlying CDP call scroll_to_bottom() uses, exposed
        directly for callers that want a few deliberate scroll ticks
        (e.g. light homepage browsing) rather than a full scroll-to-
        bottom pass.
        """

        await self._command("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": self._mouse_x, "y": self._mouse_y,
            "deltaX": delta_x, "deltaY": delta_y,
        })

    async def scroll_to_bottom(self):
        """
        Scroll to the bottom like a user would: variable-sized wheel ticks
        with variable delay and occasional reading pauses, instead of a
        perfectly uniform step/interval — uniform scrolling is itself a
        detectable signal. Occasionally scrolls back up a bit too, like
        someone re-reading a line they just passed — a scroll that only
        ever moves one direction for an entire page is itself an
        unusually mechanical pattern.
        """

        scrolled = 0
        height = await self.evaluate("document.body.scrollHeight")

        while scrolled < height:
            delta = random.randint(250, 650)
            # There is no Input.dispatchMouseWheelEvent in the real CDP
            # protocol (confirmed live: "-32601 method not found") — wheel
            # scrolling is one of the several event types
            # Input.dispatchMouseEvent itself handles via its "type" field.
            await self._command("Input.dispatchMouseEvent", {
                "type": "mouseWheel",
                "x": self._mouse_x, "y": self._mouse_y,
                "deltaX": 0, "deltaY": delta,
            })
            scrolled += delta
            await asyncio.sleep(random.uniform(0.08, 0.35))

            if random.random() < 0.1:
                await asyncio.sleep(random.uniform(0.4, 1.2))  # reading pause

            if random.random() < 0.12:
                back_delta = random.randint(80, 220)
                await self._command("Input.dispatchMouseEvent", {
                    "type": "mouseWheel",
                    "x": self._mouse_x, "y": self._mouse_y,
                    "deltaX": 0, "deltaY": -back_delta,
                })
                scrolled = max(0, scrolled - back_delta)
                await asyncio.sleep(random.uniform(0.3, 0.9))

            height = await self.evaluate("document.body.scrollHeight")
    
    async def check_detection(self) -> Dict[str, bool]:
        """Check if page contains detection/blocked indicators"""
        
        content = await self.get_content()
        content_lower = content.lower()
        
        # A bare "captcha" substring is too broad -- caught live in a
        # concurrent VRBO batch run: it false-positived on a page that
        # had loaded completely normally (real title, 181 real reviews,
        # full amenities), because Google's standard reCAPTCHA privacy
        # disclosure boilerplate ("This site is protected by reCAPTCHA
        # and the Google Privacy Policy...") is extremely common on
        # real, unblocked pages with an ordinary contact-host form or
        # fraud-prevention widget -- it says nothing about whether the
        # visitor was actually challenged. Matching actual
        # challenge-page phrasing instead is far more specific.
        indicators = {
            "datadome_captcha": "geo.captcha-delivery.com" in content,
            "captcha_present": any(p in content_lower for p in (
                "verify you are human",
                "unusual traffic from your computer",
                "i'm not a robot",
                "complete the captcha below",
                "solve the captcha",
            )),
            "blocked_message": "access denied" in content_lower,
            "rate_limited": "rate limit" in content_lower or "too many requests" in content_lower,
            "cloudflare": "cloudflare" in content_lower and "ray id" in content_lower,
            "perimeterx": "perimeterx" in content_lower or "px-captcha" in content_lower,
        }
        
        any_detected = any(indicators.values())
        
        return {
            **indicators,
            "detected": any_detected,
        }
    
    async def close(self):
        """
        Detach the driver from this page (the tab itself stays open until
        the browser closes — same as the old per-page WebSocket close).
        """

        if self._closed:
            return
        self._closed = True
        try:
            if not self._conn.closed:
                await self._conn.send(
                    "Target.detachFromTarget", {"sessionId": self.session_id},
                    timeout=5, label=f"page {self.target_id}",
                )
        except Exception:
            pass
        finally:
            self._conn.unregister_session(self.session_id)


# ─────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────

# Proxies that just got blocked, shared across runs (each Jenkins run is a
# new process, so this lives on disk): {proxy key: unix time it's usable again}.
PROXY_COOLDOWN_FILE = Path.home() / ".cache" / "jbium" / "proxy_cooldown.json"
DEFAULT_BLOCK_COOLDOWN_MINUTES = 180


class ProxyPoolExhausted(RuntimeError):
    """Every proxy in the pool is cooling down after a block."""


def _proxy_key(proxy_url: str) -> str:
    """Identify a proxy by its username (e.g. "prefix-37" = one fixed Webshare IP), else host:port."""
    parts = urlsplit(proxy_url)
    return parts.username or f"{parts.hostname}:{parts.port}"


def _load_cooldowns() -> Dict[str, float]:
    try:
        data = json.loads(PROXY_COOLDOWN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {key: until for key, until in data.items() if isinstance(until, (int, float)) and until > now}


def mark_proxy_blocked(proxy_url: str, cooldown_minutes: float = DEFAULT_BLOCK_COOLDOWN_MINUTES) -> None:
    """
    Record that a site blocked this proxy, so get_random_webshare_proxy()
    leaves it alone for `cooldown_minutes`. A block is a reputation signal
    about that IP, not a transient failure: sending it straight back in
    (or retrying seconds later) just adds another flagged visit.
    """

    cooldowns = _load_cooldowns()
    cooldowns[_proxy_key(proxy_url)] = time.time() + cooldown_minutes * 60
    PROXY_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename so a concurrent reader never sees a half-written file.
    tmp = PROXY_COOLDOWN_FILE.with_name(f"{PROXY_COOLDOWN_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cooldowns, indent=2), encoding="utf-8")
    os.replace(tmp, PROXY_COOLDOWN_FILE)
    logger.info(f"Proxy {_proxy_key(proxy_url)} cooling down for {cooldown_minutes:g} min after a block")


def proxy_is_cooling(proxy_url: str) -> bool:
    """True if mark_proxy_blocked() put this proxy on cooldown and it hasn't expired."""
    return _proxy_key(proxy_url) in _load_cooldowns()


def get_random_webshare_proxy(
    username_prefix: Optional[str] = None,
    password: Optional[str] = None,
    endpoint: Optional[str] = None,
    port: Optional[int] = None,
    mode: str = "numbered",
    pool_size: Optional[int] = None,
    skip_cooling: bool = True,
) -> str:
    """
    Generate a random Webshare proxy URL.

    Nothing is hardcoded here — pass values explicitly, or set
    STEALTH_WEBSHARE_USERNAME / STEALTH_WEBSHARE_PASSWORD / STEALTH_WEBSHARE_ENDPOINT /
    STEALTH_WEBSHARE_PORT in the environment. Endpoint/port fall back to
    Webshare's default proxy host if neither is given.

    "numbered" mode picks one of `pool_size` fixed IPs (default 100, or
    STEALTH_WEBSHARE_POOL_SIZE), skipping any that mark_proxy_blocked()
    put on cooldown unless skip_cooling=False. Raises ProxyPoolExhausted
    if every one is cooling down.
    """

    username_prefix = username_prefix or os.environ.get("STEALTH_WEBSHARE_USERNAME")
    password = password or os.environ.get("STEALTH_WEBSHARE_PASSWORD")
    endpoint = endpoint or os.environ.get("STEALTH_WEBSHARE_ENDPOINT", "p.webshare.io")
    port = port or int(os.environ.get("STEALTH_WEBSHARE_PORT", "80"))
    pool_size = pool_size or int(os.environ.get("STEALTH_WEBSHARE_POOL_SIZE", "100"))

    if not username_prefix or not password:
        raise RuntimeError(
            "Webshare credentials not set. Export STEALTH_WEBSHARE_USERNAME "
            "and STEALTH_WEBSHARE_PASSWORD, or pass username_prefix/password explicitly."
        )

    if mode == "rotating":
        return f"http://{username_prefix}-rotate:{password}@{endpoint}:{port}"

    cooling = _load_cooldowns() if skip_cooling else {}
    available = [n for n in range(1, pool_size + 1) if f"{username_prefix}-{n}" not in cooling]
    if not available:
        soonest = min(cooling.values())
        raise ProxyPoolExhausted(
            f"All {pool_size} proxies are cooling down after blocks; the first frees up at "
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(soonest))}. "
            f"Wait, use fresh IPs, or clear {PROXY_COOLDOWN_FILE}."
        )

    username = f"{username_prefix}-{random.choice(available)}"
    return f"http://{username}:{password}@{endpoint}:{port}"


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    async def main():
        # Get proxy
        proxy_url = get_random_webshare_proxy()
        print(f"Using proxy: {proxy_url}")
        
        # Launch browser
        async with Jbium() as sb:
            await sb.launch(
                proxy_url=proxy_url,
                headless=False,  # DataDome detects headless
            )
            
            # Navigate
            page = await sb.new_page()
            await page.goto("https://bot.sannysoft.com/")
            
            # Check detection
            title = await page.get_title()
            print(f"Page title: {title}")
            
            # Take screenshot
            await page.screenshot("./test_screenshot.png")
            print("Screenshot saved: ./test_screenshot.png")
            
            # Keep browser open for inspection
            print("\nPress Ctrl+C to exit...")
            try:
                await asyncio.sleep(3600)
            except KeyboardInterrupt:
                pass
    
    asyncio.run(main())
