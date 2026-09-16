# New Server Install (prebuilt binary)

Given everything built this session, the fast path is pip install + jbium fetch (prebuilt binary) — not the from-source build, which takes hours and needs heavy build resources. Here's the concrete sequence for a fresh server:

## 1. Base OS packages (Ubuntu/Debian, matching what's tested)

```bash
apt-get update
apt-get install -y python3 python3-pip python3-venv xvfb \
    libgtk-3-0 libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libgbm1 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libpango-1.0-0 libcairo2 libasound2 \
    libexpat1 libxcb1 libxkbcommon0 libatspi2.0-0 libdrm2
```

(That's the exact shared-library list `ldd` showed the binary actually needs.)

**Ubuntu 24.04+ (or any distro past the 64-bit time_t transition):** several of
these packages were renamed with a `t64` suffix, and `libasound2` in
particular is ambiguous between two providers so plain `apt-get install
libasound2` fails outright with "has no installation candidate". Use this
instead on newer systems:

```bash
apt-get install -y python3 python3-pip python3-venv xvfb \
    libgtk-3-0t64 libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libgbm1 libnss3 libnspr4 libdbus-1-3 libatk1.0-0t64 \
    libatk-bridge2.0-0t64 libcups2t64 libpango-1.0-0 libcairo2 libasound2t64 \
    libexpat1 libxcb1 libxkbcommon0 libatspi2.0-0t64 libdrm2
```

Either way, confirm nothing's missing before moving on — this is what
actually caught the `t64` issue live rather than guessing:

```bash
ldd ~/.cache/jbium/bin/jbium | grep -i "not found"
```

## 2. Install the Python package

Not on real PyPI yet — `pip install jbium` won't work as-is. Install straight from the repo instead:

```bash
pip install "git+https://github.com/ldonjibson/jbium.git#subdirectory=packaging"
# or: pip install jbium[geo] once/if it's ever published to PyPI for real
```

## 3. Fetch the browser binary and GeoIP data

```bash
jbium fetch                # pulls the v1.1.0 Linux x64 binary from the GitHub Release
jbium fetch-geoip          # free git.io/GeoLite.mmdb mirror by default, or --license-key for MaxMind's
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
```
