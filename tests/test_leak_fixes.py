"""
Regression tests for the fingerprint-leak fixes in the driver:

  1. CDP over --remote-debugging-pipe (no TCP debugging port)
  2. WebGL strings: real Chrome formats, no GL version override
  3. navigator.languages / Accept-Language list format
  4. UA-CH brand lists match the User-Agent's Chrome version
  5. UA-CH architecture / bitness / model / platformVersion set
  +  Sec-CH-UA* request headers overridden per page to match

The unit tests need no browser. The live tests launch a real Chrome/
Chromium through the driver's own spawn path; they run when one is
found (JBIUM_TEST_BROWSER, or a standard Chrome install) and are
skipped otherwise. A stock Chrome has none of the jbium patches, so the
live tests only check what the driver itself controls: the transport,
the per-page Client Hints override, and the UI locale.

Run:  python -m pytest tests/test_leak_fixes.py -v
"""

import asyncio
import http.server
import json
import os
import shutil
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from driver.device_generator import DeviceGenerator, DeviceProfile, ua_brand_lists  # noqa: E402
from driver.geoip_resolver import GeoProfile  # noqa: E402
from driver.stealth_browser import Jbium, StealthSession  # noqa: E402

REPO = Path(__file__).parent.parent
FINGERPRINTS = json.loads((REPO / "config" / "fingerprints.json").read_text(encoding="utf-8"))
PINNED_VERSION = "120.0.6099.224"


def make_geo(locale="de-DE", country="DE", tz="Europe/Berlin") -> GeoProfile:
    return GeoProfile(
        country_code=country, country_name="Germany", city="Berlin", region="Berlin",
        latitude=52.52, longitude=13.405, timezone=tz, language=locale, locale=locale,
        currency="EUR", date_format="DD.MM.YYYY", ip_type="residential", asn="0",
        isp="test", organization="test", common_screen_resolutions=[], common_fonts=[],
        os_distribution={}, confidence=1.0,
    )


def make_device(template: str = "macbook_pro", full_version: str = PINNED_VERSION) -> DeviceProfile:
    gen = DeviceGenerator(templates_path=str(REPO / "config" / "fingerprints.json"))
    device = gen.generate(make_geo(), preferred_template=template)
    if full_version != device.chrome_full_version:
        device.user_agent = device.user_agent.replace(device.chrome_full_version, full_version)
        device.chrome_full_version = full_version
    return device


def make_jbium(browser_path: str = "unused") -> Jbium:
    return Jbium(config_path=str(REPO / "config" / "settings.yaml"), browser_path=browser_path)


# ─────────────────────────────────────────────
# Unit tests (no browser)
# ─────────────────────────────────────────────

def test_brand_lists_match_real_chrome_120():
    # The Sec-CH-UA value real Chrome 120 sends, verbatim.
    brands, full = ua_brand_lists(PINNED_VERSION)
    assert brands == [("Not_A Brand", "8"), ("Chromium", "120"), ("Google Chrome", "120")]
    assert full == [("Not_A Brand", "8.0.0.0"), ("Chromium", PINNED_VERSION),
                    ("Google Chrome", PINNED_VERSION)]


# What a fresh stock Chrome reports as navigator.languages for each UI
# language (measured, and identical to IDS_ACCEPT_LANGUAGES at the
# pinned 120 tag).
@pytest.mark.parametrize("locale,ui,expected", [
    ("en-US", "en-US", ["en-US", "en"]),
    ("en-GB", "en-GB", ["en-GB", "en-US", "en"]),
    ("en-AU", "en-GB", ["en-GB", "en-US", "en"]),
    ("de-DE", "de", ["de-DE", "de", "en-US", "en"]),
    ("fr-FR", "fr", ["fr-FR", "fr", "en-US", "en"]),
    ("ja-JP", "ja", ["ja", "en-US", "en"]),
    ("ko-KR", "ko", ["ko-KR", "ko", "en-US", "en"]),
    ("es-ES", "es", ["es-ES", "es"]),
    ("es-MX", "es-419", ["es-419", "es"]),
    ("pt-BR", "pt-BR", ["pt-BR", "pt", "en-US", "en"]),
    ("zh-CN", "zh-CN", ["zh-CN", "zh"]),
    ("zh-HK", "zh-TW", ["zh-TW", "zh", "en-US", "en"]),
    ("nl-NL", "nl", ["nl-NL", "nl", "en-US", "en"]),
    ("af-ZA", "af", ["en-US", "en"]),
])
def test_accept_languages_match_stock_chrome(locale, ui, expected):
    geo = make_geo(locale)
    assert Jbium._ui_locale(geo) == ui
    assert Jbium._accept_languages(geo) == expected


