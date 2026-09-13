# CLAUDE.md

Working notes for this repo, written from a long build/debug/packaging
session. These are hard-won, verified facts — not guesses — and exist
so the next session doesn't have to re-discover them the slow way.

## What this project is

A patched, from-source-compiled Chromium build (`jbium`) plus a Python
driver (`driver/`) that configures per-session stealth fingerprinting
(canvas/WebGL noise, navigator spoofing, GeoIP-consistent
language/timezone/geolocation, etc.) via env vars the compiled patches
read at runtime. Positioned as a Camoufox-style alternative: same
category of tool, but Chromium-based instead of Firefox-based.

## Repo layout — what's isolated from what

- `driver/` — the **working, in-place** Python driver. This is what
  the actual compiled/tested build depends on. Do not rename or
  restructure this casually.
- `patches/001`-`011` — Chromium source patches, applied in order by
  `scripts/apply_all.sh`. Pinned to **exactly Chromium 120.0.6099.224**
  — see "Version pinning" below.
- `scripts/` — build (`setup.sh`, `build_linux.sh`, `build_macos.sh`,
  `build_windows.bat`), packaging (`package.sh`, `package_all.py`,
  `upload_s3.py`), and validation (`validate_patches.sh`,
  `reset_patches.sh`) tooling.
- `config/` — `args_linux.gn` / `args_macos.gn` / `args_windows.gn`
  (build-time GN args, correct/reference copies) plus
  `fingerprints.json` / `locales.json` / `settings.yaml` (runtime data
  the driver reads).
- `packaging/` — a **fully separate, isolated** pip-installable
  package (`pip install jbium`), added deliberately as its own tree so
  work on it can never destabilize the working `driver/` build. It
  contains its own copy of the driver code under `packaging/src/jbium/`
  with import paths and data-file paths already adapted for being
  pip-installed (see "Packaging" below). Changes to `driver/` do NOT
  auto-propagate here, and vice versa — this is intentional for now,
  not an oversight.

## Version pinning — this must stay in lockstep

Every patch is written and verified against **Chromium 120.0.6099.224**
specifically, pinned via `git checkout -B jbium-$VERSION tags/$VERSION`
in each build script. `config/fingerprints.json`'s `chrome_versions`
list is deliberately a single entry matching this exact version — do
**not** add more entries to fake UA version diversity; the browser's
actual compiled version is detectable through more than
`navigator.userAgent` (Client Hints, feature-gated JS APIs), so a
mismatched claimed version is a mechanically-detectable tell, not a
cosmetic issue. Real version diversity requires building and
publishing additional pinned Chromium versions.

If the pinned version ever changes, it must change consistently in:
`scripts/setup.sh`, `build_linux.sh`, `build_macos.sh`,
`build_windows.bat` (all have a `CHROMIUM_VERSION` variable), and
`config/fingerprints.json`.

## Build requirements (verified empirically, not just documented)

