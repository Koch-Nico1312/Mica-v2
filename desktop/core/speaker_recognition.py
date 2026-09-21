"""
Einfache Sprechererkennung basierend auf Audio-Fingerprinting.
Implementiert Punkt 16: Sprechererkennung.
"""
import json
import hashlib
import numpy as np
from pathlib import Path
from typing import Dict, Optional, Tuple
from collections import defaultdict
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
SPEAKER_PROFILES_PATH = BASE_DIR / "memory" / "speaker_profiles.json"


class SpeakerRecognition:
    """Einfache Sprechererkennung durch Audio-Fingerprinting."""
    
    def __init__(self):
        self.profiles = self._load_profiles()
        self.min_samples = 5  # Minimale Samples für Registrierung
        self.similarity_threshold = 0.7  # Ähnlichkeitsschwelle
    
    def _load_profiles(self) -> Dict:
        """Lade gespeicherte Sprecherprofile."""
        try:
            if SPEAKER_PROFILES_PATH.exists():
                return json.loads(SPEAKER_PROFILES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}
    
    def _save_profiles(self) -> None:
        """Speichere Sprecherprofile."""
        SPEAKER_PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
        SPEAKER_PROFILES_PATH.write_text(
            json.dumps(self.profiles, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def _extract_features(self, audio_data: np.ndarray) -> Dict:
        """Extrahiere einfache Audio-Features für Fingerprinting."""
        if len(audio_data) == 0:
            return {}
        
        # Einfache statistische Features
        features = {
            "mean": float(np.mean(audio_data)),
            "std": float(np.std(audio_data)),
            "min": float(np.min(audio_data)),
            "max": float(np.max(audio_data)),
            "rms": float(np.sqrt(np.mean(audio_data ** 2))),
            "zero_crossings": int(np.sum(np.diff(np.sign(audio_data)) != 0)),
        }
        
        # Spectral centroid approximation
        fft = np.fft.fft(audio_data)
        magnitude = np.abs(fft)
        freqs = np.fft.fftfreq(len(audio_data))
        features["spectral_centroid"] = float(np.sum(freqs * magnitude) / np.sum(magnitude))
        
        return features
    
    def _create_fingerprint(self, features: Dict) -> str:
        """Erstelle einen Hash aus den Features."""
        feature_string = json.dumps(features, sort_keys=True)
        return hashlib.sha256(feature_string.encode()).hexdigest()[:16]
    
    def _calculate_similarity(self, features1: Dict, features2: Dict) -> float:
        """Berechne Ähnlichkeit zwischen zwei Feature-Sets."""
        if not features1 or not features2:
            return 0.0
        
        similarity = 0.0
        count = 0
        
        for key in ["mean", "std", "rms", "spectral_centroid"]:
            if key in features1 and key in features2:
                val1, val2 = features1[key], features2[key]
                if val1 == 0 and val2 == 0:
                    sim = 1.0
                elif val1 == 0 or val2 == 0:
                    sim = 0.0
                else:
                    sim = 1.0 - min(abs(val1 - val2) / max(abs(val1), abs(val2)), 1.0)
                similarity += sim
                count += 1
        
        return similarity / count if count > 0 else 0.0
    
    def register_speaker(self, name: str, audio_samples: list) -> Tuple[bool, str]:
        """Registriere einen neuen Sprecher mit mehreren Audio-Samples.
        
        Args:
            name: Name des Sprechers
            audio_samples: Liste von numpy Arrays mit Audio-Daten
            
        Returns:
            (erfolg, nachricht)
        """
        if len(audio_samples) < self.min_samples:
            return False, f"Benötige mindestens {self.min_samples} Audio-Samples"
        
        # Extrahiere Features von allen Samples
        all_features = []
        for sample in audio_samples:
            if isinstance(sample, np.ndarray) and len(sample) > 0:
                features = self._extract_features(sample)
                if features:
                    all_features.append(features)
        
        if len(all_features) < self.min_samples:
            return False, "Ungültige Audio-Daten"
        
        # Erstelle Durchschnitts-Features
        avg_features = {}
        for key in all_features[0].keys():
            values = [f.get(key, 0) for f in all_features if key in f]
            if values:
                avg_features[key] = sum(values) / len(values)
        
        fingerprint = self._create_fingerprint(avg_features)
        
        # Speichere Profil
        self.profiles[name] = {
            "fingerprint": fingerprint,
            "features": avg_features,
            "sample_count": len(all_features),
            "registered": True
        }
        
        self._save_profiles()
        return True, f"Sprecher '{name}' erfolgreich registriert mit {len(all_features)} Samples"
    
    def identify_speaker(self, audio_data: np.ndarray) -> Tuple[Optional[str], float]:
        """Identifiziere Sprecher aus Audio-Daten.
        
        Args:
            audio_data: numpy Array mit Audio-Daten
            
        Returns:
            (sprecher_name, ähnlichkeit) oder (None, 0.0) wenn unbekannt
        """
        if not self.profiles:
            return None, 0.0
        
        features = self._extract_features(audio_data)
        if not features:
            return None, 0.0
        
        best_match = None
        best_similarity = 0.0
        
        for name, profile in self.profiles.items():
            if not profile.get("registered"):
                continue
            
            stored_features = profile.get("features", {})
            similarity = self._calculate_similarity(features, stored_features)
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = name
        
        if best_similarity >= self.similarity_threshold:
            return best_match, best_similarity
        
        return None, best_similarity
    
    def list_speakers(self) -> list:
        """Liste alle registrierten Sprecher."""
        return [
            {"name": name, "samples": profile.get("sample_count", 0)}
            for name, profile in self.profiles.items()
            if profile.get("registered")
        ]
    
    def remove_speaker(self, name: str) -> Tuple[bool, str]:
        """Entferne einen Sprecher."""
        if name in self.profiles:
            del self.profiles[name]
            self._save_profiles()
            return True, f"Sprecher '{name}' entfernt"
        return False, f"Sprecher '{name}' nicht gefunden"


# Globale Instanz für einfache Nutzung
_speaker_recognition = None

def get_speaker_recognition() -> SpeakerRecognition:
    """Gibt die globale SpeakerRecognition Instanz zurück."""
    global _speaker_recognition
    if _speaker_recognition is None:
        _speaker_recognition = SpeakerRecognition()
    return _speaker_recognition