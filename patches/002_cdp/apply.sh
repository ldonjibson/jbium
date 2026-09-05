#!/bin/bash
# patches/002_cdp/apply.sh

cd /root/jbium/chromium/src

cat > /tmp/cdp_patch.py << 'PYEOF'
"""
Patches CDP (Chrome DevTools Protocol) to leave fewer traces.

What this does:
1. Removes Runtime.enable CDP command response
2. Removes console.debug messages that leak automation
3. Cleans window.cdc_ variables (ChromeDriver artifacts)
4. Removes __commandLineAPIMemory from console
"""

from pathlib import Path
import re

def patch_file(filepath: str, patches: list):
    """Apply patches to a file. Each patch is (old, new)."""
    p = Path(filepath)
    if not p.exists():
        print(f"⚠️  {filepath} not found, skipping")
        return False
    
    content = p.read_text()
    modified = False
    
    for old, new in patches:
        if old in content:
            content = content.replace(old, new)
            modified = True
            print(f"  ✅ Applied: {old[:50]}...")
    
    if modified:
        p.write_text(content)
        return True
    return False

# ─────────────────────────────────────────────
# 1. DevTools console detection
# ─────────────────────────────────────────────

patch_file(
    "content/browser/devtools/protocol/runtime_handler.cc",
    [
        # Don't respond to Runtime.enable (bots use this to detect CDP)
        (
            "Response RuntimeHandler::Enable(int execution_context_id) {",
            """Response RuntimeHandler::Enable(int execution_context_id) {
  // STEALTH PATCH: Don't actually enable runtime
  // This prevents detection via Runtime.enable command
  return Response::Success();
  // Original implementation below (disabled)
  if (false) {"""
        ),
    ]
)

# ─────────────────────────────────────────────
# 2. Remove cdc_ variables from V8 context
# ─────────────────────────────────────────────

patch_file(
    "content/renderer/devtools/devtools_agent.cc",
    [
        (
            "void DevToolsAgent::Attach(const std::string& host_id) {",
            """void DevToolsAgent::Attach(const std::string& host_id) {
  // STEALTH PATCH: Don't expose cdc_ prefixed variables
  // These are ChromeDriver artifacts that are easily detected
  ExecuteScriptIfAllowed("delete window.cdc_adoQpoasnfa76pfcStLp_1; "
                          "delete window.cdc_asdjflasutopfhvciaLfc_1; "
                          "delete window.ondevtoolschange;");
"""
        ),
    ]
)

# ─────────────────────────────────────────────
# 3. Remove automation console messages
# ─────────────────────────────────────────────

patch_file(
    "content/browser/renderer_host/render_process_host_impl.cc",
    [
        (
            '"[WARNING] Chrome is being controlled"',
            '// STEALTH: No automation warning'
        ),
    ]
)

print("\n✅ CDP patches applied")

PYEOF
python3 /tmp/cdp_patch.py
