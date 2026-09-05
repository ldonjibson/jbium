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
    from driver.stealth_browser import Jbium
    
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
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

# Local imports
from driver.fingerprint_manager import FingerprintManager
from driver.geoip_resolver import GeoIPResolver, GeoProfile
from driver.device_generator import DeviceGenerator, DeviceProfile

# Third-party (for CDP communication until we build custom driver)
import websockets

logger = logging.getLogger(__name__)


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
        config_path: str = "config/settings.yaml",
        browser_path: str = None,
    ):
        self.config = self._load_config(config_path)
        self.browser_path = browser_path or self._find_browser()
        
        # Managers
        self.geoip_resolver = GeoIPResolver(
            db_path=self.config.get("geoip", {}).get(
                "database_path", "./data/GeoLite2-City.mmdb"
            )
        )
        self.fingerprint_manager = FingerprintManager()
        self.device_generator = DeviceGenerator(
            templates_path="config/fingerprints.json"
        )
        
        # State
        self._session: Optional[StealthSession] = None
        self._browser_process: Optional[subprocess.Popen] = None
        self._ws_connection = None
        self._pages: List[Dict] = []
        
        logger.info(f"Jbium initialized")
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
    ) -> StealthSession:
        """
        Launch stealth browser with complete configuration.
        
        Args:
            proxy_url: Proxy URL (http://user:pass@host:port)
            headless: Run without UI (false recommended for DataDome)
            fingerprint_profile: Optional specific device template name
            geoip_override: Optional manual GeoIP data
            
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
        )
        
        # Step 6: Wait for browser to be ready
        await self._wait_for_browser_ready()
        
        # Step 7: Connect via CDP (temporary, until custom driver)
        self._ws_url = await self._get_ws_url()
        
        logger.info("  ✅ Browser launched")
        logger.info(f"  Session: {session.session_id}")
        
        return session
    
    async def new_page(self) -> "StealthPage":
        """Create a new page/tab"""
        
        if not self._ws_connection:
            self._ws_connection = await websockets.connect(self._ws_url)
        
        # Create new target via CDP
        target_id = await self._cdp_command("Target.createTarget", {
            "url": "about:blank"
        })
        
        # Connect to the page
        page_ws_url = f"{self._ws_url.split('/')[0]}/devtools/page/{target_id['targetId']}"
        page_ws = await websockets.connect(page_ws_url)
        
        page = StealthPage(
            browser=self,
            ws_connection=page_ws,
            target_id=target_id["targetId"],
            session=self._session,
        )
        
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
        
        # Close WebSocket
        if self._ws_connection:
            await self._ws_connection.close()
        
        # Kill browser process
        if self._browser_process:
            self._browser_process.terminate()
            try:
                self._browser_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._browser_process.kill()
        
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
            with open(config_file) as f:
                return yaml.safe_load(f) or {}
        
        # Defaults
        return {
            "browser": {
                "binary_path": "/root/jbium/chromium/src/out/Release/jbium",
                "user_data_dir": "/tmp/stealth-profile",
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
        """Find the stealth browser binary"""
        
        # Check config
        if self.config.get("browser", {}).get("binary_path"):
            path = self.config["browser"]["binary_path"]
            if Path(path).exists():
                return path
        
        # Check common locations
        common_paths = [
            "/root/jbium/chromium/src/out/Release/jbium",
            "/usr/local/bin/jbium",
            "./build/jbium",
            "./jbium",
        ]
        
        for path in common_paths:
            if Path(path).exists():
                return path
        
        raise FileNotFoundError(
            "Stealth browser not found. Build it first or set binary_path in config."
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
        Generate all environment variables that the stealth
        Chromium build reads via getenv().
        
        These control all the patches we applied:
        - STEALTH_CPU_CORES → navigator.hardwareConcurrency
        - STEALTH_DEVICE_MEMORY → navigator.deviceMemory  
        - STEALTH_PLATFORM → navigator.platform
        - STEALTH_GEO_TIMEZONE → Date API timezone
        - STEALTH_GEO_LANGUAGE → navigator.language
        - etc.
        """
        
        env_vars = {}
        
        # ── Navigator spoofing (Patch 007) ──
        env_vars["STEALTH_CPU_CORES"] = str(device.cpu_cores)
        env_vars["STEALTH_DEVICE_MEMORY"] = str(device.ram_gb)
        env_vars["STEALTH_PLATFORM"] = device.platform
        env_vars["STEALTH_MAX_TOUCH_POINTS"] = str(
            10 if device.touch_support else 0
        )
        env_vars["STEALTH_UA_PLATFORM"] = device.ua_platform
        env_vars["STEALTH_UA_PLATFORM_VERSION"] = device.ua_platform_version
        
        # ── GeoIP consistency (Patch 008) ──
        env_vars["STEALTH_GEO_COUNTRY"] = geo.country_code
        env_vars["STEALTH_GEO_COUNTRY_NAME"] = geo.country_name
        env_vars["STEALTH_GEO_CITY"] = geo.city
        env_vars["STEALTH_GEO_TIMEZONE"] = geo.timezone
        env_vars["STEALTH_GEO_LANGUAGE"] = geo.language
        env_vars["STEALTH_GEO_LOCALE"] = geo.locale
        env_vars["STEALTH_GEO_LATITUDE"] = str(geo.latitude)
        env_vars["STEALTH_GEO_LONGITUDE"] = str(geo.longitude)
        env_vars["STEALTH_GEO_CURRENCY"] = geo.currency
        
        # ── Canvas/WebGL noise (Patch 004/005) ──
        env_vars["STEALTH_CANVAS_SEED"] = str(device.canvas_seed)
        env_vars["STEALTH_WEBGL_SEED"] = str(device.webgl_seed)
        env_vars["STEALTH_AUDIO_SEED"] = str(device.audio_seed)
        
        # ── GPU profile (Patch 005) ──
        # Select GPU profile based on device
        gpu_profiles = {
            "Intel": 0,
            "NVIDIA": 1,
            "AMD": 2,
            "Apple": 3,
        }
        gpu_vendor = device.gpu_vendor
        for vendor_name, profile_idx in gpu_profiles.items():
            if vendor_name.lower() in gpu_vendor.lower():
                env_vars["STEALTH_GPU_PROFILE"] = str(profile_idx)
                break
        
        # ── Font filtering (Patch 006) ──
        # Map OS to font filter
        os_font_map = {
            "Windows": "WINDOWS_11",
            "macOS": "MACOS_SONOMA",
            "Linux": "UBUNTU",
        }
        for os_name, font_os in os_font_map.items():
            if os_name in device.os:
                env_vars["STEALTH_FONT_OS"] = font_os
                break
        
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
        
        # ── WebRTC (Patch 010) ──
        env_vars["STEALTH_FILTER_WEBRTC"] = "true"
        env_vars["STEALTH_PROXY_IP"] = self._session.proxy_ip if self._session else ""
        
        return env_vars
    
    async def _spawn_browser(
        self,
        proxy_url: str,
        headless: bool,
        env_vars: Dict[str, str],
        device_profile: DeviceProfile,
        geo_profile: GeoProfile,
    ) -> subprocess.Popen:
        """Launch the stealth Chromium process"""
        
        # Build command line args
        args = [self.browser_path]
        
        # User-Agent
        args.append(f"--user-agent={device_profile.user_agent}")
        
        # Window size (use device screen size)
        if not headless:
            args.append(f"--window-size={device_profile.screen_width},{device_profile.screen_height}")
        
        # Headless (careful — use our custom headless mode)
        if headless:
            args.append("--headless=new")  # New headless mode (less detectable)
            args.append("--disable-gpu")
        
        # Proxy
        args.append(f"--proxy-server={proxy_url}")
        
        # User data directory (fresh)
        user_data_dir = f"/tmp/stealth-profile-{int(time.time())}"
        args.append(f"--user-data-dir={user_data_dir}")
        
        # Remote debugging (for CDP connection — temporary)
        debug_port = random.randint(9222, 9999)
        args.append(f"--remote-debugging-port={debug_port}")
        
        # Anti-detection args
        extra_args = self.config.get("browser", {}).get("extra_args", [])
        args.extend(extra_args)
        
        # Environment
        env = os.environ.copy()
        env.update(env_vars)
        
        logger.info(f"  Launching: {' '.join(args[:5])}...")
        logger.debug(f"  Full command: {' '.join(args)}")
        logger.debug(f"  ENV vars: {env_vars}")
        
        # Spawn
        process = subprocess.Popen(
            args,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        # Store debug port
        self._debug_port = debug_port
        
        return process
    
    async def _wait_for_browser_ready(self, timeout: int = 30):
        """Wait for browser to respond to CDP"""
        
        import aiohttp
        
        start = time.time()
        
        while time.time() - start < timeout:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{self._debug_port}/json/version",
                        timeout=aiohttp.ClientTimeout(total=2)
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            logger.info(f"  Browser version: {data.get('Browser', 'unknown')}")
                            return
            except Exception:
                await asyncio.sleep(0.5)
        
        raise RuntimeError("Browser did not become ready within timeout")
    
    async def _get_ws_url(self) -> str:
        """Get WebSocket URL for CDP"""
        
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{self._debug_port}/json/version"
            ) as response:
                data = await response.json()
                return data["webSocketDebuggerUrl"]
    
    async def _cdp_command(self, method: str, params: dict = None) -> dict:
        """Send CDP command"""
        
        if not self._ws_connection:
            self._ws_connection = await websockets.connect(self._ws_url)
        
        message_id = random.randint(1, 999999)
        message = {
            "id": message_id,
            "method": method,
        }
        if params:
            message["params"] = params
        
        await self._ws_connection.send(json.dumps(message))
        
        while True:
            response = await self._ws_connection.recv()
            data = json.loads(response)
            if data.get("id") == message_id:
                return data.get("result", {})


