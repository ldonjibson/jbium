"""
════════════════════════════════════════════════════════════
Fingerprint gap diagnostic: the vectors nothing else tests
════════════════════════════════════════════════════════════

Complements example/test_fingerprint.py, which verifies TLS
(JA4/HTTP2), Sec-CH-UA* headers, navigator/screen/GPU
consistency and the CDP port leak -- but stops there. This
script probes the corners a code review found uncovered, on a
plain https://example.com page (no fingerprinting site, no
anti-bot in the loop, so the results are pure measurements
and never contaminated by IP reputation):

  1. FONTS -- the claimed OS vs. what the page can actually
     render. The repo's documented font defense was dead code
     at runtime (driver/font_manager.py had no callers, the
     fonts/ bundles held manifest.json but no font files, no
     patch read STEALTH_FONT_OS/STEALTH_FONT_REGION, and no
     example or test ever checked fonts). Since 2026-10-06 the
     driver writes a per-session fontconfig itself at launch
     (stealth_browser._setup_session_fonts), aliasing every
     claimed-OS family to its metric-compatible substitute
     from the bundle's manifest -- but it needs the font files
     present: `python fonts/download_fonts.py --all` (repo)
     or `jbium fetch-fonts` (pip install). Without them the
     driver logs a warning and falls back to the host's fonts,
     and this check will FAIL exactly as before the fix.
     Detection here uses the same differential-measurement
     technique real fingerprinters use (an unavailable family
     falls back to the same base font, so its measured width
     equals the baseline; a resolved family -- real or
     fontconfig-substituted -- differs). Two verdicts:
       - claimed-OS families that do NOT resolve -> the page
         cannot render fonts its User-Agent says exist;
       - host-only families (DejaVu/Liberation/Ubuntu/Noto)
         that DO resolve on a Windows/macOS claim -> the page
         sees host fonts real Windows/macOS never ships.
     Honest limitation: differential detection proves family
     *resolution*, not metric fidelity -- verifying that a
     substitute has the real font's metrics would need
     reference widths measured on a genuine machine.

  2. BATTERY -- the Battery Status spec, which patch 010's
     design violates mechanically: when any STEALTH_BATTERY_*
     var is set, the patch returns hardcoded 1800 for
     chargingTime and 14400 for dischargingTime *regardless of
     charging state*, while the spec mandates
     dischargingTime=Infinity when charging and
     chargingTime=Infinity when discharging. Any script
     doing `charging ? dischargingTime === Infinity : ...`
     flags every patched session and passes every real device.
     Since 2026-10-06 the driver deliberately leaves the vars
     unset, so a patched binary now reports the real
     battery-less-server readings (level=1, charging=true,
     chargingTime=0, dischargingTime=Infinity) --
     spec-consistent, identical to every real desktop Chrome.
     Still FAIL on this script if you see 1800/14400: that
     means something set the vars again (fingerprint_overrides,
     a stale driver copy) or you're on the old binary. An
     UNPATCHED binary is also detectable here: it reports the
     same desktop-AC values, so the raw values tell you which
     build you are running.

  3. VOICES -- speechSynthesis.getVoices(): nothing spoofs
     it, so the page hears the host's voices (usually none,
     on a bare server) while the profile claims Windows/macOS,
     where real Chrome always exposes platform voices.

  4. WINDOW GEOMETRY -- outerHeight/outerWidth can never
     exceed the physical screen on real hardware (FAIL if
     they do), and screen.avail* equal to screen.* on a
     Windows/macOS claim means no taskbar/menu-bar
     reservation -- the bare-Xvfb geometry the driver's own
     comments acknowledge ("availWidth/availHeight equal the
     screen size: there is no desktop panel on a bare Xvfb").

  5. PER-SESSION NOISE WIRING -- a second full session is
     launched on purpose: the driver generates different
     STEALTH_CANVAS_SEED and STEALTH_AUDIO_SEED per session,
     so a canvas hash that changes across sessions proves
     patch 004's noise is consuming its seed, and an audio
     hash that stays identical across sessions (while the
     seeds differ) proves patch 011 is still the unwired
     helper it documents itself as. One note for reading that
     result fairly: a real Chrome's audio fingerprint is also
     constant per machine -- the tell is fleet-level (many
     "different visitors" sharing one audio fingerprint), not
     per-session, which is precisely what patch 011 was
     meant to break up and (deliberately) doesn't yet.

  6. window.chrome shape -- a compact re-check (the full one
     lives in test_fingerprint.py) so all gap areas are in
     one report.

Usage (two full sessions are launched on purpose -- the
noise-wiring proof needs a second session):
    export STEALTH_WEBSHARE_USERNAME=<your-username>
    export STEALTH_WEBSHARE_PASSWORD=<your-password>
    python example/diagnose_fingerprint_gaps.py
    python example/diagnose_fingerprint_gaps.py --proxy http://user:pass@host:port
    python example/diagnose_fingerprint_gaps.py --url https://example.com

Exit code 1 if any FAIL-level check trips, so it can gate CI.
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

# A real https origin, so context-gated APIs (Battery Status needs a
# secure context) behave like they would on a normal site. example.com
# is deliberately boring: no fingerprinting, no anti-bot, nothing that
# can make a check flaky or blend IP reputation into the result.
DEFAULT_URL = "https://example.com"

# ── Differential font probe ─────────────────────────────────────────────
# The technique real fingerprinters use (CreepJS/Panopticlick lineage):
# measure a mixed-metrics sample in "<family>, <base>" and in "<base>"
# alone; an unavailable family falls back to the base font, so every
# measurement equals the baseline. A family that resolves -- whether a
# real font or a fontconfig-substituted one -- changes the width.
# Requiring >= 2 of the 3 bases to differ avoids single-coincidence
# false positives. document.fonts.check() is reported alongside as a
# second signal (it also says "present" for substituted families, which
# is the defense working as designed).
FONT_PROBE_JS = """
async () => {
    const families = [
        // Windows always ships these (the ones a "Windows" UA promises)
        "Arial", "Calibri", "Cambria", "Consolas", "Courier New",
        "Georgia", "Impact", "Segoe UI", "Tahoma", "Times New Roman",
        "Trebuchet MS", "Verdana",
        // macOS-only families
        "American Typewriter", "Avenir", "Baskerville", "Futura",
        "Helvetica", "Helvetica Neue", "Menlo", "Monaco", "Optima",
        "Palatino",
        // Linux-host families real Windows/macOS never ship
        "DejaVu Sans", "DejaVu Sans Mono", "Liberation Mono",
        "Liberation Sans", "Liberation Serif", "Noto Sans", "Ubuntu",
    ];
    const sample = "mmmmmmwwwwWlli.10";
    const bases = ["monospace", "serif", "sans-serif"];
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const widthIn = (font) => {
        ctx.font = '72px ' + font;
        return ctx.measureText(sample).width;
    };
    const baseline = {};
    for (const base of bases) baseline[base] = widthIn(base);

    const results = {};
    for (const family of families) {
        let differing = 0;
        for (const base of bases) {
            if (widthIn('"' + family + '", ' + base) !== baseline[base]) {
                differing += 1;
            }
        }
        let check;
        try {
            check = document.fonts.check('12px "' + family + '"');
        } catch (e) {
            check = "error: " + e.message;
        }
        results[family] = {
            resolves: differing >= 2,
            differingBases: differing,
            width: widthIn('"' + family + '"'),
            check,
        };
    }
    return { baseline, results };
}
"""

# ── Battery Status spec probe ───────────────────────────────────────────
# The spec mandates: charging => dischargingTime === Infinity;
# discharging => chargingTime === Infinity. Patch 010's getters return
# their 1800/14400 constants whenever the env vars are set, so one of
# the two is always violated. Infinity is not JSON-serializable, so the
# IsInfinity booleans carry the signal (the raw fields arrive as null
# for Infinity).
BATTERY_PROBE_JS = """
async () => {
    if (!navigator.getBattery) return { available: false };
    const b = await navigator.getBattery();
    return {
        available: true,
        charging: b.charging,
        chargingTime: b.chargingTime,
        dischargingTime: b.dischargingTime,
        chargingTimeIsInfinity: b.chargingTime === Infinity,
        dischargingTimeIsInfinity: b.dischargingTime === Infinity,
        level: b.level,
    };
}
"""

# ── Geometry / window.chrome / speech voices ─────────────────────────────
ENVIRONMENT_PROBE_JS = """
async () => {
    const geometry = {
        screenWidth: screen.width,
        screenHeight: screen.height,
        availWidth: screen.availWidth,
        availHeight: screen.availHeight,
        outerWidth: window.outerWidth,
        outerHeight: window.outerHeight,
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        dpr: window.devicePixelRatio,
        colorDepth: screen.colorDepth,
    };
    const chromeKeys = window.chrome ? Object.keys(window.chrome).sort() : null;

    // getVoices() populates asynchronously in Chrome; wait briefly for
    // voiceschanged so an empty list is a real empty list, not a race.
    const voices = await new Promise((resolve) => {
        if (!('speechSynthesis' in window)) {
            resolve(["(speechSynthesis undefined)"]);
            return;
        }
        const seen = speechSynthesis.getVoices();
        const done = (list) => resolve(
            list.map(v => v.name + " [" + v.lang + "]" + (v.default ? " *" : ""))
        );
        if (seen.length) { done(seen); return; }
        let settled = false;
        const finish = (list) => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            speechSynthesis.removeEventListener('voiceschanged', onChange);
            done(list);
        };
        const onChange = () => finish(speechSynthesis.getVoices());
        const timer = setTimeout(() => finish([]), 1500);
        speechSynthesis.addEventListener('voiceschanged', onChange);
    });

    return { geometry, chromeKeys, voices };
}
"""

# ── Canvas fingerprint (noise-wiring probe) ─────────────────────────────
# Patch 004 wraps GetImage() with per-session seeded noise, so toDataURL
# must differ across sessions. FNV-1a keeps the CDP message small.
CANVAS_HASH_JS = r"""
() => {
    const c = document.createElement('canvas');
    c.width = 240;
    c.height = 60;
    const x = c.getContext('2d');
    x.textBaseline = 'top';
    x.font = '16px "Arial"';
    x.fillStyle = '#f60';
    x.fillRect(125, 1, 62, 20);
    x.fillStyle = '#069';
    x.fillText('Cwm fjordbank glyphs vext quiz, \u{1F603}', 2, 15);
    x.fillStyle = 'rgba(102, 204, 0, 0.7)';
    x.fillText('Cwm fjordbank glyphs vext quiz, \u{1F603}', 4, 17);
    const data = c.toDataURL();
    let h = 0x811c9dc5;
    for (let i = 0; i < data.length; i++) {
        h ^= data.charCodeAt(i);
        h = (h * 0x01000193) >>> 0;
    }
    return ('0000000' + h.toString(16)).slice(-8);
}
"""

# ── Audio fingerprint (noise-wiring probe) ───────────────────────────────
# The standard OfflineAudioContext fingerprint (triangle oscillator through
# a compressor; sum of absolute sample values). Stock output is deterministic
# per host/build, so with patch 011 unwired the sum is identical across
# sessions even though their STEALTH_AUDIO_SEEDs differ.
AUDIO_HASH_JS = """
async () => {
    if (typeof OfflineAudioContext === 'undefined') {
        return { error: 'OfflineAudioContext unavailable' };
    }
    try {
        const ctx = new OfflineAudioContext(1, 5000, 44100);
        const osc = ctx.createOscillator();
        osc.type = 'triangle';
        osc.frequency.value = 10000;
        const comp = ctx.createDynamicsCompressor();
        comp.threshold.value = -50;
        comp.knee.value = 40;
        comp.ratio.value = 12;
        comp.attack.value = 0;
        comp.release.value = 0.25;
        osc.connect(comp);
        comp.connect(ctx.destination);
        osc.start(0);
        const buf = await ctx.startRendering();
        const d = buf.getChannelData(0);
        let sum = 0;
        for (let i = 0; i < d.length; i++) sum += Math.abs(d[i]);
        return { sum };
    } catch (e) {
        return { error: e.name + ': ' + e.message };
    }
}
"""

# Families the claimed OS must be able to render (a confident subset of
# each OS's standard set), keyed by the device profile's ua_platform.
FONT_EXPECTED = {
    "Windows": [
        "Arial", "Calibri", "Cambria", "Consolas", "Courier New",
        "Georgia", "Impact", "Segoe UI", "Tahoma", "Times New Roman",
        "Trebuchet MS", "Verdana",
    ],
    "macOS": [
        "Helvetica", "Menlo", "Monaco", "Optima", "Palatino",
    ],
    "Linux": [
        "DejaVu Sans", "Liberation Sans", "Noto Sans", "Ubuntu",
    ],
}

# Families that exist on a typical Linux server but on NO consumer
# Windows/macOS install. If one of these resolves while the profile
# claims Windows/macOS, the page is seeing through the claimed OS.
HOST_ONLY_FAMILIES = [
    "DejaVu Sans", "DejaVu Sans Mono", "Liberation Mono",
    "Liberation Sans", "Liberation Serif", "Noto Sans", "Ubuntu",
]


def _call(fn_js: str) -> str:
    """
    StealthPage.evaluate() sends a Runtime.evaluate *expression* (it
    awaits a returned promise), so an arrow-function literal has to be
    invoked, not just passed -- otherwise the result is the function
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


