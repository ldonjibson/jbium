#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/005_webgl/apply.sh
# WebGL GPU string spoofing (vendor/renderer/version)
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd "${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"

cat > /tmp/webgl_patch.py << 'PYEOF'
"""
STEALTH PATCH: WebGL GPU String Spoofing

What actually leaks in WebGL (verified against this tree,
third_party/blink/renderer/modules/webgl/
webgl_rendering_context_base.cc, getParameter):

- Masked GL_VENDOR / GL_RENDERER: stock Chromium already returns
  the constants "WebKit" / "WebKit WebGL" — identical on every
  real Chrome, nothing to spoof.
- WEBGL_debug_renderer_info extension:
  kUnmaskedRendererWebgl returns
      String(ContextGL()->GetString(GL_RENDERER))
  and kUnmaskedVendorWebgl returns
      String(ContextGL()->GetString(GL_VENDOR))
  These expose the real GPU (and with --disable-gpu, a SwiftShader
  string that instantly flags a software/headless browser).
- GL_VERSION / GL_SHADING_LANGUAGE_VERSION: the masked strings are
  "WebGL 1.0 (<driver version>)" / "WebGL GLSL ES 1.0 (<driver>)"
  where the inner segment comes from
  ContextGL()->GetString(GL_VERSION / GL_SHADING_LANGUAGE_VERSION)
  — again a SwiftShader giveaway under --disable-gpu.

Patch strategy: wrap each of those four expressions (they are
identical in the WebGL1 and WebGL2 files) with a header-only
stealth::GPUSpoof::Xxx(...) call that returns the env-var override
when the driver sets one, and the real value otherwise. No
behavior change with no env vars → build- and runtime-safe.

What the old patch got wrong (and is gone):
- Its marker "String WebGLRenderingContextBase::GetString(GLenum
  name)" does not exist in this tree (no such member), so the
  actual spoof never applied — while the injected anonymous-
  namespace kGPUProfiles block DID land unconditionally and its
  unused functions killed the build under -Werror.
- It wrote an uncompiled stealth_gpu_profile.cc (never registered
  in BUILD.gn → undefined-symbol link failure).

Env vars (set by the jbium driver):
- STEALTH_GPU_VENDOR      e.g. "Google Inc. (NVIDIA)"
- STEALTH_GPU_RENDERER    e.g. "ANGLE (NVIDIA, NVIDIA GeForce RTX
                           3060 Direct3D11 vs_5_0 ps_5_0)"
- STEALTH_GPU_VERSION     e.g. "OpenGL ES 2.0 Chromium"
- STEALTH_GPU_GLSL_VERSION e.g. "OpenGL ES GLSL ES 1.0.17"
Unset variables pass the real driver value through unchanged.
"""

from pathlib import Path

# ─────────────────────────────────────────────
# 1. Header-only GPU string helper
# ─────────────────────────────────────────────

GPU_HEADER = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: WebGL GPU string spoofing (header-only)
// ═══════════════════════════════════════════════════════════
//
// Header-only on purpose: the patched file already belongs to a
// build target, so no BUILD.gn changes and no stealth .cc that
// could go unlinked. No global constructors: everything is a
// static function reading getenv().

#ifndef STEALTH_WEBGL_H_
#define STEALTH_WEBGL_H_

#include <cstdlib>
#include <string>

#include "third_party/blink/renderer/platform/wtf/text/wtf_string.h"

namespace stealth {

class GPUSpoof {
 public:
  // Returns the value of `env_name` as a WTF String, or
  // `real_value` when unset/empty. Called only from the patched
  // getParameter() case bodies.
  static String OrEnv(const char* env_name, String real_value) {
    const char* value = std::getenv(env_name);
    if (value && *value) {
      return String::FromUtf8(std::string(value));
    }
    return real_value;
  }

  static String Renderer(String real) {
    return OrEnv("STEALTH_GPU_RENDERER", std::move(real));
  }

  static String Vendor(String real) {
    return OrEnv("STEALTH_GPU_VENDOR", std::move(real));
  }

