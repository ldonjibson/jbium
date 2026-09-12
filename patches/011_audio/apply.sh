#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/011_audio/apply.sh
# AudioContext/OfflineAudioContext fingerprint noise
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd "${CHROMIUM_SRC:-$HOME/jbium/chromium/src}"

cat > /tmp/audio_patch.py << 'PYEOF'
"""
STEALTH PATCH: AudioContext Fingerprint Noise

STATUS: header-only helper is real and safe to use as-is. The actual
source injection below is INTENTIONALLY NOT WRITTEN, on purpose —
read this before adding it.

Why this patch stops short of touching Chromium source:

Every other patch in this repo that replaces a function body was only
written after diffing the real source at the pinned tag
(`git diff tags/120.0.6099.224 -- <path>` / `git show tags/...:<path>`)
— that discipline is what caught two real, previously-shipped
fabricated patches this session (004_canvas's GetImage() and
008_geoip's EnsureUpdatedLanguage() both invented plausible-looking
C++ that didn't match the real 120.x source and failed to compile).

This patch was written with no server access to do that same check
against third_party/blink/renderer/modules/webaudio/audio_buffer.cc
(or wherever AudioBuffer::getChannelData() actually lives in this
tree). Unlike CanvasRenderingContext2D::GetImage() — which just
returns a snapshot — getChannelData() almost certainly bounds-checks
the requested channel index against the buffer's channel count before
returning. Guessing that logic wrong in a full-body replacement isn't
a compile-time risk we'd catch immediately like every other mistake
this session was — it's a silent bounds-check removal, i.e. a
potential out-of-bounds read/write reachable from ordinary JS
(`audioBuffer.getChannelData(9999)`). That is a materially worse
failure mode than "the build fails," and not one to guess at.

What IS safe and done here: the noise-generation math itself
(deterministic per-session, using STEALTH_AUDIO_SEED exactly like
STEALTH_CANVAS_SEED / STEALTH_WEBGL_SEED) doesn't depend on knowing
anything about Blink's AudioBuffer internals, so it's written as a
header-only helper now.

TO FINISH THIS PATCH once server/build access is back:
1. Confirm the real signature and body:
     git show tags/120.0.6099.224:third_party/blink/renderer/modules/webaudio/audio_buffer.cc
   Find getChannelData() (and channelData()/copyFromChannel() if
   present) and read its actual bounds-checking logic.
2. Preferred injection point: AudioBuffer::getChannelData(), wrapping
   ONLY the return statement (same technique as 004_canvas's
   GetImage() fix) — do NOT reconstruct the bounds-check, keep it
   verbatim and only wrap what it returns on the success path.
3. Apply noise via stealth::AudioNoise::MaybeSpoofChannelData() below
   to the returned DOMFloat32Array's backing storage: tiny, sparse,
   additive noise (~1e-6 magnitude, a handful of samples) — enough to
   change a naive sample-hash, inaudible in any real playback.
4. Re-run this exact patch's checks against the tag before trusting
   it, same as every other patch this session.

Until step 2-4 happen, this patch only installs the header (inert —
nothing includes or calls it yet) and prints a loud reminder. It does
NOT touch any Chromium source file, so it cannot break the build.
"""

from pathlib import Path

NOISE_HEADER = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: AudioContext fingerprint noise (header-only)
// ═══════════════════════════════════════════════════════════
//
// NOT YET WIRED UP. Nothing in the Chromium source includes this
// header yet — see patches/011_audio/apply.sh for why, and what
// needs verifying against the real pinned source before it's wired
// into AudioBuffer::getChannelData() (or wherever the real
// injection point turns out to be).

#ifndef STEALTH_AUDIO_NOISE_H_
#define STEALTH_AUDIO_NOISE_H_

#include <cstdint>
#include <cstdlib>

namespace stealth {

class AudioNoise {
 public:
  static bool IsEnabled() {
    return std::getenv("STEALTH_AUDIO_SEED") != nullptr;
  }

  // Applies tiny, deterministic-per-session additive noise to a
  // sparse subset of samples in a raw float32 PCM buffer. Magnitude
  // is far below anything audible — intended to change a naive
  // sample-hash fingerprint, not to alter perceived audio.
  static void ApplySparseNoise(float* samples, uint32_t count) {
    if (!IsEnabled() || !samples || count == 0) {
      return;
    }
    const uint32_t seed = SessionSeed();
    const uint32_t stride = 97 + (seed % 53);
    for (uint32_t i = seed % stride; i < count; i += stride) {
      const uint32_t h = Mix(seed, i);
      // (h & 3) - 1.5, scaled tiny: roughly +/-1.5e-6.
      const float delta = (static_cast<float>(h & 3u) - 1.5f) * 1e-6f;
      samples[i] += delta;
    }
  }

 private:
  static uint32_t SessionSeed() {
    static const uint32_t seed = [] {
      const char* val = std::getenv("STEALTH_AUDIO_SEED");
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
};

}  // namespace stealth

#endif  // STEALTH_AUDIO_NOISE_H_
"""

stealth_dir = Path("third_party/blink/renderer/platform/stealth/")
stealth_dir.mkdir(parents=True, exist_ok=True)
(stealth_dir / "stealth_audio_noise.h").write_text(NOISE_HEADER)
print("✅ Audio noise helper: stealth_audio_noise.h (header-only, NOT wired up yet)")

print()
print("⚠️  011_audio is intentionally incomplete.")
print("    The noise-generation helper is installed but nothing includes")
print("    or calls it — no Chromium source file was touched, so this")
print("    cannot break the build. Wiring it into")
print("    AudioBuffer::getChannelData() needs a live check against the")
print("    pinned tag's real source first (see the docstring in")
print("    patches/011_audio/apply.sh for the exact steps).")
PYEOF

PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
"$PYTHON_BIN" /tmp/audio_patch.py
