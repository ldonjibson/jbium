#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════
S3 Uploader
════════════════════════════════════════════════════════════

Uploads the packages produced by scripts/package_all.py
(dist/jbium-<version>-<platform>.<ext>) to S3, updates
a "latest" pointer per platform, and writes a combined manifest.

Usage:
    python scripts/upload_s3.py --bucket my-bucket
    python scripts/upload_s3.py --bucket my-bucket --dist-dir dist --version 1.0.0
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    print("❌ boto3 not installed. Run: pip install boto3")
    sys.exit(1)


def find_packages(dist_dir: Path, version: str) -> List[Path]:
    """Find every archive package_all.py produced for this version."""

    patterns = [f"jbium-{version}-*.tar.gz", f"jbium-{version}-*.zip"]
    packages = []
    for pattern in patterns:
        packages.extend(sorted(dist_dir.glob(pattern)))
    return packages


def platform_name(package: Path, version: str) -> str:
    """Extract 'linux-x64' etc. out of jbium-<version>-<platform>.<ext>"""

    stem = package.name
    for ext in (".tar.gz", ".zip"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
            break

    prefix = f"jbium-{version}-"
    return stem[len(prefix):] if stem.startswith(prefix) else stem


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upload_package(s3, bucket: str, prefix: str, package: Path, plat: str) -> Dict:
    """Upload one platform's archive plus its 'latest' pointer."""

    key = f"{prefix}/{package.name}"
    latest_key = f"{prefix}/{plat}/latest{package.suffix if package.suffix != '.gz' else '.tar.gz'}"

    size = package.stat().st_size
    sha = sha256_of(package)

    print(f"  Uploading {package.name} ({size / 1024 / 1024:.1f} MB)...")
    s3.upload_file(str(package), bucket, key)

    print(f"  Updating latest pointer: {latest_key}")
    s3.copy_object(
        Bucket=bucket,
        CopySource={"Bucket": bucket, "Key": key},
        Key=latest_key,
    )

    return {
        "platform": plat,
        "file": package.name,
        "key": key,
        "size_bytes": size,
        "sha256": sha,
    }


def main():
    parser = argparse.ArgumentParser(description="Upload packaged builds to S3")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--prefix", default="jbium", help="S3 key prefix")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--dist-dir", default=None, help="Directory with packaged archives (default: <repo>/dist)")
    parser.add_argument("--version", default="1.0.0", help="Version being uploaded")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    dist_dir = Path(args.dist_dir) if args.dist_dir else project_root / "dist"

    if not dist_dir.exists():
        print(f"❌ No dist directory found at {dist_dir}. Run scripts/package_all.py first.")
        sys.exit(1)

    packages = find_packages(dist_dir, args.version)
    if not packages:
        print(f"❌ No packages found for version {args.version} in {dist_dir}")
        sys.exit(1)

    print("═" * 60)
    print("  Jbium — S3 Upload")
    print(f"  Bucket: s3://{args.bucket}/{args.prefix}/")
    print(f"  Version: {args.version}")
    print(f"  Packages: {len(packages)}")
    print("═" * 60)
    print()

    s3 = boto3.client("s3", region_name=args.region)

    uploaded = []
    for package in packages:
        plat = platform_name(package, args.version)
        try:
            uploaded.append(upload_package(s3, args.bucket, args.prefix, package, plat))
        except (BotoCoreError, ClientError) as e:
            print(f"  ❌ Failed to upload {package.name}: {e}")

    if not uploaded:
        print("\n❌ No packages uploaded successfully")
        sys.exit(1)

    manifest = {
        "version": args.version,
        "date": datetime.now(timezone.utc).isoformat(),
        "packages": uploaded,
    }

    manifest_key = f"{args.prefix}/manifest.json"
    print(f"\n  Writing manifest: {manifest_key}")
    s3.put_object(
        Bucket=args.bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2).encode(),
        ContentType="application/json",
    )

    print()
    print("═" * 60)
    print(f"  ✅ Uploaded {len(uploaded)}/{len(packages)} packages")
    print(f"  Bucket: s3://{args.bucket}/{args.prefix}/")
    for entry in uploaded:
        print(f"    - {entry['platform']}: {entry['file']}")
    print("═" * 60)


if __name__ == "__main__":
    main()
