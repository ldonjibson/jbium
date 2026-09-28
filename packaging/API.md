# jbium API Reference

Every argument documented here was pulled directly from
`packaging/src/jbium/` source, not summarized from memory — if the
source changes, this doc needs updating alongside it.

## Install

```bash
pip install jbium              # core driver
pip install jbium[geo]         # + accurate local GeoIP via MaxMind GeoLite2
jbium fetch                    # downloads the prebuilt browser binary for your OS/arch
jbium fetch-geoip              # downloads the GeoIP databases [geo] needs (see below)
```

---

## `Jbium` — the main class

```python
from jbium import Jbium
```

### `Jbium(config_path=None, browser_path=None)`

| Argument | Type | Default | Behavior |
|---|---|---|---|
| `config_path` | `str` | `None` | Path to a `settings.yaml`. If `None`, uses the packaged default at `jbium/config/settings.yaml`. If that file doesn't exist either, falls back to a hardcoded default dict (see "Config file" below). |
| `browser_path` | `str` | `None` | Explicit path to the browser binary. If `None`, auto-detected via `jbium.platform_detect.find_browser_binary()` — checks `~/.cache/jbium/bin/` (where `jbium fetch` puts it) first, then several from-source-build and system-install locations. Raises `FileNotFoundError` with a message pointing at `jbium fetch` if nothing is found. |

Common usage passes no arguments at all: `Jbium()`.

### `await jbium.launch(...) -> StealthSession`

The only method with a required argument. Resolves the proxy's exit
IP, does GeoIP lookup, generates a matching device fingerprint, sets
every `STEALTH_*` env var, and spawns the browser process.

| Argument | Type | Default | Behavior |
|---|---|---|---|
| `proxy_url` | `str` | **required** | `"http://user:pass@host:port"`. Required because the whole fingerprint pipeline is keyed off the proxy's exit IP — there's no "direct connection, no proxy" mode. |
| `headless` | `bool` | `False` | `True` adds `--headless=new --disable-gpu`. The project's own stated design assumption is headed is better for detection resistance — see the module docstring's own note about DataDome. |
| `fingerprint_profile` | `Optional[str]` | `None` | Force a specific device template by name (e.g. `"macbook_pro_m3"`) instead of letting GeoIP-weighted random selection pick one. Must match a key in `config/fingerprints.json`'s `templates` object. |
| `geoip_override` | `Optional[Dict]` | `None` | Skip GeoIP resolution entirely and construct a `GeoProfile` from this dict instead. Accepted keys (all optional, each has a sane US default if omitted): `country_code`, `country_name`, `city`, `region`, `latitude`, `longitude`, `timezone`, `language`, `locale`, `currency`, `date_format`, `ip_type`, `asn`, `isp`, `organization`, `common_resolutions`, `common_fonts`, `os_distribution`, `confidence`. |
| `extensions` | `Optional[List[str]]` | `None` | Paths to unpacked Chrome extension directories to load at startup. Silently ignored (with a logged warning) if `headless=True` — Chrome extension support is unreliable in headless mode. |
| `fingerprint_overrides` | `Optional[Dict[str, str]]` | `None` | Raw `STEALTH_*` env var overrides applied *after* the generated profile — the escape hatch for forcing one specific property without hand-building a whole device template. Example: `{"STEALTH_GPU_VENDOR": "Custom Vendor Inc."}`. See the full env var list below for every key this can override. |
| `expose_cdp_port` | `bool` | `False` | The driver always controls the browser over `--remote-debugging-pipe`, which opens no network socket, so no page can find a DevTools endpoint. `True` *additionally* opens a TCP DevTools port (picked by the browser, available as `browser._debug_port`) for external CDP clients such as Playwright's `connect_over_cdp()`. That port **is** reachable from page JavaScript (`fetch('http://127.0.0.1:<port>/json/version')`), so it makes the session detectable — leave it off unless you need it. Pages the external client opens need `browser.client_hints_override()` applied (see below). |

Returns a `StealthSession` (see "Data classes" below).

### `await jbium.new_page() -> StealthPage`

No arguments. Opens a new tab via CDP `Target.createTarget`, attaches to
it as a flattened session on the debugging pipe, and before anything
loads:

- applies `Emulation.setUserAgentOverride` with full `userAgentMetadata`
  (see `client_hints_override()`), so the `Sec-CH-UA*` request headers
  and `navigator.userAgentData` match the spoofed User-Agent. Without
  it the browser process would still send the real build's hints (e.g.
  `Sec-CH-UA-Platform: "Linux"`, a Chromium-only brand list);
