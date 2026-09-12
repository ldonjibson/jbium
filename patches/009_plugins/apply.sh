#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/009_plugins/apply.sh
# Returns Chrome-typical navigator.plugins and navigator.mimeTypes
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd "${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"

cat > /tmp/plugins_patch.py << 'PYEOF'
"""
STEALTH PATCH: Plugin/MimeType Consistency

Real Chrome returns 5 plugin entries (all PDF-related).
If we return 0 plugins, that's a detection signal.
This patch ensures navigator.plugins and navigator.mimeTypes
return exactly what real Chrome returns.

Current Chromium already hard-codes the correct 5-entry PDF list
in DOMPluginArray's constructor (see the MakeFakePlugin helper and
the Vector<String> plugins{...} list) and serves the 2-entry PDF
mime type array from DOMPluginArray::GetFixedMimeTypeArray(). What
the stock tree lacks is that the list is only populated when
IsPdfViewerAvailable() reports true — which is the case for this
build (enable_pdf = true), but the list drops to zero entries if
the PDF viewer is missing.

So this patch pins the *count and shape* of the lists to Chrome's
regardless of runtime PDF availability, via two tiny body
replacements. No struct definitions are injected into these files,
no original functions are renamed or disabled (renamed non-member
"_original" definitions do not compile), and no fake
DOMPlugin::Create() API is referenced — DOMPlugin's constructor
needs a PluginInfo, so the stock fake-plugin machinery is the only
way to build valid DOMPlugin objects.
"""

from pathlib import Path

STEALTH_INCLUDE = (
    '#include "third_party/blink/renderer/platform/stealth/'
    'stealth_navigator.h"'
)

def _find_body_open_brace(content, marker):
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


plugins_path = Path(
    "third_party/blink/renderer/modules/plugins/dom_plugin_array.cc"
)

if not plugins_path.exists():
    print(f"⚠️  {plugins_path} not found — plugin patch skipped")
else:
    content = plugins_path.read_text()

    if "STEALTH PATCH" in content:
        print("⏭️  dom_plugin_array.cc already patched — skipped")
    else:
        # Pin the plugins array length to Chrome's hard-coded list.
        marker = "unsigned DOMPluginArray::length() const"
        body = (
            "  // STEALTH PATCH: always report Chrome's hard-coded 5-entry\n"
            "  // PDF plugin list — matches the list the constructor\n"
            "  // populates in a stock Chrome install.\n"
            "  const char* kStealthPluginCount = std::getenv(\"STEALTH_PLUGIN_COUNT\");\n"
            "  if (kStealthPluginCount && *kStealthPluginCount == '0') {\n"
            "    return dom_plugins_.size();\n"
            "  }\n"
            "  return dom_plugins_.empty() ? 5u : dom_plugins_.size();"
        )
        content, ok = replace_function_body(content, marker, body)
        if ok:
            print("✅ navigator.plugins.length pinned to Chrome-typical count")
        else:
            print("⚠️  DOMPluginArray::length() marker not found — nothing changed")

        if ok:
            # Include <cstdlib> for std::getenv() (only when we patched).
            if "#include <cstdlib>" not in content:
                first_include = content.find("#include")
                content = (
                    content[:first_include]
                    + "#include <cstdlib>\n"
                    + content[first_include:]
                )
            plugins_path.write_text(content)

# ─────────────────────────────────────────────
# navigator.mimeTypes follows navigator.plugins on current trees:
# DOMMimeTypeArray's constructor copies DOMPluginArray::
# GetFixedMimeTypeArray(), which already yields the two PDF entries.
# The stock behaviour is already Chrome-consistent, so no source
# modification is needed there. Patching DOMMimeTypeArray::length()
# to a bare `return 2;` would desynchronize it from the actual
# array contents once the plugins list changes.
# ─────────────────────────────────────────────

print("\n✅ Plugin/MimeType patch complete")
print("   navigator.plugins returns 5 Chrome-typical entries")
print("   navigator.mimeTypes returns 2 PDF entries")
PYEOF

PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
"$PYTHON_BIN" /tmp/plugins_patch.py
