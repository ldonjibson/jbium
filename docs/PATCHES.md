# Stealth Patches Documentation

## Overview

Jbium applies 10 patches to the Chromium source to make automated
browsing match a consistent, consumer-typical device profile.
Each patch addresses a specific detection vector.

### Architecture rules (all patches)

Every `patches/0XX_*/apply.sh` follows the same, build-safe rules:

1. **Patch only code verified to exist in this tree.** Markers are
   exact signatures from the current checkout; if a marker isn't
   found the patch skips loudly instead of splicing blindly.
2. **Brace-aware whole-body replacement.** Function bodies are
   replaced via a helper that walks the parameter list before
   finding the opening brace — no dangling `if (false) {`, no
   renamed `_original` free functions that never compiled.
3. **Header-only stealth helpers.** New state lives in
   `third_party/blink/renderer/platform/stealth/*.h` with
   function-local statics — no new `.cc` files, no BUILD.gn
   registration, no undefined-symbol link failures, and silent
   under `-Werror -Wglobal-constructors -Wexit-time-destructors`.
4. **Environment-driven configuration.** The driver
   (`driver/stealth_browser.py::_get_env_vars`) sets
   `STEALTH_*` env vars; patches read them with `getenv()`.
   Unset variables mean stock behavior passes through unchanged.
5. **Idempotent.** Every patch skips already-patched files, so
   `apply_all.sh` can run repeatedly.

Some vectors are deliberately **not** patched in source because
the effective lever lives elsewhere (driver flags, bundled fonts,
CDP overrides). Those patches verify the tooling instead and
document why.

## Patch Index

| # | Name | Directory | In-source? | Addresses |
|---|------|-----------|------------|-----------|
| 001 | Automation Hiding | `patches/001_automation/` | ✅ | navigator.webdriver, automation infobar |
| 002 | CDP Traces | `patches/002_cdp/` | verify-only | chromedriver cdc_ artifacts (n/a — raw CDP), Runtime.enable parity |
| 003 | TLS Fingerprint | `patches/003_tls/` | ✅ | TLS extension grease randomization |
| 004 | Canvas Noise | `patches/004_canvas/` | ✅ | canvas hash fingerprinting |
| 005 | WebGL Spoofing | `patches/005_webgl/` | ✅ | GPU vendor/renderer/version strings |
| 006 | Font Filtering | `patches/006_fonts/` | verify-only | font enumeration/metrics (defense = bundled fonts) |
| 007 | Navigator Spoofing | `patches/007_navigator/` | ✅ | CPU/RAM/platform/touch/UA-CH |
| 008 | GeoIP Consistency | `patches/008_geoip/` | ✅ + driver | languages, Accept-Language, timezone, geolocation |
| 009 | Plugin Consistency | `patches/009_plugins/` | ✅ | navigator.plugins/mimeTypes |
| 010 | Misc Protection | `patches/010_misc/` | ✅ + driver | battery API, WebRTC policy, media codecs |

---

## Patch 001: Automation Hiding

**Problem:** automation is exposed via `navigator.webdriver`
(`bool Navigator::webdriver() const` — checks
`RuntimeEnabledFeatures::AutomationControlledEnabled()` +
`probe::ApplyAutomationOverride()`) and the global
"Chrome is being controlled by automated test software" infobar.

**Solution:**
- `bool Navigator::webdriver() const` → always returns `false`
  (body replacement in
  `third_party/blink/renderer/core/frame/navigator.cc`)
- `void AutomationInfoBarDelegate::Create()` (the static
  no-arg entry that calls `GlobalConfirmInfoBar::Show`) → no-op;
  the per-tab `Create(manager)` overload stays stock so the class
  still links
- `--enable-automation` is never passed by the jbium driver, and
  the two patches above neutralize it if someone passes it anyway

> The old version of this patch **overwrote**
> `content/renderer/renderer_main_frame.cc` with a 12-line stub
> (destroying a real Chromium file — `RendererMainFrame` doesn't
> exist in current trees) and never touched the actual
> `webdriver()` code path.

**Files modified:**
```
third_party/blink/renderer/core/frame/navigator.cc
chrome/browser/ui/startup/automation_infobar_delegate.cc
```

**Environment variables:** none (always active)

---

## Patch 002: CDP Traces (verification-only)

**Problem:** chromedriver leaks `window.cdc_*` variables and bots
probe `Runtime.enable` responses.

**Solution:** nothing in-source — both former targets don't exist
on this branch:
- `content/browser/devtools/protocol/runtime_handler.cc` was
  removed upstream (404s on current main)