def test_locales_json_templates_match_driver():
    # config/locales.json documents the header per locale; it must not
    # contradict what the driver actually sends.
    data = json.loads((REPO / "config" / "locales.json").read_text(encoding="utf-8"))
    for locale, header in data["accept_language_templates"].items():
        if locale.startswith("$"):
            continue
        expected = Jbium._accept_languages(make_geo(locale))
        assert [part.split(";")[0] for part in header.split(",")] == expected, locale
        assert data["language_fallbacks"][locale] == expected, locale


@pytest.mark.parametrize("template", sorted(FINGERPRINTS["templates"]))
def test_env_vars_have_no_leaky_or_dead_values(template):
    jb = make_jbium()
    device = make_device(template)
    env = jb._generate_env_vars(device, make_geo(), "http://proxy.invalid:1")

    # 2. GL version strings are left to Chrome's own constants.
    assert "STEALTH_GPU_VERSION" not in env
    assert "STEALTH_GPU_GLSL_VERSION" not in env
    # 3. Plain comma list — no q-values, no duplicates.
    langs = env["STEALTH_GEO_LANGUAGES"].split(",")
    assert all(";" not in lang and lang.strip() == lang for lang in langs)
    assert len(langs) == len(set(langs))
    # 4. Brand lists track the UA's version.
    ua_version = device.user_agent.split("Chrome/")[1].split(" ")[0]
    assert env["STEALTH_UA_FULL_BRANDS"].endswith(f"Google Chrome={ua_version}")
    assert f"Chromium={ua_version}" in env["STEALTH_UA_FULL_BRANDS"]
    assert env["STEALTH_UA_BRANDS"] == "Not_A Brand=8|Chromium=120|Google Chrome=120"
    # 5. High-entropy hints come from the profile.
    tmpl = FINGERPRINTS["templates"][template]
    assert env["STEALTH_UA_ARCHITECTURE"] == tmpl["architecture"]
    assert env["STEALTH_UA_BITNESS"] == tmpl["bitness"]
    assert env["STEALTH_UA_MODEL"] == ""
    assert env["STEALTH_UA_PLATFORM_VERSION"] == tmpl["ua_platform_version"]
    assert "STEALTH_FONT_OS" in env
    # Env vars no patch reads are not set.
    for dead in ("STEALTH_PROXY_IP", "STEALTH_FILTER_WEBRTC", "STEALTH_GEO_LANGUAGE", "STEALTH_WEBGL_SEED",
                 "STEALTH_GEO_TIMEZONE", "STEALTH_GEO_LOCALE", "STEALTH_GEO_CITY"):
        assert dead not in env


@pytest.mark.parametrize("template", sorted(FINGERPRINTS["templates"]))
def test_gpu_strings_use_chrome_120_angle_format(template):
    tmpl = FINGERPRINTS["templates"][template]
    for gpu in tmpl["gpu_options"]:
        vendor, renderer = gpu["vendor"], gpu["renderer"]
        assert vendor.startswith("Google Inc. (") and vendor.endswith(")")
        backend_vendor = vendor[len("Google Inc. ("):-1]
        assert renderer.startswith(f"ANGLE ({backend_vendor}, ")
        if tmpl["ua_platform"] == "Windows":
            assert renderer.endswith(" Direct3D11 vs_5_0 ps_5_0, D3D11)")
        elif tmpl["ua_platform"] == "macOS":
            assert "ANGLE Metal Renderer: Apple M" in renderer
            assert renderer.endswith(", Unspecified Version)")
        else:
            assert ", OpenGL 4." in renderer


def test_ua_override_params_consistent():
    jb = make_jbium()
    device = make_device("macbook_pro")
    params = jb._user_agent_override_params(device)
    meta = params["userAgentMetadata"]
    assert params["userAgent"] == device.user_agent
    assert meta["platform"] == "macOS"
    assert meta["architecture"] == "arm"
    assert meta["platformVersion"] == FINGERPRINTS["templates"]["macbook_pro"]["ua_platform_version"]
    assert meta["fullVersion"] == PINNED_VERSION
    assert meta["brands"][-1] == {"brand": "Google Chrome", "version": "120"}


# ─────────────────────────────────────────────
# Live tests (real browser through the driver's spawn path)
# ─────────────────────────────────────────────

