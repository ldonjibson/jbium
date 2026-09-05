"""
════════════════════════════════════════════════════════════
Device Generator
════════════════════════════════════════════════════════════

Generates realistic device fingerprints based on:
- Real hardware configurations
- GeoIP OS distribution
- Region-appropriate screen resolutions

Ensures all signals are internally consistent.
"""

import hashlib
import json
import random
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class DeviceProfile:
    """Complete, internally consistent device fingerprint"""
    
    # Operating System
    os: str
    os_version: str
    platform: str
    architecture: str
    bitness: str
    
    # Hardware
    cpu_cores: int
    cpu_model: str
    ram_gb: int
    gpu_vendor: str
    gpu_renderer: str
    
    # Display
    screen_width: int
    screen_height: int
    available_width: int
    available_height: int
    color_depth: int
    device_pixel_ratio: float
    refresh_rate: int
    
    # Capabilities
    touch_support: bool
    max_touch_points: int
    
    # Browser
    user_agent: str
    ua_platform: str
    ua_platform_version: str
    
    # Fingerprint seeds
    canvas_seed: int
    webgl_seed: int
    audio_seed: int
    
    # Metadata
    profile_name: str
    template_used: str


class DeviceGenerator:
    """
    Generates device profiles that are:
    1. Internally consistent (all signals match)
    2. Realistic (based on actual hardware configurations)
    3. GeoIP-appropriate (matches OS distribution for the region)
    """
    
    def __init__(self, templates_path: str = "config/fingerprints.json"):
        self.templates_path = Path(templates_path)
        self.templates = self._load_templates()
        
        logger.info(f"DeviceGenerator initialized")
        logger.info(f"  Templates: {len(self.templates.get('templates', {}))} profiles")
    
    def _load_templates(self) -> dict:
        """Load device templates"""
        
        if self.templates_path.exists():
            with open(self.templates_path) as f:
                return json.load(f)
        
        # Minimal fallback
        logger.warning(f"Templates not found: {self.templates_path}")
        return {
            "templates": {},
            "chrome_versions": [
                {"major": 120, "minor": 0, "build": 6099, "patch": "109"}
            ],
            "user_agent_templates": {
                "Windows": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{full_version} Safari/537.36",
            }
        }
    
    def generate(
        self,
        geo_profile,
        preferred_template: Optional[str] = None,
    ) -> DeviceProfile:
        """
        Generate a complete device profile.
        
        Args:
            geo_profile: GeoProfile from GeoIPResolver
            preferred_template: Optional specific template name
            
        Returns:
            DeviceProfile with all consistent values
        """
        
        # Select template
        template = self._select_template(geo_profile, preferred_template)
        template_name = template.get("_name", "unknown")
        
        logger.info(f"Selected template: {template_name}")
        
        # Random hardware choices from template
        cpu = random.choice(template["cpu_options"])
        ram = random.choice(template["device_memory"])
        gpu = random.choice(template["gpu_options"])
        screen = random.choice(template["screen_options"])
        
        # Chrome version
        chrome_version = self._pick_chrome_version()
        full_version = f"{chrome_version['major']}.{chrome_version['minor']}.{chrome_version['build']}.{chrome_version['patch']}"
        
        # User-Agent
        ua_template = self.templates.get("user_agent_templates", {}).get(
            template["ua_platform"], 
            self.templates["user_agent_templates"]["Windows"]
        )
        user_agent = ua_template.replace("{full_version}", full_version)
        
        # Calculate available screen size
        offset = template.get("available_offset", {"w": 0, "h": 40})
        available_w = screen["w"] - offset["w"]
        available_h = screen["h"] - offset["h"]
        
        # Generate seeds
        session_seed = random.randint(1000000, 9999999)
        canvas_seed = int(hashlib.md5(
            f"{session_seed}-canvas".encode()
        ).hexdigest()[:8], 16)
        webgl_seed = int(hashlib.md5(
            f"{session_seed}-webgl".encode()
        ).hexdigest()[:8], 16)
        audio_seed = int(hashlib.md5(
            f"{session_seed}-audio".encode()
        ).hexdigest()[:8], 16)
        
        # Build profile
        profile = DeviceProfile(
            # OS
            os=template["os"],
            os_version=template.get("ua_platform_version", "10.0.0"),
            platform=template["platform"],
            architecture=template["architecture"],
            bitness=template["bitness"],
            
            # Hardware
            cpu_cores=cpu["cores"],
            cpu_model=cpu["model"],
            ram_gb=min(ram, 8),  # navigator.deviceMemory caps at 8
            gpu_vendor=gpu["vendor"],
            gpu_renderer=gpu["renderer"],
            
            # Display
            screen_width=screen["w"],
            screen_height=screen["h"],
            available_width=available_w,
            available_height=available_h,
            color_depth=24,
            device_pixel_ratio=screen["dpr"],
            refresh_rate=screen.get("rate", 60),
            
            # Capabilities
            touch_support=template.get("touch", False),
            max_touch_points=10 if template.get("touch", False) else 0,
            
            # Browser
            user_agent=user_agent,
            ua_platform=template["ua_platform"],
            ua_platform_version=random.choice(
                template.get("ua_platform_versions", ["10.0.0"])
            ),
            
            # Seeds
            canvas_seed=canvas_seed,
            webgl_seed=webgl_seed,
            audio_seed=audio_seed,
            
            # Metadata
            profile_name=f"{template_name}_{session_seed}",
            template_used=template_name,
        )
        
        logger.info(f"Generated device: {profile.os} | {profile.cpu_model}")
        logger.info(f"  Screen: {profile.screen_width}x{profile.screen_height} @ {profile.device_pixel_ratio}x")
        logger.info(f"  GPU: {profile.gpu_renderer}")
        logger.info(f"  UA: {user_agent[:60]}...")
        
        return profile
    
    def _select_template(
        self,
        geo_profile,
        preferred: Optional[str],
    ) -> dict:
        """
        Select appropriate device template.
        
        Weighted by:
        1. OS distribution in the GeoIP country
        2. Template's base probability
        3. Regional compatibility
        """
        
        templates = self.templates.get("templates", {})
        
        if preferred and preferred in templates:
            result = templates[preferred]
            result["_name"] = preferred
            return result
        
        # Get OS distribution for this country
        os_dist = getattr(geo_profile, "os_distribution", {}) or {
            "Windows": 0.70, "macOS": 0.20, "Linux": 0.05
        }
        
        # Get compatible templates for this region
        country_code = getattr(geo_profile, "country_code", "US")
        
        weighted = []
        
        for name, tmpl in templates.items():
            # Check regional compatibility
            compatible_regions = tmpl.get("compatible_regions", ["all"])
            if "all" not in compatible_regions and country_code not in compatible_regions:
                continue
            
            # Get OS weight
            template_os = tmpl["os"]
            if "Windows" in template_os:
                os_weight = os_dist.get("Windows", 0.7)
            elif "macOS" in template_os:
                os_weight = os_dist.get("macOS", 0.2)
            elif "Linux" in template_os:
                os_weight = os_dist.get("Linux", 0.05)
            else:
                os_weight = 0.05
            
            # Combined weight
            weight = tmpl.get("probability", 0.1) * (os_weight * 10)
            
            weighted.append((tmpl, weight, name))
        
        if not weighted:
            # Fallback: use first template
            first_name = list(templates.keys())[0]
            result = templates[first_name]
            result["_name"] = first_name
            return result
        
        # Weighted random selection
        template_list = [t for t, w, n in weighted]
        weights = [w for t, w, n in weighted]
        names = [n for t, w, n in weighted]
        
        idx = random.choices(range(len(template_list)), weights=weights, k=1)[0]
        
        result = template_list[idx]
        result["_name"] = names[idx]
        return result
    
    def _pick_chrome_version(self) -> dict:
        """Pick a Chrome version weighted by market share"""
        
        versions = self.templates.get("chrome_versions", [
            {"major": 120, "minor": 0, "build": 6099, "patch": "109", "weight": 1.0}
        ])
        
        weights = [v.get("weight", 1.0) for v in versions]
        
        return random.choices(versions, weights=weights, k=1)[0]
