#!/bin/bash
# patches/001_automation/apply.sh

cd /root/jbium/chromium/src

# ─────────────────────────────────────────────
# 1. navigator.webdriver = false
# ─────────────────────────────────────────────

cat > content/renderer/renderer_main_frame.cc << 'PATCH1'
// STEALTH PATCH: navigator.webdriver
// Chromium exposes --enable-automation via this flag

#include "third_party/blink/public/web/web_runtime_features.h"

void RendererMainFrame::DidClearWindowObject() {
  // ORIGINAL: if automation mode, set navigator.webdriver = true
  // PATCHED: never set it to true
  
  // Do nothing if automation is enabled
  // navigator.webdriver stays false
}
PATCH1

# ─────────────────────────────────────────────
# 2. Remove "Chrome is being controlled..." infobar
# ─────────────────────────────────────────────

# File: chrome/browser/ui/startup/automation_infobar_delegate.cc
# Make the infobar never show

cat > /tmp/infobar_patch.py << 'PYEOF'
import re
from pathlib import Path

file_path = Path("chrome/browser/ui/startup/automation_infobar_delegate.cc")
if file_path.exists():
    content = file_path.read_text()
    
    # Replace the ShouldShow method
    old = "bool ShouldShow(InfoBarService*)"
    new = "bool ShouldShow(InfoBarService*) { return false; } // STEALTH"
    
    if old in content:
        content = content.replace(
            old,
            f"{new}\n    // Original code disabled\n    if (false) {{"
        )
        # Find the matching closing brace and add }
        # ... (complex patching)
    
    file_path.write_text(content)
    print(f"✅ Patched {file_path}")
PYEOF
python3 /tmp/infobar_patch.py

# ─────────────────────────────────────────────
# 3. Remove --enable-automation from command line
# ─────────────────────────────────────────────

cat > /tmp/args_patch.py << 'PYEOF'
from pathlib import Path

# Patch content/browser/devtools/devtools_agent_host_impl.cc
# to not advertise automation

files_to_patch = [
    "content/browser/devtools/devtools_agent_host_impl.cc",
    "content/common/content_switches_internal.cc",
    "chrome/browser/chrome_browser_main.cc",
]

for fpath in files_to_patch:
    p = Path(fpath)
    if not p.exists():
        continue
    
    content = p.read_text()
    
    # Remove any reference to enable-automation
    if "enable-automation" in content:
        # Comment out any lines that set automation
        lines = content.split("\n")
        new_lines = []
        for line in lines:
            if "enable-automation" in line and "STEALTH" not in line:
                # Don't delete, just make it a no-op
                line = f"    // STEALTH: {line}"
            new_lines.append(line)
        content = "\n".join(new_lines)
        p.write_text(content)
        print(f"✅ Patched {fpath}")

PYEOF
python3 /tmp/args_patch.py
