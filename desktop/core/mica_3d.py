"""
MICA-3D-Integration für Verbindung mit virtueller 3D-Umgebung.
Implementiert Punkt 99: MICA-3D-Integration.
"""
import json
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
import sys

from core.ids import new_id


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
MICA_3D_CONFIG_PATH = BASE_DIR / "config" / "mica_3d.json"


class ObjectType(Enum):
    """3D Objekt-Typen."""
    CUBE = "cube"
    SPHERE = "sphere"
    CYLINDER = "cylinder"
    PLANE = "plane"
    MODEL = "model"
    LIGHT = "light"
    CAMERA = "camera"


class InteractionMode(Enum):
    """Interaktions-Modus."""
    VIEW = "view"
    MANIPULATE = "manipulate"
    ANNOTATE = "annotate"
    NAVIGATE = "navigate"


@dataclass
class Vector3:
    """3D Vektor."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    
    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "z": self.z}
    
    @staticmethod
    def from_dict(data: dict) -> 'Vector3':
        return Vector3(data["x"], data["y"], data["z"])


@dataclass
class Quaternion:
    """Quaternion für Rotation."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0
    
    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "z": self.z, "w": self.w}


@dataclass
class Transform3D:
    """3D Transformation."""
    position: Vector3 = None
    rotation: Quaternion = None
    scale: Vector3 = None
    
    def __post_init__(self):
        if self.position is None:
            self.position = Vector3(0, 0, 0)
        if self.rotation is None:
            self.rotation = Quaternion(0, 0, 0, 1)
        if self.scale is None:
            self.scale = Vector3(1, 1, 1)
    
    def to_dict(self) -> dict:
        return {
            "position": self.position.to_dict(),
            "rotation": self.rotation.to_dict(),
            "scale": self.scale.to_dict()
        }


@dataclass
class SceneObject:
    """3D Szenen-Objekt."""
    object_id: str = ""
    object_type: ObjectType = ObjectType.CUBE
    name: str = ""
    transform: Transform3D = None
    properties: Dict = None
    visible: bool = True
    
    def __post_init__(self):
        if self.properties is None:
            self.properties = {}
        if self.transform is None:
            self.transform = Transform3D(
                position=Vector3(0, 0, 0),
                rotation=Quaternion(0, 0, 0, 1),
                scale=Vector3(1, 1, 1)
            )
        if not self.object_id:
            self.object_id = new_id("obj")

    def to_dict(self) -> dict:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type.value,
            "name": self.name,
            "transform": self.transform.to_dict(),
            "properties": self.properties,
            "visible": self.visible,
        }