def _find_browser():
    candidates = [
        os.environ.get("JBIUM_TEST_BROWSER"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"),
    ]
    return next((c for c in candidates if c and Path(c).exists()), None)


BROWSER = _find_browser()
live = pytest.mark.skipif(BROWSER is None, reason="no Chrome/Chromium found (set JBIUM_TEST_BROWSER)")


class _HeaderRecorder(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        _HeaderRecorder.seen.append({k.lower(): v for k, v in self.headers.items()})
        body = b"<html><body>ok</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        # Ask for the high-entropy hints on subsequent requests.
        self.send_header("Accept-CH", "Sec-CH-UA-Arch, Sec-CH-UA-Bitness, Sec-CH-UA-Full-Version-List, "
                                      "Sec-CH-UA-Platform-Version, Sec-CH-UA-Model")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


async def _launch_local(jb: Jbium, device: DeviceProfile, geo: GeoProfile):
    """launch() minus the proxy-IP / GeoIP network lookups."""

    env_vars = jb._generate_env_vars(device, geo, "direct://")
    jb._session = StealthSession(proxy_url="direct://", proxy_ip="127.0.0.1",
                                 geo_profile=geo, device_profile=device, env_vars=env_vars)
    jb._browser_process = await jb._spawn_browser(
        proxy_url="direct://", headless=True, env_vars=env_vars,
        device_profile=device, geo_profile=geo,
    )
    await jb._wait_for_browser_ready(device)


@live
def test_live_pipe_transport_and_client_hints():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HeaderRecorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    _HeaderRecorder.seen = []

    async def run():
        jb = make_jbium(BROWSER)
        device = make_device("macbook_pro")
        geo = make_geo("de-DE")
        await _launch_local(jb, device, geo)
        process, profile_dir = jb._browser_process, jb._user_data_dir
        try:
            assert jb._debug_port is None
            # No TCP debugging endpoint: nothing ever wrote DevToolsActivePort.
            assert not (Path(profile_dir) / "DevToolsActivePort").exists()

            page = await jb.new_page()
            await page.goto(url)
            await page.goto(url)  # second request carries the Accept-CH hints

            hints = await page.evaluate(
                "navigator.userAgentData.getHighEntropyValues(['architecture','bitness',"
                "'model','platformVersion','fullVersionList','uaFullVersion'])"
                ".then(v => JSON.stringify({...v, brands: navigator.userAgentData.brands,"
                " ua: navigator.userAgent, platform: navigator.platform,"
                " intl: Intl.DateTimeFormat().resolvedOptions().locale}))"
            )
            hints = json.loads(hints)

            # Probe the port range a detector would scan for a CDP endpoint.
            reachable = await page.evaluate("""
                (async () => {
                  const hits = [];
                  const probe = async (p) => {
                    try {
                      await fetch(`http://127.0.0.1:${p}/json/version`,
                                  {mode: 'no-cors', signal: AbortSignal.timeout(1500)});
                      hits.push(p);
                    } catch (e) {}
                  };
                  for (let p = 9222; p <= 9999; p += 64) {
                    const batch = [];
                    for (let q = p; q < Math.min(p + 64, 10000); q++) batch.push(probe(q));
                    await Promise.all(batch);
                  }
                  return hits;
                })()
            """)
            return device, hints, reachable, process, profile_dir
        finally:
            await jb.close()

    device, hints, reachable, process, profile_dir = asyncio.run(run())
    server.shutdown()

    # 1. Transport: no CDP port, clean shutdown, profile removed.
    assert reachable == [], f"ports answered from page JS: {reachable}"
    assert process.poll() is not None
    assert not Path(profile_dir).exists()

    # UA-CH in JS (driven by the per-page override on a stock browser).
    assert hints["ua"] == device.user_agent
    assert hints["platform"] == device.platform
    assert hints["architecture"] == "arm" and hints["bitness"] == "64" and hints["model"] == ""
    assert hints["platformVersion"] == device.ua_platform_version
    assert hints["uaFullVersion"] == PINNED_VERSION
    assert [b["brand"] for b in hints["brands"]] == ["Not_A Brand", "Chromium", "Google Chrome"]
    assert hints["fullVersionList"][-1] == {"brand": "Google Chrome", "version": PINNED_VERSION}
    # UI locale follows the profile's language (Intl default locale).
    assert hints["intl"].split("-")[0] == "de"

    # Same values on the wire.
    first, second = _HeaderRecorder.seen[0], _HeaderRecorder.seen[-1]
    assert first["user-agent"] == device.user_agent
    assert first["sec-ch-ua-platform"] == '"macOS"'
    assert first["sec-ch-ua"] == '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
    assert second["sec-ch-ua-arch"] == '"arm"'
    assert second["sec-ch-ua-bitness"] == '"64"'
    assert second["sec-ch-ua-platform-version"] == f'"{device.ua_platform_version}"'
    assert second["sec-ch-ua-full-version-list"].endswith(f'"Google Chrome";v="{PINNED_VERSION}"')


@live
def test_live_expose_cdp_port_is_opt_in():
    async def run():
        jb = make_jbium(BROWSER)
        device, geo = make_device("win_mainstream_laptop"), make_geo("en-US", "US", "America/New_York")
        env_vars = jb._generate_env_vars(device, geo, "direct://")
        jb._session = StealthSession(proxy_url="direct://", proxy_ip="127.0.0.1",
                                     geo_profile=geo, device_profile=device, env_vars=env_vars)
        jb._browser_process = await jb._spawn_browser(
            proxy_url="direct://", headless=True, env_vars=env_vars,
            device_profile=device, geo_profile=geo, expose_cdp_port=True,
        )
        try:
            await jb._wait_for_browser_ready(device)
            port = await jb._read_devtools_active_port()
            assert 0 < port < 65536
        finally:
            await jb.close()

    asyncio.run(run())


# ─────────────────────────────────────────────
# Virtual display (Linux only: Xvfb + --force-device-scale-factor)
# ─────────────────────────────────────────────

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="Xvfb / -displayfd are POSIX-only")


@posix_only
def test_virtual_display_reads_display_number(tmp_path, monkeypatch):
    # A stand-in Xvfb that just reports display 42 on -displayfd, then
    # sleeps like a real server — exercises the driver's own plumbing
    # without needing Xvfb installed.
    fake = tmp_path / "Xvfb"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, time\n"
        "fd = int(sys.argv[sys.argv.index('-displayfd') + 1])\n"
        "assert '3456x2234x24' in sys.argv, sys.argv\n"
        "os.write(fd, b'42\\n'); os.close(fd)\n"
        "time.sleep(60)\n"
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    async def run():
        jb = make_jbium()
        device = make_device("macbook_pro")
        device.screen_width, device.screen_height, device.device_pixel_ratio = 1728, 1117, 2.0
        display = await jb._start_virtual_display(device)
        try:
            assert display == ":42"
            assert jb._xvfb_process is not None and jb._xvfb_process.poll() is None
        finally:
            jb._xvfb_process.kill()
            jb._xvfb_process.wait()

    asyncio.run(run())


@posix_only
def test_virtual_display_missing_xvfb_falls_back(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert asyncio.run(make_jbium()._start_virtual_display(make_device())) is None


@live
@pytest.mark.skipif(not sys.platform.startswith("linux") or shutil.which("Xvfb") is None,
                    reason="needs Linux with Xvfb installed")
def test_live_screen_matches_profile_on_virtual_display():
    async def run():
        jb = make_jbium(BROWSER)
        device = make_device("macbook_pro")
        device.screen_width, device.screen_height, device.device_pixel_ratio = 1728, 1117, 2.0
        geo = make_geo("en-US", "US", "America/New_York")
        env_vars = jb._generate_env_vars(device, geo, "direct://")
        jb._session = StealthSession(proxy_url="direct://", proxy_ip="127.0.0.1",
                                     geo_profile=geo, device_profile=device, env_vars=env_vars)
        jb._browser_process = await jb._spawn_browser(
            proxy_url="direct://", headless=False, env_vars=env_vars,
            device_profile=device, geo_profile=geo,
        )
        xvfb = jb._xvfb_process
        try:
            await jb._wait_for_browser_ready(device)
            page = await jb.new_page()
            await page.goto("https://example.com/")
            screen = json.loads(await page.evaluate(
                "JSON.stringify({w: screen.width, h: screen.height, dpr: devicePixelRatio,"
                " depth: screen.colorDepth, mq: matchMedia('(resolution: 2dppx)').matches})"
            ))
        finally:
            await jb.close()
        return screen, xvfb

    screen, xvfb = asyncio.run(run())
    assert screen == {"w": 1728, "h": 1117, "dpr": 2, "depth": 24, "mq": True}
    assert xvfb is not None and xvfb.poll() is not None  # stopped by close()


def test_swiftshader_icd_manifest_is_written_when_missing(tmp_path):
    # Release archives shipped libvk_swiftshader.so without its ICD
    # manifest, which left GPU-less machines with no WebGL at all.
    platform_key = "linux" if sys.platform.startswith("linux") else sys.platform
    library_path = Jbium._SWIFTSHADER_LIBS[platform_key]
    (tmp_path / library_path.lstrip(".\\/")).write_bytes(b"")
    jb = make_jbium(str(tmp_path / "jbium"))

    jb._ensure_swiftshader_icd()
    manifest = json.loads((tmp_path / "vk_swiftshader_icd.json").read_text())
    # Byte-for-byte what the pinned SwiftShader BUILD.gn writes.
    assert manifest == {"file_format_version": "1.0.0",
                        "ICD": {"library_path": library_path, "api_version": "1.0.5"}}

    # An existing manifest is left alone.
    (tmp_path / "vk_swiftshader_icd.json").write_text("custom")
    jb._ensure_swiftshader_icd()
    assert (tmp_path / "vk_swiftshader_icd.json").read_text() == "custom"


# ─────────────────────────────────────────────
# GeoIP: timezone + language must follow the IP's actual location
# ─────────────────────────────────────────────

from types import SimpleNamespace  # noqa: E402

from driver.geoip_resolver import GeoIPResolver  # noqa: E402


def _fake_city_response(country, lat, lon, time_zone=None, city="X"):
    """The subset of a geoip2 City response GeoIPResolver reads."""
    return SimpleNamespace(
        country=SimpleNamespace(iso_code=country, name=country),
        city=SimpleNamespace(name=city),
        location=SimpleNamespace(latitude=lat, longitude=lon, time_zone=time_zone),
        subdivisions=SimpleNamespace(most_specific=SimpleNamespace(name="R")),
        traits=SimpleNamespace(organization=None),
    )


def _resolver_with(response):
    resolver = GeoIPResolver(db_path="does-not-exist.mmdb", asn_db_path="does-not-exist.mmdb")
    resolver._reader = SimpleNamespace(city=lambda ip: response)
    return resolver


@pytest.mark.parametrize("country,lat,lon,expected", [
    ("HR", 45.81, 15.98, "Europe/Zagreb"),         # Zagreb
    ("RO", 45.14, 24.68, "Europe/Bucharest"),      # Curtea de Arges
    ("US", 34.05, -118.24, "America/Los_Angeles"),
    ("US", 41.88, -87.63, "America/Chicago"),
    ("US", 40.71, -74.01, "America/New_York"),
    ("AU", -33.87, 151.21, "Australia/Sydney"),
    ("BR", -23.55, -46.63, "America/Sao_Paulo"),
])
def test_timezone_follows_ip_location_without_db_timezone(country, lat, lon, expected):
    # The free DB-IP database has coordinates but no time_zone: the zone
    # must still be the one the IP is in, never UTC or a random city's.
    geo = _resolver_with(_fake_city_response(country, lat, lon))._resolve_local("203.0.113.9")
    assert geo.timezone == expected
    assert (geo.latitude, geo.longitude) == (lat, lon)


def test_database_timezone_and_city_win_over_locales_json_cities():
    # US is in locales.json with a city list; the IP's own city/zone must
    # be used, not a randomly picked one from that list.
    response = _fake_city_response("US", 47.61, -122.33, time_zone="America/Los_Angeles", city="Seattle")
    for _ in range(20):
        geo = _resolver_with(response)._resolve_local("203.0.113.9")
        assert (geo.city, geo.timezone) == ("Seattle", "America/Los_Angeles")


@pytest.mark.parametrize("country,language,accept", [
    ("HR", "hr-HR", ["hr-HR", "hr", "en-US", "en"]),
    ("RO", "ro-RO", ["ro-RO", "ro", "en-US", "en"]),
    ("NL", "nl-NL", ["nl-NL", "nl", "en-US", "en"]),
    ("IN", "en-IN", ["en-GB", "en-US", "en"]),
    ("CA", "en-CA", ["en-GB", "en-US", "en"]),
    ("US", "en-US", ["en-US", "en"]),
    ("DE", "de-DE", ["de-DE", "de", "en-US", "en"]),  # locales.json country
])
def test_language_follows_ip_country(country, language, accept):
    geo = _resolver_with(_fake_city_response(country, 0.0, 0.0))._resolve_local("203.0.113.9")
    assert geo.language == language
    assert Jbium._accept_languages(geo) == accept


def test_country_geo_covers_every_tzdata_country():
    data = json.loads((REPO / "config" / "country_geo.json").read_text(encoding="utf-8"))["countries"]
    assert len(data) >= 240
    for cc, entry in data.items():
        assert entry["timezones"] and "-" in entry["language"], cc
