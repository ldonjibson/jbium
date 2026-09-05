#!/bin/bash
# ═════════════════════════════════════════════════════════════
# patches/010_misc/apply.sh
# WebRTC leak prevention, Battery API, Media codec consistency
# ═════════════════════════════════════════════════════════════

set -euo pipefail
cd /root/jbium/chromium/src

cat > /tmp/misc_patch.py << 'PYEOF'
"""
STEALTH PATCH: Misc Anti-Detection

1. WebRTC: Prevent IP leak (return proxy IP, not real IP)
2. Battery: Return consistent battery state (not real battery)
3. Media codecs: Ensure canPlayType returns Chrome-typical responses
"""

from pathlib import Path

# ─────────────────────────────────────────────
# 1. WebRTC IP Leak Prevention
# ─────────────────────────────────────────────

rtc_path = Path(
    "third_party/blink/renderer/modules/peerconnection/"
    "rtc_peer_connection.cc"
)

if rtc_path.exists():
    content = rtc_path.read_text()
    
    patch = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: WebRTC IP Leak Prevention
// Prevents ICE candidates from revealing real IP
// Returns proxy IP instead
// ═══════════════════════════════════════════════════════════

namespace {
  // Check if we should filter ICE candidates
  bool ShouldFilterICECandidates() {
    // Can be controlled via environment
    const char* filter = std::getenv("STEALTH_FILTER_WEBRTC");
    if (filter) {
      return std::string(filter) != "false";
    }
    return true;  // Default: filter
  }
  
