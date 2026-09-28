"""
════════════════════════════════════════════════════════════
DataDome probe: WHY is a page blocked?
════════════════════════════════════════════════════════════

A "Bot or Not?" / geo.captcha-delivery.com page only says "blocked".
The block page itself carries DataDome's verdict in an inline
`var dd={...}` object, which is what separates "this IP is banned"
from "this session looked suspicious":

  t   'bv' -> commonly reported as a hard block (banned visitor, typically
             IP/ASN reputation): no fingerprint change will help, the
             proxy is the problem.
      'fe' -> a challenge (captcha) was served: the session itself
             (fingerprint/behaviour/rate) scored as suspicious.
  rt  'c'  -> captcha,  'i' -> interstitial (device check page)

These meanings come from DataDome's public block-page behaviour as widely
observed, not from DataDome documentation -- treat them as strong hints.

This walks the same path as the scraper (homepage, then one listing)
through the normal driver and prints, per navigation: HTTP status,
DataDome response headers, title, the parsed dd object, whether a
datadome cookie was set, and saves the HTML next to this script.

Usage:
    export STEALTH_WEBSHARE_USERNAME=... STEALTH_WEBSHARE_PASSWORD=...
    python example/datadome_probe.py --listing https://www.vrbo.com/1603735?dateless=true
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from driver.stealth_browser import Jbium, get_random_webshare_proxy
except ModuleNotFoundError:
    from jbium.stealth_browser import Jbium, get_random_webshare_proxy

OUT_DIR = Path(__file__).parent

DD_OBJECT = re.compile(r"var\s+dd\s*=\s*\{(.*?)\}", re.S)
DD_PAIR = re.compile(r"""['"](\w+)['"]\s*:\s*(?:['"]([^'"]*)['"]|([-\d.]+))""")


def parse_dd(html: str):
    match = DD_OBJECT.search(html)
    if not match:
        return None
    return {key: (text if text or not number else number)
            for key, text, number in DD_PAIR.findall(match.group(1))}


def verdict_from_url(url: str):
    """
    DataDome often serves the challenge as a document from
    geo.captcha-delivery.com (loaded in a frame), with the verdict in the
    query string: /captcha/?...&t=fe  or  /interstitial/?...
    """
    from urllib.parse import parse_qs, urlsplit

    parts = urlsplit(url or "")
    if "captcha-delivery.com" not in parts.netloc:
        return None
    query = parse_qs(parts.query)
    kind = "c" if "/captcha" in parts.path else "i" if "/interstitial" in parts.path else None
    return {"t": (query.get("t") or [None])[0], "rt": kind, "source": "captcha-delivery URL"}


def explain(dd):
    if dd is None:
        return "no DataDome block object on the page"
    verdict = {"bv": "HARD BLOCK (banned visitor -- typically the IP/ASN)",
               "fe": "CHALLENGE (session scored suspicious: fingerprint/behaviour/rate)"}
    kind = {"c": "captcha", "i": "interstitial device check"}
    return (f"t={dd.get('t')!r}: {verdict.get(dd.get('t'), 'unknown')}; "
            f"rt={dd.get('rt')!r}: {kind.get(dd.get('rt'), 'unknown')}")


async def ip_location_via_proxy(proxy_url: str) -> dict:
    import aiohttp

    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(
                "http://ip-api.com/json/?fields=status,message,query,countryCode,city,timezone,isp,org,as,hosting,proxy,mobile",
                proxy=proxy_url, timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                return await response.json(content_type=None)
    except Exception as e:
        return {"status": "fail", "message": f"{type(e).__name__}: {e}"}


async def connection_fingerprint(page):
    """
    The TLS / HTTP2 fingerprint this browser presents -- what DataDome can
    judge before any page JavaScript runs (a block on the very first
    request is decided on IP + this + headers alone). tls.peet.ws echoes
    the ClientHello and HTTP/2 SETTINGS it received, through the same
    proxy/session the scraper uses.
    """
    await page.goto("https://tls.peet.ws/api/all")
    raw = await page.evaluate("document.body ? document.body.innerText : ''")
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        print(f"\n=== Connection fingerprint: could not read tls.peet.ws ({(raw or '')[:120]!r})")
        return
    tls, http2 = data.get("tls", {}), data.get("http2", {})
    print("\n=== Connection fingerprint (tls.peet.ws)")
    print(f"  http_version: {data.get('http_version')}")
    print(f"  ja4:          {tls.get('ja4')}")
    print(f"  ja3_hash:     {tls.get('ja3_hash')}  (varies per connection in Chrome: extension order is randomized)")
    print(f"  peetprint:    {tls.get('peetprint_hash')}")
    print(f"  http2 akamai: {http2.get('akamai_fingerprint')}")
    print(f"  user-agent seen: {data.get('user_agent')}")


async def visit(page, url: str, label: str):
    documents = []

    def on_response(params):
        if params.get("type") == "Document":
            response = params.get("response", {})
            documents.append((response.get("url"), response.get("status"), response.get("headers", {})))

    page.on("Network.responseReceived", on_response)
    await page.goto(url)
    await page.idle(3)

    html = await page.get_content()
    title = await page.get_title()
    detection = await page.check_detection()
    cookies = (await page._command("Network.getCookies", {"urls": [url]})).get("cookies", [])
    dd = parse_dd(html)
    if dd is None:
        for doc_url, _, _ in documents:
            dd = verdict_from_url(doc_url) or dd

    print(f"\n=== {label}: {url}")
    for doc_url, status, headers in documents:
        dd_headers = {k: v for k, v in headers.items() if k.lower().startswith(("x-datadome", "x-dd", "server"))}
        print(f"  document {status} {doc_url}")
        if dd_headers:
            print(f"    headers: {json.dumps(dd_headers)}")
    print(f"  title: {title!r}")
    print(f"  detected: {[k for k, v in detection.items() if v and k != 'detected'] or 'no'}")
    print(f"  datadome cookie set: {any(c['name'] == 'datadome' for c in cookies)}")
    print(f"  dd object: {json.dumps(dd)}")
    print(f"  verdict: {explain(dd)}")

    out = OUT_DIR / f"datadome_probe_{label}.html"
    out.write_text(html, encoding="utf-8")
    print(f"  html saved: {out}")


async def main(listing: str, home: str):
    proxy_url = get_random_webshare_proxy()

    where = await ip_location_via_proxy(proxy_url)
    print("=== Exit IP (ip-api.com, via the proxy)")
    print(f"  {json.dumps(where)}")
    if where.get("hosting") or where.get("proxy"):
        print("  WARNING: ip-api flags this exit as "
              f"{'hosting/datacenter' if where.get('hosting') else ''}"
              f"{' + ' if where.get('hosting') and where.get('proxy') else ''}"
              f"{'proxy' if where.get('proxy') else ''} -- DataDome weighs IP reputation "
              "before any browser signal, so blocks on such IPs say little about the browser.")

    async with Jbium() as browser:
        session = await browser.launch(proxy_url=proxy_url, headless=False)
        geo = session.geo_profile
        print(f"  driver profile: {geo.country_code} {geo.city} tz={geo.timezone} lang={geo.language} "
              f"ip_type={getattr(geo.ip_type, 'value', geo.ip_type)} asn={geo.asn} isp={geo.isp}")

        page = await browser.new_page()
        await connection_fingerprint(page)
        await visit(page, home, "home")
        await visit(page, listing, "listing")


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listing", required=True, help="A listing URL the scraper got blocked on")
    parser.add_argument("--home", default="https://www.vrbo.com", help="Page visited first (default: VRBO homepage)")
    args = parser.parse_args()
    asyncio.run(main(args.listing, args.home))