- **Disk:** 150GB hard-enforced floor in `setup.sh`; 300GB+ realistic
  recommendation (Chromium's `out/Release` alone is 80-120GB+).
- **RAM:** 32GB hard-enforced floor; **64GB is the real threshold** —
  `build_linux.sh`/`build_macos.sh` cut parallelism to `RAM_GB / 2`
  below 64GB regardless of core count, so a 32-core/32GB box builds no
  faster than a 16-core/32GB one.
- **CPU:** more cores = faster, and this dominates below ~16 cores.
  6 cores/12 threads (verified) makes a first full build take
  20-30+ hours; 38 cores (verified) completes in ~4-5 hours.
- GPU/VRAM are irrelevant — this is a pure CPU compile.

## depot_tools bootstrap — use the right tool

A freshly-cloned `depot_tools` needs bootstrapping before `fetch`/
`gclient` work, or you get `"python3_bin_reldir.txt not found"`.

- `gclient --version` does **not** trigger it (short-circuits before
  the bootstrap check).
- `update_depot_tools` does **not** reliably trigger it either — it
  can exit 0 without doing anything (verified live).
- **`ensure_bootstrap` is the one that actually works.**

Separately, `update_depot_tools` refuses to run when `$USER` is
literally the string `"root"` ("Running depot tools as root is sad.")
and just exits — this is a check on `$USER`, not real privilege.
**Fix: override `$USER`, e.g. `export USER=jbium-builder`.** Do NOT
use `VPYTHON_BYPASS` to get past this instead — verified live that it
makes vpython3 skip its own managed-interpreter selection and fall
back to bare system `python3` (3.10 on Ubuntu 22.04), which lacks
`enum.StrEnum` that `gclient.py` needs (3.11+), trading one failure
for a worse, silently-hidden one.

## After pinning the version, re-sync DEPS

`fetch` syncs all `third_party/` DEPS-managed directories against
`origin/main`'s tip **before** the version pin is applied. Switching
`src`'s own branch via `git checkout` does not touch those
directories — they stay on newer revisions. Concretely, this made
`third_party/angle` stay new enough to use "allowlist" naming while
the pinned tag's root `.gn` still expected "whitelist", and `gn gen`
failed outright. **Fix: run `gclient sync --nohooks --no-history -D`
immediately after checking out the pinned tag, before hooks/build.**

`gclient runhooks` also aborts entirely on the first failing hook,
even for optional data (verified: v8's wasm fuzzer test corpus fails
to fetch on a `--no-history` shallow checkout and has zero bearing on
building the actual browser). All three build scripts now warn and
continue on a `runhooks` failure rather than treating it as fatal —
don't revert that without reintroducing a real single-point-of-failure.

## `setup.sh` has its own separate, duplicated `args.gn` heredoc

This has drifted from the correct `config/args_linux.gn` **three
separate times** this session (`chrome_pgo_phase`, `safe_browsing_mode`,
`enable_print_preview` — all three broke the build or the link when
wrong). **Any time you touch build args, diff `setup.sh`'s inline
heredoc against `config/args_linux.gn`'s "REMOVE BLOAT" section** —
assume they've drifted again until proven otherwise.

## Never write a full-function-body-replacement patch unverified

Two patches this session (`004_canvas`'s `GetImage()`,
`008_geoip`'s `EnsureUpdatedLanguage()`) had fabricated bodies —
plausible-looking C++ invented from general Chromium knowledge that
didn't match this actual pinned version's real source, and either
failed to compile or would have silently misbehaved. The fix pattern
that caught both:

```bash
git diff tags/120.0.6099.224 -- <path>      # what did our patch actually change?
git show tags/120.0.6099.224:<path>         # what does the real original look like?
```

Any patch that does a full body replacement (not just wrapping one
expression, like the WebGL GPU-string patches do safely) must be
checked this way before being trusted. `patches/011_audio` is
deliberately left as a header-only, unwired stub for exactly this
reason — completing it without a live build box to verify
`AudioBuffer::getChannelData()`'s real signature risks silently
removing a bounds check (a security bug, not just a compile failure).
See its docstring for the exact verification steps before finishing it.

## Debugging discipline: don't trust truncated output

`gn gen ... | tail -1` and `gclient runhooks | grep -E "(Running|Still)"`
each hid the real error behind cosmetic output-limiting this session —
one buried a `gn gen` error message behind its own caret-formatting
line, the other filtered out an `ImportError` traceback because it
didn't contain "Running" or "Still". Both are now `tee`'d to a log
file with a real `tail -20` instead. When diagnosing any future
failure, prefer `tee` + full log over any truncating pipe.

## Cross-platform gotchas actually hit this session

- Windows batch `for %%d in (pattern)` only matches **files**, never
  directories — needs `for /D %%d in (...)` for a patch-directory loop.
  This silently made 0 patches apply on Windows before being caught.
- Git on Windows checks out `.sh` files as CRLF (`core.autocrlf=true`)
  even though the actual git blob is LF — manually piping a file to a
  remote Linux box (`cat file | ssh ... "cat > remote"`) carries the
  CRLF over and breaks multi-line `if` continuations; always
  `tr -d '\r'` in that pipe. Files committed via `git commit` are fine
  (autocrlf normalizes to LF in the stored blob) — this only bites
  manual out-of-band transfers.
- `--remote-debugging-port` (what the driver uses) is an open,
  unauthenticated local HTTP/WebSocket endpoint — a page the browser
  loads can `fetch('http://127.0.0.1:<port>/json/version')` and
  brute-force the whole port range to detect CDP automation.
  `--remote-debugging-pipe` closes this (stdin/stdout instead of a
  TCP port) but is a real transport-layer rewrite, not a flag swap —
  see conversation history if picking this up.
- The Linux binary is genuinely Linux-only (ELF, glibc/GTK/X11-linked)
  — WSL2 can run it unmodified today; native Windows/macOS need their
  own builds via `build_windows.bat`/`build_macos.sh`, neither of
  which has been run to completion yet (unlike Linux, which has a
  fully verified, working build).

## `.gitignore` — avoid bare name-only patterns

A previous bare `jbium` / `jbium.exe` / `src/` pattern (no slash
scoping) matched **any** file or directory with that literal name
anywhere in the repo, not just build output. Consequence: `launcher/jbium`
(a real, complete launcher script) was **never actually trackable in
git**, silently, because this project's own name keeps recurring as a
legitimate path component. Fixed by relying on the already-present
`chromium/`, `dist/`, `builds/`, `packages/` ignores (which cover
every real location a compiled binary lands) instead of a generic
name match. If adding new ignore rules, scope them with a leading or
embedded `/` rather than a bare name, especially anything containing
"jbium" or "src".

## Packaging (`pip install jbium` / `pip install jbium[geo]`)

Lives entirely under `packaging/` (src-layout: `packaging/src/jbium/`).
Two real bugs fixed there that only matter once actually installed
(not from-source): every hardcoded `"config/fingerprints.json"`-style
relative path only worked because development always runs from the
repo root — fixed to resolve via `Path(__file__).parent`, with the
runtime config/font data actually copied into the package as
`package_data`. `jbium fetch` (in `jbium/cli.py`) downloads the
platform-matched prebuilt binary from a GitHub Release into
`~/.cache/jbium/bin/`, using the exact archive-naming/URL convention
`scripts/package_all.py` already established. As of this writing, only
a Linux binary has ever been built — `jbium fetch` on Windows/macOS
will correctly report "no build published for your platform" rather
than fail confusingly, which is intentional, not a bug to silently
paper over.

## Attribution

Commits and PRs from Claude Code sessions should end with the
`Co-Authored-By` / generation footer lines the harness provides at
commit time — see the system reminder in-session rather than hardcoding
a specific line here, since it can change.
