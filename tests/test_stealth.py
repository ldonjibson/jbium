#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════
Stealth Test Suite
════════════════════════════════════════════════════════════

Tests the stealth browser against known detection sites.
Generates a report of what passed and what was detected.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from driver.stealth_browser import Jbium, get_random_webshare_proxy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("stealth_test")


# ═════════════════════════════════════════════
# Test definitions
# ═════════════════════════════════════════════

DETECTION_SITES = [
    {
        "name": "Sannysoft Bot Test",
        "url": "https://bot.sannysoft.com/",
        "check": "sannysoft",
        "description": "Tests navigator.webdriver, plugins, languages, WebGL",
    },
    {
        "name": "Are You Headless",
        "url": "https://arh.antoinevastel.com/bots/areyouheadless",
        "check": "headless",
        "description": "Detects headless Chrome via various methods",
    },
    {
        "name": "FingerprintJS",
        "url": "https://fingerprintjs.github.io/fingerprintjs/",
        "check": "fingerprint",
        "description": "Generates browser fingerprint",
    },
    {
        "name": "BrowserLeaks JS",
        "url": "https://browserleaks.com/javascript",
        "check": "browserleaks_js",
        "description": "JavaScript fingerprinting",
    },
    {
        "name": "BrowserLeaks Canvas",
        "url": "https://browserleaks.com/canvas",
        "check": "canvas",
        "description": "Canvas fingerprint test",
    },
    {
        "name": "BrowserLeaks WebGL",
        "url": "https://browserleaks.com/webgl",
        "check": "webgl",
        "description": "WebGL fingerprint test",
    },
    {
        "name": "BrowserLeaks Fonts",
        "url": "https://browserleaks.com/fonts",
        "check": "fonts",
        "description": "Font detection fingerprint",
    },
    {
        "name": "TLS Fingerprint",
        "url": "https://tls.peet.ws/",
        "check": "tls",
        "description": "TLS ClientHello fingerprint",
    },
    {
        "name": "JA3 Fingerprint",
        "url": "https://ja3er.com/",
        "check": "ja3",
        "description": "JA3 hash of TLS handshake",
    },
]

# Real-world tests
PROTECTED_SITES = [
    {
        "name": "Vrbo (DataDome)",
        "url": "https://www.vrbo.com/",
        "check": "datadome",
        "description": "Vacation rental site protected by DataDome",
    },
]


# ═════════════════════════════════════════════
# Test runner
# ═════════════════════════════════════════════

