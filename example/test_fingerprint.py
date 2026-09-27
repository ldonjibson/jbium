"""
════════════════════════════════════════════════════════════
Fingerprint test: concrete pass/fail checks, not just a screenshot
════════════════════════════════════════════════════════════

Complements example/visit_creepjs.py, which screenshots CreepJS for
manual review and leaves the browser open indefinitely -- useful for
eyeballing CreepJS's trust score, but not something you can run
unattended or get a clear yes/no out of.

This script runs checks with actual expected values, so it can tell
you PASS/FAIL instead of "here's a picture, you decide":

  1. Classic automation tells read directly from navigator/screen --
     navigator.webdriver, window.chrome.runtime presence, plugin
     count, and the permissions-API/Notification.permission mismatch
     that headless Chrome has historically leaked (the check popularized
     by intoli's "not so headless chrome" writeup).

  2. STEALTH_* fingerprint consistency: jbium generates a DeviceProfile/
     GeoProfile server-side (platform, CPU cores, screen size, timezone,
     GPU vendor/renderer, ...) and sets STEALTH_* env vars for the
     compiled Chromium patches to read at runtime. This compares what
     jbium *meant* to set against what the page's own JS actually
     reports -- catches "a patch silently isn't wired up" bugs, which a
     generic trust score wouldn't clearly point at.

  3. The CDP debug-port leak: a page can fetch('http://127.0.0.1:<port>/
     json/version') across the usual DevTools port range to detect a
     --remote-debugging-port endpoint. The driver now uses
     --remote-debugging-pipe (no TCP port at all), and this runs the
     same scan a detector would, from inside the page (mode: 'no-cors',
     so only whether the fetch resolves matters -- the signal a real
     port scanner uses), to prove nothing answers.

  4. Header/JS consistency the patches and the driver must keep:
     navigator.languages is a clean list (no ";q=" parameters),
     Intl's default locale matches navigator.language, the WebGL
     VERSION / SHADING_LANGUAGE_VERSION strings are Chrome's constants,
     navigator.userAgentData (brands, fullVersionList, architecture,
     bitness, platformVersion) matches the User-Agent and the profile,
     and the Sec-CH-UA* headers a server actually receives say the same
     thing (read back from https://httpbin.org/headers).

  5. A CreepJS visit + full-page screenshot, same as visit_creepjs.py --
     its detailed trust-score breakdown isn't something to reimplement,
     so that part still needs a human glance at the saved PNG.

Run headed (headless=False) deliberately -- CreepJS (and most real
anti-bot/fingerprinting systems) specifically check for headless tells.

Usage:
    export STEALTH_WEBSHARE_USERNAME=<your-username>
    export STEALTH_WEBSHARE_PASSWORD=<your-password>
    python example/test_fingerprint.py
    python example/test_fingerprint.py --keep-open   # stay open after, for manual CreepJS review
"""

import argparse
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

CREEPJS_URL = "https://abrahamjuliot.github.io/creepjs"
SCREENSHOT_PATH = str(Path(__file__).parent / "test_fingerprint_creepjs.png")

# Everything here is a well-documented, stable JS-observable property or
# API -- deliberately not scraping CreepJS's own DOM/markup, which isn't
# something to guess at without reading its source, and could change.
CHECKS_JS = """
async () => {
    const results = {};

    // 1. Classic automation tells
    results.webdriver = navigator.webdriver;
    results.hasChromeRuntime = !!(window.chrome && window.chrome.runtime);
    results.pluginsLength = navigator.plugins.length;

    // Permissions-API / Notification.permission mismatch: in real
    // Chrome these two always agree. A gap between them (typically
    // Notification.permission === 'denied' while permissions.query()
    // still reports 'prompt') is a well-known headless tell.
    try {
        const status = await navigator.permissions.query({name: 'notifications'});
        results.permissionMismatch = (
            Notification.permission === 'denied' && status.state === 'prompt'
        );
    } catch (e) {
        results.permissionMismatch = `error: ${e.message}`;
    }

    // 2. Values to compare against jbium's intended STEALTH_* fingerprint
    results.platform = navigator.platform;
    results.hardwareConcurrency = navigator.hardwareConcurrency;
    results.deviceMemory = navigator.deviceMemory;
    results.userAgent = navigator.userAgent;
    results.language = navigator.language;
    results.languages = navigator.languages;
    results.screenWidth = screen.width;
    results.screenHeight = screen.height;
    results.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    results.intlLocale = Intl.DateTimeFormat().resolvedOptions().locale;
    results.maxTouchPoints = navigator.maxTouchPoints;

    if (navigator.userAgentData) {
        const uad = navigator.userAgentData;
        results.uaPlatform = uad.platform;
        results.uaHighEntropy = await uad.getHighEntropyValues(
            ['architecture', 'bitness', 'model', 'platformVersion', 'fullVersionList', 'uaFullVersion']);
    }

    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (gl) {
        const dbg = gl.getExtension('WEBGL_debug_renderer_info');
        results.webglVendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
        results.webglRenderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
        results.webglVersion = gl.getParameter(gl.VERSION);
        results.webglGlslVersion = gl.getParameter(gl.SHADING_LANGUAGE_VERSION);
    } else {
        results.webglVendor = null;
        results.webglRenderer = null;
    }

    return results;
}
"""


