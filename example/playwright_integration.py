"""
════════════════════════════════════════════════════════════
Example: driving jbium with Playwright
════════════════════════════════════════════════════════════

jbium's own StealthPage (goto/evaluate/click/type_text/screenshot) is
intentionally minimal — it's a thin synchronous CDP wrapper, not a full
automation framework. It has no request/response event listener at
all: every _command() call blocks waiting for a matching response id,
so a CDP *event* (as opposed to a command reply) arriving mid-wait
would just be silently discarded. That's fine for the stealth/fingerprint
work jbium exists to do, but it means jbium alone cannot listen to
network traffic, intercept requests, or inspect GraphQL/XHR/fetch
calls.

It doesn't need to. jbium launches a real, unmodified-at-the-protocol-
level Chromium with a normal CDP endpoint
(--remote-debugging-port=<port>), so any real automation framework can
attach to it directly with Playwright's own connect_over_cdp() and use
its mature request/response interception — you get jbium's proxy
handling, GeoIP-consistent fingerprint generation, and stealth patches
*underneath*, and Playwright's full API *on top*.

Division of responsibility:
  - jbium:       proxy → GeoIP → device fingerprint → launch the
                  patched, stealth Chromium binary
  - Playwright:   everything else — network interception, request/
                  response inspection, GraphQL detection, route
                  mocking, tracing, etc.

Usage:
    pip install playwright   # only the Python package — no need to
                              # run `playwright install`; we're
                              # attaching to jbium's own binary, not
                              # one of Playwright's managed browsers
    python example/playwright_integration.py

Verified live (2026-09-14) against a real Webshare proxy and
https://abrahamjuliot.github.io/creepjs: Playwright's page.on("request")
correctly captured every request the page made, including jbium's own
internal chrome://resources/... calls and the real page's document/
script/stylesheet/fetch requests.
"""

import asyncio
import sys
from pathlib import Path

# Works two ways: from inside a full repo checkout (driver.stealth_browser,
# via the repo-root sys.path insert below) or after `pip install jbium`
# on a fresh server (jbium.stealth_browser, a real installed package --
# no sys.path hack needed, but harmless if already on sys.path).
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from driver.stealth_browser import Jbium, get_random_webshare_proxy
except ModuleNotFoundError:
    from jbium.stealth_browser import Jbium, get_random_webshare_proxy
from playwright.async_api import async_playwright

TARGET_URL = "https://abrahamjuliot.github.io/creepjs"


def is_graphql_request(request) -> bool:
    """
    Heuristic GraphQL detection — there's no single reliable signal, so
    this checks the two most common conventions: a URL path containing
    "graphql" (the overwhelming majority of real-world APIs), or a POST
    body that looks like a GraphQL operation ("query"/"mutation" plus
    an "operationName" or "variables" key, which regular REST JSON
    bodies essentially never combine).
    """

    if "graphql" in request.url.lower():
        return True

    if request.method == "POST":
        post_data = request.post_data or ""
        looks_like_graphql = (
            '"query"' in post_data or '"mutation"' in post_data
        ) and (
            '"operationName"' in post_data or '"variables"' in post_data
        )
        if looks_like_graphql:
            return True

    return False


async def main():
    proxy_url = get_random_webshare_proxy()
    print(f"Using proxy: {proxy_url}")

    async with Jbium() as browser:
        await browser.launch(proxy_url=proxy_url, headless=False)

        # jbium's own CDP debug port — this is the hand-off point to
        # Playwright. Anything opened via connect_over_cdp shares the
        # same browser process, same proxy, same fingerprint patches.
        cdp_url = f"http://127.0.0.1:{browser._debug_port}"
        print(f"Handing off to Playwright at {cdp_url}")

        async with async_playwright() as p:
            pw_browser = await p.chromium.connect_over_cdp(cdp_url)
            context = pw_browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()

            # ── Network / API / GraphQL call listening ──
            # This is the part jbium's own driver cannot do — Playwright's
            # page.on() event system handles every request/response the
            # page makes, including ones jbium's own CDP wrapper would
            # have silently dropped.
            all_requests = []
            api_calls = []
            graphql_calls = []

            def on_request(request):
                all_requests.append(request)
                if request.resource_type in ("xhr", "fetch"):
                    api_calls.append(request)
                if is_graphql_request(request):
                    graphql_calls.append(request)

            def on_response(response):
                # Response bodies are fetched lazily — only call
                # response.text()/.json() for the ones you actually
                # care about, since reading every body on every
                # response is wasteful on a busy page.
                pass

            page.on("request", on_request)
            page.on("response", on_response)

            print(f"Navigating to {TARGET_URL} ...")
            await page.goto(TARGET_URL, wait_until="load")
            await asyncio.sleep(5)  # let async fingerprinting/XHR calls settle

            print(f"\nTotal requests captured: {len(all_requests)}")
            print(f"XHR/fetch (API) calls: {len(api_calls)}")
            for req in api_calls:
                print(f"  [{req.method}] {req.url}")

            print(f"GraphQL-looking calls: {len(graphql_calls)}")
            for req in graphql_calls:
                print(f"  [{req.method}] {req.url}")
                if req.post_data:
                    print(f"    body: {req.post_data[:200]}")

            # Example: read a specific response body once you've found
            # the request you care about (uncomment and adapt):
            #
            # response = await page.wait_for_response(
            #     lambda r: "graphql" in r.url
            # )
            # data = await response.json()

            # Route interception / mocking is also available directly
            # from Playwright, on top of jbium's stealth patches:
            #
            # await page.route("**/graphql", lambda route: route.fulfill(
            #     status=200, body='{"data": {"mocked": true}}'
            # ))

            await pw_browser.close()


if __name__ == "__main__":
    asyncio.run(main())
