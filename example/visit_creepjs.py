"""
════════════════════════════════════════════════════════════
Example: visit CreepJS with jbium, headed
════════════════════════════════════════════════════════════

CreepJS (https://abrahamjuliot.github.io/creepjs) is one of the most
thorough public browser-fingerprinting test suites available — it
scores canvas, WebGL, audio, fonts, navigator properties, timezone/
locale consistency, and general "automation likelihood" signals, and
renders a detailed visual report plus an overall trust score. It's a
good sanity check for whether jbium's stealth patches are actually
doing something a real fingerprinting script would notice, rather
than just compiling.

Run headed (headless=False) deliberately — CreepJS (and most real
anti-bot/fingerprinting systems) specifically check for headless
tells, and jbium's whole design assumes headed operation for that
reason (see driver/stealth_browser.py's own comment: "headless=False
recommended for DataDome").

Usage:
    python example/visit_creepjs.py

Requires a real proxy — jbium's fingerprint generation resolves the
proxy's exit IP for GeoIP-consistent language/timezone/screen
choices, so `Jbium.launch()` takes proxy_url as a required argument.
This example uses the same Webshare-env-var convention every other
script in this repo uses (see driver/stealth_browser.py's
get_random_webshare_proxy()):

    export STEALTH_WEBSHARE_USERNAME=<your-username>
    export STEALTH_WEBSHARE_PASSWORD=<your-password>

If you're using a different proxy provider, just replace the
`proxy_url = get_random_webshare_proxy()` line below with your own
"http://user:pass@host:port" string.
"""

import asyncio
import sys
from pathlib import Path

# Run from anywhere without installing the package first — resolves
# the repo root so `driver` imports regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

from driver.stealth_browser import Jbium, get_random_webshare_proxy

CREEPJS_URL = "https://abrahamjuliot.github.io/creepjs"
SCREENSHOT_PATH = str(Path(__file__).parent / "creepjs_result.png")

# A handful of standard, well-documented navigator/screen properties —
# not CreepJS-specific internals, which aren't something to guess at
# without reading CreepJS's own source — just enough to eyeball
# whether the basic spoofed values look consistent before looking at
# CreepJS's own, much more detailed visual report.
QUICK_CHECK_JS = """
(() => ({
    webdriver: navigator.webdriver,
    platform: navigator.platform,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: navigator.deviceMemory,
    languages: navigator.languages,
    pluginsLength: navigator.plugins.length,
    screen: `${screen.width}x${screen.height}`,
    timezoneOffset: new Date().getTimezoneOffset(),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
}))()
"""


async def main():
    proxy_url = get_random_webshare_proxy()
    print(f"Using proxy: {proxy_url}")

    async with Jbium() as browser:
        await browser.launch(
            proxy_url=proxy_url,
            headless=False,  # headed on purpose — see module docstring
        )

        page = await browser.new_page()
        print(f"Navigating to {CREEPJS_URL} ...")
        await page.goto(CREEPJS_URL)

        # CreepJS runs a battery of async checks (canvas/WebGL/audio
        # rendering, timing-based tests) after the initial page load —
        # give it time to finish before screenshotting the result.
        print("Waiting for CreepJS to finish computing its fingerprint...")
        await asyncio.sleep(10)

        quick_check = await page.evaluate(QUICK_CHECK_JS)
        print("\nQuick navigator self-check:")
        for key, value in quick_check.items():
            print(f"  {key}: {value}")

        await page.screenshot(SCREENSHOT_PATH)
        print(f"\nFull CreepJS report screenshot saved: {SCREENSHOT_PATH}")
        print("Open it to see CreepJS's detailed trust score and breakdown.")

        print("\nBrowser will stay open for manual inspection — Ctrl+C to exit.")
        try:
            await asyncio.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    asyncio.run(main())
