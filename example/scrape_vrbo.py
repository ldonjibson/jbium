"""
════════════════════════════════════════════════════════════
Example: scraping + interacting with a real VRBO listing
════════════════════════════════════════════════════════════

vrbo.com is the site referenced in stealth_browser.py's own module
docstring from the start of this project — a real commercial listing
site with real anti-bot protection, not a synthetic fingerprinting
test page like CreepJS. This example is the fuller, real-world
counterpart to example/visit_creepjs.py: navigate, confirm nothing
tripped detection, extract real listing data, then click into two
different in-page modals (guest reviews, full amenities) using
StealthPage's humanized click() rather than just reading static
content.

Verified live (2026-09-14) against
https://www.vrbo.com/7298930ha?dateless=true through a real Webshare
proxy: page loaded fully rendered with zero detection flags, listing
data extracted correctly (title, rating, property details), and both
clicks produced genuine app-state changes — the reviews click changed
the URL to include `?pwaDialog=product-reviews` and opened a real
`[role=dialog]`, the amenities click grew the DOM from 273 to 474
nodes as the full categorized amenities list rendered.

Note on selectors: this deliberately matches elements by their visible
text ("see all 52 reviews", "see all") rather than a specific CSS
class or data-testid, since those are far more likely to survive a
markup change than an auto-generated class name — but real-world
sites do change over time, so don't assume this will match forever.
Also worth knowing: jbium randomizes screen resolution per session
(part of its device-fingerprint generation), and VRBO's own responsive
layout renders some sections differently at different viewport
widths — an element present at one screen size may simply not exist
in the DOM at another, which is normal site behavior, not a jbium bug.

Usage:
    export STEALTH_WEBSHARE_USERNAME=<your-username>
    export STEALTH_WEBSHARE_PASSWORD=<your-password>
    python example/scrape_vrbo.py
"""

import asyncio
import sys
from pathlib import Path

# Run from anywhere without installing the package first — resolves
# the repo root so `driver` imports regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

from driver.stealth_browser import Jbium, get_random_webshare_proxy

VRBO_URL = "https://www.vrbo.com/7298930ha?dateless=true"
SCREENSHOT_DIR = Path(__file__).parent

EXTRACT_JS = """
(() => ({
    title: document.title,
    h1: document.querySelector('h1')?.innerText || null,
    bodyTextSample: document.body.innerText.slice(0, 500),
}))()
"""

# document.querySelector can't match by visible text on its own, so
# these tag the matching element with a temporary data attribute
# first, then click() targets that attribute — see the module
# docstring's note on why text-matching was chosen over CSS classes.
TAG_REVIEWS_JS = """
(() => {
    const el = [...document.querySelectorAll('a, button')].find(
        e => e.innerText && e.innerText.toLowerCase().includes('reviews')
    );
    if (!el) return false;
    el.setAttribute('data-jbium-example', 'reviews-link');
    return el.innerText;
})()
"""

TAG_AMENITIES_JS = """
(() => {
    const el = [...document.querySelectorAll('a, button')].find(
        e => e.innerText && e.innerText.trim().toLowerCase() === 'see all'
    );
    if (!el) return false;
    el.setAttribute('data-jbium-example', 'amenities-link');
    return el.innerText;
})()
"""


async def main():
    proxy_url = get_random_webshare_proxy()
    print(f"Using proxy: {proxy_url}")

    async with Jbium() as browser:
        await browser.launch(proxy_url=proxy_url, headless=False)
        page = await browser.new_page()

        print(f"Navigating to {VRBO_URL} ...")
        await page.goto(VRBO_URL, timeout=45)

        # idle() rather than a bare sleep -- see StealthPage.idle's own
        # docstring for why a motionless browser during an async wait
        # is itself worth avoiding.
        print("Letting the page settle...")
        await page.idle(5.0)

        detection = await page.check_detection()
        print(f"\nDetection check: {detection}")

        data = await page.evaluate(EXTRACT_JS)
        print("\nExtracted listing data:")
        print(f"  title: {data.get('title')!r}")
        print(f"  h1: {data.get('h1')!r}")
        print(f"  bodyTextSample: {data.get('bodyTextSample')!r}")

        await page.screenshot(str(SCREENSHOT_DIR / "vrbo_result.png"))
        print(f"\nScreenshot saved: {SCREENSHOT_DIR / 'vrbo_result.png'}")

        # --- Interaction 1: open the guest reviews dialog ---
        found = await page.evaluate(TAG_REVIEWS_JS)
        if found:
            print(f"\nClicking reviews link ({found!r})...")
            await page.click('[data-jbium-example="reviews-link"]')
            await page.idle(3.0)
            url_after = await page.evaluate("window.location.href")
            dialog_open = await page.evaluate('!!document.querySelector("[role=dialog]")')
            print(f"  URL after click: {url_after!r}")
            print(f"  Dialog open: {dialog_open}")
            await page.screenshot(str(SCREENSHOT_DIR / "vrbo_reviews_dialog.png"))
        else:
            print("\nReviews link not found at this viewport/layout -- skipping")

        # Re-navigate for a clean second interaction test.
        await page.goto(VRBO_URL, timeout=45)
        await page.idle(4.0)

        # --- Interaction 2: expand the full amenities list ---
        found = await page.evaluate(TAG_AMENITIES_JS)
        if found:
            print(f"\nClicking amenities link ({found!r})...")
            nodes_before = await page.evaluate("document.querySelectorAll('*').length")
            await page.click('[data-jbium-example="amenities-link"]')
            await page.idle(2.0)
            nodes_after = await page.evaluate("document.querySelectorAll('*').length")
            print(f"  DOM node count: {nodes_before} -> {nodes_after}")
            await page.screenshot(str(SCREENSHOT_DIR / "vrbo_amenities_dialog.png"))
        else:
            print("\nAmenities 'See all' not found at this viewport/layout -- skipping")


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(main())