def _fmt_infinity(raw, is_inf):
    """Raw Infinity arrives as JSON null; render it honestly."""
    if is_inf:
        return "Infinity"
    if raw is None:
        return "null"
    return raw


def report_font_checks(probe, device, env_vars, failures: int, warnings: int):
    claimed = device.ua_platform
    results = probe.get("results", {})
    font_os = env_vars.get("STEALTH_FONT_OS", "(unset)")
    font_region = env_vars.get("STEALTH_FONT_REGION", "(unset)")

    print(f"\n--- Fonts vs. claimed OS ({claimed}, "
          f"STEALTH_FONT_OS={font_os}, STEALTH_FONT_REGION={font_region}) ---")
    print("  (driver writes a per-session fontconfig at launch, but it needs the"
          " font files: 'python fonts/download_fonts.py --all' (repo) or"
          " 'jbium fetch-fonts' (pip install); without them it warns and uses"
          " the host's fonts)")

    expected = FONT_EXPECTED.get(claimed)
    if expected is None:
        print(f"  [WARN] No expected-font set for claimed platform {claimed!r}"
              " -- font check skipped")
        return failures, warnings + 1

    for family in expected:
        r = results.get(family, {})
        if not _report(f"{family} renders (as a real {claimed} install does)",
                       r.get("resolves", False),
                       f"fonts.check={r.get('check')!r}, width={r.get('width')!r}"):
            failures += 1

    if claimed in ("Windows", "macOS"):
        for family in HOST_ONLY_FAMILIES:
            r = results.get(family, {})
            if not _report(f"host-only {family} invisible to the page (real"
                           f" {claimed} does not ship it)",
                           not r.get("resolves", False),
                           f"fonts.check={r.get('check')!r}"):
                failures += 1

    return failures, warnings


