"""
Flexible Smart Home Grundarchitektur.
Implementiert Punkte 41-50: Smart Home Basis-Funktionalität.
"""
import json
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


class SmartHomeManager:
    """Verwaltet alle Smart Home Geräte."""
    
    def __init__(self):
        self.devices: Dict[str, SmartHomeDevice] = {}
        self.scenes: Dict[str, List[dict]] = {}
        self.automation_rules: List[dict] = []
        self.config = self._load_config()
        self.away_mode = False
        
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
            }
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
        return True
    
    def remove_device(self, device_id: str) -> bool:
        """Entferne Gerät."""
        if device_id in self.devices:
            del self.devices[device_id]
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
        
        try:
            if action == "turn_on":
                return device.turn_on()
            elif action == "turn_off":
                return device.turn_off()
            elif action == "set_brightness" and isinstance(device, Light):
                return device.set_brightness(kwargs.get("level", 100))
            elif action == "set_color" and isinstance(device, Light):
                return device.set_color(kwargs.get("color", "#FFFFFF"))
            elif action == "set_temperature" and isinstance(device, Thermostat):
                return device.set_temperature(kwargs.get("temp", 22))
            elif action == "set_mode" and isinstance(device, Thermostat):
                return device.set_mode(kwargs.get("mode", "auto"))
            else:
                return False
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
        
        success_count = 0
        for action in self.scenes[scene_name]:
            device_id = action.get("device_id")
            action_name = action.get("action")
            params = action.get("params", {})
            
            if self.control_device(device_id, action_name, **params):
                success_count += 1
        
        return success_count > 0
    
    def activate_away_mode(self) -> bool:
        """
        Aktiviere "Haus verlassen"-Modus.
        
        Returns:
            True wenn erfolgreich
        """
        self.away_mode = True
        
        # Führe konfigurierte Aktionen aus
        actions = self.config.get("away_mode", {}).get("actions", [])
        for action in actions:
            device_id = action.get("device_id")
            action_name = action.get("action")
            params = action.get("params", {})
            self.control_device(device_id, action_name, **params)
        
        return True
    
    def deactivate_away_mode(self) -> bool:
        """
        Deaktiviere "Haus verlassen"-Modus.
        
        Returns:
            True wenn erfolgreich
        """
        self.away_mode = False
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
                device_type.value: len(self.get_devices_by_type(DeviceType[device_type.value.upper()]))
                for device_type in DeviceType
            },
            "scenes": list(self.scenes.keys()),
            "away_mode": self.away_mode,
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