# The range DevTools ports conventionally live in, and what a detection
# script typically sweeps. With --remote-debugging-pipe nothing listens.
PORT_SCAN_JS = """
async () => {
    const hits = [];
    const probe = async (port) => {
        try {
            await fetch(`http://127.0.0.1:${port}/json/version`,
                        { mode: 'no-cors', signal: AbortSignal.timeout(1500) });
            hits.push(port);
        } catch (e) {}
    };
    for (let p = 9222; p <= 9999; p += 64) {
        const batch = [];
        for (let q = p; q < Math.min(p + 64, 10000); q++) batch.push(probe(q));
        await Promise.all(batch);
    }
    return hits;
}
"""

# Headers exactly as a server receives them (httpbin echoes them back
# with CORS enabled). A cross-origin fetch from a secure page carries the
# default low-entropy client hints: Sec-CH-UA, -Mobile, -Platform.
SERVER_HEADERS_JS = """
async () => {
    try {
        const r = await fetch('https://httpbin.org/headers', { signal: AbortSignal.timeout(10000) });
        return (await r.json()).headers;
    } catch (e) {
        return { error: `${e.name}: ${e.message}` };
    }
}
"""


def _call(fn_js: str) -> str:
    """
    StealthPage.evaluate() sends a Runtime.evaluate *expression* (it
    awaits a returned promise), so an arrow-function literal has to be
    invoked, not just passed — otherwise the result is the function
    object itself, which serializes to {}.
    """
    return f"({fn_js.strip()})()"