def report_battery_checks(battery, failures: int, warnings: int):
    print("\n--- Battery Status spec consistency ---")
    if not battery or not battery.get("available"):
        print("  [WARN] navigator.getBattery unavailable -- "
              "cannot check (needs a secure context; use an https --url)")
        return failures, warnings + 1

    print(f"  raw: charging={battery['charging']!r} "
          f"level={battery['level']!r} "
          f"chargingTime={_fmt_infinity(battery.get('chargingTime'), battery.get('chargingTimeIsInfinity'))!r} "
          f"dischargingTime={_fmt_infinity(battery.get('dischargingTime'), battery.get('dischargingTimeIsInfinity'))!r}")

    if battery["charging"]:
        if not _report("charging -> dischargingTime is Infinity (spec)",
                       battery.get("dischargingTimeIsInfinity"),
                       f"got {_fmt_infinity(battery.get('dischargingTime'), battery.get('dischargingTimeIsInfinity'))!r}"):
            failures += 1
    else:
        if not _report("discharging -> chargingTime is Infinity (spec)",
                       battery.get("chargingTimeIsInfinity"),
                       f"got {_fmt_infinity(battery.get('chargingTime'), battery.get('chargingTimeIsInfinity'))!r}"):
            failures += 1

    ct, dt = battery.get("chargingTime"), battery.get("dischargingTime")
    if ct == 1800 or dt == 14400:
        print("  [WARN] chargingTime/dischargingTime match patch 010's hardcoded"
              " 1800/14400 exactly -- the driver no longer sets STEALTH_BATTERY_*"
              " (since 2026-10-06), so seeing these constants means a stale"
              " driver copy, a fingerprint_overrides force, or the old behavior"
              " is back (cross-session cluster signature)")
        warnings += 1
    if (ct == 1800 or dt == 14400) and (
        (battery["charging"] and not battery.get("dischargingTimeIsInfinity"))
        or (not battery["charging"] and not battery.get("chargingTimeIsInfinity"))
    ):
        print("  -> diagnosis: patch 010's constant-return design is active (see"
              " patches/010_misc/apply.sh -- the getters ignore charging state"
              " whenever STEALTH_BATTERY_* is set)")
    if battery.get("level") == 1.0 and battery.get("charging") and \
            battery.get("chargingTime") == 0 and battery.get("dischargingTimeIsInfinity"):
        print("  -> info: spec-consistent desktop-AC values (level=1,"
              " charging=true, chargingTime=0, dischargingTime=Infinity) --"
              " the healthy state after the battery-var fix: what every real"
              " desktop Chrome on AC reports. (An UNPATCHED binary reports the"
              " same values -- the spec check alone can't tell them apart,"
              " which is fine: both pass)")

    return failures, warnings


