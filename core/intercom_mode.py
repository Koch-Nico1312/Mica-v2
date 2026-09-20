"""
Telefon-/Intercom-Modus für Sprachkommunikation zwischen Geräten/Räumen.
Implementiert Punkt 20: Telefon-/Intercom-Modus.
"""
import json
import queue
import threading
from pathlib import Path
from typing import Dict, Optional, Callable
from datetime import datetime
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
INTERCOM_CONFIG_PATH = BASE_DIR / "config" / "intercom_config.json"


class IntercomMode:
    """Verwaltet Intercom-Kommunikation zwischen Geräten/Räumen."""
    
    def __init__(self):
        self.active = False
        self.current_room = "default"
        self.connected_rooms = set()
        self.message_queue = queue.Queue()
        self.call_history = []
        self.config = self._load_config()
        self.audio_callback: Optional[Callable] = None
        
    def _load_config(self) -> dict:
        """Lade Intercom-Konfiguration."""
        default_config = {
            "rooms": {
                "default": {"name": "Standard", "enabled": True},
                "living_room": {"name": "Wohnzimmer", "enabled": False},
                "kitchen": {"name": "Küche", "enabled": False},
                "bedroom": {"name": "Schlafzimmer", "enabled": False},
                "office": {"name": "Büro", "enabled": False},
            },
            "auto_answer": False,
            "max_history": 50
        }
        
        try:
            if INTERCOM_CONFIG_PATH.exists():
                loaded = json.loads(INTERCOM_CONFIG_PATH.read_text(encoding="utf-8"))
                # Merge mit defaults
                rooms = {**default_config["rooms"], **loaded.get("rooms", {})}
                return {
                    **default_config,
                    **loaded,
                    "rooms": rooms
                }
        except Exception:
            pass
        
        return default_config
    
    def _save_config(self) -> None:
        """Speichere Intercom-Konfiguration."""
        INTERCOM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        INTERCOM_CONFIG_PATH.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def set_audio_callback(self, callback: Callable) -> None:
        """Setze Callback für Audio-Ausgabe."""
        self.audio_callback = callback
    
    def activate(self, room: str = "default") -> bool:
        """
        Aktiviere Intercom-Modus für einen Raum.
        
        Args:
            room: Raum-ID
            
        Returns:
            True wenn erfolgreich aktiviert
        """
        if room not in self.config["rooms"]:
            # Füge Raum hinzu falls nicht vorhanden
            self.config["rooms"][room] = {"name": room.capitalize(), "enabled": True}
        
        if not self.config["rooms"][room].get("enabled", False):
            self.config["rooms"][room]["enabled"] = True
        
        self.active = True
        self.current_room = room
        print(f"[Intercom] Aktiviert für Raum: {self.config['rooms'][room]['name']}")
        return True
    
    def deactivate(self) -> None:
        """Deaktiviere Intercom-Modus."""
        self.active = False
        self.connected_rooms.clear()
        print("[Intercom] Deaktiviert")
    
    def connect_to_room(self, target_room: str) -> bool:
        """
        Verbinde mit einem anderen Raum.
        
        Args:
            target_room: Ziel-Raum-ID
            
        Returns:
            True wenn erfolgreich verbunden
        """
        if not self.active:
            return False
        
        if target_room not in self.config["rooms"]:
            # Füge Raum hinzu falls nicht vorhanden
            self.config["rooms"][target_room] = {"name": target_room.capitalize(), "enabled": True}
        
        if not self.config["rooms"][target_room].get("enabled", False):
            self.config["rooms"][target_room]["enabled"] = True
        
        if target_room == self.current_room:
            return False
        
        self.connected_rooms.add(target_room)
        print(f"[Intercom] Verbunden mit: {self.config['rooms'][target_room]['name']}")
        
        # Logge Verbindung
        self._log_call("connect", target_room)
        return True
    
    def disconnect_from_room(self, target_room: str) -> bool:
        """
        Trenne Verbindung zu einem Raum.
        
        Args:
            target_room: Ziel-Raum-ID
            
        Returns:
            True wenn erfolgreich getrennt
        """
        if target_room in self.connected_rooms:
            self.connected_rooms.remove(target_room)
            print(f"[Intercom] Getrennt von: {self.config['rooms'][target_room]['name']}")
            self._log_call("disconnect", target_room)
            return True
        return False
    
    def disconnect_all(self) -> None:
        """Trenne alle Verbindungen."""
        for room in list(self.connected_rooms):
            self.disconnect_from_room(room)
    
    def send_message(self, message: str, target_room: Optional[str] = None) -> bool:
        """
        Sende eine Nachricht an verbundene Räume.
        
        Args:
            message: Nachricht
            target_room: Spezifischer Zielraum (None = alle verbundenen)
            
        Returns:
            True wenn erfolgreich gesendet
        """
        if not self.active:
            return False
        
        target_rooms = [target_room] if target_room else list(self.connected_rooms)
        
        if not target_rooms:
            # Füge aktuellen Raum als Ziel hinzu falls keine verbundenen
            target_rooms = [self.current_room]
        
        message_data = {
            "from_room": self.current_room,
            "to_rooms": target_rooms,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "type": "text"
        }
        
        self.message_queue.put(message_data)
        
        # Wenn Audio-Callback gesetzt, spiele Nachricht ab
        if self.audio_callback:
            try:
                self.audio_callback(message)
            except Exception:
                pass
        
        self._log_call("message", target_room if target_room else "all", message)
        return True
    
    def send_audio(self, audio_data: bytes, target_room: Optional[str] = None) -> bool:
        """
        Sende Audio-Daten an verbundene Räume.
        
        Args:
            audio_data: Audio-Daten
            target_room: Spezifischer Zielraum (None = alle verbundenen)
            
        Returns:
            True wenn erfolgreich gesendet
        """
        if not self.active:
            return False
        
        target_rooms = [target_room] if target_room else list(self.connected_rooms)
        
        if not target_rooms:
            return False
        
        message_data = {
            "from_room": self.current_room,
            "to_rooms": target_rooms,
            "audio_data": audio_data,
            "timestamp": datetime.now().isoformat(),
            "type": "audio"
        }
        
        self.message_queue.put(message_data)
        self._log_call("audio", target_room if target_room else "all")
        return True
    
    def receive_message(self) -> Optional[dict]:
        """
        Empfange Nachricht aus der Queue.
        
        Returns:
            Nachricht-Dict oder None wenn Queue leer
        """
        try:
            return self.message_queue.get_nowait()
        except queue.Empty:
            return None
    
    def _log_call(self, action: str, target: str, details: str = "") -> None:
        """Logge Intercom-Aktivität."""
        entry = {
            "action": action,
            "from": self.current_room,
            "to": target,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
        
        self.call_history.append(entry)
        
        # Begrenze Historie
        max_history = self.config.get("max_history", 50)
        if len(self.call_history) > max_history:
            self.call_history = self.call_history[-max_history:]
    
    def get_call_history(self, limit: int = 20) -> list:
        """Gib Anruflhistorie zurück."""
        return self.call_history[-limit:]
    
    def get_connected_rooms(self) -> list:
        """Gib Liste der verbundenen Räume zurück."""
        return [
            {
                "id": room,
                "name": self.config["rooms"][room]["name"]
            }
            for room in self.connected_rooms
        ]
    
    def get_available_rooms(self) -> list:
        """Gib Liste der verfügbaren Räume zurück."""
        return [
            {
                "id": room_id,
                "name": room_data["name"],
                "enabled": room_data.get("enabled", False),
                "current": room_id == self.current_room
            }
            for room_id, room_data in self.config["rooms"].items()
        ]
    
    def enable_room(self, room_id: str) -> bool:
        """Aktiviere einen Raum für Intercom."""
        if room_id in self.config["rooms"]:
            self.config["rooms"][room_id]["enabled"] = True
            self._save_config()
            return True
        return False
    
    def disable_room(self, room_id: str) -> bool:
        """Deaktiviere einen Raum für Intercom."""
        if room_id in self.config["rooms"]:
            self.config["rooms"][room_id]["enabled"] = False
            self._save_config()
            return True
        return False
    
    def set_auto_answer(self, enabled: bool) -> None:
        """Aktiviere/Deaktiviere automatische Annahme."""
        self.config["auto_answer"] = enabled
        self._save_config()
    
    def is_active(self) -> bool:
        """Prüfe ob Intercom aktiv ist."""
        return self.active
    
    def get_status(self) -> dict:
        """Gib aktuellen Status zurück."""
        return {
            "active": self.active,
            "current_room": self.current_room,
            "current_room_name": self.config["rooms"][self.current_room]["name"],
            "connected_rooms": self.get_connected_rooms(),
            "auto_answer": self.config.get("auto_answer", False),
            "message_queue_size": self.message_queue.qsize()
        }


# Globale Instanz für einfache Nutzung
_intercom_mode = None

def get_intercom_mode() -> IntercomMode:
    """Gibt die globale IntercomMode Instanz zurück."""
    global _intercom_mode
    if _intercom_mode is None:
        _intercom_mode = IntercomMode()
    return _intercom_mode