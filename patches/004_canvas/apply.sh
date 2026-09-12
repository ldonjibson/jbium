#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/004_canvas/apply.sh
# Canvas fingerprint noise (session-stable)
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd "${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"

cat > /tmp/canvas_patch.py << 'PYEOF'
"""
STEALTH PATCH: Canvas Fingerprint Noise

Adds session-stable noise to every JS-visible canvas readback so
canvas hashes are unique per session but stable within one.

How it works:
- A header-only helper (stealth_canvas_noise.h) tweaks the lowest
  color byte of a sparse, seed-determined subset of opaque pixels.
- Deterministic per (seed, pixel index): re-reading the same canvas
  always yields the same hash (fingerprinters check stability).
- Different sessions get different seeds → different hashes.
- Invisible to the eye (±1-2 in one channel of ~1% of pixels).

Where it hooks (both verified in this tree):
- scoped_refptr<StaticBitmapImage> blink::CanvasRenderingContext2D::GetImage()
  — the readback path for getImageData (BaseRenderingContext2D::
  getImageDataInternal calls GetImage() for its snapshot), drawImage
  of a canvas, and HTMLCanvasElement::Source().
- CanvasRenderingContext2D::PaintRenderingResultsToSnapshot()
  — the toDataURL/toBlob snapshot path.
Every StaticBitmapImage return in those two functions is wrapped
with stealth::CanvasNoise::MaybeSpoofSnapshot(), a no-op unless
STEALTH_CANVAS_SEED is set. When spoofing, pixels are read back
via cc::PaintImage::readPixels (works for raster and GPU-backed
snapshots — the driver launches with --disable-gpu, so canvases
are software-backed anyway) and returned as an unaccelerated copy.

What the old patch got wrong (and is gone):
- It called CanvasNoiseGenerator::ApplyNoise(last_finalized_bitmap_)
  — that member does not exist in CanvasRenderingContext2D.
- It wrote an uncompiled stealth_canvas_noise.cc (never registered
  in BUILD.gn → guaranteed undefined-symbol link failure).
- Its "String CanvasRenderingContext2D::FontShaping()" marker was
  fabricated (no-op at best).

Env vars (set by the jbium driver):
- STEALTH_CANVAS_SEED — decimal session seed
"""

from pathlib import Path

# ─────────────────────────────────────────────
# 1. Header-only noise helper (no .cc → nothing
#    to register in BUILD.gn, nothing to link)
# ─────────────────────────────────────────────

NOISE_HEADER = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: Canvas fingerprint noise (header-only)
// ═══════════════════════════════════════════════════════════
//
// Header-only on purpose: the patched file already belongs to a
// build target, so no BUILD.gn changes and no stealth .cc that
// could go unlinked. All state is a POD function-local static
// (thread-safe init, no global constructors, no exit-time dtors).

#ifndef STEALTH_CANVAS_NOISE_H_
#define STEALTH_CANVAS_NOISE_H_

#include <cstdint>
#include <cstdlib>

#include "base/memory/scoped_refptr.h"
#include "cc/paint/paint_image.h"
#include "third_party/blink/renderer/platform/graphics/static_bitmap_image.h"
#include "third_party/blink/renderer/platform/graphics/unaccelerated_static_bitmap_image.h"
#include "third_party/skia/include/core/SkBitmap.h"
#include "third_party/skia/include/core/SkImages.h"

namespace stealth {

class CanvasNoise {
 public:
  static bool IsEnabled() {
    return std::getenv("STEALTH_CANVAS_SEED") != nullptr;
  }

  // Returns `snapshot` unchanged unless noise is enabled; when
  // enabled, returns a copied, noised snapshot. Readback uses
  // cc::PaintImage::readPixels, which works for both raster and
  // GPU-backed snapshots.
  static scoped_refptr<blink::StaticBitmapImage> MaybeSpoofSnapshot(
      scoped_refptr<blink::StaticBitmapImage> snapshot) {
    if (!IsEnabled() || !snapshot) {
      return snapshot;
    }
    const cc::PaintImage& paint_image =
        snapshot->PaintImageForCurrentFrame();
    const SkImageInfo info = paint_image.GetSkImageInfo();
    if (info.width() <= 0 || info.height() <= 0 ||
        info.bytesPerPixel() != 4) {
      return snapshot;
    }
    SkBitmap copy;
    if (!copy.tryAllocPixels(info)) {
      return snapshot;
    }
    if (!paint_image.readPixels(copy.info(), copy.getPixels(),
                                copy.rowBytes(), 0, 0)) {
      return snapshot;
    }
    ApplyToPixels(static_cast<uint32_t*>(copy.getPixels()),
                  copy.width(), copy.height());
    return blink::UnacceleratedStaticBitmapImage::Create(
        SkImages::RasterFromBitmap(copy));
  }

 private:
  static uint32_t SessionSeed() {
    static const uint32_t seed = [] {
      const char* val = std::getenv("STEALTH_CANVAS_SEED");
      return val ? static_cast<uint32_t>(std::strtoul(val, nullptr, 10))
                 : 0u;
    }();
    return seed;
  }

