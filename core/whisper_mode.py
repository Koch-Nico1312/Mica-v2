"""
Flüstermodus für leise Spracheingabe.
Implementiert Punkt 18: Flüstermodus.
"""
import numpy as np
from typing import Tuple


class WhisperMode:
    """Erkennt und verarbeitet Flüstersprache."""
    
    def __init__(self, normal_threshold: float = 0.05, whisper_threshold: float = 0.015):
        """
        Args:
            normal_threshold: Schwellwert für normale Sprache (0-1)
            whisper_threshold: Schwellwert für Flüstersprache (0-1)
        """
        self.normal_threshold = normal_threshold
        self.whisper_threshold = whisper_threshold
        self.current_mode = "normal"  # "normal" oder "whisper"
        self.consecutive_whisper_frames = 0
        self.consecutive_normal_frames = 0
        self.mode_change_threshold = 5  # Frames bis zum Moduswechsel
    
    def calculate_rms(self, audio_data: np.ndarray) -> float:
        """Berechne RMS (Root Mean Square) als Lautstärkemessung."""
        if len(audio_data) == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio_data ** 2)))
    
    def normalize_level(self, rms: float, max_expected: float = 0.1) -> float:
        """Normalisiere RMS auf 0-1 Skala."""
        return min(rms / max_expected, 1.0)
    
    def detect_speech_mode(self, audio_data: np.ndarray) -> Tuple[str, float]:
        """
        Erkenne ob normal gesprochen oder geflüstert wird.
        
        Args:
            audio_data: numpy Array mit Audio-Daten
            
        Returns:
            (mode, level) - mode ist "normal", "whisper" oder "silence"
        """
        rms = self.calculate_rms(audio_data)
        level = self.normalize_level(rms)
        
        if level < self.whisper_threshold:
            detected = "silence"
        elif level < self.normal_threshold:
            detected = "whisper"
        else:
            detected = "normal"
        
        # Glättung: Mehrere aufeinanderfolgende Frames für Moduswechsel
        if detected == "whisper":
            self.consecutive_whisper_frames += 1
            self.consecutive_normal_frames = 0
        elif detected == "normal":
            self.consecutive_normal_frames += 1
            self.consecutive_whisper_frames = 0
        else:
            self.consecutive_whisper_frames = max(0, self.consecutive_whisper_frames - 1)
            self.consecutive_normal_frames = max(0, self.consecutive_normal_frames - 1)
        
        # Moduswechsel nur bei genug aufeinanderfolgenden Frames
        if self.consecutive_whisper_frames >= self.mode_change_threshold:
            self.current_mode = "whisper"
        elif self.consecutive_normal_frames >= self.mode_change_threshold:
            self.current_mode = "normal"
        
        return self.current_mode, level
    
    def should_use_whisper_response(self, audio_data: np.ndarray) -> bool:
        """
        Entscheide ob die Antwort im Flüstermodus erfolgen soll.
        
        Args:
            audio_data: numpy Array mit Audio-Daten
            
        Returns:
            True wenn Flüstermodus aktiviert werden soll
        """
        mode, level = self.detect_speech_mode(audio_data)
        return mode == "whisper"
    
    def get_response_volume_multiplier(self, audio_data: np.ndarray) -> float:
        """
        Gib den Volumen-Multiplikator für die Antwort zurück.
        
        Args:
            audio_data: numpy Array mit Audio-Daten
            
        Returns:
            Multiplikator (0.3 für Flüster, 1.0 für normal)
        """
        mode, level = self.detect_speech_mode(audio_data)
        if mode == "whisper":
            return 0.3  # 30% Lautstärke für Flüsterantworten
        return 1.0  # Normale Lautstärke
    
    def adjust_audio_gain(self, audio_data: np.ndarray, target_gain: float) -> np.ndarray:
        """
        Passe die Audio-Lautstärke an.
        
        Args:
            audio_data: numpy Array mit Audio-Daten
            target_gain: Ziel-Verstärkung (0-1)
            
        Returns:
            Angepasstes Audio-Array
        """
        if target_gain == 1.0:
            return audio_data
        
        return audio_data * target_gain
    
    def is_speech_present(self, audio_data: np.ndarray) -> bool:
        """
        Prüfe ob Sprache vorhanden ist (über Flüster-Schwelle).
        
        Args:
            audio_data: numpy Array mit Audio-Daten
            
        Returns:
            True wenn Sprache vorhanden
        """
        _, level = self.detect_speech_mode(audio_data)
        return level >= self.whisper_threshold
    
    def get_audio_description(self, audio_data: np.ndarray) -> str:
        """
        Gib eine Beschreibung des Audio-Levels zurück.
        
        Args:
            audio_data: numpy Array mit Audio-Daten
            
        Returns:
            Beschreibung des Audio-Levels
        """
        mode, level = self.detect_speech_mode(audio_data)
        
        if mode == "silence":
            return "Stille"
        elif mode == "whisper":
            return f"Flüstern ({level:.3f})"
        else:
            return f"Normal ({level:.3f})"


# Globale Instanz für einfache Nutzung
_whisper_mode = None

def get_whisper_mode() -> WhisperMode:
    """Gibt die globale WhisperMode Instanz zurück."""
    global _whisper_mode
    if _whisper_mode is None:
        _whisper_mode = WhisperMode()
    return _whisper_mode