def report_environment_checks(env, device, failures: int, warnings: int):
    geom = env["geometry"]
    claimed = device.ua_platform
    print(f"\n--- Window geometry ---")
    print(f"  screen={geom['screenWidth']}x{geom['screenHeight']} "
          f"avail={geom['availWidth']}x{geom['availHeight']} "
          f"outer={geom['outerWidth']}x{geom['outerHeight']} "
          f"inner={geom['innerWidth']}x{geom['innerHeight']} "
          f"dpr={geom['dpr']} colorDepth={geom['colorDepth']}")

    if not _report("window fits the physical screen (outer* <= screen.*)",
                   geom["outerHeight"] <= geom["screenHeight"]
                   and geom["outerWidth"] <= geom["screenWidth"],
                   f"outer {geom['outerWidth']}x{geom['outerHeight']} vs "
                   f"screen {geom['screenWidth']}x{geom['screenHeight']}"):
        failures += 1

    avail_equals_screen = (geom["availWidth"] == geom["screenWidth"]
                           and geom["availHeight"] == geom["screenHeight"])
    if claimed in ("Windows", "macOS"):
        if avail_equals_screen:
            print(f"  [WARN] screen.avail* reserves no desktop area on a claimed"
                  f" {claimed} -- avail == screen is bare-Xvfb geometry (a"
                  " real consumer display never reports this; the closest"
                  " genuine case, an auto-hide Windows taskbar, is rare)")
            warnings += 1
        else:
            print(f"  [PASS] screen.avail* reserves a desktop area on {claimed}"
                  f" ({geom['screenWidth'] - geom['availWidth']}x"
                  f"{geom['screenHeight'] - geom['availHeight']})")
    elif avail_equals_screen:
        print("  [WARN] avail == screen on a Linux claim -- plausible on"
              " a real minimal desktop, but bare-Xvfb looks the same way")
        warnings += 1

    print("\n--- window.chrome shape ---")
    chrome_keys = env["chromeKeys"]
    if not _report("window.chrome exposes app/csi/loadTimes (as real Chrome does)",
                   chrome_keys is not None and {"app", "csi", "loadTimes"} <= set(chrome_keys),
                   f"got {chrome_keys!r}"):
        warnings += 1

    print("\n--- speechSynthesis voices ---")
    voices = env["voices"]
    print(f"  voices ({len(voices)}): {voices if len(voices) <= 8 else voices[:8]}")
    if claimed in ("Windows", "macOS") and not voices:
        print(f"  [WARN] no voices at all on a claimed {claimed} profile --"
              " real Chrome on consumer Windows/macOS always exposes platform"
              " voices; nothing in jbium spoofs them, so the host's"
              " speech-dispatcher state shows through")
        warnings += 1
    elif any("speechSynthesis undefined" in v for v in voices):
        print("  [WARN] speechSynthesis is undefined entirely")
        warnings += 1

    return failures, warnings


