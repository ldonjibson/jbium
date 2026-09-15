"""
════════════════════════════════════════════════════════════
Example: concurrent scraping across multiple VRBO listings
════════════════════════════════════════════════════════════

The concurrent counterpart to example/scrape_vrbo.py — instead of one
browser visiting one listing, this launches several independent
Jbium() browsers at once (each gets its own real proxy IP via
get_random_webshare_proxy(), its own device fingerprint, its own
profile) to scrape a batch of listings in parallel, then writes one
JSON summary plus one screenshot per listing so you can see at a
glance which succeeded and which didn't.

Verified live (2026-09-14) against the 11 real listing URLs below, at
CONCURRENCY=4: this surfaced and led to fixing a real, previously
unknown bug in the driver itself — Jbium._spawn_browser() built each
browser's --user-data-dir from int(time.time()), only 1-second
resolution, so two concurrent launch() calls landing in the same
wall-clock second got the *identical* profile directory. Chrome's own
single-instance-per-profile lock then silently forwarded the second
process's request to the first one and exited cleanly, without ever
opening its own CDP debug port — surfacing here as a confusing
"Browser did not become ready within timeout" with no indication of
the real cause. That's now fixed at the source (driver/stealth_browser.py
generates a uuid4-based directory instead), verified with 12/12
successes across repeated concurrent runs after the fix. Before the
fix, the same 4-listing subset failed intermittently (5/11, then
10/11 with the retry+stagger below, then 12/12 once the real bug was
fixed) -- this example still keeps a light stagger and one retry as
cheap, harmless insurance against ordinary transient failures (a slow
proxy, a flaky network blip), not because the original bug is still
present.

Usage:
    export STEALTH_WEBSHARE_USERNAME=<your-username>
    export STEALTH_WEBSHARE_PASSWORD=<your-password>
    python example/concurrent_scrape_vrbo.py
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from driver.stealth_browser import Jbium, get_random_webshare_proxy

URLS = [
    "https://www.vrbo.com/1457914?dateless=true",
    "https://www.vrbo.com/4682000?dateless=true",
    "https://www.vrbo.com/4533366ha?dateless=true",
    "https://www.vrbo.com/3316902?dateless=true",
    "https://www.vrbo.com/1809022?dateless=true",
    "https://www.vrbo.com/5381969?dateless=true",
    "https://www.vrbo.com/5000383?dateless=true",
    "https://www.vrbo.com/3512802?dateless=true",
    "https://www.vrbo.com/1833473?dateless=true",
    "https://www.vrbo.com/5020693?dateless=true",
    "https://www.vrbo.com/3173476?dateless=true",
]

CONCURRENCY = 4
STAGGER_SEC = 2.0   # spread concurrent cold-starts out a little, purely
                    # to look less robotic and ease startup bursts -- not
                    # required for correctness since the uuid4 fix
MAX_ATTEMPTS = 2    # retry once on a transient failure

RESULTS_DIR = Path(__file__).parent / "vrbo_batch_results"
SCREENSHOT_DIR = RESULTS_DIR / "screenshots"

EXTRACT_JS = r"""
(() => ({
    title: document.title,
    h1: document.querySelector('h1')?.innerText || null,
    rating: document.body.innerText.match(/(\d\.\d) out of 10/)?.[1] || null,
    reviewCount: document.body.innerText.match(/See all (\d+) reviews?/)?.[1] || null,
}))()
"""


def listing_id(url: str) -> str:
    m = re.search(r"vrbo\.com/([^?]+)", url)
    return m.group(1) if m else url.replace("/", "_")


async def scrape_attempt(url: str, lid: str) -> dict:
    proxy_url = get_random_webshare_proxy()

    async with Jbium() as browser:
        await browser.launch(proxy_url=proxy_url, headless=False)
        page = await browser.new_page()
        await page.goto(url, timeout=45)
        await page.idle(5.0)  # let async fingerprinting/content settle

        detection = await page.check_detection()
        data = await page.evaluate(EXTRACT_JS)

        screenshot_path = SCREENSHOT_DIR / f"{lid}.png"
        await page.screenshot(str(screenshot_path))

        return {
            "success": not detection.get("detected", False),
            "detection": detection,
            "title": data.get("title"),
            "h1": data.get("h1"),
            "rating": data.get("rating"),
            "reviewCount": data.get("reviewCount"),
            "screenshot": str(screenshot_path),
            "proxy_ip": browser._session.proxy_ip,
        }


async def scrape_one(url: str, index: int, sem: asyncio.Semaphore) -> dict:
    lid = listing_id(url)
    result = {"url": url, "listing_id": lid, "success": False, "attempts": 0}
    start = time.time()

    # Stagger so CONCURRENCY tasks don't all cold-start their browser
    # process in the exact same instant.
    await asyncio.sleep(index * STAGGER_SEC / CONCURRENCY)

    async with sem:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            result["attempts"] = attempt
            try:
                data = await scrape_attempt(url, lid)
                result.update(data)
                result["elapsed_sec"] = round(time.time() - start, 1)
                print(f"[OK]   {lid} (attempt {attempt}): {data['title']!r} "
                      f"(detected={data['detection'].get('detected')})")
                return result
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                if attempt < MAX_ATTEMPTS:
                    print(f"[RETRY] {lid} (attempt {attempt}): {err}")
                    await asyncio.sleep(3.0)
                    continue
                result.update({
                    "success": False,
                    "error": err,
                    "elapsed_sec": round(time.time() - start, 1),
                })
                print(f"[FAIL] {lid} (attempt {attempt}): {err}")
                return result

    return result


async def main():
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [scrape_one(url, i, sem) for i, url in enumerate(URLS)]
    results = await asyncio.gather(*tasks)

    summary_path = RESULTS_DIR / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)

    succeeded = sum(1 for r in results if r["success"])
    print(f"\n{succeeded}/{len(results)} succeeded")
    print(f"Summary saved: {summary_path}")
    print(f"Screenshots saved: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(main())