- applies `Emulation.setGeolocationOverride` using the session's GeoIP
  coordinates with small random per-call jitter (±0.05°).

### `jbium.client_hints_override() -> dict`

The `Emulation.setUserAgentOverride` params `new_page()` applies. Only
needed for pages something else opens (e.g. Playwright attached through
`expose_cdp_port=True`) — send it once per page before navigating.

### `await jbium.close()`

No arguments. Detaches every open page, closes the debugging pipe (the
browser's signal to shut down cleanly), waits up to 5s, then falls back
to terminate and finally kill. Removes the temporary profile directory
and the proxy-auth extension directory.

### Context manager

```python
async with Jbium() as browser:
    await browser.launch(proxy_url="...")
    page = await browser.new_page()
    ...
# browser.close() called automatically on exit, even on exception
```

---

## `StealthPage` — returned by `new_page()`

Never construct this directly — always via `jbium.new_page()`.

| Method | Arguments | Returns | Notes |
|---|---|---|---|
| `goto(url, wait_until="load", timeout=30)` | `url: str`, `wait_until: str`, `timeout: int` | `None` | `"load"` / `"domcontentloaded"` wait for the matching CDP lifecycle event; `"networkidle"` waits until no request has been in flight for 500ms. Waits up to `timeout` seconds, then a short settle delay. Raises on a navigation error. |
| `get_content()` | none | `str` | `document.documentElement.outerHTML`. |
| `get_title()` | none | `str` | `document.title`. |
| `evaluate(expression)` | `expression: str` | `Any` | Runs arbitrary JS via `Runtime.evaluate` with `returnByValue=True, awaitPromise=True` — a returned Promise is awaited before the value comes back. |
| `screenshot(filepath, full_page=True)` | `filepath: str`, `full_page: bool` | `None` | PNG via `Page.captureScreenshot`, written to `filepath`; `full_page=True` captures the whole scrollable page. |
| `click(selector)` | `selector: str` | `None` | Moves the mouse along a curved path to a randomized point inside the element (never dead-center), then dispatches real `Input.dispatchMouseEvent` press/release with a randomized dwell. Logs a warning and returns silently if the selector matches nothing. |
| `type_text(selector, text)` | `selector: str`, `text: str` | `None` | Clicks the field first (to focus it like a real user), then dispatches per-character trusted `Input.dispatchKeyEvent` with jittered inter-key delay and an 8% chance of a longer "thinking" pause per character. |
| `move_mouse_to(x, y)` | `x: float`, `y: float` | `None` | Lower-level primitive `click()` builds on — bezier-curved, variable-speed mouse movement via real Input events (`isTrusted=true`, unlike a synthetic JS `MouseEvent`). |
| `scroll_to_bottom()` | none | `None` | Variable-sized wheel ticks with variable delay and a 10% chance of a longer "reading pause" per tick, instead of uniform scrolling. |
| `check_detection()` | none | `Dict[str, bool]` | Greps page content for known blocking/CAPTCHA signals (DataDome, generic CAPTCHA text, "access denied", rate-limit text, Cloudflare challenge, PerimeterX). Returns each indicator plus an aggregate `"detected"` key. This is a content-string heuristic, not a CreepJS-style fingerprint score. |
| `enable_network_capture()` / `wait_for_graphql_response(operation_name, timeout=30)` / `get_captured_graphql(operation_name)` | — | — | GraphQL response capture keyed by `operationName` (`goto()` enables capture automatically). |
| `on(method, handler)` | `method: str`, `handler: callable` | `None` | Register a handler for a raw CDP event on this page (e.g. `"Network.responseReceived"`). |
| `close()` | none | `None` | Detaches the driver from this page's CDP session (the tab stays open until the browser closes). |

---

## `get_random_webshare_proxy(...)`

```python
from jbium import get_random_webshare_proxy
```

| Argument | Type | Default | Behavior |
|---|---|---|---|
| `username_prefix` | `Optional[str]` | `None` | Falls back to `STEALTH_WEBSHARE_USERNAME` env var. |
| `password` | `Optional[str]` | `None` | Falls back to `STEALTH_WEBSHARE_PASSWORD` env var. |
| `endpoint` | `Optional[str]` | `None` | Falls back to `STEALTH_WEBSHARE_ENDPOINT` env var, then `"p.webshare.io"`. |
| `port` | `Optional[int]` | `None` | Falls back to `STEALTH_WEBSHARE_PORT` env var, then `80`. |
| `mode` | `str` | `"numbered"` | `"numbered"` appends a random `-N` (1-100) suffix to the username each call (sticky-ish rotation across many proxy ports); `"rotating"` appends `-rotate` instead (a single rotating-gateway username). |

Raises `RuntimeError` if credentials are missing. This is a Webshare-specific
convenience — for any other proxy provider, just build your own
`"http://user:pass@host:port"` string and pass it to `launch()` directly.

---

## `jbium fetch` — CLI

```bash
jbium fetch [version] [--checksum SHA256] [--force]
```

| Argument | Required | Default | Behavior |
|---|---|---|---|
| `version` | No | The installed `jbium` package's own `__version__` | Which GitHub Release tag (`vVERSION`) to fetch from. |
| `--checksum` | No | `None` | Expected SHA256 of the downloaded archive. If provided and it doesn't match, the corrupted download is deleted and the command exits non-zero. |
| `--force` | No | `False` | Re-download even if a cached archive already exists at `~/.cache/jbium/<archive-name>`. |

Exits `0` on success, `1` on any failure (network error, checksum
mismatch, or no build published for your platform — the last one
prints a specific, non-cryptic message rather than a raw 404).

Override where it fetches from with the `JBIUM_RELEASE_BASE_URL`
environment variable (e.g. for a fork or a self-hosted mirror).

---

## `jbium fetch-geoip` — CLI

```bash
jbium fetch-geoip [--license-key KEY] [--city-url URL] [--asn-url URL] [--force]
```

Downloads the two GeoIP databases `GeoIPResolver` uses — GeoLite2-City
and GeoLite2-ASN — to `~/.cache/jbium/geoip/`, which `GeoIPResolver`
checks automatically (right after an explicit path and the
`STEALTH_GEOIP_DB_PATH`/`STEALTH_GEOIP_ASN_DB_PATH` env vars, before
falling back to the less accurate heuristic resolver). Neither `pip
install jbium[geo]` nor plain `jbium fetch` gets you these — `[geo]`
only installs the `geoip2` library, and the actual `.mmdb` data can't
be bundled in the package at all (MaxMind's license forbids
redistributing it).

| Argument | Required | Default | Behavior |
|---|---|---|---|
| `--license-key` | No | `None` (also read from `GEOIP_LICENSE_KEY`) | A MaxMind license key — free to generate at [maxmind.com](https://www.maxmind.com/en/accounts/current/license-key). Without one, falls back to the free `git.io/GeoLite.mmdb` mirror (no signup, genuine GeoLite2 data, just refreshed on someone else's schedule instead of pulled fresh from MaxMind). |
| `--city-url` | No | `None` (also read from `GEOIP_CITY_URL`) | Fetch the City database from an arbitrary URL instead — your own CDN, an internal mirror, a public community mirror. Takes priority over `--license-key` for this one file. Shape is inferred from the URL's suffix: bare `.mmdb` is saved as-is, `.mmdb.gz` is gunzipped, `.tar.gz` is unwrapped the same way a MaxMind archive is. |
| `--asn-url` | No | `None` (also read from `GEOIP_ASN_URL`) | Same as `--city-url`, for the ASN database. |
| `--force` | No | `False` | Re-download even if both databases already exist in the cache. |

Each database's source is chosen independently: its own `--*-url` first,
then `--license-key`, then the free mirror default — so e.g. a custom
`--city-url` with no `--asn-url` still gets a working ASN database via
the mirror.

The default no-signup source (`https://git.io/GeoLite2-City.mmdb` /
`https://git.io/GeoLite2-ASN.mmdb`) redirects to
[P3TERX/GeoLite.mmdb](https://github.com/P3TERX/GeoLite.mmdb), a
daily-updated third-party redistribution of MaxMind's real GeoLite2
data (verified working — genuine data, not a substitute). It has no
official MaxMind backing, so for production use without a MaxMind
account, point `--city-url`/`--asn-url` at your own mirror instead.

---

## Data classes

Returned or embedded in return values — you generally read these
rather than construct them.

**`StealthSession`** (returned by `launch()`):
`proxy_url`, `proxy_ip`, `geo_profile: GeoProfile`, `device_profile: DeviceProfile`,
`browser_process`, `ws_url`, `env_vars: Dict[str,str]`, `session_id`, `created_at`.

**`DeviceProfile`** (`session.device_profile`): `os`, `os_version`, `platform`,
`architecture`, `bitness`, `cpu_cores`, `cpu_model`, `ram_gb`, `gpu_vendor`,
`gpu_renderer`, `screen_width`, `screen_height`, `available_width`,
`available_height`, `color_depth`, `device_pixel_ratio`, `refresh_rate`,
`touch_support`, `max_touch_points`, `user_agent`, `ua_platform`,
`ua_platform_version`, `canvas_seed`, `webgl_seed`, `audio_seed`,
`profile_name`, `template_used`.

**`GeoProfile`** (`session.geo_profile`): `country_code`, `country_name`,
`city`, `region`, `latitude`, `longitude`, `timezone`, `language`, `locale`,
`currency`, `date_format`, `ip_type` (an `IPType` enum: `residential`/
`mobile`/`datacenter`/`vpn`/`hosting`/`cdn`/`tor`/`unknown`), `asn`, `isp`,
`organization`, `common_screen_resolutions`, `common_fonts`,
`os_distribution`, `confidence`, `fallback_used`.

---

## Config file (`settings.yaml`)

Loaded from the path passed to `Jbium(config_path=...)`, or the
packaged default. Recognized top-level keys (all optional — every one
has a code-level default if the key or the whole file is absent):

```yaml
browser:
  binary_path: ""        # explicit override; empty = auto-detect
  headless: false
  virtual_display: true   # Linux + headed: per-session Xvfb sized to the profile's screen,
                          # plus --force-device-scale-factor, so screen.* / devicePixelRatio
                          # match the profile (needs the xvfb package; false = use $DISPLAY)
  extra_args: []          # extra Chrome CLI flags appended verbatim (--remote-debugging-* are dropped)

proxy:
  provider: webshare
  endpoint: p.webshare.io
  port: 80
  username_prefix: ""    # normally set via STEALTH_WEBSHARE_USERNAME instead
  password: ""            # normally set via STEALTH_WEBSHARE_PASSWORD instead

geoip:
  enabled: true
  database_path: ./data/geoip/GeoLite2-City.mmdb       # MaxMind GeoLite2, not bundled — see [geo] extra
  asn_database_path: ./data/geoip/GeoLite2-ASN.mmdb    # optional — see `jbium fetch-geoip`; without it, asn/isp/ip_type stay Unknown/RESIDENTIAL

anti_detection:
  filter_webrtc: true
  spoof_battery: true
  canvas_noise: true
  webgl_spoof: true
  font_filter: true
```

Note: `anti_detection.*` keys are read into the config dict but are
not currently wired to any conditional logic in `launch()` — the
actual patches always apply when their corresponding `STEALTH_*` env
var is set, regardless of these flags. Don't rely on them to
selectively disable a patch category yet.

---

## Every `STEALTH_*` environment variable `launch()` sets

Useful for `fingerprint_overrides`, or for understanding what a given
patch actually reads. Each is documented in more depth in the main
repo's `docs/PATCHES.md`.

| Variable | Source | Consumed by |
|---|---|---|
| `STEALTH_CPU_CORES` | `device.cpu_cores` | `navigator.hardwareConcurrency` (007) |
| `STEALTH_DEVICE_MEMORY` | `device.ram_gb` | `navigator.deviceMemory` (007) |
| `STEALTH_PLATFORM` | `device.platform` | `navigator.platform` (007) |
| `STEALTH_MAX_TOUCH_POINTS` | `10` if touch else `0` | `navigator.maxTouchPoints` (007) |
| `STEALTH_UA_PLATFORM` | `device.ua_platform` | `navigator.userAgentData.platform` (007) |
| `STEALTH_UA_PLATFORM_VERSION` | template's `ua_platform_version` (e.g. `15.0.0` = Windows 11, `14.1.0` = macOS 14) | high-entropy `platformVersion` (007) |
| `STEALTH_UA_ARCHITECTURE` / `STEALTH_UA_BITNESS` | `device.architecture` / `device.bitness` | high-entropy `architecture` / `bitness` (007) |
| `STEALTH_UA_MODEL` | `""` (desktop) | high-entropy `model` (007) |
| `STEALTH_UA_BRANDS` / `STEALTH_UA_FULL_BRANDS` | Chrome's GREASE algorithm over the UA's exact version, e.g. `Not_A Brand=8` / `Chromium=120` / `Google Chrome=120` joined with `\|` | `brands` / `fullVersionList` / `uaFullVersion` (007) |
| `STEALTH_GEO_LANGUAGES` | Chrome's own default list for the profile's UI locale, e.g. `de-DE,de,en-US,en` or `ja,en-US,en` — plain comma list, no q-values | `navigator.language(s)`, `Accept-Language` (008 adds the q-values) |
| `TZ` | `geo.timezone` | libc/ICU/V8 read this natively — `Date.getTimezoneOffset()`, `Intl`, date formatting |
| `LANGUAGE` (Linux only) | the profile's Chrome UI locale | UI locale, which sets `Intl`'s default locale (Windows/macOS get `--lang` instead) |
| `STEALTH_CANVAS_SEED` | `device.canvas_seed` | Canvas noise (004) |
| `STEALTH_AUDIO_SEED` | `device.audio_seed` | **Not consumed yet** — `patches/011_audio` in the main repo is deliberately unwired |
| `STEALTH_GPU_VENDOR` / `STEALTH_GPU_RENDERER` | `device.gpu_vendor`/`device.gpu_renderer` — ANGLE strings in the exact form Chrome 120 reports per OS | WebGL unmasked vendor/renderer (005) |
| `STEALTH_FONT_OS` | mapped from `device.ua_platform` | Font profile for the fontconfig tooling (006) |
| `STEALTH_FONT_REGION` | mapped from `geo.country_code` | Font profile for the fontconfig tooling (006) |
| `STEALTH_BATTERY_LEVEL` / `STEALTH_BATTERY_CHARGING` | derived from `canvas_seed` | Battery API (010) |

Deliberately **not** set: `STEALTH_GPU_VERSION` / `STEALTH_GPU_GLSL_VERSION`
(Chrome's WebGL version strings are fixed constants, identical on every
machine — overriding them is what creates a tell) and the geo/WebRTC
variables no patch reads. Any inherited `STEALTH_*`, `TZ` or `LANGUAGE`
in the caller's own environment is dropped before launch.

---

## Which folders are load-bearing for `pip install` to actually work

Everything under `packaging/` matters for *building* the package, but
only some of it is load-bearing at runtime:

```
packaging/
├── pyproject.toml          ← REQUIRED — the package definition itself
├── README.md                ← REQUIRED to build — pyproject.toml's readme= points here; missing = build fails
└── src/
    └── jbium/                ← REQUIRED — this whole tree IS the installed package
        ├── __init__.py
        ├── stealth_browser.py
        ├── device_generator.py
        ├── geoip_resolver.py
        ├── fingerprint_manager.py
        ├── platform_detect.py
        ├── cli.py
        ├── config/            ← REQUIRED at runtime (declared in [tool.setuptools.package-data])
        │   ├── fingerprints.json
        │   ├── locales.json
        │   └── settings.yaml
        └── fonts/              ← REQUIRED at runtime (same package-data declaration)
            ├── fontconfig_template.xml
            ├── linux/manifest.json
            ├── macos/manifest.json
            └── windows/manifest.json
```

**If `config/` or `fonts/` ever went missing from the package** (e.g. a
future edit to `[tool.setuptools.package-data]` in `pyproject.toml`
that forgets to list them, or someone adds a new JSON file there
without updating that list), the package would still *install*
successfully — pip has no way to know data files were supposed to be
there — but would silently degrade at runtime: `DeviceGenerator`,
`GeoIPResolver`, and font handling all have code-level fallback
defaults for a missing file, so nothing crashes, but you'd silently
lose most of the actual template/locale/font diversity. This is the
single most likely way this package could "work" but not actually do
what it's supposed to — if fingerprint diversity or GeoIP consistency
ever looks wrong after a packaging change, check `pyproject.toml`'s
`package-data` list against what's actually in `src/jbium/config/`
and `src/jbium/fonts/` first.

**Two things that must never be missing, unlike the above (real crash,
not silent degradation):**
- `pyproject.toml` itself and `README.md` — the build tool fails outright.
- `src/jbium/__init__.py` — without it, `src/jbium/` isn't a package at all.

**Not needed for `pip install` at all** (build-time only, part of the
separate from-source Chromium build in the main repo, not this
package): `patches/`, `scripts/`, the top-level `config/*.gn` files,
`launcher/`.
