# Stealth Patches Documentation

## Overview

Jbium applies 10 patches to the Chromium source to make
automated browsing undetectable by anti-bot systems. Each patch
addresses a specific detection vector.

## Patch Index

| # | Name | Directory | Addresses |
|---|------|-----------|-----------|
| 001 | Automation Detection | `patches/001_automation/` | navigator.webdriver, automation infobar, CLI args |
| 002 | CDP Traces | `patches/002_cdp/` | DevTools protocol detection, console leaks |
| 003 | TLS Fingerprint | `patches/003_tls/` | JA3/JA4 hash matching |
| 004 | Canvas Noise | `patches/004_canvas/` | Canvas hash fingerprinting |
| 005 | WebGL Spoofing | `patches/005_webgl/` | GPU vendor/renderer detection |
| 006 | Font Filtering | `patches/006_fonts/` | Font enumeration fingerprinting |
| 007 | Navigator Spoofing | `patches/007_navigator/` | CPU/RAM/platform/touch/UA hints |
| 008 | GeoIP Consistency | `patches/008_geoip/` | Timezone/language/location mismatches |
| 009 | Plugin Consistency | `patches/009_plugins/` | navigator.plugins/mimeTypes array |
| 010 | Misc Protection | `patches/010_misc/` | WebRTC IP leak, battery API, media codecs |

---

## Patch 001: Automation Detection

**Problem:** Chromium exposes automation via:
- `navigator.webdriver = true`
- "Chrome is being controlled" infobar
- `--enable-automation` command line flag

**Solution:**
- Patches `content/renderer/renderer_main_frame.cc` to never set webdriver
- Removes infobar trigger from `automation_infobar_delegate.cc`
- Strips automation args from command line parser

**Files modified:**
```
content/renderer/renderer_main_frame.cc
chrome/browser/ui/startup/automation_infobar_delegate.cc
content/browser/devtools/devtools_agent_host_impl.cc
content/common/content_switches_internal.cc
chrome/browser/chrome_browser_main.cc
```

**Environment variables:** None (always active)

---

## Patch 004: Canvas Noise

**Problem:** Canvas fingerprinting works by:
1. Drawing specific text/shapes on a `<canvas>` element
2. Calling `canvas.toDataURL()` or `ctx.getImageData()`
3. Hashing the pixel data
4. The hash is unique to the GPU/driver/OS combination
5. Anti-bot systems match against known automated hashes

**Solution:**
- Generates a unique 128-bit session seed at browser launch
- Pre-computes a 256×256 noise lookup table (64KB)
- On every `GetImage()` call, modifies 128 pixels in the blue channel
- Blue channel changes are invisible to human eye (±1-2 value)
- Changes are deterministic within a session (same canvas → same hash)
- Changes are unique across sessions (new session → new hash)

**Performance impact:** <0.1ms per canvas operation (uses lookup table)

**Files modified:**
```
third_party/blink/renderer/platform/stealth/stealth_canvas_noise.h (NEW)
third_party/blink/renderer/platform/stealth/stealth_canvas_noise.cc (NEW)
third_party/blink/renderer/modules/canvas/canvas2d/canvas_rendering_context_2d.cc (MODIFIED)
```

**Environment variables:**
- `STEALTH_CANVAS_SEED` — Override session seed (from fingerprint manager)

---

## Patch 007: Navigator Spoofing

**Problem:** JavaScript can read hardware information:
- `navigator.hardwareConcurrency` → real CPU core count
- `navigator.deviceMemory` → real RAM amount
- `navigator.platform` → actual OS platform
- `navigator.maxTouchPoints` → touch capability
- User-Agent Client Hints → high-entropy OS info

Automated browsers often run on servers with unusual specs (64 cores,
256GB RAM) that no consumer has.

**Solution:**
- Reads spoofed values from environment variables
- Returns consumer-typical hardware specs
- All values are internally consistent with the device profile

**Files modified:**
```
third_party/blink/renderer/platform/stealth/stealth_navigator.h (NEW)
third_party/blink/renderer/platform/stealth/stealth_navigator.cc (NEW)
third_party/blink/renderer/core/frame/navigator_id.cc (MODIFIED)
third_party/blink/renderer/core/frame/navigator_max_touch_points.cc (MODIFIED)
third_party/blink/renderer/core/frame/navigator_ua_data.cc (MODIFIED)
```

