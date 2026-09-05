# Jbium

A patched, fingerprint-hardened build of Chromium (compiled binary: `jbium`/`jbium.exe`), driven at runtime by a Python layer that keeps every anti-detection signal — navigator properties, canvas/WebGL noise, TLS fingerprint, fonts, GeoIP, plugins — internally consistent per session, and interacts with pages via real CDP input events rather than instant, untrusted JS calls.

## How it's built

Two independent layers:

1. **Build-time** — [`config/`](config/) (per-platform GN args) and [`patches/`](patches/) (10 numbered patches applied to Chromium's own source) compile into the `jbium` binary via [`scripts/setup.sh`](scripts/setup.sh) or the platform `build_*` scripts.
2. **Run-time** — [`launcher/`](launcher/) starts that binary and configures [`driver/`](driver/), which reads [`fonts/`](fonts/) and `config/fingerprints.json` on every launch, then drives pages over CDP.

[`tests/`](tests/) exercises both.

### Patches

| # | Name | Addresses |
|---|------|-----------|
| 001 | Automation Detection | `navigator.webdriver`, automation infobar, CLI args |
| 002 | CDP Traces | DevTools protocol detection (`Runtime.enable` leak), console leaks, `cdc_` variables |
| 003 | TLS Fingerprint | JA3/JA4 hash matching |
| 004 | Canvas Noise | Canvas hash fingerprinting |
| 005 | WebGL Spoofing | GPU vendor/renderer detection |
| 006 | Font Filtering | Font enumeration fingerprinting |
| 007 | Navigator Spoofing | CPU/RAM/platform/touch/UA client hints |
| 008 | GeoIP Consistency | Timezone/language/location mismatches |
| 009 | Plugin Consistency | `navigator.plugins`/`mimeTypes` array |
| 010 | Misc Protection | WebRTC IP leak, battery API, media codecs |

See [`docs/PATCHES.md`](docs/PATCHES.md) for detail on each.

## Building on Vast.ai

`scripts/setup.sh` is written specifically for this: rent an Ubuntu 22.04 instance, run one script, get a compiled binary.

**Instance:** 48+ cores / 128GB+ RAM recommended (the script hard-fails under 32GB RAM or 150GB free disk, and warns under 16 cores). Fetching + building Chromium is disk- and RAM-heavy, not just CPU-heavy.

```bash
# 1. Rent the instance on vast.ai, then SSH in as root
ssh -p <port> root@<instance-ip>

# 2. Get this repo onto the instance
git clone <your-repo-url> ~/jbium
cd ~/jbium

# 3. Run setup — installs the toolchain, fetches Chromium (~15GB),
#    lays out the project structure. ~30-45 min, mostly download time.
chmod +x scripts/setup.sh
nohup bash scripts/setup.sh > ~/setup.log 2>&1 &
tail -f ~/setup.log
```

`setup.sh` fetches Chromium into `~/jbium/chromium/src` and generates its own copies of `build.sh`/`package.sh` under the project directory — or use the more complete versioned scripts directly:

```bash
# 4. Build — applies all 10 patches, compiles, strips, and renames
#    the ninja output (chrome) to jbium. 2-4 hours.
bash scripts/build_linux.sh
```

`build_linux.sh` leaves you with `~/jbium/chromium/src/out/Release/jbium` and a portable `jbium-linux-<arch>.tar.gz` bundle next to it.

```bash
# 5. Pull the build back down to work with locally
scp -P <port> root@<instance-ip>:~/jbium/chromium/src/out/Release/jbium-linux-x64.tar.gz .
```

Rebuilding after a patch change is incremental — `bash patches/apply_all.sh && bash scripts/build_linux.sh` only recompiles what changed. `scripts/auto_build.sh` will watch `patches/` and rebuild automatically if you're iterating on a patch.

## Running it

```bash
# Python side: dependencies, fonts, GeoIP database
pip install -r requirements.txt
python fonts/download_fonts.py --platform linux
bash scripts/download_geoip.sh

# Point the driver at the binary you built
export STEALTH_BROWSER_PATH=~/jbium/chromium/src/out/Release/jbium

# Your own proxy credentials — never hardcoded in source
export STEALTH_WEBSHARE_USERNAME=<your-username>
export STEALTH_WEBSHARE_PASSWORD=<your-password>
export STEALTH_WEBSHARE_ENDPOINT=p.webshare.io   # optional, this is the default
export STEALTH_WEBSHARE_PORT=80                  # optional, this is the default

# Smoke test
python scripts/quick_check.py https://bot.sannysoft.com/
```

Or from Python directly:

```python
from driver.stealth_browser import Jbium

async with Jbium(proxy_url="http://user:pass@proxy:80") as browser:
    page = await browser.new_page()
    await page.goto("https://example.com")
    print(await page.get_title())
```

## Packaging & distribution

```bash
python scripts/package_all.py --output dist/    # bundles all built platforms + a universal installer
python scripts/upload_s3.py --bucket <bucket>    # publish dist/ to S3
```

## Repo layout

```
config/     per-platform GN build args, fingerprint/locale data, settings.yaml
patches/    001-010, applied to Chromium source in order
driver/     Python modules that drive the built browser at runtime
launcher/   cross-platform entrypoints (jbium / jbium.bat / jbium.ps1)
fonts/      per-OS font manifests + downloader
scripts/    build, package, upload, and dev tooling
tests/      consistency + stealth test suites
docs/       BUILD.md, PATCHES.md
```

## License

MIT — see [`license`](license).