class StealthTester:
    
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.results: List[Dict] = []
        self.screenshot_dir = Path("test_results/screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        
        # Browser properties to verify
        self.browser_props: Dict[str, Any] = {}
    
    async def run_all(self, proxy_url: str) -> Dict:
        """Run all stealth tests"""
        
        logger.info("════════════════════════════════════════════")
        logger.info("  Starting Stealth Test Suite")
        logger.info("════════════════════════════════════════════")
        
        async with Jbium() as browser:
            # Launch with proxy
            session = await browser.launch(
                proxy_url=proxy_url,
                headless=self.headless,
            )
            
            logger.info(f"  Session: {session.session_id}")
            logger.info(f"  IP: {session.proxy_ip}")
            logger.info(f"  Location: {session.geo_profile.city}, {session.geo_profile.country_name}")
            logger.info(f"  Device: {session.device_profile.os}")
            logger.info("")
            
            # Create page
            page = await browser.new_page()
            
            # First, collect browser properties
            await self._collect_browser_props(page)
            
            # Run detection site tests
            for site in DETECTION_SITES:
                result = await self._test_detection_site(page, site)
                self.results.append(result)
                await asyncio.sleep(2)  # Rate limit
            
            # Run protected site tests
            for site in PROTECTED_SITES:
                result = await self._test_protected_site(page, site)
                self.results.append(result)
                await asyncio.sleep(3)  # Rate limit
        
        # Generate report
        report = self._generate_report()
        
        return report
    
    async def _collect_browser_props(self, page):
        """Collect all browser properties for verification"""
        
        logger.info("Collecting browser properties...")
        
        props = {
            "user_agent": await page.evaluate("navigator.userAgent"),
            "platform": await page.evaluate("navigator.platform"),
            "language": await page.evaluate("navigator.language"),
            "languages": await page.evaluate("JSON.stringify(navigator.languages)"),
            "hardware_concurrency": await page.evaluate("navigator.hardwareConcurrency"),
            "device_memory": await page.evaluate("navigator.deviceMemory"),
            "max_touch_points": await page.evaluate("navigator.maxTouchPoints"),
            "webdriver": await page.evaluate("navigator.webdriver"),
            "cookie_enabled": await page.evaluate("navigator.cookieEnabled"),
            "do_not_track": await page.evaluate("navigator.doNotTrack"),
            "plugins_length": await page.evaluate("navigator.plugins.length"),
            "mime_types_length": await page.evaluate("navigator.mimeTypes.length"),
            
            # Screen
            "screen_width": await page.evaluate("screen.width"),
            "screen_height": await page.evaluate("screen.height"),
            "available_width": await page.evaluate("screen.availWidth"),
            "available_height": await page.evaluate("screen.availHeight"),
            "color_depth": await page.evaluate("screen.colorDepth"),
            "pixel_depth": await page.evaluate("screen.pixelDepth"),
            "device_pixel_ratio": await page.evaluate("window.devicePixelRatio"),
            
            # Timezone
            "timezone": await page.evaluate(
                "Intl.DateTimeFormat().resolvedOptions().timeZone"
            ),
            "timezone_offset": await page.evaluate("new Date().getTimezoneOffset()"),
            
            # WebRTC
            "webrtc_supported": await page.evaluate(
                "typeof RTCPeerConnection !== 'undefined'"
            ),
            
            # Canvas (basic check)
            "canvas_supported": await page.evaluate(
                "!!document.createElement('canvas').getContext"
            ),
            
            # WebGL
            "webgl_vendor": await page.evaluate("""
                (() => {
                    const c = document.createElement('canvas');
                    const gl = c.getContext('webgl');
                    if (!gl) return 'not supported';
                    return gl.getParameter(gl.VENDOR);
                })()
            """),
            "webgl_renderer": await page.evaluate("""
                (() => {
                    const c = document.createElement('canvas');
                    const gl = c.getContext('webgl');
                    if (!gl) return 'not supported';
                    return gl.getParameter(gl.RENDERER);
                })()
            """),
        }
        
        self.browser_props = props
        
        logger.info("  User-Agent:    " + str(props["user_agent"]))
        logger.info(f"  Platform:     {props['platform']}")
        logger.info(f"  Language:     {props['language']}")
        logger.info(f"  CPU cores:    {props['hardware_concurrency']}")
        logger.info(f"  Device memory: {props['device_memory']}GB")
        logger.info(f"  Screen:       {props['screen_width']}x{props['screen_height']}")
        logger.info(f"  Timezone:     {props['timezone']}")
        logger.info(f"  WebGL vendor: {props['webgl_vendor']}")
        logger.info(f"  WebGL renderer: {props['webgl_renderer']}")
        logger.info(f"  webdriver:    {props['webdriver']}")
        logger.info("")
    
    async def _test_detection_site(self, page, site: Dict) -> Dict:
        """Test against a detection site"""
        
        logger.info(f"Testing: {site['name']}")
        logger.info(f"  URL: {site['url']}")
        
        result = {
            "name": site["name"],
            "url": site["url"],
            "description": site["description"],
            "timestamp": time.time(),
            "status": "unknown",
            "detected": False,
            "details": {},
        }
        
        try:
            # Navigate
            await page.goto(site["url"])
            await asyncio.sleep(3)
            
            # Get page content
            content = await page.get_content()
            title = await page.get_title()
            
            # Screenshot
            screenshot_path = self.screenshot_dir / f"{site['check']}.png"
            await page.screenshot(str(screenshot_path))
            
            # Analyze based on check type
            if site["check"] == "sannysoft":
                result["details"] = await self._analyze_sannysoft(page, content)
            
            elif site["check"] == "headless":
                result["details"] = await self._analyze_headless(page, content)
            
            elif site["check"] == "canvas":
                result["details"] = await self._analyze_canvas(page, content)
            
            elif site["check"] == "webgl":
                result["details"] = await self._analyze_webgl(page, content)
            
            elif site["check"] == "tls" or site["check"] == "ja3":
                result["details"] = await self._analyze_tls(page, content)
            
            else:
                # Generic check
                detection_indicators = [
                    "bot", "automated", "headless", "selenium",
                    "puppeteer", "webdriver", "detected", "flagged"
                ]
                content_lower = content.lower()
                found_indicators = [
                    ind for ind in detection_indicators 
                    if ind in content_lower
                ]
                result["details"] = {
                    "title": title,
                    "indicators_found": found_indicators,
                }
                result["detected"] = len(found_indicators) > 2
            
            result["status"] = "completed"
            
            # Overall detection
            if result["details"].get("detected", False):
                result["detected"] = True
                logger.warning(f"  ⚠️  DETECTED!")
            else:
                logger.info(f"  ✅ Passed")
            
        except Exception as e:
            result["status"] = "error"
            result["details"]["error"] = str(e)
            logger.error(f"  ❌ Error: {e}")
        
        return result
    
    async def _analyze_sannysoft(self, page, content: str) -> Dict:
        """Analyze Sannysoft bot detection results"""
        
        # Sannysoft uses table cells with "present" or "missing"
        # and red/green indicators
        
        checks = {
            "webdriver": await page.evaluate("navigator.webdriver"),
            "chrome_runtime": await page.evaluate(
                "typeof chrome !== 'undefined' && typeof chrome.runtime !== 'undefined'"
            ),
            "permission_notifications": await page.evaluate("""
                typeof Notification !== 'undefined' && 
                Notification.permission !== 'denied'
            """),
            "plugins_count": await page.evaluate("navigator.plugins.length"),
            "languages": await page.evaluate("navigator.languages.length"),
        }
        
        # Count pass/fail
        passed = 0
        failed = 0
        
        if checks["webdriver"] == False:
            passed += 1
        else:
            failed += 1
        
        if checks["plugins_count"] > 0:
            passed += 1
        else:
            failed += 1
        
        if checks["languages"] > 0:
            passed += 1
        else:
            failed += 1
        
        return {
            "checks": checks,
            "passed": passed,
            "failed": failed,
            "detected": failed > 2,
        }
    
    async def _analyze_headless(self, page, content: str) -> Dict:
        """Analyze headless detection"""
        
        content_lower = content.lower()
        
        indicators = {
            "says_headless": "headless" in content_lower,
            "says_not_headless": "not headless" in content_lower,
            "you_are_headless": "you are headless" in content_lower,
        }
        
        return {
            "indicators": indicators,
            "detected": indicators["says_headless"] and not indicators["says_not_headless"],
        }
    
    async def _analyze_canvas(self, page, content: str) -> Dict:
        """Analyze canvas fingerprint"""
        
        # Generate canvas fingerprint
        canvas_hash = await page.evaluate("""
            (() => {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                
                // Draw something unique
                ctx.textBaseline = 'top';
                ctx.font = '14px Arial';
                ctx.fillStyle = '#f60';
                ctx.fillRect(125, 1, 62, 20);
                ctx.fillStyle = '#069';
                ctx.fillText('Stealth test', 2, 15);
                ctx.fillStyle = 'rgba(102,204,0,0.7)';
                ctx.fillText('Canvas', 4, 17);
                
                // Get hash
                const dataURL = canvas.toDataURL();
                let hash = 0;
                for (let i = 0; i < dataURL.length; i++) {
                    const char = dataURL.charCodeAt(i);
                    hash = ((hash << 5) - hash) + char;
                    hash = hash & hash;
                }
                return hash.toString();
            })()
        """)
        
        return {
            "canvas_hash": canvas_hash,
            "detected": False,  # Can't easily detect from hash alone
            "note": "Canvas hash should be unique per session",
        }
    
    async def _analyze_webgl(self, page, content: str) -> Dict:
        """Analyze WebGL fingerprint"""
        
        webgl_info = await page.evaluate("""
            (() => {
                const canvas = document.createElement('canvas');
                const gl = canvas.getContext('webgl');
                if (!gl) return null;
                
                const ext = gl.getExtension('WEBGL_debug_renderer_info');
                const vendor = ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : null;
                const renderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null;
                const version = gl.getParameter(gl.VERSION);
                const shading = gl.getParameter(gl.SHADING_LANGUAGE_VERSION);
                
                return { vendor, renderer, version, shading };
            })()
        """)
        
        # Check for suspicious renderer strings
        suspicious = ["SwiftShader", "llvmpipe", "Software", "VirtualBox", "VMware"]
        
        if webgl_info and webgl_info.get("renderer"):
            is_suspicious = any(
                s in webgl_info["renderer"] for s in suspicious
            )
        else:
            is_suspicious = False
        
        return {
            "webgl_info": webgl_info,
            "detected": is_suspicious,
            "note": "Renderer should not contain SwiftShader/llvmpipe/Software",
        }
    
    async def _analyze_tls(self, page, content: str) -> Dict:
        """Analyze TLS fingerprint"""
        
        # Extract JA3 from page
        ja3 = await page.evaluate("""
            (() => {
                const el = document.querySelector('[class*="ja3"], [id*="ja3"]');
                return el ? el.textContent : null;
            })()
        """)
        
        return {
            "ja3_hash": ja3,
            "detected": False,
            "note": "JA3 should not match known automated browser hashes",
        }
    
    async def _test_protected_site(self, page, site: Dict) -> Dict:
        """Test against a protected site (DataDome, etc.)"""
        
        logger.info(f"Testing: {site['name']}")
        logger.info(f"  URL: {site['url']}")
        
        result = {
            "name": site["name"],
            "url": site["url"],
            "description": site["description"],
            "timestamp": time.time(),
            "status": "unknown",
            "detected": False,
            "details": {},
        }
        
        try:
            await page.goto(site["url"])
            await asyncio.sleep(5)
            
            # Check for blocks
            detection = await page.check_detection()
            
            title = await page.get_title()
            screenshot_path = self.screenshot_dir / f"{site['check']}.png"
            await page.screenshot(str(screenshot_path))
            
            result["details"] = {
                "title": title,
                "detection_indicators": detection,
                "screenshot": str(screenshot_path),
            }
            
            result["detected"] = detection.get("detected", False)
            
            if result["detected"]:
                logger.warning(f"  ⚠️  BLOCKED by anti-bot system!")
            else:
                logger.info(f"  ✅ Access granted")
            
            result["status"] = "completed"
            
        except Exception as e:
            result["status"] = "error"
            result["details"]["error"] = str(e)
            logger.error(f"  ❌ Error: {e}")
        
        return result
    
    def _generate_report(self) -> Dict:
        """Generate final test report"""
        
        total = len(self.results)
        passed = sum(1 for r in self.results if r["status"] == "completed" and not r["detected"])
        detected = sum(1 for r in self.results if r["detected"])
        errors = sum(1 for r in self.results if r["status"] == "error")
        
        report = {
            "timestamp": time.time(),
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "summary": {
                "total_tests": total,
                "passed": passed,
                "detected": detected,
                "errors": errors,
                "stealth_score": (passed / total * 100) if total > 0 else 0,
            },
            "browser_properties": self.browser_props,
            "test_results": self.results,
        }
        
        # Print summary
        logger.info("")
        logger.info("════════════════════════════════════════════")
        logger.info("  TEST RESULTS")
        logger.info("════════════════════════════════════════════")
        logger.info(f"  Total tests:    {total}")
        logger.info(f"  Passed:         {passed}")
        logger.info(f"  Detected:       {detected}")
        logger.info(f"  Errors:         {errors}")
        logger.info(f"  Stealth Score:  {report['summary']['stealth_score']:.1f}%")
        logger.info("════════════════════════════════════════════")
        logger.info("")
        
        for result in self.results:
            status_icon = "✅" if not result["detected"] else "❌"
            if result["status"] == "error":
                status_icon = "⚠️"
            
            logger.info(
                f"  {status_icon} {result['name']}"
                + (" — DETECTED" if result["detected"] else "")
                + (" — ERROR" if result["status"] == "error" else "")
            )
        
        logger.info("")
        
        # Save report
        report_path = Path("test_results/report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"  Report saved: {report_path}")
        
        return report


# ═════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Jbium Test Suite")
    parser.add_argument(
        "--proxy",
        type=str,
        default=None,
        help="Proxy URL (default: random Webshare proxy)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run headless (not recommended for DataDome)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="test_results/report.json",
        help="Output report path"
    )
    
    args = parser.parse_args()
    
    # Get proxy
    if args.proxy:
        proxy_url = args.proxy
    else:
        proxy_url = get_random_webshare_proxy()
    
    print(f"Proxy: {proxy_url}")
    
    # Run tests
    tester = StealthTester(headless=args.headless)
    report = await tester.run_all(proxy_url)
    
    # Exit code based on stealth score
    score = report["summary"]["stealth_score"]
    if score >= 80:
        print(f"\n✅ Good stealth score: {score:.1f}%")
        sys.exit(0)
    elif score >= 50:
        print(f"\n⚠️  Moderate stealth score: {score:.1f}%")
        sys.exit(1)
    else:
        print(f"\n❌ Low stealth score: {score:.1f}%")
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