async def collect_hashes(page):
    canvas = await page.evaluate(_call(CANVAS_HASH_JS))
    audio = await page.evaluate(_call(AUDIO_HASH_JS))
    return {"canvas": canvas, "audio": audio}


async def run_session(proxy_url: str, url: str, full: bool):
    """
    One full session. `full=True` also runs the font/battery/geometry
    checks and prints them; `full=False` only collects the noise-wiring
    hashes quietly (those are host-constant, so one full pass is enough).
    Returns (facts, failures, warnings); facts carries the hashes and
    the seeds the driver generated for this session.
    """
    failures = warnings = 0
    async with Jbium() as browser:
        session = await browser.launch(proxy_url=proxy_url, headless=False)
        device = session.device_profile
        env_vars = session.env_vars or {}

        if full:
            print(f"\n{'=' * 62}")
            print(f"Session 1 -- claimed {device.ua_platform} ({device.os}),"
                  f" screen {device.screen_width}x{device.screen_height}")
            print(f"driver seeds: STEALTH_CANVAS_SEED={env_vars.get('STEALTH_CANVAS_SEED')}"
                  f" STEALTH_AUDIO_SEED={env_vars.get('STEALTH_AUDIO_SEED')}")
            print(f"{'=' * 62}")

        page = await browser.new_page()
        await page.goto(url)
        await page.idle(1.0)

        if full:
            print("\nProbing fonts, battery, geometry, voices...")
            font_probe = await page.evaluate(_call(FONT_PROBE_JS))
            if not isinstance(font_probe, dict) or "results" not in font_probe:
                print(f"  [WARN] font probe returned {font_probe!r} -- skipping font checks")
                warnings += 1
            else:
                failures, warnings = report_font_checks(
                    font_probe, device, env_vars, failures, warnings)

            try:
                battery = await page.evaluate(_call(BATTERY_PROBE_JS))
            except Exception as e:
                print(f"  [WARN] battery probe failed: {type(e).__name__}: {e}")
                battery = None
            failures, warnings = report_battery_checks(battery, failures, warnings)

            try:
                env_probe = await page.evaluate(_call(ENVIRONMENT_PROBE_JS))
            except Exception as e:
                print(f"  [WARN] environment probe failed: {type(e).__name__}: {e}")
                env_probe = None
            if env_probe:
                failures, warnings = report_environment_checks(
                    env_probe, device, failures, warnings)
            else:
                warnings += 1

        hashes = await collect_hashes(page)
        if full:
            print(f"\n  canvas hash (session 1): {hashes['canvas']}")
            audio_val = hashes["audio"].get("sum") if isinstance(hashes["audio"], dict) else hashes["audio"]
            print(f"  audio sum  (session 1): {audio_val!r}")

        return {
            "hashes": hashes,
            "canvas_seed": env_vars.get("STEALTH_CANVAS_SEED"),
            "audio_seed": env_vars.get("STEALTH_AUDIO_SEED"),
        }, failures, warnings


