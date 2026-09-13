"""
════════════════════════════════════════════════════════════
Fingerprint Manager
════════════════════════════════════════════════════════════

Manages fingerprint state:
- Generates unique seeds for canvas/webgl/audio noise
- Tracks fingerprint consistency within a session
- Rotates fingerprints between sessions
"""

import hashlib
import json
import random
import time
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class FingerprintSeeds:
    """Seeds for noise generation. Must be consistent within a session."""
    
    session_id: str
    canvas_seed: int
    webgl_seed: int
    audio_seed: int
    client_rects_seed: int
    font_metrics_seed: int
    created_at: float
    
    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "canvas_seed": self.canvas_seed,
            "webgl_seed": self.webgl_seed,
            "audio_seed": self.audio_seed,
            "client_rects_seed": self.client_rects_seed,
            "font_metrics_seed": self.font_metrics_seed,
            "created_at": self.created_at,
        }


class FingerprintManager:
    """
    Manages fingerprint generation and consistency.
    
    A "fingerprint" in this context means:
    - The unique noise seeds applied to canvas/webgl/audio
    - These must be consistent within a single browsing session
    - They should be different between sessions
    
    This prevents:
    - Canvas hash tracking across sessions
    - WebGL fingerprint matching
    - AudioContext fingerprint persistence
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self._session_seeds: Dict[str, FingerprintSeeds] = {}
        self._current_session: Optional[str] = None
        
        logger.info("FingerprintManager initialized")
    
    def _load_config(self, path: Optional[str]) -> dict:
        """Load configuration"""
        
        defaults = {
            "noise_level": 0.5,
            "seed_rotation": "per_session",
            "persist_seeds": False,
            "seeds_file": "./data/fingerprint_seeds.json",
        }
        
        if path and Path(path).exists():
            with open(path) as f:
                config = json.load(f)
                defaults.update(config)
        
        return defaults
    
    def create_session(self, session_id: Optional[str] = None) -> FingerprintSeeds:
        """
        Create a new fingerprint session with unique seeds.
        
        Args:
            session_id: Optional custom session ID
            
        Returns:
            FingerprintSeeds with all noise seeds
        """
        
        if session_id is None:
            session_id = f"fp_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        
        # Generate seeds
        # These should be different for each session
        # but deterministic if we need to resume a session
        
        base_seed = random.randint(1000000, 9999999)
        
        # Derive related seeds from base
        # (so they're all unique but related to the session)
        canvas_seed = int(hashlib.md5(
            f"{base_seed}-canvas".encode()
        ).hexdigest()[:8], 16)
        
        webgl_seed = int(hashlib.md5(
            f"{base_seed}-webgl".encode()
        ).hexdigest()[:8], 16)
        
        audio_seed = int(hashlib.md5(
            f"{base_seed}-audio".encode()
        ).hexdigest()[:8], 16)
        
        client_rects_seed = int(hashlib.md5(
            f"{base_seed}-rects".encode()
        ).hexdigest()[:8], 16)
        
        font_metrics_seed = int(hashlib.md5(
            f"{base_seed}-fonts".encode()
        ).hexdigest()[:8], 16)
        
        seeds = FingerprintSeeds(
            session_id=session_id,
            canvas_seed=canvas_seed,
            webgl_seed=webgl_seed,
            audio_seed=audio_seed,
            client_rects_seed=client_rects_seed,
            font_metrics_seed=font_metrics_seed,
            created_at=time.time(),
        )
        
        self._session_seeds[session_id] = seeds
        self._current_session = session_id
        
        logger.info(f"Created fingerprint session: {session_id}")
        logger.debug(f"  Canvas seed: {canvas_seed}")
        logger.debug(f"  WebGL seed: {webgl_seed}")
        logger.debug(f"  Audio seed: {audio_seed}")
        
        return seeds
    
    def get_current_seeds(self) -> Optional[FingerprintSeeds]:
        """Get seeds for current session"""
        
        if self._current_session:
            return self._session_seeds.get(self._current_session)
        return None
    
    def get_seeds(self, session_id: str) -> Optional[FingerprintSeeds]:
        """Get seeds for a specific session"""
        
        return self._session_seeds.get(session_id)
    
    def rotate(self) -> FingerprintSeeds:
        """
        Rotate to a new fingerprint session.
        Called when you want a completely new identity.
        """
        
        old_session = self._current_session
        logger.info(f"Rotating fingerprint (old: {old_session})")
        
        return self.create_session()
    
    def generate_canvas_noise(self, width: int, height: int, seed: int) -> list:
        """
        Generate canvas noise for a given canvas size.
        Returns a list of (x, y, noise_value) tuples.
        
        This is used by the driver to pre-compute noise
        if the browser doesn't handle it internally.
        """
        
        noise_level = self.config.get("noise_level", 0.5)
        num_pixels = max(1, int(width * height * noise_level * 0.001))
        
        noise = []
        random.seed(seed)
        
        for _ in range(num_pixels):
            x = random.randint(0, width - 1)
            y = random.randint(0, height - 1)
            value = random.randint(-2, 2)  # Subtle blue channel change
            noise.append((x, y, value))
        
        return noise
    
    def save_state(self):
        """Persist seed state (for resuming sessions)"""
        
        if not self.config.get("persist_seeds"):
            return
        
        path = Path(self.config["seeds_file"])
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "current_session": self._current_session,
            "sessions": {
                sid: seeds.to_dict() 
                for sid, seeds in self._session_seeds.items()
            }
        }
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Seeds saved to {path}")
    
    def load_state(self):
        """Load persisted seed state"""
        
        path = Path(self.config.get("seeds_file", ""))
        
        if not path.exists():
            return
        
        with open(path) as f:
            data = json.load(f)
        
        self._current_session = data.get("current_session")
        
        for sid, seed_data in data.get("sessions", {}).items():
            self._session_seeds[sid] = FingerprintSeeds(**seed_data)
        
        logger.info(f"Loaded {len(self._session_seeds)} sessions from {path}")
