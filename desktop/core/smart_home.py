"""
Flexible Smart Home Grundarchitektur.
Implementiert Punkte 41-50: Smart Home Basis-Funktionalität.
"""
import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Callable
from datetime import datetime, time
from enum import Enum
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
SMART_HOME_CONFIG_PATH = BASE_DIR / "config" / "smart_home.json"


class DeviceType(Enum):
    """Smart Home Gerätetypen."""
    LIGHT = "light"
    SWITCH = "switch"
    THERMOSTAT = "thermostat"
    SENSOR = "sensor"
    CAMERA = "camera"
    MOTION_SENSOR = "motion_sensor"
    DOOR_SENSOR = "door_sensor"
    WINDOW_SENSOR = "window_sensor"


class DeviceState(Enum):
    """Geräte-Zustände."""
    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


class SmartHomeAdapter:
    """Transport boundary for real smart-home operations."""

    def control(self, device: "SmartHomeDevice", action: str, parameters: dict) -> bool:
        raise NotImplementedError


class InMemorySmartHomeAdapter(SmartHomeAdapter):
    """Explicit test/demo adapter; never selected automatically."""

    def control(self, device: "SmartHomeDevice", action: str, parameters: dict) -> bool:
        return True


class HomeAssistantAdapter(SmartHomeAdapter):
    """Minimal Home Assistant REST adapter."""

    def __init__(self, base_url: str, token: str, timeout: float = 5.0):
        if not base_url or not token:
            raise ValueError("Home Assistant URL and token are required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def control(self, device: "SmartHomeDevice", action: str, parameters: dict) -> bool:
        import requests

        domain = {
            DeviceType.LIGHT: "light",
            DeviceType.SWITCH: "switch",
            DeviceType.THERMOSTAT: "climate",
        }.get(device.device_type)
        if domain is None:
            return False

        service_map = {
            "turn_on": "turn_on",
            "turn_off": "turn_off",
            "set_brightness": "turn_on",
            "set_color": "turn_on",
            "set_temperature": "set_temperature",
            "set_mode": "set_hvac_mode",
        }
        service = service_map.get(action)
        if service is None:
            return False

        payload = {"entity_id": device.device_id}
        if action == "set_brightness":
            payload["brightness_pct"] = int(parameters.get("level", 100))
        elif action == "set_color":
            color = str(parameters.get("color", ""))
            if color.startswith("#") and len(color) == 7:
                payload["rgb_color"] = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
            else:
                payload["color_name"] = color
        elif action == "set_temperature":
            payload["temperature"] = float(parameters.get("temp", 22))
        elif action == "set_mode":
            payload["hvac_mode"] = str(parameters.get("mode", "auto"))

        response = requests.post(
            f"{self.base_url}/api/services/{domain}/{service}",
            headers={"Authorization": f"Bearer {self.token}"},
            json=payload,
            timeout=self.timeout,
        )
        return 200 <= response.status_code < 300


class SmartHomeDevice:
    """Basisklasse für Smart Home Geräte."""
    
    def __init__(self, device_id: str, name: str, device_type: DeviceType, room: str = "default"):
        self.device_id = device_id
        self.name = name
        self.device_type = device_type
        self.room = room
        self.state = DeviceState.OFF
        self.last_updated = None
        self.capabilities = []
    
    def turn_on(self) -> bool:
        """Schalte Gerät ein."""
        self.state = DeviceState.ON
        self.last_updated = datetime.now()
        return True
    
    def turn_off(self) -> bool:
        """Schalte Gerät aus."""
        self.state = DeviceState.OFF
        self.last_updated = datetime.now()
        return True
    
    def get_state(self) -> DeviceState:
        """Gib aktuellen Zustand zurück."""
        return self.state
    
    def to_dict(self) -> dict:
        """Konvertiere zu Dict für Speicherung."""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "device_type": self.device_type.value,
            "room": self.room,
            "state": self.state.value,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "capabilities": self.capabilities
        }


class Light(SmartHomeDevice):
    """Lampe mit Dimmfunktion."""
    
    def __init__(self, device_id: str, name: str, room: str = "default"):
        super().__init__(device_id, name, DeviceType.LIGHT, room)
        self.brightness = 100  # 0-100
        self.color = None  # Hex color or None
        self.capabilities = ["on_off", "brightness", "color"]
    
    def set_brightness(self, level: int) -> bool:
        """Setze Helligkeit (0-100)."""
        if 0 <= level <= 100:
            self.brightness = level
            self.last_updated = datetime.now()
            return True
        return False
    
    def set_color(self, color: str) -> bool:
        """Setze Farbe (Hex format)."""
        self.color = color
        self.last_updated = datetime.now()
        return True
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "brightness": self.brightness,
            "color": self.color
        })
        return data