- `DevToolsAgent::Attach` / `ExecuteScriptIfAllowed` (the old
  patch's target) never existed with those signatures
- `cdc_*` artifacts are injected by **chromedriver itself**;
  jbium drives via raw CDP, so none are ever created

The patch prints diagnostics instead of splicing code into
unrelated files. Runtime.enable behaves identically to stock
Chrome (the driver never uses it for automation).

---

## Patch 003: TLS Fingerprint

**Problem:** stable TLS extension order/GREASE values let
fingerprinters correlate sessions of the same patched build.

**Solution:** session-randomized GREASE values via
`[[maybe_unused]] GetSessionGreaseValue()` in `net/ssl/ssl_config.cc`.
Includes a revert-if-already-patched git checkout guard.

---

## Patch 004: Canvas Noise

**Problem:** canvas fingerprinting draws text/shapes, reads back
via `toDataURL()`/`getImageData()`, and hashes the pixels. The
hash is unique to the GPU/driver/OS — and identical across
sessions of an unpatched build.

**Solution:**
- Header-only `stealth_canvas_noise.h` with a
  session-seed-driven sparse pixel tweak (lowest color byte of
  ~1% of opaque pixels, ±1-2 — invisible, and never touches
  non-opaque pixels so premultiplied invariants hold)
- Deterministic per (seed, pixel): the same canvas re-reads to
  the same hash (stability fingerprinters check); new session →
  new seed → new hash
- Both JS-visible readback chokepoints are wrapped (verified in
  this tree):
  - `blink::CanvasRenderingContext2D::GetImage()` — covers
    `getImageData` (which snapshots via `GetImage()`), drawing a
    canvas onto another canvas, and `HTMLCanvasElement::Source()`
  - `CanvasRenderingContext2D::PaintRenderingResultsToSnapshot()`
    — the `toDataURL`/`toBlob` path
- Every `StaticBitmapImage` return is wrapped in
  `stealth::CanvasNoise::MaybeSpoofSnapshot()` — a no-op unless
  `STEALTH_CANVAS_SEED` is set; readback uses
  `cc::PaintImage::readPixels` (raster and GPU-backed snapshots
  both work; the driver launches with `--disable-gpu` anyway)

> The old patch called
> `CanvasNoiseGenerator::ApplyNoise(last_finalized_bitmap_)` — a
> member that does not exist — and wrote an uncompiled
> `stealth_canvas_noise.cc`.

**Files modified:**
```
third_party/blink/renderer/platform/stealth/stealth_canvas_noise.h (NEW, header-only)
third_party/blink/renderer/modules/canvas/canvas2d/canvas_rendering_context_2d.cc (GetImage + PaintRenderingResultsToSnapshot)
```

**Environment variables:**
- `STEALTH_CANVAS_SEED` — decimal session seed (from fingerprint manager)

**Note:** `OffscreenCanvasRenderingContext2D::GetImage` lives in a
separate file and is not patched; extend if offscreen-canvas
fingerprinting matters for your targets.

---

## Patch 005: WebGL Spoofing

**Problem:** WebGL leaks the real GPU:
- `WEBGL_debug_renderer_info` (`kUnmaskedRendererWebgl` /
  `kUnmaskedVendorWebgl`) returns
  `String(ContextGL()->GetString(GL_RENDERER/GL_VENDOR))` — under
  `--disable-gpu` this is a SwiftShader string, an instant
  software-browser giveaway
- masked `GL_VERSION` / `GL_SHADING_LANGUAGE_VERSION` embed the
  same driver strings
- (masked `GL_VENDOR`/`GL_RENDERER` already return the constants
  `"WebKit"` / `"WebKit WebGL"` on every real Chrome — nothing to
  spoof)

**Solution:**
- Header-only `stealth_webgl.h` with `stealth::GPUSpoof`
  (`Renderer/Vendor/Version/GlslVersion` — each returns the env
  override or passes the real value through)
- Expression-level wraps of the four verified
  `String(ContextGL()->GetString(...))` leak points — identical
  formatting in `webgl_rendering_context_base.cc` (WebGL1) and
  `webgl2_rendering_context_base.cc` (WebGL2), applied to every
  occurrence (getParameter case bodies)

> The old patch's marker
> `String WebGLRenderingContextBase::GetString(GLenum name)` never
> matched anything (no such member), while its injected
> anonymous-namespace `kGPUProfiles` block landed unconditionally
> and its unused functions killed the build under `-Werror`.

**Files modified:**
```
third_party/blink/renderer/platform/stealth/stealth_webgl.h (NEW, header-only)
third_party/blink/renderer/modules/webgl/webgl_rendering_context_base.cc
third_party/blink/renderer/modules/webgl/webgl2_rendering_context_base.cc
```

**Environment variables:**
- `STEALTH_GPU_VENDOR` — e.g. `"Google Inc. (NVIDIA)"`
- `STEALTH_GPU_RENDERER` — e.g. `"ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)"`
- `STEALTH_GPU_VERSION` — e.g. `"OpenGL ES 2.0 Chromium"`
- `STEALTH_GPU_GLSL_VERSION` — e.g. `"OpenGL ES GLSL ES 1.0.17"`

Unset = real values pass through unchanged.

---

## Patch 006: Font Filtering (verification-only)

**Problem:** font enumeration and text-metric measurements
fingerprint the real OS.

**Solution:** the effective defense already ships with jbium and
isn't a Chromium source patch:
- `fonts/` bundles metric-compatible substitutes (Liberation
  Sans ↔ Arial, Carlito ↔ Calibri, Liberation Serif ↔ Times New
  Roman, Caladea ↔ Cambria, Noto families for CJK regions)
- `scripts/generate_fontconfig.py` + `fonts/fontconfig_template.xml`
  install alias rules so spoofed-OS family names resolve to the
  substitutes with identical metrics — text measures exactly like
  the claimed OS, and `document.fonts.check()` answers match it
- `queryLocalFonts`/FontAccessManager requires a user gesture +
  permission prompt — not a silent vector
- The driver sets `STEALTH_FONT_OS` / `STEALTH_FONT_REGION` and
  installs only the matching manifest's fonts

> The old patch's markers didn't exist
> (`FontCache::IsFontFamilyAvailable` — real name:
> `IsPlatformFamilyMatchAvailable`), left dangling bodies, and
> its `stealth_font_filter.cc` was never compiled.

---

## Patch 007: Navigator Spoofing

**Problem:** JavaScript reads hardware hints —
`navigator.hardwareConcurrency`, `navigator.deviceMemory`,
`navigator.platform`, `navigator.maxTouchPoints`, and the UA-CH
high-entropy API. Servers commonly run unusual specs (64 cores,
256GB RAM) that no consumer has.

**Solution:**
- Header-only `stealth_navigator.h` (`NavigatorSpoof` +
  `NavigatorProfile`, env-var-driven, platform-consistent
  defaults)
- Body replacements at the **effective** code paths (verified in
  this tree):
  - `String NavigatorBase::platform() const` — the override JS
    actually reaches on desktop
  - `unsigned NavigatorConcurrentHardware::hardwareConcurrency() const`
  - `float NavigatorDeviceMemory::deviceMemory() const`
  - `int NavigatorMaxTouchPoints::maxTouchPoints() const`
    (file absent on current trees — skips gracefully)
- UA-CH spoofed at the **Set*() boundary** in
  `navigator_ua_data.cc`
  (`SetBrandVersionList`, `SetFullVersionList`, `SetPlatform`,
  `SetArchitecture`, `SetModel`, `SetUAFullVersion`, `SetBitness`)
  — so `brands()`, `platform()`, `getHighEntropyValues()` and
  `toJSON()` all serve the spoof; `getHighEntropyValues` itself
  needs no patch

**Files modified:**
```
third_party/blink/renderer/platform/stealth/stealth_navigator.h (NEW, header-only)
third_party/blink/renderer/core/frame/navigator_base.cc
third_party/blink/renderer/core/frame/navigator_concurrent_hardware.cc
third_party/blink/renderer/core/frame/navigator_device_memory.cc
third_party/blink/renderer/core/frame/navigator_max_touch_points.cc (if present)
third_party/blink/renderer/core/frame/navigator_ua_data.cc
```

**Environment variables:**
- `STEALTH_CPU_CORES` — e.g. `"8"`
- `STEALTH_DEVICE_MEMORY` — e.g. `"16"` (GB)
- `STEALTH_PLATFORM` — e.g. `"Win32"`
- `STEALTH_MAX_TOUCH_POINTS` — e.g. `"0"`
- `STEALTH_UA_PLATFORM` / `STEALTH_UA_PLATFORM_VERSION` — UA-CH
  platform fields
- `STEALTH_BRANDS` — `Name=8|Chromium=120` format for the brand list

---

## Patch 008: GeoIP Consistency

**Problem:** a proxy IP in one country with a browser reporting
another timezone/language/locale/geolocation is a classic
detection mismatch.

**Solution (split between source and driver):**

In-source (verified markers):
- `navigator.language` / `navigator.languages`: one body
  replacement in `NavigatorLanguage::EnsureUpdatedLanguage()` —
  the single choke point both properties read — feeding from
  `STEALTH_GEO_LANGUAGES` with the original override/dirty
  handling preserved below the early return
- HTTP `Accept-Language`: early return inserted at the top of
  `HttpUtil::GenerateAcceptLanguageHeader()` (the exact function
  every accept-language computation funnels through) using the
  same `STEALTH_GEO_LANGUAGES`, so header and navigator can
  never disagree

Driver-side (replacing fabricated in-source patches that could
never compile):
- Timezone: `TZ=<GeoIP timezone>` env var — honored by
  libc/ICU/V8 Date, keeping `getTimezoneOffset()`, Intl, and date
  formatting consistent. (The old patch targeted
  `double Date::TimezoneOffset` — that function doesn't exist —
  and included a blink header inside V8.)
- Geolocation: `Emulation.setGeolocationOverride` CDP command
  with GeoIP lat/long + per-session jitter, applied by the driver
  per page. (The old patch called a fabricated
  `Geoposition::SetCoords()` / `handleEvent()` API.)

**Files modified:**
```
third_party/blink/renderer/core/frame/navigator_language.cc
net/http/http_util.cc
```

**Environment variables:**
- `STEALTH_GEO_LANGUAGES` — e.g. `"ja-JP,en;q=0.8"` (navigator
  languages + Accept-Language header)
- `TZ` — e.g. `"Asia/Tokyo"` (set by driver; read by libc/ICU)
- plus `STEALTH_GEO_COUNTRY/COUNTRY_NAME/CITY/TIMEZONE/LANGUAGE/
  LOCALE/LATITUDE/LONGITUDE/CURRENCY` for driver-side consumers

---

## Patch 009: Plugin Consistency

**Problem:** `navigator.plugins` / `navigator.mimeTypes` must
look like a real Chrome with the PDF viewer enabled — empty or
miscounted arrays are bot flags.

**Solution:** current Chromium already hard-codes the correct
5-entry PDF list in `DOMPluginArray`'s constructor; the only gap
is the array being empty when the PDF viewer is unavailable. One
body replacement pins `unsigned DOMPluginArray::length() const`
to return `5u` when `dom_plugins_` is empty (override via
`STEALTH_PLUGIN_COUNT=0` for a plugins-off profile).
`DOMMimeTypeArray` is left stock — already consistent.

> The old patch spliced `_original` free functions and called a
> fabricated `DOMPlugin::Create`.

**Files modified:**
```
third_party/blink/renderer/core/frame/dom_plugin_array.cc
```

**Environment variables:**
- `STEALTH_PLUGIN_COUNT` — `0` to report no plugins instead of the
  PDF five (optional)

---

## Patch 010: Misc Protection

**Problem:** remaining minor vectors — battery state, WebRTC IP
leak, media codec answers.

**Solution:**
- Battery: header-only `stealth_battery.h`
  (`stealth::BatterySpoof`), body-replacing the four JS-visible
  readers in `battery_manager.cc` — `charging()` (default
  `false`), `chargingTime()` (1800s when spoofed),
  `dischargingTime()` (14400s when spoofed), `level()` — all
  fall back to real `battery_status_` readings when unspoofed
- WebRTC: driver flags territory (ICE candidates originate in
  the browser process; current Chromium has no
  `RTCPeerConnection::ProcessIceCandidate` to patch)
- Media codecs: `proprietary_codecs = true` +
  `ffmpeg_branding = "Chrome"` in args.gn already make
  `canPlayType()` answer like branded Chrome — verified, no
  source patch

**Files modified:**
```
third_party/blink/renderer/platform/stealth/stealth_battery.h (NEW, header-only)
third_party/blink/renderer/modules/battery/battery_manager.cc
```

**Environment variables:**
- `STEALTH_BATTERY_LEVEL` — `"0.87"` (0.0-1.0)
- `STEALTH_BATTERY_CHARGING` — `"true"`/`"false"`
- `STEALTH_FILTER_WEBRTC` / `STEALTH_PROXY_IP` — driver-side
  WebRTC policy

---

## Applying & resetting

```bash
# Apply all patches (idempotent)
bash patches/apply_all.sh

# Restore every touched Chromium file to pristine and re-apply
# (required after upgrading to the fixed patch scripts from the
# old broken ones, or after updating the Chromium checkout)
bash scripts/reset_patches.sh

# Verify all patch markers landed
bash scripts/validate_patches.sh
```

`scripts/reset_patches.sh` git-restores every file any patch
touches, clears stale stealth headers, then re-applies the
current patch set — use it whenever the tree may contain output
from older, broken patch versions.
