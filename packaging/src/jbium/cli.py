"""
════════════════════════════════════════════════════════════
Jbium CLI — `jbium fetch`
════════════════════════════════════════════════════════════

Downloads the prebuilt stealth Chromium binary for the current
platform from a GitHub Release, verifies it, and extracts it to
~/.cache/jbium/bin/ — the first location jbium.platform_detect's
find_browser_binary() checks.

This mirrors scripts/package_all.py's own naming convention exactly
(same archive name format, same download URL template, same
~/.cache/jbium cache location) so a release built with that script
is fetchable by this CLI with no translation step.
"""

import hashlib
import json
import os
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from jbium.platform_detect import detect_platform_info, Platform, Architecture

# Override via env var to self-host releases (e.g. a fork, or an
# internal mirror) without touching this file.
DEFAULT_RELEASE_BASE = "https://github.com/REPLACE_WITH_OWNER/jbium/releases/download"

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

    try:
        with urllib.request.urlopen(url) as response:
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
                f"https://github.com/REPLACE_WITH_OWNER/jbium for the "
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

    return 1


if __name__ == "__main__":
    sys.exit(main())
