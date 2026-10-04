"""
Offline-Fallback für Spracherkennung bei Verbindungsproblemen.
Implementiert Punkt 19: Offline-Spracherkennung (einfacher Fallback).
"""
import re
import json
from pathlib import Path
from typing import Tuple, Optional
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
OFFLINE_COMMANDS_PATH = BASE_DIR / "config" / "offline_commands.json"


class OfflineFallback:
    """Einfacher Offline-Fallback für grundlegende Kommandos."""
    
    def __init__(self):
        self.commands = self._load_commands()
        self.active = False  # Wird bei Verbindungsproblemen aktiviert
    
    def _load_commands(self) -> dict:
        """Lade Offline-Kommandos aus Konfiguration."""
        default_commands = {
            "stop": ["stop", "stopp", "halt", "pause", "anhalten"],
            "help": ["help", "hilfe", "hilfe"],
            "yes": ["yes", "ja", "ja", "okay", "ok"],
            "no": ["no", "nein", "nein", "nop"],
            "cancel": ["cancel", "abbrechen", "abbruch", "cancel"],
            "repeat": ["repeat", "wiederholen", "nochmal", "repeat"],
            "volume_up": ["lauter", "volume up", "lauter"],
            "volume_down": ["leiser", "volume down", "leiser"],
            "shutdown": ["shutdown", "ausschalten", "beenden", "shutdown"],
        }
        
        try:
            if OFFLINE_COMMANDS_PATH.exists():
                loaded = json.loads(OFFLINE_COMMANDS_PATH.read_text(encoding="utf-8"))
                return {**default_commands, **loaded}
        except Exception:
            pass
        
        return default_commands
    
    def _save_commands(self) -> None:
        """Speichere Offline-Kommandos."""
        OFFLINE_COMMANDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        OFFLINE_COMMANDS_PATH.write_text(
            json.dumps(self.commands, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def add_command(self, command: str, variations: list) -> None:
        """Füge ein neues Offline-Kommando hinzu."""
        self.commands[command] = variations
        self._save_commands()
    
    def activate(self) -> None:
        """Aktiviere Offline-Modus."""
        self.active = True
        print("[Offline] Offline-Modus aktiviert")
    
    def deactivate(self) -> None:
        """Deaktiviere Offline-Modus."""
        self.active = False
        print("[Offline] Offline-Modus deaktiviert")
    
    def process_text(self, text: str) -> Tuple[Optional[str], bool]:
        """
        Verarbeite Text im Offline-Modus.
        
        Args:
            text: Erkannter Text
            
        Returns:
            (erkanntes_kommando, war_offline_erkannt)
        """
        if not self.active:
            return None, False
        
        text_lower = text.lower().strip()
        
        # Prüfe jedes Kommando und seine Variationen
        for command, variations in self.commands.items():
            for variation in variations:
                if variation.lower() in text_lower:
                    return command, True
        
        # Wenn kein Kommando erkannt, gib zurück dass offline aktiv ist
        return None, True
    
    def is_simple_command(self, text: str) -> bool:
        """
        Prüfe ob Text ein einfaches Kommando ist das offline verarbeitet werden kann.
        
        Args:
            text: Zu prüfender Text
            
        Returns:
            True wenn einfaches Kommando
        """
        text_lower = text.lower().strip()
        
        for variations in self.commands.values():
            for variation in variations:
                if variation.lower() in text_lower:
                    return True
        
        return False
    
    def get_available_commands(self) -> list:
        """Gib Liste der verfügbaren Offline-Kommandos zurück."""
        return list(self.commands.keys())
    
    def get_command_variations(self, command: str) -> list:
        """Gib Variationen für ein spezifisches Kommando zurück."""
        return self.commands.get(command, [])


class NetworkDetector:
    """Erkennt Netzwerkprobleme für automatischen Offline-Fallback."""
    
    def __init__(self):
        self.consecutive_failures = 0
        self.failure_threshold = 3  # 3 aufeinanderfolgende Fehler
        self.recovery_threshold = 2  # 2 Erfolge für Recovery
        self.consecutive_successes = 0
    
    def report_success(self) -> None:
        """Melde erfolgreiche Netzwerkoperation."""
        self.consecutive_failures = 0
        self.consecutive_successes += 1
    
    def report_failure(self) -> None:
        """Melde fehlgeschlagene Netzwerkoperation."""
        self.consecutive_failures += 1
        self.consecutive_successes = 0
    
    def should_use_offline(self) -> bool:
        """
        Entscheide ob Offline-Modus verwendet werden sollte.
        
        Returns:
            True wenn zu viele aufeinanderfolgende Fehler
        """
        return self.consecutive_failures >= self.failure_threshold
    
    def should_recover(self) -> bool:
        """
        Entscheide ob Recovery versucht werden sollte.
        
        Returns:
            True wenn genug aufeinanderfolgende Erfolge
        """
        return self.consecutive_successes >= self.recovery_threshold


# Globale Instanzen für einfache Nutzung
_offline_fallback = None
_network_detector = None

def get_offline_fallback() -> OfflineFallback:
    """Gibt die globale OfflineFallback Instanz zurück."""
    global _offline_fallback
    if _offline_fallback is None:
        _offline_fallback = OfflineFallback()
    return _offline_fallback

def get_network_detector() -> NetworkDetector:
    """Gibt die globale NetworkDetector Instanz zurück."""
    global _network_detector
    if _network_detector is None:
        _network_detector = NetworkDetector()
    return _network_detector