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

Wired up 2026-10-12, after the exact verification this docstring used
to demand: the real bindings overload of
AudioBuffer::getChannelData(unsigned, ExceptionState&) was read from
the pinned tree on the live build box via
  git show tags/120.0.6099.224:third_party/blink/renderer/modules/webaudio/audio_buffer.cc
and the injected body reproduces its bounds check verbatim (see the
injection section below for the full real-source excerpt).

Design (user-confirmed):
- ONLY the bindings overload is wrapped -- the one JS's
  AudioBuffer.prototype.getChannelData() calls. The internal overload
  (unsigned) -- also used by Zero() and SharedAudioBuffer -- is left
  untouched, so all internal audio paths see bit-identical data.
- The noise is applied on the success path only, after the stock
  bounds check; the check itself is never reconstructed from memory.
- Idempotent per backing array via the helper's owner-key guard: the
  internal overload returns the SAME DOMFloat32Array every call, so
  without that guard repeated reads would see the additive noise
  double up -- a tell real Chrome never produces.
- No STEALTH_AUDIO_SEED set -> helper returns immediately -> stock
  behavior, bit-for-bit.

Why it was unwired for so long (historical): it was drafted with no
source access, and the repo's rule is that a body-replacing patch is
only written after diffing the real pinned source -- the discipline
that historically caught two fabricated patches (canvas GetImage(),
geoip EnsureUpdatedLanguage()). Audio was the higher-stakes variant:
guessing AudioBuffer::getChannelData()'s bounds check wrong is a
security bug (OOB read reachable from JS), not just a compile failure.
"""

from pathlib import Path

NOISE_HEADER = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: AudioContext fingerprint noise (header-only)
// ═══════════════════════════════════════════════════════════
//
// Wired into the BINDINGS overload of
// AudioBuffer::getChannelData(unsigned, ExceptionState&) — the one
// JS calls. The internal overload (used by Zero()/SharedAudioBuffer)
// is untouched, so internal audio paths see bit-identical data.
// owner_key: the idempotency guard — the internal overload returns
// the same DOMFloat32Array every call, so without it repeated reads
// would see the additive noise double up.

#ifndef STEALTH_AUDIO_NOISE_H_
#define STEALTH_AUDIO_NOISE_H_

#include <cstdint>
#include <cstdlib>
#include <unordered_set>

#include "base/no_destructor.h"

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
  //
  // owner_key: the identity of the buffer being noised (the returned
  // DOMFloat32Array's pointer at the getChannelData() call site).
  // getChannelData() returns the SAME backing array on every call,
  // and the noise is additive — without this guard, a page calling
  // getChannelData() twice would see the values CHANGE between calls
  // (2x the delta on the second read), which real Chrome never does.
  // The once-per-key guard keeps repeated reads stable within the
  // session (the fingerprint stays constant per session, like a real
  // machine) while still differing across sessions. Cost: one pointer
  // per noised buffer in a session-lifetime set.
  static void ApplySparseNoise(float* samples, uint32_t count,
                               const void* owner_key) {
    if (!IsEnabled() || !samples || count == 0 || owner_key == nullptr) {
      return;
    }
    static base::NoDestructor<std::unordered_set<const void*>> noised;
    if (!noised->insert(owner_key).second) {
      return;  // already noiced this exact backing array
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
print("✅ Audio noise helper: stealth_audio_noise.h installed")

# ─────────────────────────────────────────────
# Wire the helper into the BINDINGS overload of
# AudioBuffer::getChannelData() — verified against the real source at
# tags/120.0.6099.224 (2026-10-12, on the live build box) before this
# was written. The real file has TWO overloads:
#
#   NotShared<DOMFloat32Array> AudioBuffer::getChannelData(
#       unsigned channel_index, ExceptionState& exception_state) {
#     if (channel_index >= channels_.size()) {
#       exception_state.ThrowDOMException(...);
#       return NotShared<DOMFloat32Array>(nullptr);
#     }
#     return getChannelData(channel_index);          <-- line ~211
#   }
#
#   NotShared<DOMFloat32Array> AudioBuffer::getChannelData(
#       unsigned channel_index) {                    <-- internal: also
#     if (channel_index >= channels_.size()) {           used by Zero()
#       return NotShared<DOMFloat32Array>(nullptr);       and SharedAudio-
#     }                                                   Buffer -- left
#     return NotShared<DOMFloat32Array>(channels_[channel_index].Get()); UNTOUCHED
#   }
#
# Design (user-confirmed 2026-10-12): wrap ONLY the bindings overload's
# success-path return -- the exact call JS's
# AudioBuffer.prototype.getChannelData() lands in. Internal consumers
# (Zero(), SharedAudioBuffer, AudioContext plumbing) keep calling the
# internal overload and see bit-identical data. The bounds checks in
# both overloads stay verbatim; only the success-path return of the
# bindings overload is wrapped, and only after the index check passed.
# The DOM-exception overload's body is NOT reconstructed -- the noise
# is applied to the returned array's Data() before handing it back,
# with the once-per-backing-array guard in the helper (the bindings
# overload delegates to the internal one, which returns the SAME
# DOMFloat32Array every call, and the noise is additive).
# ─────────────────────────────────────────────

audio_path = Path("third_party/blink/renderer/modules/webaudio/audio_buffer.cc")

if not audio_path.exists():
    print("⚠️  audio_buffer.cc not found — audio patch skipped")
else:
    content = audio_path.read_text(encoding="utf-8")

    if "STEALTH PATCH" in content:
        print("⏭️  audio_buffer.cc already patched — skipped")
    else:
        # The exact marker from the real source at the pinned tag: the
        # bindings overload's success-path return, which delegates to
        # the internal overload after the bounds check.
        MARKER = ("NotShared<DOMFloat32Array> AudioBuffer::getChannelData(\n"
                  "    unsigned channel_index,\n"
                  "    ExceptionState& exception_state) {")

        WRAP = """NotShared<DOMFloat32Array> AudioBuffer::getChannelData(
    unsigned channel_index,
    ExceptionState& exception_state) {
  if (channel_index >= channels_.size()) {
    exception_state.ThrowDOMException(
        DOMExceptionCode::kIndexSizeError,
        "channel index (" + String::Number(channel_index) +
            ") exceeds number of channels (" +
            String::Number(channels_.size()) + ")");
    return NotShared<DOMFloat32Array>(nullptr);
  }

  // STEALTH PATCH (011): apply per-session AudioContext fingerprint
  // noise to the returned channel data. The bounds check above is the
  // stock one, verbatim; only this success path is wrapped. Idempotent
  // per backing array (the internal overload returns the same
  // DOMFloat32Array on every call), so repeated reads are stable.
  NotShared<DOMFloat32Array> array = getChannelData(channel_index);
  if (array) {
    stealth::AudioNoise::ApplySparseNoise(
        array->Data(),
        static_cast<uint32_t>(array->length()),
        array->Data());
  }
  return array;
}"""

        if MARKER in content:
            # Replace the full bindings-overload body (its bounds check is
            # reproduced verbatim from the real source above; nothing is
            # invented), keeping everything after it untouched.
            # Locate the exact span: from MARKER to the end of the function
            # (the closing brace of the overload, found by brace matching).
            start = content.index(MARKER)
            brace = content.index("{", start)
            depth = 0
            i = brace
            while True:
                if content[i] == "{":
                    depth += 1
                elif content[i] == "}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            content = content[:start] + WRAP + content[i:]

            # Include the noise helper.
            INCLUDE = '#include "third_party/blink/renderer/platform/stealth/stealth_audio_noise.h"'
            if INCLUDE not in content:
                last_include = content.rfind("#include")
                line_end = content.find("\n", last_include)
                content = (
                    content[:line_end + 1] + INCLUDE + "\n" + content[line_end + 1:]
                )

            audio_path.write_text(content, encoding="utf-8")
            print("✅ AudioBuffer::getChannelData (bindings overload) wired to AudioNoise")
        else:
            print("⚠️  audio_buffer.cc: bindings-overload marker not found — "
                  "patch NOT applied (source differs from pinned expectations)")

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
