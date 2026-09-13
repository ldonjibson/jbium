# jbium

Python driver for the jbium stealth Chromium browser.

```bash
pip install jbium
# or, for accurate local GeoIP lookups via MaxMind GeoLite2:
pip install jbium[geo]

jbium fetch          # downloads the prebuilt browser binary for your platform
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
