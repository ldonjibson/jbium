#!/usr/bin/env python3
"""
One-off repair for a Chromium checkout that already had patches/008_geoip
applied with the old, broken splice logic in sections 5 and 6 (geolocation.cc,
http_util.cc) — it matched only a function's bare signature (missing the
parameter list) and inserted a brace right after it, leaving the real
"(params) {" dangling after the injected block instead of attached to the
function name.

Sections 3 and 4 (v8_binding_for_core.cc, date.cc) are broken in a
different, less mechanical way (they rename the original via a bogus
"_original" suffix instead of leaving params dangling) and are NOT handled
here — if ninja fails on those files, paste the error and get a targeted fix.

Run from the Chromium src root: python3 scripts/fix_geoip_patch.py
"""

import re
from pathlib import Path

FIXES = [
    ("net/http/http_util.cc", "std::string HttpUtil::GenerateAcceptLanguageHeader"),
    (
        "third_party/blink/renderer/modules/geolocation/geolocation.cc",
        "void Geolocation::getCurrentPosition",
    ),
]


def fix_file(path: Path, name: str) -> str:
    if not path.exists():
        return "file not found (patch section likely never applied) — skipped"

    text = path.read_text()

    # NAME {  <injected block>  // Original ...\n  (params) {\n
    pattern = re.compile(
        re.escape(name) + r" \{\n" + r"(.*?)" + r"(  // Original[^\n]*\n)" + r"(\([^\n]*\{\n)",
        re.DOTALL,
    )

    def repl(m):
        injected, marker, params_line = m.groups()
        return f"{name}{params_line}{injected}{marker}"

    new_text, n = pattern.subn(repl, text, count=1)
    if n == 0:
        return "already correct or pattern didn't match — left untouched"

    path.write_text(new_text)
    return "fixed"


def main():
    for rel_path, name in FIXES:
        result = fix_file(Path(rel_path), name)
        print(f"{rel_path}: {result}")


if __name__ == "__main__":
    main()