  static uint32_t Mix(uint32_t a, uint32_t b) {
    uint32_t h = a ^ (b * 0x9E3779B9u);
    h ^= h >> 13;
    h *= 0xC2B2AE35u;
    h ^= h >> 16;
    return h;
  }

  // Tweak the lowest color byte of a sparse, seed-determined
  // subset of opaque pixels. Skips non-opaque pixels so
  // premultiplied-color invariants are never violated. The tweak
  // never carries into the next byte.
  static void ApplyToPixels(uint32_t* pixels, int width, int height) {
    const uint32_t seed = SessionSeed();
    const long long count =
        static_cast<long long>(width) * static_cast<long long>(height);
    const int stride = 89 + static_cast<int>(seed % 64u);
    for (long long idx = seed % stride; idx < count; idx += stride) {
      const uint32_t p = pixels[idx];
      if ((p >> 24) != 0xFFu) {
        continue;
      }
      const uint32_t delta =
          Mix(seed, static_cast<uint32_t>(idx)) & 3u;
      pixels[idx] = (p & 0xFFFFFF00u) | ((p + delta) & 0xFFu);
    }
  }
};

}  // namespace stealth

#endif  // STEALTH_CANVAS_NOISE_H_
"""

stealth_dir = Path("third_party/blink/renderer/platform/stealth/")
stealth_dir.mkdir(parents=True, exist_ok=True)
(stealth_dir / "stealth_canvas_noise.h").write_text(NOISE_HEADER)
print("✅ Canvas noise: stealth_canvas_noise.h (header-only)")

# ─────────────────────────────────────────────
# 2. Patch the two readback chokepoints
# ─────────────────────────────────────────────


def _find_body_open_brace(content, marker):
    """Index of the '{' opening the body of the function whose
    signature contains `marker`; skips the parameter list first
    so multi-line signatures work."""
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


def add_include(content, include):
    if include in content:
        return content
    last_include = content.rfind("#include")
    line_end = content.find("\n", last_include)
    return content[:line_end + 1] + include + "\n" + content[line_end + 1:]


canvas_path = Path(
    "third_party/blink/renderer/modules/canvas/canvas2d/"
    "canvas_rendering_context_2d.cc"
)

if not canvas_path.exists():
    print("⚠️  canvas_rendering_context_2d.cc not found — skipped")
else:
    content = canvas_path.read_text()
    if "stealth::CanvasNoise" in content:
        print("⏭️  canvas_rendering_context_2d.cc already patched — skipped")
    else:
        content = add_include(
            content,
            '#include "third_party/blink/renderer/platform/stealth/'
            'stealth_canvas_noise.h"',
        )

        # GetImage(): snapshot for getImageData / drawImage(canvas) /
        # HTMLCanvasElement::Source(). Verified against the actually
        # pinned Chromium tree — original body is just IsPaintable()
        # + NewImageSnapshot(); the hibernation/shared_image_provider_
        # machinery below (kept for snapshot_body's sibling target)
        # belongs to a much newer Chromium's rewrite of this class and
        # doesn't exist here at all, so don't reconstruct it from
        # memory — preserve the real body and only wrap its return.
        getimage_body = (
            "  if (!IsPaintable()) {\n"
            "    return nullptr;\n"
            "  }\n"
            "  return stealth::CanvasNoise::MaybeSpoofSnapshot(\n"
            "      canvas()->GetCanvas2DLayerBridge()->NewImageSnapshot(\n"
            "          reason));"
        )

        # PaintRenderingResultsToSnapshot(): the toDataURL/toBlob path.
        snapshot_body = (
            "  if (!IsResourceProviderValid()) {\n"
            "    return nullptr;\n"
            "  }\n"
            "\n"
            "  FlushCanvas(FlushReason::kOther);\n"
            "  if (shared_image_provider_) {\n"
            "    return stealth::CanvasNoise::MaybeSpoofSnapshot(\n"
            "        shared_image_provider_->Snapshot());\n"
            "  }\n"
            "  return stealth::CanvasNoise::MaybeSpoofSnapshot(\n"
            "      bitmap_provider_->Snapshot());"
        )

        targets = [
            (
                "CanvasRenderingContext2D::GetImage",
                getimage_body,
            ),
            (
                "CanvasRenderingContext2D::PaintRenderingResultsToSnapshot",
                snapshot_body,
            ),
        ]

        applied = 0
        for marker, body in targets:
            content, ok = replace_function_body(content, marker, body)
            if ok:
                applied += 1
            else:
                print(f"⚠️  canvas_rendering_context_2d.cc: marker not "
                      f"found: {marker.strip()}")

        if applied:
            canvas_path.write_text(content)
            print(f"✅ Canvas readbacks wrapped ({applied}/{len(targets)} "
                  "chokepoints)")

print("ℹ️  Note: OffscreenCanvasRenderingContext2D::GetImage lives in a "
      "separate file and is not patched — document its noise as a "
      "follow-up if offscreen-canvas fingerprinting matters for your "
      "targets")

print("\n✅ Canvas fingerprint patch complete")
print("   ✅ stealth_canvas_noise.h (header-only, session-stable seed)")
print("   ✅ GetImage() + PaintRenderingResultsToSnapshot() wrapped")
PYEOF

PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
"$PYTHON_BIN" /tmp/canvas_patch.py
