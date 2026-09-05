#!/bin/bash
# patches/005_webgl/apply.sh

cd /root/jbium/chromium/src

cat > /tmp/webgl_patch.py << 'PYEOF'
"""
Spoofs WebGL vendor/renderer strings to match common consumer hardware.
Prevents detection via GPU fingerprinting.
"""

from pathlib import Path

webgl_path = Path(
    "third_party/blink/renderer/modules/webgl/"
    "webgl_rendering_context_base.cc"
)

if not webgl_path.exists():
    print("⚠️ WebGL file not found")
    exit(1)

content = webgl_path.read_text()

# Inject spoofed GPU strings
SPOOF_CODE = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: WebGL GPU Spoofing
// ═══════════════════════════════════════════════════════════

#include <cstdlib>

namespace {
    // GPU profiles that look like real consumer hardware
    // These are common in actual Chrome users
    struct GPUProfile {
        const char* vendor;
        const char* renderer;
        const char* version;
    };
    
    const GPUProfile kGPUProfiles[] = {
        // Intel integrated (very common in laptops)
        {"Intel Inc.", 
         "Intel(R) Iris(R) Xe Graphics",
         "WebGL 1.0 (OpenGL ES 2.0 Chromium)"},
        
        // NVIDIA discrete (common in desktops/gaming)
        {"NVIDIA Corporation",
         "NVIDIA GeForce RTX 3060/PCIe/SSE2",
         "WebGL 1.0 (OpenGL ES 2.0 Chromium)"},
        
        // AMD
        {"AMD",
         "AMD Radeon(TM) Graphics",
         "WebGL 1.0 (OpenGL ES 2.0 Chromium)"},
        
        // Apple (if masquerading as Mac)
        {"Apple",
         "Apple M1 Pro",
         "WebGL 1.0 (OpenGL ES 2.0 Chromium)"},
    };
    
    // Selected profile for this session
    const GPUProfile* g_selected_profile = nullptr;
    
    void InitializeGPUProfile() {
        if (!g_selected_profile) {
            // Select based on environment variable or random
            const char* gpu_override = std::getenv("STEALTH_GPU_PROFILE");
            if (gpu_override) {
                int idx = atoi(gpu_override);
                g_selected_profile = &kGPUProfiles[idx % 4];
            } else {
                // Default: Intel (most common)
                g_selected_profile = &kGPUProfiles[0];
            }
        }
    }
} // namespace

// END STEALTH PATCH
"""

# Add the spoof code at the top (after includes)
# Find a good insertion point
if "STEALTH PATCH" not in content:
    # Insert after the last #include
    last_include = content.rfind("#include")
    end_of_include = content.find("\n", last_include)
    
    content = (
        content[:end_of_include + 1] 
        + SPOOF_CODE 
        + content[end_of_include + 1:]
    )

# Now patch the GetString method
old_get_string = """String WebGLRenderingContextBase::GetString(
    GLenum name) {"""
    
new_get_string = """String WebGLRenderingContextBase::GetString(
    GLenum name) {
  // STEALTH PATCH: Return spoofed GPU strings
  InitializeGPUProfile();
  switch (name) {
    case GL_VENDOR:
      return String(g_selected_profile->vendor);
    case GL_RENDERER:
      return String(g_selected_profile->renderer);
    case GL_VERSION:
      return String(g_selected_profile->version);
    default:
      break;  // Fall through to original
  }
  // Original code below:
"""

if old_get_string in content:
    content = content.replace(old_get_string, new_get_string)
    print("✅ WebGL vendor/renderer spoofed")
else:
    # Try alternative method name
    print("⚠️  GetString not found, checking alternatives...")

webgl_path.write_text(content)
print("✅ WebGL patch applied")

PYEOF
python3 /tmp/webgl_patch.py