class Mica3DIntegration:
    """MICA-3D-Integration."""
    
    def __init__(
        self,
        connector: Optional[Callable[[str], bool]] = None,
        disconnecter: Optional[Callable[[], None]] = None,
    ):
        self.connected = False
        self._connector = connector
        self._disconnecter = disconnecter
        self.scene_objects: Dict[str, SceneObject] = {}
        self.cameras: Dict[str, dict] = {}
        self.lights: Dict[str, dict] = {}
        self.config = self._load_config()
        self.current_interaction_mode = InteractionMode.VIEW
        
    def _load_config(self) -> dict:
        """Lade 3D-Konfiguration."""
        default_config = {
            "default_scene": "default",
            "auto_save": True,
            "render_quality": "medium",
            "enable_physics": False,
            "connection_string": ""
        }
        
        try:
            if MICA_3D_CONFIG_PATH.exists():
                loaded = json.loads(MICA_3D_CONFIG_PATH.read_text(encoding="utf-8"))
                return {**default_config, **loaded}
        except Exception:
            pass
        
        return default_config
    
    def _save_config(self) -> None:
        """Speichere 3D-Konfiguration."""
        MICA_3D_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        MICA_3D_CONFIG_PATH.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def connect(self, connection_string: str = "") -> bool:
        """
        Verbinde mit 3D-Umgebung.
        
        Args:
            connection_string: Verbindungs-String
            
        Returns:
            True wenn erfolgreich
        """
        target = connection_string.strip() or str(
            self.config.get("connection_string", "")
        ).strip()
        self.connected = False

        # A configured address is not proof of a live engine.  Only an injected
        # adapter that has actually performed its own handshake may establish the
        # connection.
        if self._connector is None or not target:
            return False

        try:
            verified = self._connector(target) is True
        except Exception as exc:
            print(f"[Mica3D] Verbindung fehlgeschlagen: {exc}")
            return False

        if not verified:
            return False

        self.config["connection_string"] = target
        self._save_config()
        self.connected = True
        return True
    
    def disconnect(self) -> bool:
        """Trenne Verbindung."""
        if self.connected and self._disconnecter is not None:
            try:
                self._disconnecter()
            except Exception as exc:
                print(f"[Mica3D] Trennen fehlgeschlagen: {exc}")
                return False
        self.connected = False
        return True
    
    def create_object(self, 
                     object_type: ObjectType, 
                     name: str, 
                     position: Tuple[float, float, float] = (0, 0, 0),
                     scale: Tuple[float, float, float] = (1, 1, 1)) -> str:
        """
        Erstelle 3D-Objekt.
        
        Args:
            object_type: Typ des Objekts
            name: Name
            position: Position (x, y, z)
            scale: Skalierung (x, y, z)
            
        Returns:
            Objekt ID
        """
        object_id = new_id("obj")
        
        transform = Transform3D(
            position=Vector3(*position),
            rotation=Quaternion(0, 0, 0, 1),  # Identity rotation
            scale=Vector3(*scale)
        )
        
        scene_object = SceneObject(
            object_id=object_id,
            object_type=object_type,
            name=name,
            transform=transform,
            properties={},
            visible=True
        )
        
        self.scene_objects[object_id] = scene_object
        return object_id
    
    def delete_object(self, object_id: str) -> bool:
        """Lösche Objekt."""
        if object_id in self.scene_objects:
            del self.scene_objects[object_id]
            return True
        return False
    
    def move_object(self, object_id: str, position: Tuple[float, float, float]) -> bool:
        """Bewege Objekt."""
        if object_id in self.scene_objects:
            self.scene_objects[object_id].transform.position = Vector3(*position)
            return True
        return False
    
    def rotate_object(self, object_id: str, rotation: Tuple[float, float, float, float]) -> bool:
        """Rotiere Objekt."""
        if object_id in self.scene_objects:
            self.scene_objects[object_id].transform.rotation = Quaternion(*rotation)
            return True
        return False
    
    def scale_object(self, object_id: str, scale: Tuple[float, float, float]) -> bool:
        """Skaliere Objekt."""
        if object_id in self.scene_objects:
            self.scene_objects[object_id].transform.scale = Vector3(*scale)
            return True
        return False
    
    def set_object_visibility(self, object_id: str, visible: bool) -> bool:
        """Setze Objekt-Sichtbarkeit."""
        if object_id in self.scene_objects:
            self.scene_objects[object_id].visible = visible
            return True
        return False
    
    def get_object_properties(self, object_id: str) -> Optional[dict]:
        """Gib Objekt-Eigenschaften zurück."""
        if object_id in self.scene_objects:
            obj = self.scene_objects[object_id]
            return {
                "object_id": obj.object_id,
                "object_type": obj.object_type.value,
                "name": obj.name,
                "transform": obj.transform.to_dict(),
                "visible": obj.visible,
                "properties": obj.properties
            }
        return None
    
    def list_objects(self, object_type: Optional[ObjectType] = None) -> List[dict]:
        """Liste alle Objekte auf."""
        objects = []
        for obj in self.scene_objects.values():
            if object_type is None or obj.object_type == object_type:
                objects.append({
                    "object_id": obj.object_id,
                    "object_type": obj.object_type.value,
                    "name": obj.name,
                    "visible": obj.visible
                })
        return objects
    
    def set_interaction_mode(self, mode: InteractionMode) -> None:
        """Setze Interaktions-Modus."""
        self.current_interaction_mode = mode
    
    def get_camera_view(self, camera_id: str = "default") -> Optional[dict]:
        """Gib Kamera-Sicht zurück."""
        return self.cameras.get(camera_id, {
            "position": {"x": 0, "y": 5, "z": 10},
            "target": {"x": 0, "y": 0, "z": 0},
            "up": {"x": 0, "y": 1, "z": 0}
        })
    
    def set_camera_view(self, 
                      camera_id: str, 
                      position: Tuple[float, float, float],
                      target: Tuple[float, float, float]) -> bool:
        """Setze Kamera-Sicht."""
        self.cameras[camera_id] = {
            "position": {"x": position[0], "y": position[1], "z": position[2]},
            "target": {"x": target[0], "y": target[1], "z": target[2]},
            "up": {"x": 0, "y": 1, "z": 0}
        }
        return True
    
    def add_light(self, 
                 light_id: str, 
                 light_type: str = "point",
                 position: Tuple[float, float, float] = (0, 5, 0),
                 intensity: float = 1.0,
                 color: Tuple[float, float, float] = (1, 1, 1)) -> bool:
        """Füge Licht hinzu."""
        self.lights[light_id] = {
            "light_type": light_type,
            "position": {"x": position[0], "y": position[1], "z": position[2]},
            "intensity": intensity,
            "color": {"r": color[0], "g": color[1], "b": color[2]}
        }
        return True
    
    def remove_light(self, light_id: str) -> bool:
        """Entferne Licht."""
        if light_id in self.lights:
            del self.lights[light_id]
            return True
        return False
    
    def save_scene(self, scene_name: str) -> bool:
        """Speichere Szene."""
        scene_data = {
            "scene_name": scene_name,
            "objects": {k: v.to_dict() for k, v in self.scene_objects.items()},
            "cameras": self.cameras,
            "lights": self.lights,
            "saved_at": datetime.now().isoformat()
        }
        
        scene_path = BASE_DIR / "mica_3d_scenes" / f"{scene_name}.json"
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        
        scene_path.write_text(
            json.dumps(scene_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        return True
    
    def load_scene(self, scene_name: str) -> bool:
        """Lade Szene."""
        scene_path = BASE_DIR / "mica_3d_scenes" / f"{scene_name}.json"
        
        if not scene_path.exists():
            return False
        
        try:
            scene_data = json.loads(scene_path.read_text(encoding="utf-8"))
            
            # Rekonstruiere Objekte (streng validiert)
            restored_objects = {}
            for obj_id, obj_data in scene_data.get("objects", {}).items():
                if not isinstance(obj_data, dict):
                    raise ValueError(f"Invalid object entry: {obj_id}")
                transform_data = obj_data["transform"]
                transform = Transform3D(
                    position=Vector3.from_dict(transform_data["position"]),
                    rotation=Quaternion(**transform_data["rotation"]),
                    scale=Vector3.from_dict(transform_data["scale"])
                )
                
                scene_object = SceneObject(
                    object_id=obj_id,
                    object_type=ObjectType(obj_data["object_type"]),
                    name=obj_data["name"],
                    transform=transform,
                    properties=dict(obj_data.get("properties", {})),
                    visible=bool(obj_data.get("visible", True))
                )
                
                restored_objects[obj_id] = scene_object
            
            # Kameras/Lichter nur übernehmen, wenn es strukturell gültige Dicts sind
            cameras = scene_data.get("cameras", {})
            lights = scene_data.get("lights", {})
            if not isinstance(cameras, dict) or not isinstance(lights, dict):
                raise ValueError("cameras and lights must be objects")
            for cam in cameras.values():
                if not isinstance(cam, dict) or not all(k in cam for k in ("position", "target", "up")):
                    raise ValueError("Invalid camera entry in scene file")
            for light in lights.values():
                if not isinstance(light, dict) or not all(k in light for k in ("light_type", "position", "intensity", "color")):
                    raise ValueError("Invalid light entry in scene file")
            
            self.scene_objects = restored_objects
            self.cameras = cameras
            self.lights = lights
            
            return True
        except (KeyError, TypeError, ValueError) as e:
            print(f"[Mica3D] Error loading scene: {e}")
            self.scene_objects = {}
            self.cameras = {}
            self.lights = {}
            return False
    
    def get_scene_info(self) -> dict:
        """Gib Szenen-Informationen zurück."""
        return {
            "connected": self.connected,
            "object_count": len(self.scene_objects),
            "camera_count": len(self.cameras),
            "light_count": len(self.lights),
            "interaction_mode": self.current_interaction_mode.value,
            "last_updated": datetime.now().isoformat()
        }
    
    def export_scene(self, format: str = "json") -> str:
        """Exportiere Szene."""
        scene_data = {
            "objects": {k: v.to_dict() for k, v in self.scene_objects.items()},
            "cameras": self.cameras,
            "lights": self.lights,
            "exported_at": datetime.now().isoformat()
        }
        
        if format == "json":
            return json.dumps(scene_data, indent=2, ensure_ascii=False)
        else:
            return str(scene_data)


# Globale Instanz für einfache Nutzung
_mica_3d_integration = None

def get_mica_3d_integration() -> Mica3DIntegration:
    """Gibt die globale Mica3DIntegration Instanz zurück."""
    global _mica_3d_integration
    if _mica_3d_integration is None:
        _mica_3d_integration = Mica3DIntegration()
    return _mica_3d_integration
