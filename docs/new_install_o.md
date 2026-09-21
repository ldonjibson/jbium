# New Server Install (prebuilt binary)

Given everything built this session, the fast path is pip install + jbium fetch (prebuilt binary) — not the from-source build, which takes hours and needs heavy build resources. Here's the concrete sequence for a fresh server:

## 1. Base OS packages (Ubuntu/Debian, matching what's tested)
```bash
sudo apt-get install -y python3 python3-pip python3-venv xvfb \
    libgtk-3-0t64 libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libgbm1 libnss3 libnspr4 libdbus-1-3 libatk1.0-0t64 \
    libatk-bridge2.0-0t64 libcups2t64 libpango-1.0-0 libcairo2 libasound2t64 \
    libexpat1 libxcb1 libxkbcommon0 libatspi2.0-0t64 libdrm2

ldd ~/.cache/jbium/bin/jbium | grep -i "not found"
```
## ------------------------------

(That's the exact shared-library list `ldd` showed the binary actually needs.)

## 2. Install the Python package

Not on real PyPI yet — `pip install jbium` won't work as-is. Install straight from the repo instead:

```bash
pip install "git+https://github.com/ldonjibson/jbium.git#subdirectory=packaging"
# or: pip install jbium[geo] once/if it's ever published to PyPI for real
```

## 3. Fetch the browser binary and GeoIP data

```bash
jbium fetch                # pulls the v1.1.0 Linux x64 binary from the GitHub Release
jbium fetch-geoip          # free DB-IP data by default, or --license-key for MaxMind's
```

## 4. Set credentials (never hardcoded)

```bash
export STEALTH_WEBSHARE_USERNAME=<your-username>
export STEALTH_WEBSHARE_PASSWORD=<your-password>
```

## 5. Your run script + Xvfb wrapper

Since headed operation is required, every real run needs Xvfb:

```bash
xvfb-run -a --server-args='-screen 0 1920x1080x24' python3 your_script.py
OR
xvfb-run -a python3 your_script.py
```

## -- you have to install to read the location
pip install "jbium[geo] @ git+https://github.com/ldonjibson/jbium.git#subdirectory=packaging"

pip install geoip2