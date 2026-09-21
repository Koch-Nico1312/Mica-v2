"""
Telefon-/Intercom-Modus für Sprachkommunikation zwischen Geräten/Räumen.
Implementiert Punkt 20: Telefon-/Intercom-Modus.
"""
import json
import base64
import hmac
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    
    def __init__(self, transport: Optional[Callable[[dict, dict], bool]] = None):
        self.active = False
        self.current_room = "default"
        self.connected_rooms = set()
        self.message_queue = queue.Queue()
        self.call_history = []
        self.config = self._load_config()
        self.audio_callback: Optional[Callable] = None
        self.transport = transport or self._http_transport
        self._http_server: Optional[ThreadingHTTPServer] = None
        self._http_thread: Optional[threading.Thread] = None
        
    def _load_config(self) -> dict:
        """Lade Intercom-Konfiguration."""
        default_config = {
            "rooms": {
                "default": {"name": "Standard", "enabled": True, "endpoint": ""},
                "living_room": {"name": "Wohnzimmer", "enabled": False, "endpoint": ""},
                "kitchen": {"name": "Küche", "enabled": False, "endpoint": ""},
                "bedroom": {"name": "Schlafzimmer", "enabled": False, "endpoint": ""},
                "office": {"name": "Büro", "enabled": False, "endpoint": ""},
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

    @staticmethod
    def _http_transport(room_config: dict, payload: dict) -> bool:
        """Deliver an intercom payload to a configured room endpoint."""
        import requests

        endpoint = str(room_config.get("endpoint", "")).strip()
        if not endpoint:
            return False
        headers = {"Content-Type": "application/json"}
        token_env = room_config.get("token_env")
        if token_env and os.getenv(token_env):
            headers["Authorization"] = f"Bearer {os.environ[token_env]}"
        response = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=float(room_config.get("timeout", 5)),
        )
        return 200 <= response.status_code < 300
    
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
        self.stop_http_server()
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
            self.config["rooms"][target_room] = {
                "name": target_room.capitalize(), "enabled": True, "endpoint": ""
            }
        
        if not self.config["rooms"][target_room].get("enabled", False):
            self.config["rooms"][target_room]["enabled"] = True
        
        if target_room == self.current_room:
            return False

        room_config = self.config["rooms"][target_room]
        probe = {
            "from_room": self.current_room,
            "to_rooms": [target_room],
            "timestamp": datetime.now().isoformat(),
            "type": "probe",
        }
        try:
            if not self.transport(room_config, probe):
                endpoint = str(room_config.get("endpoint", "")).strip()
                if not endpoint:
                    print(
                        f"[Intercom] Verbindung zu {target_room} abgelehnt: "
                        "kein Endpunkt konfiguriert"
                    )
                else:
                    print(
                        f"[Intercom] Verbindung zu {target_room} abgelehnt: "
                        "Transport negativ"
                    )
                return False
        except Exception as exc:
            print(f"[Intercom] Verbindung fehlgeschlagen: {exc}")
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
            return False
        
        message_data = {
            "from_room": self.current_room,
            "to_rooms": target_rooms,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "type": "text"
        }
        
        delivered = []
        for room in target_rooms:
            room_config = self.config["rooms"].get(room)
            if not room_config:
                print(f"[Intercom] Unbekannter Zielraum: {room}")
                return False
            try:
                if self.transport(room_config, {**message_data, "to_rooms": [room]}):
                    delivered.append(room)
                else:
                    print(f"[Intercom] Nachricht an {room} abgelehnt (Transport negativ)")
            except Exception as exc:
                print(f"[Intercom] Nachricht an {room} fehlgeschlagen: {exc}")

        if len(delivered) != len(target_rooms):
            return False
        
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
        
        encoded_message = {
            **message_data,
            "audio_data": base64.b64encode(audio_data).decode("ascii"),
            "encoding": "base64",
        }
        delivered = []
        for room in target_rooms:
            room_config = self.config["rooms"].get(room)
            if not room_config:
                return False
            try:
                if self.transport(room_config, {**encoded_message, "to_rooms": [room]}):
                    delivered.append(room)
            except Exception as exc:
                print(f"[Intercom] Audio an {room} fehlgeschlagen: {exc}")
        if len(delivered) != len(target_rooms):
            return False
        self._log_call("audio", target_room if target_room else "all")
        return True

    def enqueue_incoming_message(self, message: dict) -> bool:
        """Accept a message received by the local HTTP/server integration."""
        if not self._is_valid_incoming_message(message):
            return False
        self.message_queue.put(message)
        return True

    def _is_valid_incoming_message(self, message: object) -> bool:
        if not isinstance(message, dict):
            return False
        if not isinstance(message.get("from_room"), str) or not message["from_room"].strip():
            return False
        message_type = message.get("type")
        if message_type not in {"text", "audio", "probe"}:
            return False
        targets = message.get("to_rooms")
        if not isinstance(targets, list) or not all(isinstance(room, str) for room in targets):
            return False
        if self.current_room not in targets:
            return False
        if message_type == "text":
            return isinstance(message.get("message"), str) and bool(message["message"].strip())
        if message_type == "audio":
            if message.get("encoding") != "base64" or not isinstance(message.get("audio_data"), str):
                return False
            try:
                base64.b64decode(message["audio_data"], validate=True)
            except (ValueError, TypeError):
                return False
        return True
    
    def start_http_server(self, host: str = "0.0.0.0", port: int = 8080) -> bool:
        """
        Start HTTP server to receive incoming intercom messages.
        
        Args:
            host: Host to bind to
            port: Port to listen on
            
        Returns:
            True if server started successfully
        """
        if self._http_server is not None:
            return True
        if not self.active or not isinstance(port, int) or not 0 <= port <= 65535:
            return False

        intercom = self
        try:
            max_body_size = int(self.config.get("max_message_bytes", 1_048_576))
        except (TypeError, ValueError):
            return False
        if max_body_size < 1:
            return False
        token_env = self.config.get("server_token_env")

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if self.path.rstrip("/") != "/intercom/message":
                    self._reply(404, {"accepted": False, "error": "not_found"})
                    return
                expected_token = os.getenv(str(token_env)) if token_env else None
                if expected_token:
                    supplied = self.headers.get("Authorization", "")
                    if not hmac.compare_digest(supplied, f"Bearer {expected_token}"):
                        self._reply(401, {"accepted": False, "error": "unauthorized"})
                        return
                if self.headers.get_content_type() != "application/json":
                    self._reply(415, {"accepted": False, "error": "content_type"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    length = -1
                if length < 1 or length > max_body_size:
                    self._reply(413, {"accepted": False, "error": "body_size"})
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._reply(400, {"accepted": False, "error": "invalid_json"})
                    return
                if (
                    isinstance(payload, dict)
                    and payload.get("type") == "probe"
                    and intercom._is_valid_incoming_message(payload)
                ):
                    self._reply(200, {"accepted": True, "room": intercom.current_room})
                    return
                if not intercom.enqueue_incoming_message(payload):
                    self._reply(422, {"accepted": False, "error": "invalid_message"})
                    return
                self._reply(202, {"accepted": True})

            def _reply(self, status: int, body: dict) -> None:
                encoded = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        try:
            server = ThreadingHTTPServer((host, port), Handler)
        except (OSError, ValueError) as exc:
            print(f"[Intercom] HTTP-Server konnte nicht gestartet werden: {exc}")
            return False

        thread = threading.Thread(
            target=server.serve_forever,
            name="mica-intercom-http",
            daemon=True,
        )
        self._http_server = server
        self._http_thread = thread
        thread.start()
        return thread.is_alive()

    @property
    def http_server_address(self) -> Optional[tuple]:
        """Return the bound address, including the assigned port when port 0 was used."""
        if self._http_server is None:
            return None
        return self._http_server.server_address

    def stop_http_server(self) -> None:
        """Stop and release the inbound HTTP receiver, if it is running."""
        server = self._http_server
        thread = self._http_thread
        self._http_server = None
        self._http_thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
    
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
