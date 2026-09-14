"""
════════════════════════════════════════════════════════════
Jbium CLI — `jbium fetch` / `jbium fetch-geoip`
════════════════════════════════════════════════════════════

`jbium fetch` downloads the prebuilt stealth Chromium binary for the
current platform from a GitHub Release, verifies it, and extracts it
to ~/.cache/jbium/bin/ — the first location jbium.platform_detect's
find_browser_binary() checks.

This mirrors scripts/package_all.py's own naming convention exactly
(same archive name format, same download URL template, same
~/.cache/jbium cache location) so a release built with that script
is fetchable by this CLI with no translation step.

`jbium fetch-geoip` downloads the GeoIP databases GeoIPResolver uses
(MaxMind's GeoLite2-City + GeoLite2-ASN with a license key, or their
free DB-IP equivalents without one) to ~/.cache/jbium/geoip/ — the
pip-installed-package equivalent of scripts/download_geoip.sh, which
only exists in the from-source repo tree and isn't shipped with this
package. Kept logically in sync with that script's two download paths;
see its own comments for the MaxMind-endpoint and DB-IP-URL specifics
this mirrors.
"""

import gzip
import hashlib
import json
import os
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

from jbium.platform_detect import detect_platform_info, Platform, Architecture

# Override via env var to self-host releases (e.g. a fork, or an
# internal mirror) without touching this file.
DEFAULT_RELEASE_BASE = "https://github.com/ldonjibson/jbium/releases/download"

_PLATFORM_KEY = {
    (Platform.LINUX, Architecture.X86_64): "linux-x64",
    (Platform.LINUX, Architecture.ARM64): "linux-arm64",
    (Platform.WINDOWS, Architecture.X86_64): "windows-x64",
    (Platform.MACOS, Architecture.X86_64): "macos-x64",
    (Platform.MACOS, Architecture.ARM64): "macos-arm64",
}

_ARCHIVE_EXT = {
    "linux-x64": "tar.gz",
    "linux-arm64": "tar.gz",
    "windows-x64": "zip",
    "macos-x64": "tar.gz",
    "macos-arm64": "tar.gz",
}


def _cache_dir() -> Path:
    return Path.home() / ".cache" / "jbium"


def _bin_dir() -> Path:
    return _cache_dir() / "bin"


def _geoip_dir() -> Path:
    return _cache_dir() / "geoip"


def _release_base() -> str:
    return os.environ.get("JBIUM_RELEASE_BASE_URL", DEFAULT_RELEASE_BASE)


def _platform_key() -> str:
    info = detect_platform_info()
    key = _PLATFORM_KEY.get((info.platform, info.architecture))
    if key is None:
        raise RuntimeError(
            f"No published jbium build for {info.platform.value}/"
            f"{info.architecture.value}. Supported: "
            f"{', '.join(sorted(_PLATFORM_KEY.values()))}."
        )
    return key