async def main(url: str, proxy_url: str = None) -> None:
    proxy1 = proxy_url or get_random_webshare_proxy()
    print(f"Session 1 proxy: {proxy1}")
    facts1, failures, warnings = await run_session(proxy1, url, full=True)

    # Second session: different session seed (and by default a different
    # proxy) to prove which noise layers actually consume their seed.
    proxy2 = get_random_webshare_proxy()
    print(f"\nSession 2 proxy: {proxy2} (noise-wiring comparison only)")
    try:
        facts2, _, _ = await run_session(proxy2, url, full=False)
    except Exception as e:
        print(f"\n[WARN] Second session failed ({type(e).__name__}: {e}) --"
              " noise-wiring comparison skipped; everything else above stands")
        sys.exit(1 if failures else 0)

    print(f"\n--- Per-session noise wiring (session 2:"
          f" STEALTH_CANVAS_SEED={facts2['canvas_seed']}"
          f" STEALTH_AUDIO_SEED={facts2['audio_seed']}) ---")
    print(f"  canvas hash (session 2): {facts2['hashes']['canvas']}")
    audio2 = facts2["hashes"]["audio"]
    audio2_val = audio2.get("sum") if isinstance(audio2, dict) else audio2
    print(f"  audio sum  (session 2): {audio2_val!r}")

    seeds_differ = facts1["canvas_seed"] != facts2["canvas_seed"]
    canvas_differs = facts1["hashes"]["canvas"] != facts2["hashes"]["canvas"]
    if not _report("canvas hash differs across sessions (patch 004 noise wired)",
                   canvas_differs,
                   f"seeds {'differ' if seeds_differ else 'are IDENTICAL'}"
                   f" ({facts1['canvas_seed']} vs {facts2['canvas_seed']}),"
                   f" hashes {'differ' if canvas_differs else 'are identical'}"):
        failures += 1
    if canvas_differs and seeds_differ:
        print("  -> diagnosis: patch 004 canvas noise is consuming"
              " STEALTH_CANVAS_SEED (working as designed)")
    elif not canvas_differs:
        print("  -> diagnosis: canvas output is seed-independent -- patch 004"
              " is not active in this binary (stale pre-patch build?), or"
              " canvas_noise is disabled")

    audio1_val = facts1["hashes"]["audio"]
    audio1_sum = audio1_val.get("sum") if isinstance(audio1_val, dict) else None
    audio2_sum = audio2.get("sum") if isinstance(audio2, dict) else None
    if audio1_sum is None or audio2_sum is None:
        print("  [WARN] audio fingerprint could not be rendered in one or both"
              " sessions -- patch 011 wiring check skipped")
        warnings += 1
    elif audio1_sum == audio2_sum:
        print("  [WARN] audio fingerprint is IDENTICAL across sessions while"
              " their STEALTH_AUDIO_SEEDs differ -- patch 011 (AudioContext"
              " noise) confirmed unwired (the known, deliberate helper-only"
              " stub; see patches/011_audio/apply.sh). One host also matches"
              " real Chrome; the tell is fleet-level: every jbium session on"
              " this host claims a different device but shares one audio"
              " fingerprint")
        warnings += 1
    else:
        print("  [PASS] audio fingerprint differs across sessions --"
              " patch 011 noise is active in this build (newer than the"
              " known helper-only state)")

    print(f"\n{'=' * 62}")
    print(f"Summary: {failures} FAIL, {warnings} WARN")
    print(f"{'=' * 62}")
    print("""
Diagnosis guide (finding -> root cause):
  fonts missing for claimed OS / host families visible
      -> the font files are still not installed: run
         'python fonts/download_fonts.py --all' (repo) or
         'jbium fetch-fonts' (pip install). The driver's
         per-session fontconfig only builds when the claimed
         OS's bundle actually contains .ttf files; until then
         it warns and leaves the host's fonts in place
  battery spec violation + 1800/14400 constants
      -> something set STEALTH_BATTERY_* again (old driver copy,
         fingerprint_overrides) -- since 2026-10-06 the driver
         leaves them unset on purpose (patch 010's getters return
         the constants regardless of charging state, a spec
         violation; unset, the real battery-less readings pass
         through spec-consistently)
  battery spec-consistent desktop-AC values (level=1,
  charging=true, chargingTime=0)
      -> the healthy state after the fix: identical to what every
         real desktop Chrome reports. If the driver ALSO logged
         STEALTH_BATTERY_* vars, you're on a stale binary
  voices empty on a Windows/macOS claim
      -> no spoofing exists; the host's speech-dispatcher shows through
  avail == screen on a Windows/macOS claim
      -> bare-Xvfb geometry (accepted in driver comments, still a tell)
  canvas hash identical across sessions
      -> patch 004 noise not active in this binary
  audio hash identical across sessions (seeds differ)
      -> patch 011 unwired (known, deliberate) -- fleet-level cluster tell
""")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(
        description="Diagnose the fingerprint gaps no other check covers: "
                    "fonts vs claimed OS, Battery Status spec, voices, "
                    "window geometry, and per-session noise wiring.")
    parser.add_argument("--proxy", default=None,
                        help="Proxy URL to use for session 1, e.g. "
                             "http://user:pass@host:port (default: a random "
                             "Webshare proxy from STEALTH_WEBSHARE_*)")
    parser.add_argument("--url", default=DEFAULT_URL,
                        help="Page to probe on (must be https -- the Battery "
                             "API needs a secure context)")
    args = parser.parse_args()

    asyncio.run(main(args.url, args.proxy))