# 1. On a fresh Ubuntu 22.04+ box, 32GB+ RAM, 150GB+ disk, as root — get the repo there, then:
cd ~/jbium
bash scripts/setup.sh              # ~30-45 min: installs build deps, fetches Chromium, generates config

# 2. Build (fetches remaining source if needed, applies the 10 patches, compiles, renames chrome -> jbium)
bash scripts/build_linux.sh        # 2-4 hours

# 3. Python side — deps, fonts, GeoIP database
pip install -r requirements.txt
python fonts/download_fonts.py --platform linux
bash scripts/download_geoip.sh     # populates ./data/GeoLite2-City.mmdb for GeoIPResolver

# 4. Point the driver at the binary you just built
export STEALTH_BROWSER_PATH=~/jbium/chromium/src/out/Release/jbium

# 5. Set your Webshare proxy credentials (yours — no longer hardcoded in source)
export STEALTH_WEBSHARE_USERNAME=lnrqiugy
export STEALTH_WEBSHARE_PASSWORD=iekhuh2qp013

# 6. Run the actual test
python scripts/quick_check.py https://bot.sannysoft.com/