class StealthPage:
    """
    Represents a single page/tab in the stealth browser.
    Provides navigation, content extraction, and interaction.
    """
    
    def __init__(
        self,
        browser: Jbium,
        ws_connection,
        target_id: str,
        session: StealthSession,
    ):
        self.browser = browser
        self.ws = ws_connection
        self.target_id = target_id
        self.session = session
        self._message_id = 0

        # Tracked cursor position, so mouse moves start from where the
        # "hand" actually is instead of teleporting in from nowhere.
        self._mouse_x = session.device_profile.screen_width * random.uniform(0.3, 0.7)
        self._mouse_y = session.device_profile.screen_height * random.uniform(0.3, 0.7)

        logger.info(f"New page created: {target_id}")
    
    async def _command(self, method: str, params: dict = None) -> dict:
        """Send CDP command to this page"""
        
        self._message_id += 1
        message = {
            "id": self._message_id,
            "method": method,
        }
        if params:
            message["params"] = params
        
        await self.ws.send(json.dumps(message))
        
        while True:
            response = await asyncio.wait_for(self.ws.recv(), timeout=30)
            data = json.loads(response)
            if data.get("id") == self._message_id:
                if "error" in data:
                    raise RuntimeError(f"CDP error: {data['error']}")
                return data.get("result", {})
    
    async def goto(self, url: str, wait_until: str = "load", timeout: int = 30):
        """Navigate to URL"""
        
        logger.info(f"  goto: {url}")
        
        wait_for_map = {
            "load": "loadEventFired",
            "domcontentloaded": "domContentEventFired",
            "networkidle": "networkIdle",  # Requires Network.enable
        }
        
        await self._command("Page.enable")
        
        result = await self._command("Page.navigate", {
            "url": url
        })
        
        if "errorText" in result:
            raise RuntimeError(f"Navigation failed: {result['errorText']}")
        
        # Wait for load
        await asyncio.sleep(3)  # Simple wait for now
        # TODO: Implement proper event waiting
    
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
    
    async def screenshot(self, filepath: str):
        """Take screenshot"""
        
        result = await self._command("Page.captureScreenshot", {
            "format": "png"
        })
        
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

    async def type_text(self, selector: str, text: str):
        """
        Type into a field like a user would: click it first to focus (real
        users don't teleport focus in), then dispatch trusted per-character
        key events with jittered inter-key delay and occasional longer
        pauses — a single .value= assignment is instant and untrusted.
        """

        await self.click(selector)
        await asyncio.sleep(random.uniform(0.1, 0.3))

        for char in text:
            await self._command("Input.dispatchKeyEvent", {
                "type": "keyDown", "text": char, "unmodifiedText": char, "key": char,
            })
            await asyncio.sleep(random.uniform(0.01, 0.04))
            await self._command("Input.dispatchKeyEvent", {
                "type": "keyUp", "text": char, "unmodifiedText": char, "key": char,
            })

            delay = random.uniform(0.05, 0.18)
            if random.random() < 0.08:
                delay += random.uniform(0.2, 0.5)  # occasional "thinking" pause
            await asyncio.sleep(delay)

    async def scroll_to_bottom(self):
        """
        Scroll to the bottom like a user would: variable-sized wheel ticks
        with variable delay and occasional reading pauses, instead of a
        perfectly uniform step/interval — uniform scrolling is itself a
        detectable signal.
        """

        scrolled = 0
        height = await self.evaluate("document.body.scrollHeight")

        while scrolled < height:
            delta = random.randint(250, 650)
            await self._command("Input.dispatchMouseWheelEvent", {
                "type": "mouseWheel",
                "x": self._mouse_x, "y": self._mouse_y,
                "deltaX": 0, "deltaY": delta,
            })
            scrolled += delta
            await asyncio.sleep(random.uniform(0.08, 0.35))

            if random.random() < 0.1:
                await asyncio.sleep(random.uniform(0.4, 1.2))  # reading pause

            height = await self.evaluate("document.body.scrollHeight")
    
    async def check_detection(self) -> Dict[str, bool]:
        """Check if page contains detection/blocked indicators"""
        
        content = await self.get_content()
        content_lower = content.lower()
        
        indicators = {
            "datadome_captcha": "geo.captcha-delivery.com" in content,
            "captcha_present": "captcha" in content_lower,
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
        """Close this page"""
        
        try:
            await self.ws.close()
        except Exception:
            pass


# ─────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────

def get_random_webshare_proxy(
    username_prefix: Optional[str] = None,
    password: Optional[str] = None,
    endpoint: Optional[str] = None,
    port: Optional[int] = None,
    mode: str = "numbered",
) -> str:
    """
    Generate a random Webshare proxy URL.

    Nothing is hardcoded here — pass values explicitly, or set
    STEALTH_WEBSHARE_USERNAME / STEALTH_WEBSHARE_PASSWORD / STEALTH_WEBSHARE_ENDPOINT /
    STEALTH_WEBSHARE_PORT in the environment. Endpoint/port fall back to
    Webshare's default proxy host if neither is given.
    """

    username_prefix = username_prefix or os.environ.get("STEALTH_WEBSHARE_USERNAME")
    password = password or os.environ.get("STEALTH_WEBSHARE_PASSWORD")
    endpoint = endpoint or os.environ.get("STEALTH_WEBSHARE_ENDPOINT", "p.webshare.io")
    port = port or int(os.environ.get("STEALTH_WEBSHARE_PORT", "80"))

    if not username_prefix or not password:
        raise RuntimeError(
            "Webshare credentials not set. Export STEALTH_WEBSHARE_USERNAME "
            "and STEALTH_WEBSHARE_PASSWORD, or pass username_prefix/password explicitly."
        )

    if mode == "rotating":
        username = f"{username_prefix}-rotate"
    else:
        num = random.randint(1, 100)
        username = f"{username_prefix}-{num}"
    
    return f"http://{username}:{password}@{endpoint}:{port}"


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
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
            session = await sb.launch(
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
