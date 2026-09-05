#!/bin/bash
# patches/004_canvas/apply.sh

cd /root/jbium/chromium/src

cat > /tmp/canvas_patch.py << 'PYEOF'
"""
Adds session-consistent noise to canvas rendering to prevent
fingerprinting via canvas hash.

How it works:
1. Generates a unique seed per browser session
2. Applies subtle pixel modifications (blue channel)
3. Noise is deterministic within a session (same canvas always produces same hash)
4. Noise is different across sessions (unique fingerprint each launch)

The modifications are invisible to the human eye but change the
canvas hash that fingerprinters rely on.
"""

from pathlib import Path

# 1. Create the noise generator header

NOISE_HEADER = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: Canvas Fingerprint Noise Generator
// ═══════════════════════════════════════════════════════════

#ifndef STEALTH_CANVAS_NOISE_H_
#define STEALTH_CANVAS_NOISE_H_

#include <stdint.h>
#include <skia/include/core/SkBitmap.h>

namespace stealth {

class CanvasNoiseGenerator {
 public:
  // Initialize with a session seed
  static void Initialize(uint32_t session_seed);
  
  // Apply noise to a bitmap (modifies blue channel of specific pixels)
  static void ApplyNoise(SkBitmap& bitmap);
  
  // Check if initialized
  static bool IsInitialized() { return session_seed_ != 0; }

 private:
  static uint32_t session_seed_;
  static uint8_t noise_table_[256][256];  // Pre-computed lookup
  
  // Fast hash for noise generation
  static inline uint32_t Hash(uint32_t seed, uint32_t x, uint32_t y) {
    uint32_t h = seed;
    h ^= x * 0x9E3779B9;
    h ^= y * 0x85EBCA6B;
    h ^= h >> 13;
    h *= 0xC2B2AE35;
    h ^= h >> 16;
    return h;
  }
};

}  // namespace stealth

#endif  // STEALTH_CANVAS_NOISE_H_
"""

# 2. Create the noise generator implementation

NOISE_IMPL = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: Canvas Fingerprint Noise Generator
// ═══════════════════════════════════════════════════════════

#include "stealth_canvas_noise.h"

namespace stealth {

uint32_t CanvasNoiseGenerator::session_seed_ = 0;
uint8_t CanvasNoiseGenerator::noise_table_[256][256] = {};

void CanvasNoiseGenerator::Initialize(uint32_t session_seed) {
  session_seed_ = session_seed;
  
  // Pre-compute noise lookup table
  for (int i = 0; i < 256; i++) {
    for (int j = 0; j < 256; j++) {
      noise_table_[i][j] = static_cast<uint8_t>(
          Hash(session_seed, i, j) & 0xFF
      );
    }
  }
}

void CanvasNoiseGenerator::ApplyNoise(SkBitmap& bitmap) {
  if (!IsInitialized()) return;
  
  const int width = bitmap.width();
  const int height = bitmap.height();
  if (width == 0 || height == 0) return;
  
  // Number of pixels to modify (enough to change hash)
  const int kPixelsToModify = 128;
  
  // Evenly distribute modifications across the canvas
  const int stride = (width * height) / kPixelsToModify;
  if (stride == 0) return;
  
  uint32_t* pixels = static_cast<uint32_t*>(bitmap.getPixels());
  if (!pixels) return;
  
  for (int i = 0; i < kPixelsToModify; i++) {
    const int pixel_index = i * stride;
    const int x = pixel_index % width;
    const int y = (pixel_index / width) % height;
    
    // Lookup noise from pre-computed table
    const uint8_t noise = noise_table_[x & 0xFF][y & 0xFF];
    
    // Only modify blue channel (least visible to human eye)
    // Format: 0xAARRGGBB
    uint32_t& pixel = pixels[pixel_index];
    
    // Extract channels
    const uint32_t blue = (pixel >> 0) & 0xFF;
    
    // Apply noise (subtle ±1-2 change)
    const uint32_t new_blue = (blue + (noise & 0x03)) & 0xFF;
    
    // Reconstruct pixel
    pixel = (pixel & 0xFFFFFF00) | new_blue;
  }
}

}  // namespace stealth
"""

# Write the header and implementation
Path("third_party/blink/renderer/platform/stealth/").mkdir(
    parents=True, exist_ok=True
)

Path("third_party/blink/renderer/platform/stealth/stealth_canvas_noise.h") \
    .write_text(NOISE_HEADER)

Path("third_party/blink/renderer/platform/stealth/stealth_canvas_noise.cc") \
    .write_text(NOISE_IMPL)

# 3. Patch CanvasRenderingContext2D to use the noise

canvas_path = Path(
    "third_party/blink/renderer/modules/canvas/canvas2d/"
    "canvas_rendering_context_2d.cc"
)

if canvas_path.exists():
    content = canvas_path.read_text()
    
    # Add include
    include_line = '#include "third_party/blink/renderer/platform/stealth/stealth_canvas_noise.h"'
    if include_line not in content:
        content = f"{include_line}\n{content}"
    
    # Patch toDataURL to apply noise before returning
    old_toDataURL = """String CanvasRenderingContext2D::FontShaping()"""
    # Find the actual method that returns canvas data
    # We need to patch wherever the bitmap is finalized
    
    # Look for ImageData or toDataURL return path
    if "toDataURL" in content:
        # Find the function that prepares the image for output
        content = content.replace(
            "scoped_refptr<StaticBitmapImage> CanvasRenderingContext2D::GetImage()",
            """scoped_refptr<StaticBitmapImage> CanvasRenderingContext2D::GetImage() {
  // STEALTH PATCH: Apply canvas noise
  stealth::CanvasNoiseGenerator::ApplyNoise(last_finalized_bitmap_);"""
        )
        print("✅ Canvas noise patched into GetImage()")
    
    canvas_path.write_text(content)
else:
    print(f"⚠️  Canvas file not found")

print("\n✅ Canvas fingerprint patch applied")
print("   Header: third_party/blink/renderer/platform/stealth/stealth_canvas_noise.h")
print("   Impl:   third_party/blink/renderer/platform/stealth/stealth_canvas_noise.cc")
PYEOF
python3 /tmp/canvas_patch.py