def _report(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {label}"
    if detail:
        line += f" -- {detail}"
    print(line)
    return ok


async def main(keep_open: bool) -> None:
    proxy_url = get_random_webshare_proxy()
    print(f"Using proxy: {proxy_url}")

    failures = 0
    warnings = 0

    async with Jbium() as browser:
        session = await browser.launch(
            proxy_url=proxy_url,
            headless=False,  # headed on purpose -- see module docstring
        )

        page = await browser.new_page()
        print(f"Navigating to {CREEPJS_URL} ...")
        await page.goto(CREEPJS_URL)

        # CreepJS runs a battery of async checks (canvas/WebGL/audio
        # rendering, timing-based tests) after the initial page load --
        # give it time to finish before screenshotting or reading any
        # of its own state.
        print("Waiting for CreepJS to finish computing its fingerprint...")
        await asyncio.sleep(10)

        print("\n--- Automation tells ---")
        checks = await page.evaluate(_call(CHECKS_JS))

        if not _report("navigator.webdriver is false/undefined",
                        not checks["webdriver"], f"got {checks['webdriver']!r}"):
            failures += 1
        if not _report("window.chrome.runtime present (real Chrome has this)",
                        checks["hasChromeRuntime"]):
            warnings += 1
        if not _report("navigator.plugins non-empty",
                        checks["pluginsLength"] > 0, f"length={checks['pluginsLength']}"):
            warnings += 1
        if checks["permissionMismatch"] is True:
            _report("Permissions API / Notification.permission consistency", False)
            failures += 1
        elif checks["permissionMismatch"] is False:
            _report("Permissions API / Notification.permission consistency", True)
        else:
            print(f"  [WARN] Permissions API check errored: {checks['permissionMismatch']}")
            warnings += 1

        print("\n--- CDP debug-port leak probe ---")
        reachable = await page.evaluate(_call(PORT_SCAN_JS))
        if not _report("No local port in 9222-9999 answers page JS",
                        not reachable,
                        f"answered: {reachable}" if reachable else "driver uses --remote-debugging-pipe"):
            failures += 1

        print("\n--- Header / JS consistency ---")
        device = session.device_profile
        claimed_version = device.user_agent.split("Chrome/")[1].split(" ")[0]
        languages = checks["languages"] or []
        if not _report("navigator.languages has no q-values or duplicates",
                        all(";" not in lang for lang in languages) and len(languages) == len(set(languages)),
                        f"got {languages!r}"):
            failures += 1
        if not _report("Intl default locale matches navigator.language",
                        checks["intlLocale"].split("-")[0] == checks["language"].split("-")[0],
                        f"Intl={checks['intlLocale']!r} navigator.language={checks['language']!r}"):
            failures += 1
        if not _report("WebGL VERSION is Chrome's constant",
                        checks.get("webglVersion") == "WebGL 1.0 (OpenGL ES 2.0 Chromium)",
                        f"got {checks.get('webglVersion')!r}"):
            failures += 1
        if not _report("WebGL SHADING_LANGUAGE_VERSION is Chrome's constant",
                        checks.get("webglGlslVersion") == "WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)",
                        f"got {checks.get('webglGlslVersion')!r}"):
            failures += 1

        high_entropy = checks.get("uaHighEntropy") or {}
        full_versions = {b["brand"]: b["version"] for b in high_entropy.get("fullVersionList", [])}
        for label, ok, detail in [
            ("userAgentData.platform == profile",
             checks.get("uaPlatform") == device.ua_platform,
             f"{checks.get('uaPlatform')!r} vs {device.ua_platform!r}"),
            ("fullVersionList matches the UA's Chrome version",
             full_versions.get("Google Chrome") == claimed_version == full_versions.get("Chromium"),
             f"{full_versions} vs UA {claimed_version}"),
            ("uaFullVersion matches the UA",
             high_entropy.get("uaFullVersion") == claimed_version,
             f"{high_entropy.get('uaFullVersion')!r} vs {claimed_version!r}"),
            ("architecture == profile",
             high_entropy.get("architecture") == device.architecture,
             f"{high_entropy.get('architecture')!r} vs {device.architecture!r}"),
            ("bitness == profile",
             high_entropy.get("bitness") == device.bitness,
             f"{high_entropy.get('bitness')!r} vs {device.bitness!r}"),
            ("platformVersion == profile",
             high_entropy.get("platformVersion") == device.ua_platform_version,
             f"{high_entropy.get('platformVersion')!r} vs {device.ua_platform_version!r}"),
        ]:
            if not _report(label, ok, detail):
                failures += 1

        server_headers = {k.lower(): v for k, v in (await page.evaluate(_call(SERVER_HEADERS_JS))).items()}
        if "error" in server_headers:
            print(f"  [WARN] Could not read headers back from httpbin: {server_headers['error']}")
            warnings += 1
        else:
            major = claimed_version.split(".")[0]
            for label, header, ok_fn in [
                ("User-Agent header == navigator.userAgent", "user-agent",
                 lambda v: v == checks["userAgent"]),
                ("Sec-CH-UA-Platform header == profile", "sec-ch-ua-platform",
                 lambda v: v == f'"{device.ua_platform}"'),
                ("Sec-CH-UA header lists Google Chrome at the UA's major version", "sec-ch-ua",
                 lambda v: f'"Google Chrome";v="{major}"' in v),
            ]:
                got = server_headers.get(header)
                if not _report(label, got is not None and ok_fn(got), f"got {got!r}"):
                    failures += 1

        print("\n--- STEALTH_* fingerprint consistency (intended vs. observed) ---")
        geo = session.geo_profile
        comparisons = [
            ("platform", device.platform, checks["platform"]),
            ("hardwareConcurrency", device.cpu_cores, checks["hardwareConcurrency"]),
            ("deviceMemory", device.ram_gb, checks["deviceMemory"]),
            ("screen width", device.screen_width, checks["screenWidth"]),
            ("screen height", device.screen_height, checks["screenHeight"]),
            ("timezone", geo.timezone, checks["timezone"]),
            ("maxTouchPoints", 10 if device.touch_support else 0, checks["maxTouchPoints"]),
            ("WebGL vendor", device.gpu_vendor, checks["webglVendor"]),
            ("WebGL renderer", device.gpu_renderer, checks["webglRenderer"]),
        ]
        for label, intended, observed in comparisons:
            if not _report(f"{label}: intended == observed",
                            intended == observed,
                            f"intended={intended!r} observed={observed!r}"):
                warnings += 1

        await page.screenshot(SCREENSHOT_PATH)
        print(f"\nFull CreepJS report screenshot saved: {SCREENSHOT_PATH}")
        print("Open it for CreepJS's own trust score and detailed breakdown --")
        print("that part still needs a human glance, not something this script scrapes.")

        print(f"\n{'='*60}")
        print(f"Summary: {failures} FAIL, {warnings} WARN")
        print(f"{'='*60}")

        if keep_open:
            print("\n--keep-open set -- browser will stay open for manual inspection. Ctrl+C to exit.")
            try:
                await asyncio.sleep(3600)
            except KeyboardInterrupt:
                pass

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep-open', action='store_true',
                         help="Leave the browser open after the checks finish, for manual CreepJS review")
    args = parser.parse_args()

    asyncio.run(main(args.keep_open))