class Switch(SmartHomeDevice):
    """Steckdose."""
    
    def __init__(self, device_id: str, name: str, room: str = "default"):
        super().__init__(device_id, name, DeviceType.SWITCH, room)
        self.power_consumption = 0.0  # Watt
        self.capabilities = ["on_off", "power_monitoring"]
    
    def get_power_consumption(self) -> float:
        """Gib aktuellen Stromverbrauch zurück."""
        return self.power_consumption
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "power_consumption": self.power_consumption
        })
        return data


class Thermostat(SmartHomeDevice):
    """Thermostat für Heizungssteuerung."""
    
    def __init__(self, device_id: str, name: str, room: str = "default"):
        super().__init__(device_id, name, DeviceType.THERMOSTAT, room)
        self.current_temp = 20.0  # Celsius
        self.target_temp = 22.0  # Celsius
        self.mode = "auto"  # auto, heat, cool, off
        self.capabilities = ["temperature", "mode", "scheduling"]
    
    def set_temperature(self, temp: float) -> bool:
        """Setze Zieltemperatur."""
        if 5 <= temp <= 35:
            self.target_temp = temp
            self.last_updated = datetime.now()
            return True
        return False
    
    def set_mode(self, mode: str) -> bool:
        """Setze Modus (auto, heat, cool, off)."""
        if mode in ["auto", "heat", "cool", "off"]:
            self.mode = mode
            self.last_updated = datetime.now()
            return True
        return False
    
    def get_current_temperature(self) -> float:
        """Gib aktuelle Temperatur zurück."""
        return self.current_temp
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "current_temp": self.current_temp,
            "target_temp": self.target_temp,
            "mode": self.mode
        })
        return data


class Sensor(SmartHomeDevice):
    """Allgemeiner Sensor."""
    
    def __init__(self, device_id: str, name: str, sensor_type: str, room: str = "default"):
        super().__init__(device_id, name, DeviceType.SENSOR, room)
        self.sensor_type = sensor_type  # temperature, humidity, air_quality, etc.
        self.value = None
        self.unit = ""
        self.capabilities = ["reading"]
    
    def set_reading(self, value: float, unit: str = "") -> None:
        """Setze Sensor-Wert."""
        self.value = value
        self.unit = unit
        self.last_updated = datetime.now()
    
    def get_reading(self) -> Optional[tuple]:
        """Gib Sensor-Wert zurück (value, unit)."""
        if self.value is not None:
            return (self.value, self.unit)
        return None
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "sensor_type": self.sensor_type,
            "value": self.value,
            "unit": self.unit
        })
        return data


class Camera(SmartHomeDevice):
    """Kamera mit Stream-URL und Ereignisprotokoll (Punkt 46)."""

    def __init__(self, device_id: str, name: str, room: str = "default",
                 stream_url: str = ""):
        super().__init__(device_id, name, DeviceType.CAMERA, room)
        self.stream_url = stream_url
        self.events: List[dict] = []
        self.capabilities = ["stream", "events"]

    def record_event(self, description: str) -> None:
        """Zeichne erkanntes Kamera-Ereignis auf."""
        self.events.append({
            "description": description,
            "timestamp": datetime.now().isoformat(),
        })
        self.events = self.events[-50:]
        self.last_updated = datetime.now()


class MotionSensor(Sensor):
    """Bewegungsmelder (Punkt 47)."""

    def __init__(self, device_id: str, name: str, room: str = "default"):
        super().__init__(device_id, name, "motion", room)
        self.device_type = DeviceType.MOTION_SENSOR
        self.motion_detected = False
        gate = get_motion_gate()
        if gate is not None:
            gate.register_sensor(device_id, self)

    def trigger_motion(self) -> None:
        """Melde erkannte Bewegung."""
        self.motion_detected = True
        self.value = 1.0
        self.unit = "detected"
        self.last_updated = datetime.now()
        gate = get_motion_gate()
        if gate is not None:
            gate.publish(self)

    def clear_motion(self) -> None:
        """Setze Bewegungsstatus zurück."""
        self.motion_detected = False
        self.value = 0.0
        self.last_updated = datetime.now()

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["motion_detected"] = self.motion_detected
        return data


