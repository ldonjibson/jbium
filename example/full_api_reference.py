"""
════════════════════════════════════════════════════════════
Example: every attribute and method jbium exposes
════════════════════════════════════════════════════════════

A single, runnable walkthrough of the entire public surface of the
`Jbium` / `StealthSession` / `StealthPage` API, as it actually exists
in driver/stealth_browser.py — every field and method below was read
directly from source, not from memory or docs, so this stays accurate
as the real signature list rather than an aspirational one.

This is a reference, not a "best practices" example — real code should
only touch the handful of methods it actually needs. Run it top to
bottom to see every value jbium generates and every action StealthPage
supports.

Usage:
    export STEALTH_WEBSHARE_USERNAME=<prefix>
    export STEALTH_WEBSHARE_PASSWORD=<password>
    python example/full_api_reference.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from driver.stealth_browser import Jbium, get_random_webshare_proxy

TARGET_URL = "https://example.com"


def section(title: str):
    print(f"\n{'─' * 60}\n{title}\n{'─' * 60}")


async def main():
    proxy_url = get_random_webshare_proxy()

    # ── Jbium() constructor ──
    # config_path:  path to settings.yaml (browser.extra_args,
    #               browser.filter_webrtc, geoip.database_path, ...)
    # browser_path: explicit path to the compiled binary; omit to use
    #               PlatformInfo's own search order (fetch cache, then
    #               a from-source build output dir, then STEALTH_BROWSER_PATH)
    browser = Jbium(
        config_path="config/settings.yaml",
        browser_path=None,
    )

    async with browser:
        # ── launch() — every parameter ──
        session = await browser.launch(
            proxy_url=proxy_url,
            headless=False,               # False recommended — see module docstring in stealth_browser.py
            fingerprint_profile=None,     # or an exact template name, e.g. "macbook_air"
            geoip_override=None,          # or {"country_code": "GB", "city": "London", ...}
            extensions=None,              # list of unpacked extension directory paths
            fingerprint_overrides=None,   # or {"STEALTH_GPU_VENDOR": "Custom Vendor Inc."}
        )

        # ── StealthSession — every field ──
        section("StealthSession")
        print("proxy_url:      ", session.proxy_url)
        print("proxy_ip:       ", session.proxy_ip)
        print("session_id:     ", session.session_id)
        print("created_at:     ", session.created_at)
        print("ws_url:         ", session.ws_url)
        print("env_vars keys:  ", list((session.env_vars or {}).keys()))

        # ── GeoProfile — every field (session.geo_profile) ──
        geo = session.geo_profile
        section("GeoProfile (session.geo_profile)")
        print("country_code:            ", geo.country_code)
        print("country_name:            ", geo.country_name)
        print("city:                    ", geo.city)
        print("region:                  ", geo.region)
        print("latitude:                ", geo.latitude)
        print("longitude:               ", geo.longitude)
        print("timezone:                ", geo.timezone)
        print("language:                ", geo.language)
        print("locale:                  ", geo.locale)
        print("currency:                ", geo.currency)
        print("date_format:             ", geo.date_format)
        print("ip_type:                 ", geo.ip_type)
        print("asn:                     ", geo.asn)
        print("isp:                     ", geo.isp)
        print("organization:            ", geo.organization)
        print("common_screen_resolutions:", geo.common_screen_resolutions)

        # ── DeviceProfile — every field (session.device_profile) ──
        dev = session.device_profile
        section("DeviceProfile (session.device_profile)")
        print("os:                  ", dev.os)
        print("os_version:          ", dev.os_version)
        print("platform:            ", dev.platform)
        print("architecture:        ", dev.architecture)
        print("bitness:             ", dev.bitness)
        print("cpu_cores:           ", dev.cpu_cores)
        print("cpu_model:           ", dev.cpu_model)
        print("ram_gb:              ", dev.ram_gb)
        print("gpu_vendor:          ", dev.gpu_vendor)
        print("gpu_renderer:        ", dev.gpu_renderer)
        print("screen_width:        ", dev.screen_width)
        print("screen_height:       ", dev.screen_height)
        print("available_width:     ", dev.available_width)
        print("available_height:    ", dev.available_height)
        print("color_depth:         ", dev.color_depth)
        print("device_pixel_ratio:  ", dev.device_pixel_ratio)
        print("refresh_rate:        ", dev.refresh_rate)
        print("touch_support:       ", dev.touch_support)
        print("max_touch_points:    ", dev.max_touch_points)
        print("user_agent:          ", dev.user_agent)
        print("ua_platform:         ", dev.ua_platform)
        print("ua_platform_version: ", dev.ua_platform_version)
        print("canvas_seed:         ", dev.canvas_seed)
        print("webgl_seed:          ", dev.webgl_seed)
        print("audio_seed:          ", dev.audio_seed)
        print("profile_name:        ", dev.profile_name)
        print("template_used:       ", dev.template_used)

        # ── new_page() → StealthPage ──
        page = await browser.new_page()

        # ── StealthPage — every method ──
        section("StealthPage methods")

        await page.goto(TARGET_URL, wait_until="load", timeout=30)
        print("goto() ->", TARGET_URL)

        title = await page.get_title()
        print("get_title() ->", title)

        content = await page.get_content()
        print("get_content() -> ", len(content), "chars")

        value = await page.evaluate("navigator.userAgent")
        print("evaluate('navigator.userAgent') ->", value)

        await page.move_mouse_to(400, 300)
        print("move_mouse_to(400, 300) -> done (tracks cursor position for later click()/type_text())")

        # click()/type_text() need a real selector on the current
        # page — example.com has none worth clicking, so these are
        # shown as calls you'd make against your own target page:
        #
        # await page.click("#submit-button")
        # await page.type_text("#search-input", "hello world")

        await page.scroll_to_bottom()
        print("scroll_to_bottom() -> done")

        detection = await page.check_detection()
        section("check_detection()")
        for key, val in detection.items():
            print(f"  {key}: {val}")

        screenshot_path = str(Path(__file__).parent / "full_api_reference_result.png")
        await page.screenshot(screenshot_path, full_page=True)
        print(f"\nscreenshot(full_page=True) -> {screenshot_path}")

        await page.close()
        # browser.close() runs automatically via `async with browser`


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(main())
