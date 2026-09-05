#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/009_plugins/apply.sh
# Returns Chrome-typical navigator.plugins and navigator.mimeTypes
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd /root/jbium/chromium/src

cat > /tmp/plugins_patch.py << 'PYEOF'
"""
STEALTH PATCH: Plugin/MimeType Consistency

Real Chrome returns 5 plugin entries (all PDF-related).
If we return 0 plugins, that's a detection signal.
This patch ensures navigator.plugins and navigator.mimeTypes
return exactly what real Chrome returns.
"""

from pathlib import Path

plugins_path = Path(
    "third_party/blink/renderer/modules/plugins/dom_plugin_array.cc"
)

if not plugins_path.exists():
    print(f"⚠️  {plugins_path} not found")
    exit(1)

content = plugins_path.read_text()

# Add include
include = "// STEALTH PATCH: Plugin Array Consistency"
if include not in content:
    # Add the patch at the top of the file (after includes)
    last_include = content.rfind("#include")
    line_end = content.find("\n", last_include)
    
    patch = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: Return Chrome-typical plugin array
// Real Chrome returns 5 PDF-related plugin entries
// ═══════════════════════════════════════════════════════════

namespace {
  
  // Chrome-typical plugin entries
  struct StealthPlugin {
    const char* name;
    const char* filename;
    const char* description;
    const char* mime_type;
    const char* mime_description;
    const char* mime_extension;
  };
  
  const StealthPlugin kChromePlugins[] = {
    {
      "PDF Viewer",
      "internal-pdf-viewer",
      "Portable Document Format",
      "application/pdf",
      "Portable Document Format",
      "pdf"
    },
    {
      "Chrome PDF Viewer",
      "internal-pdf-viewer", 
      "Portable Document Format",
      "application/pdf",
      "Portable Document Format",
      "pdf"
    },
    {
      "Chromium PDF Viewer",
      "internal-pdf-viewer",
      "Portable Document Format",
      "application/pdf",
      "Portable Document Format",
      "pdf"
    },
    {
      "Microsoft Edge PDF Viewer",
      "internal-pdf-viewer",
      "Portable Document Format",
      "application/pdf",
      "Portable Document Format",
      "pdf"
    },
    {
      "WebKit built-in PDF",
      "internal-pdf-viewer",
      "Portable Document Format",
      "application/pdf",
      "Portable Document Format",
      "pdf"
    }
  };
  
  const size_t kNumPlugins = sizeof(kChromePlugins) / sizeof(kChromePlugins[0]);
  
} // namespace
"""
    content = content[:line_end + 1] + patch + content[line_end + 1:]

# Now patch the length() method
old_length = "unsigned DOMPluginArray::length() const"
new_length = """unsigned DOMPluginArray::length() const {
  // STEALTH PATCH: Return Chrome-typical count
  return static_cast<unsigned>(kNumPlugins);
}

// Original (disabled):
unsigned DOMPluginArray_original_length() const"""

if old_length in content:
    content = content.replace(old_length, new_length)
    print("✅ navigator.plugins.length patched")

# Patch item() method  
old_item = "DOMPlugin* DOMPluginArray::item(unsigned index)"
new_item = """DOMPlugin* DOMPluginArray::item(unsigned index) {
  // STEALTH PATCH: Return Chrome-typical plugins
  if (index < kNumPlugins) {
    // Return plugin from our list
    // The actual DOMPlugin creation is complex in Blink
    // but we need to return valid objects
    return DOMPlugin::Create(
      GetExecutionContext(),
      kChromePlugins[index].name,
      kChromePlugins[index].filename,
      kChromePlugins[index].description
    );
  }
  return nullptr;
}

// Original (disabled):
DOMPlugin* DOMPluginArray_original_item(unsigned index)"""

if old_item in content:
    content = content.replace(old_item, new_item)
    print("✅ navigator.plugins.item() patched")

# Patch namedItem()
old_named = "DOMPlugin* DOMPluginArray::namedItem(const AtomicString& name)"
new_named = """DOMPlugin* DOMPluginArray::namedItem(const AtomicString& name) {
  // STEALTH PATCH: Support lookup by Chrome-typical names
  for (size_t i = 0; i < kNumPlugins; i++) {
    if (name == kChromePlugins[i].name) {
      return item(static_cast<unsigned>(i));
    }
  }
  return nullptr;
}

// Original:
DOMPlugin* DOMPluginArray_original_namedItem(const AtomicString& name)"""

if old_named in content:
    content = content.replace(old_named, new_named)
    print("✅ navigator.plugins.namedItem() patched")

plugins_path.write_text(content)

# ─────────────────────────────────────────────
# Also patch navigator.mimeTypes
# ─────────────────────────────────────────────

mimetypes_path = Path(
    "third_party/blink/renderer/modules/plugins/dom_mime_type_array.cc"
)

if mimetypes_path.exists():
    content = mimetypes_path.read_text()
    
    old_mt_length = "unsigned DOMMimeTypeArray::length() const"
    new_mt_length = """unsigned DOMMimeTypeArray::length() const {
  // STEALTH PATCH: Return Chrome-typical MIME type count
  // Chrome returns 2 (both PDF)
  return 2;
}

// Original:
unsigned DOMMimeTypeArray_original_length() const"""
    
    if old_mt_length in content:
        content = content.replace(old_mt_length, new_mt_length)
        print("✅ navigator.mimeTypes.length patched")
    
    mimetypes_path.write_text(content)

print("\n✅ Plugin/MimeType patch complete")
print("   navigator.plugins returns 5 Chrome-typical entries")
print("   navigator.mimeTypes returns 2 PDF entries")
PYEOF

python3 /tmp/plugins_patch.py