  static String Version(String real) {
    return OrEnv("STEALTH_GPU_VERSION", std::move(real));
  }

  static String GlslVersion(String real) {
    return OrEnv("STEALTH_GPU_GLSL_VERSION", std::move(real));
  }
};

}  // namespace stealth

#endif  // STEALTH_WEBGL_H_
"""

stealth_dir = Path("third_party/blink/renderer/platform/stealth/")
stealth_dir.mkdir(parents=True, exist_ok=True)
(stealth_dir / "stealth_webgl.h").write_text(GPU_HEADER)
print("✅ WebGL spoof: stealth_webgl.h (header-only)")

# ─────────────────────────────────────────────
# 2. Wrap the four leak expressions
# ─────────────────────────────────────────────

# Expression-level replacements: formatting-independent, so they
# land identically in the WebGL1 and WebGL2 getParameter switches.
REPLACEMENTS = [
    (
        "String(ContextGL()->GetString(GL_RENDERER))",
        "stealth::GPUSpoof::Renderer(\n"
        "            String(ContextGL()->GetString(GL_RENDERER)))",
        "unmasked renderer (WEBGL_debug_renderer_info)",
    ),
    (
        "String(ContextGL()->GetString(GL_VENDOR))",
        "stealth::GPUSpoof::Vendor(\n"
        "            String(ContextGL()->GetString(GL_VENDOR)))",
        "unmasked vendor (WEBGL_debug_renderer_info)",
    ),
    (
        "String(ContextGL()->GetString(GL_VERSION))",
        "stealth::GPUSpoof::Version(\n"
        "            String(ContextGL()->GetString(GL_VERSION)))",
        "driver GL_VERSION segment",
    ),
    (
        "String(ContextGL()->GetString(GL_SHADING_LANGUAGE_VERSION))",
        "stealth::GPUSpoof::GlslVersion(\n"
        "            String(ContextGL()->GetString(\n"
        "                GL_SHADING_LANGUAGE_VERSION)))",
        "driver GLSL version segment",
    ),
]

STEALTH_INCLUDE = (
    '#include "third_party/blink/renderer/platform/stealth/'
    'stealth_webgl.h"'
)


def add_include(content, include):
    if include in content:
        return content
    last_include = content.rfind("#include")
    line_end = content.find("\n", last_include)
    return content[:line_end + 1] + include + "\n" + content[line_end + 1:]


TARGET_FILES = [
    ("third_party/blink/renderer/modules/webgl/"
     "webgl_rendering_context_base.cc",
     "WebGL1"),
    ("third_party/blink/renderer/modules/webgl/"
     "webgl2_rendering_context_base.cc",
     "WebGL2"),
]

for fpath, label in TARGET_FILES:
    path = Path(fpath)
    if not path.exists():
        print(f"⚠️  {fpath} not found — {label} patch skipped")
        continue

    content = path.read_text()
    if "stealth::GPUSpoof" in content:
        print(f"⏭️  {label}: already patched — skipped")
        continue

    content = add_include(content, STEALTH_INCLUDE)

    applied = 0
    for old, new, what in REPLACEMENTS:
        count = content.count(old)
        if count == 0:
            print(f"⚠️  {label}: marker not found: {what}")
            continue
        content = content.replace(old, new)
        applied += count
        print(f"✅ {label}: {what} wrapped (x{count})")

    if applied:
        path.write_text(content)
        print(f"✅ {label}: {applied} leak point(s) wrapped")

print("\nℹ️  Masked GL_VENDOR/GL_RENDERER already return the "
      "constants \"WebKit\"/\"WebKit WebGL\" (stock behavior, "
      "nothing to spoof)")
print("ℹ️  Unset STEALTH_GPU_* env vars pass real values through "
      "unchanged")

print("\n✅ WebGL patches complete")
print("   ✅ stealth_webgl.h (header-only, env-driven)")
print("   ✅ Unmasked vendor/renderer spoofed")
print("   ✅ GL_VERSION / GLSL version segments spoofed")
PYEOF

PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
"$PYTHON_BIN" /tmp/webgl_patch.py
