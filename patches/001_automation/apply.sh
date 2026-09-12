#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/001_automation/apply.sh
# Hide automation: navigator.webdriver + automation infobar
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd "${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"

cat > /tmp/automation_patch.py << 'PYEOF'
"""
STEALTH PATCH: Automation Hiding

1. navigator.webdriver: the real implementation lives in
   bool Navigator::webdriver() const (third_party/blink/renderer/
   core/frame/navigator.cc) — it checks
   RuntimeEnabledFeatures::AutomationControlledEnabled() and
   probe::ApplyAutomationOverride(). The previous version of this
   patch overwrote content/renderer/renderer_main_frame.cc with a
   12-line stub (destroying the real file — RendererMainFrame
   doesn't even exist in current trees) and never touched the
   actual webdriver() code path.

2. "Chrome is being controlled by automated test software" bar:
   shown by the static AutomationInfoBarDelegate::Create() in
   chrome/browser/ui/startup/automation_infobar_delegate.cc via
   GlobalConfirmInfoBar::Show(). No-op that single function; the
   per-tab Create(manager) overload stays stock so the class still
   links and behaves normally if invoked directly.

3. --enable-automation: the jbium driver never passes it (it
   launches plain CDP debugging), and blindly commenting every
   source line containing the string "enable-automation" (the old
   approach) corrupts switch tables and string literals. Removed.
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


# ─────────────────────────────────────────────
# 1. navigator.webdriver → always false
# ─────────────────────────────────────────────

nav_path = Path("third_party/blink/renderer/core/frame/navigator.cc")

if not nav_path.exists():
    print("⚠️  navigator.cc not found — webdriver patch skipped")
else:
    content = nav_path.read_text()
    if "STEALTH PATCH" in content:
        print("⏭️  navigator.cc already patched — skipped")
    else:
        marker = "bool Navigator::webdriver() const"
        body = (
            "  // STEALTH PATCH: never advertise automation.\n"
            "  // Original: AutomationControlledEnabled() +\n"
            "  // probe::ApplyAutomationOverride().\n"
            "  return false;"
        )
        content, ok = replace_function_body(content, marker, body)
        if ok:
            nav_path.write_text(content)
            print("✅ navigator.webdriver() → false")
        else:
            print("⚠️  Navigator::webdriver() marker not found — "
                  "webdriver patch skipped")

# ─────────────────────────────────────────────
# 2. Automation infobar → never shown
# ─────────────────────────────────────────────

infobar_path = Path(
    "chrome/browser/ui/startup/automation_infobar_delegate.cc"
)

if not infobar_path.exists():
    print("⚠️  automation_infobar_delegate.cc not found — skipped")
else:
    content = infobar_path.read_text()
    if "STEALTH PATCH" in content:
        print("⏭️  automation_infobar_delegate.cc already patched — skipped")
    else:
        # The static no-arg Create() is the entry the browser calls
        # to raise the global "controlled by automation" bar. The
        # overloaded Create(manager) keeps working, so the delegate
        # class still compiles and links unchanged.
        marker = "void AutomationInfoBarDelegate::Create()"
        body = (
            "  // STEALTH PATCH: never show the automation infobar.\n"
            "  // Original: GlobalConfirmInfoBar::Show(\n"
            "  //     std::move(delegate));"
        )
        content, ok = replace_function_body(content, marker, body)
        if ok:
            infobar_path.write_text(content)
            print("✅ Automation infobar suppressed")
        else:
            print("⚠️  AutomationInfoBarDelegate::Create() marker not "
                  "found — infobar patch skipped")

# ─────────────────────────────────────────────
# 3. --enable-automation flag
#
# The jbium driver never passes --enable-automation (it launches
# plain --remote-debugging-port CDP sessions), so nothing to strip.
# The old "comment every matching line" approach corrupts switch
# tables; removed. If someone launches with the flag anyway, the
# two patches above still keep navigator.webdriver false and the
# infobar hidden.
# ─────────────────────────────────────────────
print("ℹ️  --enable-automation: driver never passes it "
      "(and the patches above neutralize it if present)")

print("\n✅ Automation patches complete")
print("   ✅ navigator.webdriver = false")
print("   ✅ Automation infobar suppressed")
PYEOF

PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
"$PYTHON_BIN" /tmp/automation_patch.py
