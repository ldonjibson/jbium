#!/usr/bin/env python3
"""
Quick check — launch browser, visit one site, check detection.
Useful for rapid iteration after patch changes.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from driver.stealth_browser import Jbium, get_random_webshare_proxy


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://bot.sannysoft.com/"
    
    proxy = get_random_webshare_proxy()
    print(f"Proxy: {proxy}")
    
    async with Jbium() as browser:
        session = await browser.launch(
            proxy_url=proxy,
            headless=False,
        )
        
        page = await browser.new_page()
        await page.goto(url)
        
        # Quick detection check
        detection = await page.check_detection()
        
        print(f"\n{'═' * 50}")
        print(f"URL: {url}")
        print(f"Title: {await page.get_title()}")
        print(f"Detected: {detection['detected']}")
        
        if detection['detected']:
            for key, val in detection.items():
                if val and key != "detected":
                    print(f"  ⚠️  {key}")
        
        print(f"{'═' * 50}\n")
        
        # Take screenshot
        await page.screenshot("quick_check.png")
        print("Screenshot: quick_check.png")
        
        # Print key props
        ua = await page.evaluate("navigator.userAgent")
        platform = await page.evaluate("navigator.platform")
        cores = await page.evaluate("navigator.hardwareConcurrency")
        webdriver = await page.evaluate("navigator.webdriver")
        
        print(f"User-Agent: {ua}")
        print(f"Platform: {platform}")
        print(f"CPU cores: {cores}")
        print(f"navigator.webdriver: {webdriver}")
        
        # Wait for manual inspection
        input("\nPress Enter to close...")


if __name__ == "__main__":
    asyncio.run(main())