def _download(url: str, dest: Path) -> None:
    """Stream a download to `dest` with a simple progress indicator."""

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    # DB-IP's download host (Cloudflare-fronted) 403s Python's default
    # "Python-urllib/x.y" User-Agent specifically -- confirmed live:
    # curl succeeds with any UA, bare urlopen() fails, only the UA
    # differs. GitHub Releases (the other thing this function fetches)
    # doesn't care either way, so a generic browser-shaped UA is safe
    # for both call sites.
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; jbium-fetch)"}
    )

    try:
        with urllib.request.urlopen(request) as response:
            total = int(response.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            with open(tmp, "wb") as f:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        print(
                            f"\r  Downloading... {pct}% "
                            f"({downloaded // (1024 * 1024)}MB / "
                            f"{total // (1024 * 1024)}MB)",
                            end="", file=sys.stderr,
                        )
            print("", file=sys.stderr)
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        if e.code == 404:
            raise RuntimeError(
                f"No build published at {url}\n"
                f"This usually means a jbium release for your platform "
                f"hasn't been published yet - see "
                f"https://github.com/ldonjibson/jbium for the "
                f"current release status, or build it yourself with "
                f"scripts/build_linux.sh / build_macos.sh / "
                f"build_windows.bat."
            ) from e
        raise RuntimeError(f"Download failed ({e.code}): {url}") from e
    except urllib.error.URLError as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Could not reach {url}: {e.reason}") from e

    tmp.replace(dest)


def _verify_checksum(archive: Path, expected_sha256: str) -> None:
    h = hashlib.sha256()
    with open(archive, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected_sha256:
        archive.unlink(missing_ok=True)
        raise RuntimeError(
            f"Checksum mismatch for {archive.name}:\n"
            f"  expected: {expected_sha256}\n"
            f"  actual:   {actual}\n"
            f"Deleted the corrupted download - re-run `jbium fetch` to retry."
        )


def _extract(archive: Path, dest_dir: Path) -> None:
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest_dir)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(dest_dir)


def fetch(version: str, checksum: str = None, force: bool = False) -> Path:
    """
    Download and extract the jbium binary for the current platform and
    the given release version. Returns the path to the extracted
    binary directory (jbium.platform_detect will find the binary
    inside it on the next call).
    """

    platform_key = _platform_key()
    ext = _ARCHIVE_EXT[platform_key]
    archive_name = f"jbium-{version}-{platform_key}.{ext}"
    archive_path = _cache_dir() / archive_name
    bin_dir = _bin_dir()

    if not force and archive_path.exists() and (checksum is None or True):
        print(f"  Using cached download: {archive_path}")
    else:
        url = f"{_release_base()}/v{version}/{archive_name}"
        print(f"  Fetching {platform_key} build (v{version})...")
        print(f"  URL: {url}")
        _download(url, archive_path)

    if checksum:
        _verify_checksum(archive_path, checksum)

    print(f"  Extracting to {bin_dir}...")
    _extract(archive_path, bin_dir)

    print(f"OK: jbium v{version} ({platform_key}) ready at {bin_dir}")
    return bin_dir


def _fetch_maxmind_edition(edition: str, license_key: str, dest: Path) -> None:
    """
    Download one MaxMind GeoLite2 edition and flatten its .mmdb out of
    the versioned subfolder MaxMind's tarball wraps it in, straight to
    `dest`. Uses the long-standing direct-download endpoint (only a
    license key needed, no account ID) -- see
    scripts/download_geoip.sh's own comment for why, and for the newer
    REST endpoint this deliberately avoids.
    """

    tmp_tar = dest.with_name(dest.name + ".tar.gz")
    url = (
        "https://download.maxmind.com/app/geoip_download"
        f"?edition_id={edition}&license_key={license_key}&suffix=tar.gz"
    )
    print(f"  Downloading {edition}...")
    _download(url, tmp_tar)

    try:
        with tarfile.open(tmp_tar) as tf:
            member = next(
                (m for m in tf.getmembers() if m.name.endswith(".mmdb")), None
            )
            if not member:
                raise RuntimeError(f"No .mmdb file found in the {edition} archive")
            member.name = dest.name
            tf.extract(member, dest.parent)
    finally:
        tmp_tar.unlink(missing_ok=True)


def _fetch_dbip_edition(name: str, month: str, dest: Path) -> None:
    """Download one free DB-IP Lite edition and gunzip it to `dest`."""

    tmp_gz = dest.with_name(dest.name + ".gz")
    url = f"https://download.db-ip.com/free/{name}-{month}.mmdb.gz"
    print(f"  Downloading {name}...")
    _download(url, tmp_gz)

    try:
        with gzip.open(tmp_gz, "rb") as f_in, open(dest, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    finally:
        tmp_gz.unlink(missing_ok=True)


def fetch_geoip(license_key: str = None, force: bool = False) -> Path:
    """
    Download GeoLite2-City + GeoLite2-ASN (MaxMind, with a license
    key) or their free DB-IP equivalents (without one) to
    ~/.cache/jbium/geoip/ -- the location GeoIPResolver checks
    automatically, right after STEALTH_GEOIP_DB_PATH/
    STEALTH_GEOIP_ASN_DB_PATH and before falling back to the less
    accurate heuristic resolver.
    """

    geoip_dir = _geoip_dir()
    geoip_dir.mkdir(parents=True, exist_ok=True)

    city_path = geoip_dir / "GeoLite2-City.mmdb"
    asn_path = geoip_dir / "GeoLite2-ASN.mmdb"

    if not force and city_path.exists() and asn_path.exists():
        print(f"  Using cached GeoIP databases: {geoip_dir}")
        return geoip_dir

    license_key = license_key or os.environ.get("GEOIP_LICENSE_KEY")

    if license_key:
        print("  Using MaxMind license key...")
        _fetch_maxmind_edition("GeoLite2-City", license_key, city_path)
        _fetch_maxmind_edition("GeoLite2-ASN", license_key, asn_path)
    else:
        print("  Using free DB-IP database (no license key)...")
        print("  For better accuracy, pass --license-key or set GEOIP_LICENSE_KEY")
        month = date.today().strftime("%Y-%m")
        _fetch_dbip_edition("dbip-city-lite", month, city_path)
        _fetch_dbip_edition("dbip-asn-lite", month, asn_path)

    print(f"OK: GeoIP databases ready at {geoip_dir}")
    return geoip_dir


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="jbium", description="Jbium stealth browser CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Download the prebuilt browser binary")
    fetch_p.add_argument(
        "version", nargs="?", default=None,
        help="Release version to fetch (default: matches the installed "
             "jbium package version)",
    )
    fetch_p.add_argument("--checksum", default=None, help="Expected SHA256 of the archive")
    fetch_p.add_argument(
        "--force", action="store_true",
        help="Re-download even if a cached archive already exists",
    )

    geoip_p = sub.add_parser(
        "fetch-geoip", help="Download GeoIP databases (City + ASN) for accurate GeoIP resolution"
    )
    geoip_p.add_argument(
        "--license-key", default=None,
        help="MaxMind license key (uses free DB-IP data if omitted; "
             "also read from GEOIP_LICENSE_KEY)",
    )
    geoip_p.add_argument(
        "--force", action="store_true",
        help="Re-download even if cached databases already exist",
    )

    args = parser.parse_args(argv)

    if args.command == "fetch":
        version = args.version
        if version is None:
            from jbium import __version__
            version = __version__
        try:
            fetch(version, checksum=args.checksum, force=args.force)
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        return 0

    if args.command == "fetch-geoip":
        try:
            fetch_geoip(license_key=args.license_key, force=args.force)
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