**Environment variables:**
- `STEALTH_CPU_CORES` — Spoofed core count (e.g., "8")
- `STEALTH_DEVICE_MEMORY` — Spoofed RAM in GB (capped at 8, e.g., "8")
- `STEALTH_PLATFORM` — Platform string (e.g., "Win32")
- `STEALTH_MAX_TOUCH_POINTS` — Touch points (e.g., "0")
- `STEALTH_UA_PLATFORM` — UA Client Hints platform (e.g., "Windows")
- `STEALTH_UA_PLATFORM_VERSION` — UA Client Hints platform version

---

## Patch 008: GeoIP Consistency

**Problem:** Anti-bot systems check if browser configuration matches IP location:
- IP says Tokyo, but timezone says New York → FLAG
- IP says Germany, but language says en-US → FLAG
- navigator.geolocation returns coords for wrong country → FLAG

**Solution:**
- Driver resolves proxy IP → GeoIP data
- Passes location data via environment variables
- Chromium patches override:
  - `Date.getTimezoneOffset()` → returns GeoIP timezone offset
  - `Intl.DateTimeFormat().resolvedOptions().timeZone` → GeoIP timezone
  - `navigator.language` / `navigator.languages` → GeoIP language
  - `navigator.geolocation` → returns GeoIP coordinates + jitter
  - HTTP `Accept-Language` header → GeoIP language

**Files modified:**
```
third_party/blink/renderer/platform/stealth/stealth_geoip.h (NEW)
third_party/blink/renderer/platform/stealth/stealth_geoip.cc (NEW)
third_party/blink/renderer/core/frame/navigator_language.cc (MODIFIED)
third_party/blink/renderer/bindings/core/v8/v8_binding_for_core.cc (MODIFIED)
v8/src/date/date.cc (MODIFIED)
third_party/blink/renderer/modules/geolocation/geolocation.cc (MODIFIED)
net/http/http_util.cc (MODIFIED)
```

**Environment variables:**
- `STEALTH_GEO_COUNTRY` — Country code (e.g., "JP")
- `STEALTH_GEO_COUNTRY_NAME` — Country name (e.g., "Japan")
- `STEALTH_GEO_CITY` — City name (e.g., "Tokyo")
- `STEALTH_GEO_TIMEZONE` — Timezone (e.g., "Asia/Tokyo")
- `STEALTH_GEO_LANGUAGE` — Language (e.g., "ja-JP")
- `STEALTH_GEO_LOCALE` — Locale (e.g., "ja-JP")
- `STEALTH_GEO_LATITUDE` — Latitude (e.g., "35.6762")
- `STEALTH_GEO_LONGITUDE` — Longitude (e.g., "139.6503")
- `STEALTH_GEO_CURRENCY` — Currency (e.g., "JPY")

---

## Patch 010: Misc Protection

### WebRTC IP Leak Prevention

**Problem:** WebRTC can reveal the real IP address even behind a proxy:
- `RTCPeerConnection` generates ICE candidates
- Local candidates contain real IP addresses
- JavaScript can read these via `onicecandidate` event

**Solution:**
- Filters ICE candidate generation
- Removes private IP candidates (192.168.x.x, 10.x.x.x)
- Only allows proxy IP or mDNS (.local) candidates
- Keeps TURN/relay candidates (server IPs, not client IPs)

**Environment variables:**
- `STEALTH_FILTER_WEBRTC` — Enable/disable ("true"/"false")
- `STEALTH_PROXY_IP` — The proxy exit IP to allow

### Battery API Spoofing

**Problem:** `navigator.getBattery()` reveals:
- Charging status (real device state)
- Battery level (unique per session)
- Charging/discharging time (varies per device)

**Solution:**
- Returns consistent, plausible battery state
- Same values within a session
- Different values between sessions

### Media Codec Consistency

**Problem:** `video.canPlayType()` returns codec support info:
- Automated browsers may return "" for codecs they should support
- If build omits proprietary codecs, H.264 returns "" instead of "probably"
- This inconsistency is a detection signal

**Solution:**
- Hard-codes Chrome-typical responses for common MIME types
- `video/mp4` → "probably" (not "")
- `audio/mpeg` → "probably"
- `video/webm; codecs="vp9"` → "probably"
