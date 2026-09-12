#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/008_geoip/apply.sh
# Makes timezone, locale, and geolocation consistent with proxy IP
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd "${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"

cat > /tmp/geoip_patch.py << 'PYEOF'
"""
STEALTH PATCH: GeoIP Consistency

Makes the renderer's timezone, language and locale signals
consistent with the proxy IP's geographic location.

What is patched in-source (verified against this tree):
- navigator.language / navigator.languages: one body replacement in
  NavigatorLanguage::EnsureUpdatedLanguage() — the single choke
  point both properties read from — so they can never disagree.
- HTTP Accept-Language header: an early return inserted into
  HttpUtil::GenerateAcceptLanguageHeader() (the exact function
  every accept-language computation funnels through, verified via
  the tree).

What is deliberately NOT patched in-source anymore:
- Timezone (Date APIs, Intl.DateTimeFormat): the driver sets the
  TZ environment variable to the GeoIP timezone before launch.
  V8's Date cache and ICU both honor TZ, which keeps
  getTimezoneOffset(), Intl default timezone, and date formatting
  consistent with zero source patches. The previous approach
  ("double Date::TimezoneOffset" in v8/src/date/date.cc,
  "GetDefaultTimeZone" in v8_binding_for_core.cc) referenced
  functions that do not exist in this tree and included a blink
  header from inside V8 — neither can compile.
- navigator.geolocation: the driver overrides coordinates over CDP
  (Emulation.setGeolocationOverride) with the GeoIP lat/long +
  jitter. The previous in-source injection called a fabricated
  Geoposition::SetCoords()/handleEvent() API that does not exist.

Env vars (set by the jbium driver):
- STEALTH_GEO_LANGUAGE — e.g. "ja-JP" (navigator.languages +
  Accept-Language header)
- TZ                  — e.g. "Asia/Tokyo" (set by the driver, read
                        by libc/ICU, not by this patch)
"""

from pathlib import Path