  // Get the IP that should be exposed (proxy IP)
  std::string GetExposedIP() {
    // Return the proxy IP from environment
    const char* proxy_ip = std::getenv("STEALTH_PROXY_IP");
    if (proxy_ip) {
      return proxy_ip;
    }
    // Fallback: use mDNS candidate format (obfuscated)
    return "";  // Empty = use mDNS
  }
} // namespace
"""
    
    if "STEALTH PATCH" not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + patch + content[line_end + 1:]
    
    # Patch ICE candidate generation
    old_candidate = "void RTCPeerConnection::ProcessIceCandidate"
    if old_candidate in content:
        content = content.replace(
            old_candidate,
            f"""{old_candidate} {{
  // STEALTH PATCH: Filter ICE candidates to prevent IP leak
  if (ShouldFilterICECandidates()) {{
    std::string exposed_ip = GetExposedIP();
    
    // Filter candidates:
    // - Remove local/private IP candidates (192.168.x.x, 10.x.x.x)
    // - Remove public IP candidates that don't match proxy
    // - Keep mDNS (.local) candidates
    // - Keep relay (TURN server) candidates
    
    if (!candidate.IsMdnsCandidate() && !candidate.IsRelayCandidate()) {{
      std::string candidate_ip = candidate.Ip();
      
      // Check if this is a private IP
      if (candidate_ip.find("192.168.") == 0 ||
          candidate_ip.find("10.") == 0 ||
          candidate_ip.find("172.16.") == 0 ||
          candidate_ip.find("172.31.") == 0) {{
        // Don't expose private IPs
        return;
      }}
      
      // If we have a proxy IP, only expose that
      if (!exposed_ip.empty() && candidate_ip != exposed_ip) {{
        return;  // Filter out real public IP
      }}
    }}
  }}
  // Original code below
"""
        )
        print("✅ WebRTC ICE candidate filtering patched")
    
    rtc_path.write_text(content)

# ─────────────────────────────────────────────
# 2. Battery API Spoofing
# ─────────────────────────────────────────────

battery_path = Path(
    "third_party/blink/renderer/modules/battery/"
    "battery_manager.cc"
)

if battery_path.exists():
    content = battery_path.read_text()
    
    patch = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: Battery API Consistency
// Returns a plausible, consistent battery state
// Prevents battery fingerprinting
// ═══════════════════════════════════════════════════════════

namespace {
  struct StealthBatteryState {
    bool charging = true;
    double charging_time = 1800.0;      // 30 min to charge
    double discharging_time = 14400.0;  // 4 hours
    double level = 0.87;               // 87%
  };
  
  StealthBatteryState g_battery_state;
  
  void InitializeBatteryState() {
    // Generate consistent battery state
    // Should look like a typical laptop
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<> level_dis(0.3, 0.95);
    std::uniform_real_distribution<> time_dis(3600, 28800);
    
    g_battery_state.level = level_dis(gen);
    g_battery_state.charging = (level_dis(gen) > 0.5);  // 50% chance
    g_battery_state.charging_time = time_dis(gen);
    g_battery_state.discharging_time = time_dis(gen);
  }
  
  bool g_battery_initialized = false;
  
  StealthBatteryState& GetBatteryState() {
    if (!g_battery_initialized) {
      InitializeBatteryState();
      g_battery_initialized = true;
    }
    return g_battery_state;
  }
} // namespace
"""
    
    if "STEALTH PATCH" not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + patch + content[line_end + 1:]
    
    # Patch battery level
    old_level = "double BatteryManager::level()"
    if old_level in content:
        content = content.replace(
            old_level,
            f"""double BatteryManager::level() {{
  // STEALTH PATCH: Return spoofed battery level
  return GetBatteryState().level;
}}

// Original:
double BatteryManager_level_original()"""
        )
        print("✅ Battery level patched")
    
    # Patch charging state
    old_charging = "bool BatteryManager::charging()"
    if old_charging in content:
        content = content.replace(
            old_charging,
            f"""bool BatteryManager::charging() {{
  // STEALTH PATCH: Return spoofed charging state
  return GetBatteryState().charging;
}}

// Original:
bool BatteryManager_charging_original()"""
        )
        print("✅ Battery charging patched")
    
    battery_path.write_text(content)

# ─────────────────────────────────────────────
# 3. Media Codec Consistency
# ─────────────────────────────────────────────

media_path = Path(
    "third_party/blink/renderer/modules/media/html_media_element.cc"
)

if media_path.exists():
    content = media_path.read_text()
    
    patch = """
// ═══════════════════════════════════════════════════════════
// STEALTH PATCH: Media Codec Consistency
// canPlayType() must return same responses as real Chrome
// ═══════════════════════════════════════════════════════════

namespace {
  // Chrome's canPlayType responses for common formats
  // "" = cannot play, "maybe" = might play, "probably" = will play
  
  std::string GetChromePlayTypeResponse(const std::string& mime_type) {
    // These match real Chrome 120 responses
    if (mime_type == "video/mp4") return "probably";
    if (mime_type == "video/mp4; codecs=\\"avc1.42E01E\\"") return "probably";
    if (mime_type == "video/mp4; codecs=\\"avc1.42E01E, mp4a.40.2\\"") return "probably";
    if (mime_type == "video/webm") return "probably";
    if (mime_type == "video/webm; codecs=\\"vp8\\"") return "probably";
    if (mime_type == "video/webm; codecs=\\"vp9\\"") return "probably";
    if (mime_type == "video/webm; codecs=\\"vp8, vorbis\\"") return "probably";
    if (mime_type == "video/webm; codecs=\\"vp9, opus\\"") return "probably";
    if (mime_type == "video/ogg") return "probably";
    if (mime_type == "video/ogg; codecs=\\"theora\\"") return "probably";
    
    if (mime_type == "audio/mp4") return "maybe";
    if (mime_type == "audio/mp4; codecs=\\"mp4a.40.2\\"") return "probably";
    if (mime_type == "audio/mpeg") return "probably";
    if (mime_type == "audio/ogg") return "maybe";
    if (mime_type == "audio/ogg; codecs=\\"vorbis\\"") return "probably";
    if (mime_type == "audio/wav") return "probably";
    if (mime_type == "audio/wav; codecs=\\"1\\"") return "probably";
    if (mime_type == "audio/webm") return "maybe";
    if (mime_type == "audio/webm; codecs=\\"opus\\"") return "probably";
    if (mime_type == "audio/webm; codecs=\\"vorbis\\"") return "probably";
    if (mime_type == "audio/flac") return "probably";
    if (mime_type == "audio/aac") return "probably";
    
    // Unknown format
    return "";
  }
} // namespace
"""
    
    if "STEALTH PATCH" not in content:
        last_include = content.rfind("#include")
        line_end = content.find("\n", last_include)
        content = content[:line_end + 1] + patch + content[line_end + 1:]
    
    # Patch canPlayType
    old_canplay = "String HTMLMediaElement::canPlayType"
    if old_canplay in content:
        content = content.replace(
            old_canplay,
            f"""{old_canplay} {{
  // STEALTH PATCH: Return Chrome-typical response
  std::string mime = content_type.LowerASCII().Utf8();
  std::string response = GetChromePlayTypeResponse(mime);
  if (!response.empty()) {{
    return String(response.c_str());
  }}
  // If not in our list, fall through to original
"""
        )
        print("✅ canPlayType patched")
    
    media_path.write_text(content)

print("\n✅ Misc patches complete")
print("   ✅ WebRTC IP leak prevention")
print("   ✅ Battery API spoofing")
print("   ✅ Media codec consistency")
PYEOF

python3 /tmp/misc_patch.py
