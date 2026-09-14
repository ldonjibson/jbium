# jbium

Python driver for the jbium stealth Chromium browser.

```bash
pip install jbium
# or, for accurate local GeoIP lookups via MaxMind GeoLite2:
pip install jbium[geo]

jbium fetch          # downloads the prebuilt browser binary for your platform
jbium fetch-geoip    # downloads the GeoIP databases (City + ASN) [geo] needs to actually resolve anything
```

```python
from jbium import Jbium

async with Jbium(proxy_url="http://user:pass@proxy:80") as browser:
    page = await browser.new_page()
    await page.goto("https://example.com")
    print(await page.get_content())
```

This package ships only the Python driver — the browser binary itself
is downloaded separately by `jbium fetch` (or automatically on first
use), matched to your OS/architecture. See the main project repo for
how the browser itself is built and patched.

Similarly, `[geo]` only installs the `geoip2` library — it doesn't
install the actual GeoIP data (MaxMind's license forbids bundling it).
Without it, `Jbium` still works, just with less accurate GeoIP-derived
signals (language, timezone, screen resolution weighting). `jbium
fetch-geoip` needs no signup by default (uses a free DB-IP mirror);
pass `--license-key` (or set `GEOIP_LICENSE_KEY`) for MaxMind's more
accurate GeoLite2 data instead, or `--city-url`/`--asn-url` to pull
from your own CDN or mirror. See `API.md` for the full flag reference.