def _find_body_open_brace(content, marker):
    """Index of the '{' opening the body of the function whose
    signature contains `marker`; skips the parameter list first so
    multi-line signatures work."""
    idx = content.find(marker)
    if idx == -1:
        return -1
    paren_idx = content.find("(", idx)
    if paren_idx == -1:
        return -1
    depth = 0
    i = paren_idx
    n = len(content)
    while i < n:
        c = content[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                i += 1
                break
        i += 1
    while i < n and content[i] != "{":
        i += 1
    return i if i < n else -1


def replace_function_body(content, marker, new_body):
    brace_idx = _find_body_open_brace(content, marker)
    if brace_idx == -1:
        return content, False
    depth = 0
    i = brace_idx
    n = len(content)
    while i < n:
        c = content[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                i += 1
                break
        i += 1
    new_content = content[:brace_idx] + "{\n" + new_body + "\n}" + content[i:]
    return new_content, True


def insert_after_body_open(content, marker, insertion):
    """Insert `insertion` right after the function body's opening
    brace, leaving the rest of the original body intact (early
    return pattern — no dead code, nothing renamed)."""
    brace_idx = _find_body_open_brace(content, marker)
    if brace_idx == -1:
        return content, False
    new_content = content[:brace_idx + 1] + insertion + content[brace_idx + 1:]
    return new_content, True


def add_include(content, include):
    if include in content:
        return content
    last_include = content.rfind("#include")
    line_end = content.find("\n", last_include)
    return content[:line_end + 1] + include + "\n" + content[line_end + 1:]


# ─────────────────────────────────────────────
# 1. navigator.language / navigator.languages
# ─────────────────────────────────────────────

lang_path = Path(
    "third_party/blink/renderer/core/frame/navigator_language.cc"
)

if not lang_path.exists():
    print("⚠️  navigator_language.cc not found — language patch skipped")
else:
    content = lang_path.read_text()
    if "STEALTH PATCH" in content:
        print("⏭️  navigator_language.cc already patched — skipped")
    else:
        # EnsureUpdatedLanguage() is where languages_ is (re)built;
        # language() returns languages().front() and languages()
        # returns languages_ directly, so one replacement keeps
        # both consistent. Note the real signature returns
        # AtomicString for language() — the old marker
        # "String NavigatorLanguage::language() const" never
        # matched this tree and silently did nothing.
        marker = "void NavigatorLanguage::EnsureUpdatedLanguage()"
        body = (
            "  // STEALTH PATCH: GeoIP-consistent navigator.languages.\n"
            "  // Inject the profile language (e.g. \"ja-JP,en;q=0.8\")\n"
            "  // before any override/dirty-state handling so both\n"
            "  // navigator.language and navigator.languages serve it.\n"
            "  if (const char* geo_languages =\n"
            "          std::getenv(\"STEALTH_GEO_LANGUAGES\")) {\n"
            "    if (*geo_languages) {\n"
            "      languages_ = ParseAndSanitize(\n"
            "          String::FromUTF8(geo_languages));\n"
            "      languages_dirty_ = false;\n"
            "      return;\n"
            "    }\n"
            "  }\n"
            "\n"
            "  String accept_languages_override;\n"
            "  probe::ApplyAcceptLanguageOverride(execution_context_,\n"
            "                                      &accept_languages_override);\n"
            "  if (!accept_languages_override.IsNull()) {\n"
            "    // If the language has override, force use the override\n"
            "    // regardless of the `languages_dirty_` state. This is\n"
            "    // required to allow for workers to respect the override.\n"
            "    languages_ = ParseAndSanitize(accept_languages_override);\n"
            "    // Mark the language as dirty, so that if the override is\n"
            "    // removed, the language will be updated.\n"
            "    languages_dirty_ = true;\n"
            "    return;\n"
            "  }\n"
            "\n"
            "  if (languages_dirty_) {\n"
            "    languages_ = ParseAndSanitize(GetAcceptLanguages());\n"
            "    // Reduce the Accept-Language if the ReduceAcceptLanguage\n"
            "    // deprecation trial is not enabled and feature flag\n"
            "    // ReduceAcceptLanguage is enabled.\n"
            "    if (RuntimeEnabledFeatures::DisableReduceAcceptLanguageEnabled(\n"
            "            execution_context_)) {\n"
            "      UseCounter::Count(\n"
            "          execution_context_,\n"
            "          WebFeature::kDisableReduceAcceptLanguage);\n"
            "    } else if (\n"
            "        base::FeatureList::IsEnabled(\n"
            "            network::features::kReduceAcceptLanguage) &&\n"
            "        !base::CommandLine::ForCurrentProcess()->HasSwitch(\n"
            "            blink::switches::kDisableReduceAcceptLanguage)) {\n"
            "      languages_ = Vector<String>({languages_.front()});\n"
            "    }\n"
            "    languages_dirty_ = false;\n"
            "  }"
        )
        content = add_include(content, "#include <cstdlib>")
        content, ok = replace_function_body(content, marker, body)
        if ok:
            lang_path.write_text(content)
            print("✅ navigator.language/languages patched "
                  "(EnsureUpdatedLanguage)")
        else:
            print("⚠️  NavigatorLanguage::EnsureUpdatedLanguage() not "
                  "found — language patch skipped")

# ─────────────────────────────────────────────
# 2. HTTP Accept-Language header
# ─────────────────────────────────────────────

http_path = Path("net/http/http_util.cc")

if not http_path.exists():
    print("⚠️  http_util.cc not found — header patch skipped")
else:
    content = http_path.read_text()
    if "STEALTH PATCH" in content:
        print("⏭️  http_util.cc already patched — skipped")
    else:
        # Early return at the top of the body; the original logic
        # stays intact below for the no-spoof case.
        marker = "std::string HttpUtil::GenerateAcceptLanguageHeader"
        insertion = (
            "\n"
            "  // STEALTH PATCH: Accept-Language consistent with the\n"
            "  // GeoIP profile (and navigator.languages, which is\n"
            "  // patched to the same env var).\n"
            "  if (const char* geo_lang =\n"
            "          std::getenv(\"STEALTH_GEO_LANGUAGES\")) {\n"
            "    if (*geo_lang) {\n"
            "      const std::string geo_list(geo_lang);\n"
            "      std::string header;\n"
            "      // Comma-separated list, q-values descending.\n"
            "      double q = 1.0;\n"
            "      size_t start = 0;\n"
            "      while (start <= geo_list.size()) {\n"
            "        size_t comma = geo_list.find(',', start);\n"
            "        std::string lang = geo_list.substr(\n"
            "            start, (comma == std::string::npos\n"
            "                         ? geo_list.size()\n"
            "                         : comma) - start);\n"
            "        if (!lang.empty()) {\n"
            "          if (!header.empty()) {\n"
            "            header += \",\";\n"
            "          }\n"
            "          header += lang;\n"
            "          if (q < 1.0) {\n"
            "            char qbuf[16];\n"
            "            std::snprintf(qbuf, sizeof(qbuf), \";q=%.1f\", q);\n"
            "            header += qbuf;\n"
            "          }\n"
            "          q -= 0.1;\n"
            "          if (q < 0.1) {\n"
            "            q = 0.1;\n"
            "          }\n"
            "        }\n"
            "        if (comma == std::string::npos) {\n"
            "          break;\n"
            "        }\n"
            "        start = comma + 1;\n"
            "      }\n"
            "      if (!header.empty()) {\n"
            "        return header;\n"
            "      }\n"
            "    }\n"
            "  }\n"
        )
        content = add_include(content, "#include <cstdlib>")
        content = add_include(content, "#include <cstdio>")
        content, ok = insert_after_body_open(content, marker, insertion)
        if ok:
            http_path.write_text(content)
            print("✅ Accept-Language header patched "
                  "(GenerateAcceptLanguageHeader)")
        else:
            print("⚠️  HttpUtil::GenerateAcceptLanguageHeader not found — "
                  "header patch skipped")

# ─────────────────────────────────────────────
# 3. Timezone + geolocation — handled by the driver:
#    - TZ=<GeoIP timezone> env var (honored by libc/ICU/V8 Date)
#    - Emulation.setGeolocationOverride CDP command (lat/long +
#      accuracy from the GeoIP profile, with per-session jitter)
# ─────────────────────────────────────────────
print("ℹ️  Timezone: driver sets TZ env var (no source patch)")
print("ℹ️  Geolocation: driver applies CDP "
      "Emulation.setGeolocationOverride (no source patch)")

print("\n✅ GeoIP consistency patch complete")
print("   Patched: navigator.languages, Accept-Language header")
print("   Driver-side: TZ env var, CDP geolocation override")
PYEOF

PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
"$PYTHON_BIN" /tmp/geoip_patch.py