class ContactSensor(Sensor):
    """Tür-/Fenstersensor (Punkt 48)."""

    def __init__(self, device_id: str, name: str, room: str = "default",
                 contact_type: str = "door"):
        super().__init__(device_id, name, contact_type, room)
        self.device_type = (
            DeviceType.DOOR_SENSOR if contact_type == "door" else DeviceType.WINDOW_SENSOR
        )
        self.open_state = False
        self.capabilities = ["open_close", "alert"]

    def set_open(self, is_open: bool) -> None:
        """Setze Öffnungszustand."""
        previous = self.open_state
        self.open_state = is_open
        self.value = 1.0 if is_open else 0.0
        self.unit = "open" if is_open else "closed"
        self.last_updated = datetime.now()
        if previous != is_open and is_open:
            gate = get_motion_gate()
            if gate is not None:
                gate.publish(self)

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["open_state"] = self.open_state
        return data


class MotionGate:
    """Verteilt Sensor-Ereignisse (Bewegung, Tür/Fenster-Öffnen) an
    registrierte Callbacks. Ohne Callbacks werden Ereignisse nur protokolliert.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._callbacks = []
        self._sensors = {}
        self.log = []

    def register(self, callback) -> None:
        """Registriere Callback (device_id, event, sensor) -> None."""
        if not callable(callback):
            raise ValueError("Motion gate callback must be callable")
        with self._lock:
            self._callbacks.append(callback)

    def register_sensor(self, device_id: str, sensor) -> None:
        with self._lock:
            self._sensors[device_id] = sensor

    def publish(self, sensor, event: str = "triggered") -> None:
        """Verteile ein Sensor-Ereignis an alle Callbacks."""
        entry = {
            "device_id": sensor.device_id,
            "sensor_type": getattr(sensor, "sensor_type", "generic"),
            "room": sensor.room,
            "event": event,
            "timestamp": datetime.now().isoformat(),
        }
        with self._lock:
            self.log.append(entry)
            self.log = self.log[-100:]
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback(entry["device_id"], entry["event"], sensor)
            except Exception as exc:
                print(f"[SmartHome] Motion callback error: {exc}")

    def status(self) -> dict:
        with self._lock:
            return {
                "callbacks": len(self._callbacks),
                "sensors": len(self._sensors),
                "recent_events": list(self.log[-10:]),
            }


def get_motion_gate() -> MotionGate:
    """Gibt den globalen MotionGate zurück."""
    global _motion_gate
    if _motion_gate is None:
        _motion_gate = MotionGate()
    return _motion_gate


_motion_gate = None


# --- Typed device classes for camera/motion/contact (Punkte 46-48) ---


class SmartHomeManager:
    """Verwaltet alle Smart Home Geräte."""
    
    def __init__(self, adapter: Optional[SmartHomeAdapter] = None):
        self.devices: Dict[str, SmartHomeDevice] = {}
        self.scenes: Dict[str, List[dict]] = {}
        self.automation_rules: List[dict] = []
        self.config = self._load_config()
        self.away_mode = bool(self.config.get("away_mode", {}).get("enabled", False))
        self.adapter = adapter if adapter is not None else self._build_adapter()
        self._restore_state()
        
    def _load_config(self) -> dict:
        """Lade Smart Home Konfiguration."""
        default_config = {
            "rooms": {
                "default": {"name": "Standard", "enabled": True},
                "living_room": {"name": "Wohnzimmer", "enabled": False},
                "kitchen": {"name": "Küche", "enabled": False},
                "bedroom": {"name": "Schlafzimmer", "enabled": False},
                "office": {"name": "Büro", "enabled": False},
            },
            "away_mode": {
                "enabled": False,
                "actions": []  # Aktionen die bei "Haus verlassen" ausgeführt werden
            },
            "provider": {"type": "none"},
            "devices": {},
            "scenes": {},
        }
        
        try:
            if SMART_HOME_CONFIG_PATH.exists():
                loaded = json.loads(SMART_HOME_CONFIG_PATH.read_text(encoding="utf-8"))
                rooms = {**default_config["rooms"], **loaded.get("rooms", {})}
                return {
                    **default_config,
                    **loaded,
                    "rooms": rooms
                }
        except Exception:
            pass
        
        return default_config

    def _build_adapter(self) -> Optional[SmartHomeAdapter]:
        provider = self.config.get("provider", {})
        if provider.get("type") != "home_assistant":
            return None
        token = os.getenv(provider.get("token_env", "MICA_HOME_ASSISTANT_TOKEN"), "")
        base_url = provider.get("base_url", "")
        if not base_url or not token:
            return None
        return HomeAssistantAdapter(base_url, token, float(provider.get("timeout", 5)))

    def _restore_state(self) -> None:
        self.scenes = dict(self.config.get("scenes", {}))
        for device_id, raw in self.config.get("devices", {}).items():
            try:
                device_type = DeviceType(raw["device_type"])
                if device_type == DeviceType.LIGHT:
                    device = Light(device_id, raw["name"], raw.get("room", "default"))
                    device.brightness = int(raw.get("brightness", 100))
                    device.color = raw.get("color")
                elif device_type == DeviceType.SWITCH:
                    device = Switch(device_id, raw["name"], raw.get("room", "default"))
                    device.power_consumption = float(raw.get("power_consumption", 0.0))
                elif device_type == DeviceType.THERMOSTAT:
                    device = Thermostat(device_id, raw["name"], raw.get("room", "default"))
                    device.current_temp = float(raw.get("current_temp", 20.0))
                    device.target_temp = float(raw.get("target_temp", 22.0))
                    device.mode = raw.get("mode", "auto")
                elif device_type == DeviceType.CAMERA:
                    device = Camera(
                        device_id, raw["name"], raw.get("room", "default"),
                        raw.get("stream_url", ""),
                    )
                    device.events = list(raw.get("events", []))
                elif device_type == DeviceType.MOTION_SENSOR:
                    device = MotionSensor(device_id, raw["name"], raw.get("room", "default"))
                    device.motion_detected = bool(raw.get("motion_detected", False))
                    device.value = raw.get("value")
                    device.unit = raw.get("unit", "")
                elif device_type in (DeviceType.DOOR_SENSOR, DeviceType.WINDOW_SENSOR):
                    device = ContactSensor(
                        device_id, raw["name"], raw.get("room", "default"),
                        "door" if device_type == DeviceType.DOOR_SENSOR else "window",
                    )
                    device.open_state = bool(raw.get("open_state", False))
                    device.value = raw.get("value")
                    device.unit = raw.get("unit", "")
                else:
                    device = Sensor(
                        device_id, raw["name"], raw.get("sensor_type", device_type.value),
                        raw.get("room", "default")
                    )
                    device.value = raw.get("value")
                    device.unit = raw.get("unit", "")
                device.state = DeviceState(raw.get("state", DeviceState.UNKNOWN.value))
                last_updated = raw.get("last_updated")
                device.last_updated = datetime.fromisoformat(last_updated) if last_updated else None
                self.devices[device_id] = device
            except (KeyError, TypeError, ValueError):
                continue

    def _persist_state(self) -> None:
        self.config["devices"] = self.get_device_states()
        self.config["scenes"] = self.scenes
        self.config.setdefault("away_mode", {})["enabled"] = self.away_mode
        self._save_config()
    
    def _save_config(self) -> None:
        """Speichere Smart Home Konfiguration."""
        SMART_HOME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        SMART_HOME_CONFIG_PATH.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def add_device(self, device: SmartHomeDevice) -> bool:
        """Füge Gerät hinzu."""
        if device.device_id in self.devices:
            return False
        self.devices[device.device_id] = device
        self._persist_state()
        return True
    
    def remove_device(self, device_id: str) -> bool:
        """Entferne Gerät."""
        if device_id in self.devices:
            del self.devices[device_id]
            self._persist_state()
            return True
        return False
    
    def get_device(self, device_id: str) -> Optional[SmartHomeDevice]:
        """Gib Gerät zurück."""
        return self.devices.get(device_id)
    
    def get_devices_by_room(self, room: str) -> List[SmartHomeDevice]:
        """Gib alle Geräte in einem Raum zurück."""
        return [d for d in self.devices.values() if d.room == room]
    
    def get_devices_by_type(self, device_type: DeviceType) -> List[SmartHomeDevice]:
        """Gib alle Geräte eines Typs zurück."""
        return [d for d in self.devices.values() if d.device_type == device_type]
    
    def control_device(self, device_id: str, action: str, **kwargs) -> bool:
        """
        Kontrolliere ein Gerät.
        
        Args:
            device_id: Geräte-ID
            action: Aktion (turn_on, turn_off, set_brightness, etc.)
            **kwargs: Zusätzliche Parameter für die Aktion
            
        Returns:
            True wenn erfolgreich
        """
        device = self.get_device(device_id)
        if not device:
            return False

        if self.adapter is None:
            return False

        if action == "set_brightness" and (
            not isinstance(device, Light) or not 0 <= int(kwargs.get("level", 100)) <= 100
        ):
            return False
        if action == "set_color" and (
            not isinstance(device, Light) or not str(kwargs.get("color", "")).strip()
        ):
            return False
        if action == "set_temperature" and (
            not isinstance(device, Thermostat) or not 5 <= float(kwargs.get("temp", 22)) <= 35
        ):
            return False
        if action == "set_mode" and (
            not isinstance(device, Thermostat)
            or kwargs.get("mode", "auto") not in {"auto", "heat", "cool", "off"}
        ):
            return False
        if action not in {"turn_on", "turn_off", "set_brightness", "set_color", "set_temperature", "set_mode"}:
            return False
        
        try:
            if not self.adapter.control(device, action, kwargs):
                return False
            if action == "turn_on":
                success = device.turn_on()
            elif action == "turn_off":
                success = device.turn_off()
            elif action == "set_brightness" and isinstance(device, Light):
                success = device.set_brightness(kwargs.get("level", 100))
            elif action == "set_color" and isinstance(device, Light):
                success = device.set_color(kwargs.get("color", "#FFFFFF"))
            elif action == "set_temperature" and isinstance(device, Thermostat):
                success = device.set_temperature(kwargs.get("temp", 22))
            elif action == "set_mode" and isinstance(device, Thermostat):
                success = device.set_mode(kwargs.get("mode", "auto"))
            else:
                return False
            if success:
                self._persist_state()
            return success
        except Exception:
            return False
    
    def create_scene(self, scene_name: str, actions: List[dict]) -> bool:
        """
        Erstelle eine Szene (mehrere Aktionen mit einem Befehl).
        
        Args:
            scene_name: Name der Szene
            actions: Liste von Aktionen [{"device_id": "...", "action": "...", "params": {...}}]
            
        Returns:
            True wenn erfolgreich
        """
        self.scenes[scene_name] = actions
        self._persist_state()
        return True
    
    def execute_scene(self, scene_name: str) -> bool:
        """
        Führe eine Szene aus.
        
        Args:
            scene_name: Name der Szene
            
        Returns:
            True wenn erfolgreich
        """
        if scene_name not in self.scenes:
            return False
        
        actions = self.scenes[scene_name]
        success_count = 0
        for action in actions:
            device_id = action.get("device_id")
            action_name = action.get("action")
            params = action.get("params") or {}
            
            if self.control_device(device_id, action_name, **params):
                success_count += 1
        
        return bool(actions) and success_count == len(actions)
    
    def activate_away_mode(self) -> bool:
        """
        Aktiviere "Haus verlassen"-Modus.
        
        Returns:
            True wenn erfolgreich
        """
        # Führe konfigurierte Aktionen aus
        actions = self.config.get("away_mode", {}).get("actions", [])
        all_succeeded = True
        for action in actions:
            device_id = action.get("device_id")
            action_name = action.get("action")
            params = action.get("params") or {}
            all_succeeded = self.control_device(device_id, action_name, **params) and all_succeeded
        if actions and not all_succeeded:
            return False
        self.away_mode = True
        self._persist_state()
        return True
    
    def deactivate_away_mode(self) -> bool:
        """
        Deaktiviere "Haus verlassen"-Modus.
        
        Returns:
            True wenn erfolgreich
        """
        self.away_mode = False
        self._persist_state()
        return True
    
    def get_sensor_readings(self, sensor_type: Optional[str] = None) -> List[dict]:
        """
        Gib alle Sensor-Werte zurück.
        
        Args:
            sensor_type: Optionaler Filter nach Sensortyp
            
        Returns:
            Liste von Sensor-Werten
        """
        readings = []
        for device in self.devices.values():
            if isinstance(device, Sensor):
                if sensor_type is None or device.sensor_type == sensor_type:
                    reading = device.get_reading()
                    if reading:
                        readings.append({
                            "device_id": device.device_id,
                            "name": device.name,
                            "room": device.room,
                            "sensor_type": device.sensor_type,
                            "value": reading[0],
                            "unit": reading[1],
                            "last_updated": device.last_updated
                        })
        return readings
    
    def get_device_states(self) -> dict:
        """Gib Zustände aller Geräte zurück."""
        return {
            device_id: device.to_dict()
            for device_id, device in self.devices.items()
        }
    
    def get_status(self) -> dict:
        """Gib overall Smart Home Status zurück."""
        return {
            "total_devices": len(self.devices),
            "devices_by_type": {
                device_type.value: len(self.get_devices_by_type(device_type))
                for device_type in DeviceType
            },
            "scenes": list(self.scenes.keys()),
            "away_mode": self.away_mode,
            "adapter_configured": self.adapter is not None,
            "rooms": self.config.get("rooms", {})
        }


# Globale Instanz für einfache Nutzung
_smart_home_manager = None

def get_smart_home_manager() -> SmartHomeManager:
    """Gibt die globale SmartHomeManager Instanz zurück."""
    global _smart_home_manager
    if _smart_home_manager is None:
        _smart_home_manager = SmartHomeManager()
    return _smart_home_manager
