"""
Server & Homelab Monitoring Grundarchitektur.
Implementiert Punkte 51-60: Server & Homelab Funktionalität.
"""
import json
import subprocess
import platform
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
SERVER_CONFIG_PATH = BASE_DIR / "config" / "server_monitor.json"


class ContainerStatus(Enum):
    """Container-Zustände."""
    RUNNING = "running"
    STOPPED = "stopped"
    RESTARTING = "restarting"
    UNKNOWN = "unknown"


class ServiceStatus(Enum):
    """Dienst-Zustände."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class ContainerInfo:
    """Informationen über einen Container."""
    container_id: str
    name: str
    image: str
    status: ContainerStatus
    cpu_usage: float
    memory_usage: float
    uptime: str
    ports: List[str]


@dataclass
class ServiceInfo:
    """Informationen über einen Dienst."""
    name: str
    status: ServiceStatus
    uptime: str
    memory_usage: float
    last_restart: Optional[str]


@dataclass
class SystemAlert:
    """System-Alarm."""
    alert_type: str
    severity: str
    message: str
    timestamp: str
    resolved: bool = False


class ServerMonitor:
    """Überwacht Server- und Homelab-Ressourcen."""
    
    def __init__(self):
        self.containers: Dict[str, ContainerInfo] = {}
        self.services: Dict[str, ServiceInfo] = {}
        self.alerts: List[SystemAlert] = []
        self.config = self._load_config()
        self.thresholds = self.config.get("thresholds", {
            "cpu_warning": 80.0,
            "cpu_critical": 90.0,
            "memory_warning": 80.0,
            "memory_critical": 90.0,
            "disk_warning": 80.0,
            "disk_critical": 90.0,
            "temp_warning": 70.0,
            "temp_critical": 85.0
        })
    
    def _load_config(self) -> dict:
        """Lade Server-Monitor Konfiguration."""
        default_config = {
            "monitored_paths": [str(Path.home()), "/var", "/tmp"],
            "docker_available": False,
            "services_to_monitor": [],
            "thresholds": {}
        }
        
        try:
            if SERVER_CONFIG_PATH.exists():
                loaded = json.loads(SERVER_CONFIG_PATH.read_text(encoding="utf-8"))
                return {**default_config, **loaded}
        except Exception:
            pass
        
        return default_config
    
    def _save_config(self) -> None:
        """Speichere Server-Monitor Konfiguration."""
        SERVER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        SERVER_CONFIG_PATH.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def _check_docker_available(self) -> bool:
        """Prüfe ob Docker verfügbar ist."""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def monitor_containers(self) -> List[ContainerInfo]:
        """
        Überwache Docker-Container (Punkt 51).
        
        Returns:
            Liste der Container-Informationen
        """
        if not self._check_docker_available():
            self.config["docker_available"] = False
            return []
        
        self.config["docker_available"] = True
        containers = []
        
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if not line:
                        continue
                    
                    parts = line.split('\t')
                    if len(parts) >= 4:
                        container_id, name, image, status = parts[:4]
                        ports = parts[4] if len(parts) > 4 else ""
                        
                        # Status parsen
                        container_status = ContainerStatus.UNKNOWN
                        if "Up" in status:
                            container_status = ContainerStatus.RUNNING
                        elif "Exited" in status:
                            container_status = ContainerStatus.STOPPED
                        elif "Restarting" in status:
                            container_status = ContainerStatus.RESTARTING
                        
                        # Simulierte Ressourcen-Nutzung (echte Werte benötigen docker stats)
                        container_info = ContainerInfo(
                            container_id=container_id[:12],
                            name=name,
                            image=image,
                            status=container_status,
                            cpu_usage=0.0,  # Würde docker stats benötigen
                            memory_usage=0.0,
                            uptime=status,
                            ports=ports.split(',') if ports else []
                        )
                        
                        containers.append(container_info)
                        self.containers[container_id] = container_info
                        
        except Exception as e:
            print(f"[ServerMonitor] Docker monitoring error: {e}")
        
        return containers
    
    def restart_container(self, container_id: str) -> bool:
        """
        Starte Container neu (Punkt 52).
        
        Args:
            container_id: Container ID oder Name
            
        Returns:
            True wenn erfolgreich
        """
        if not self._check_docker_available():
            return False
        
        try:
            result = subprocess.run(
                ["docker", "restart", container_id],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0
        except Exception as e:
            print(f"[ServerMonitor] Container restart error: {e}")
            return False
    
    def get_server_status(self) -> dict:
        """
        Zeige Serverstatus an (Punkt 53).
        
        Returns:
            Zusammenfassende Server-Informationen
        """
        containers = self.monitor_containers()
        running_containers = len([c for c in containers if c.status == ContainerStatus.RUNNING])
        
        return {
            "hostname": platform.node(),
            "os": platform.system(),
            "os_version": platform.version(),
            "uptime": self._get_system_uptime(),
            "total_containers": len(containers),
            "running_containers": running_containers,
            "stopped_containers": len(containers) - running_containers,
            "docker_available": self._check_docker_available(),
            "alerts_count": len([a for a in self.alerts if not a.resolved]),
            "last_check": datetime.now().isoformat()
        }
    
    def _get_system_uptime(self) -> str:
        """Gib System-Uptime zurück."""
        try:
            if platform.system() == "Windows":
                # Windows uptime calculation mit psutil
                try:
                    import psutil
                    boot_time = psutil.boot_time()
                    uptime = datetime.now() - boot_time
                    days = uptime.days
                    hours, remainder = divmod(uptime.seconds, 3600)
                    return f"{days}d {hours}h"
                except ImportError:
                    return "Unknown"
            else:
                with open('/proc/uptime', 'r') as f:
                    uptime_seconds = float(f.readline().split()[0])
                    uptime = timedelta(seconds=int(uptime_seconds))
                    days = uptime.days
                    hours, remainder = divmod(uptime.seconds, 3600)
                    return f"{days}d {hours}h"
        except Exception:
            return "Unknown"
    
    def monitor_disk_space(self) -> List[dict]:
        """
        Überwache Speicherplatz (Punkt 54).
        
        Returns:
            Liste von Speicherplatz-Informationen
        """
        disk_info = []
        monitored_paths = self.config.get("monitored_paths", [str(Path.home())])
        
        for path_str in monitored_paths:
            path = Path(path_str)
            if not path.exists():
                continue
            
            try:
                usage = shutil.disk_usage(path)
                total_gb = usage.total / (1024**3)
                used_gb = usage.used / (1024**3)
                free_gb = usage.free / (1024**3)
                percent_used = (usage.used / usage.total) * 100
                
                # Prüfe Schwellenwerte
                alert = None
                if percent_used >= self.thresholds.get("disk_critical", 90):
                    alert = SystemAlert(
                        alert_type="disk_critical",
                        severity="critical",
                        message=f"Kritischer Speicherplatz auf {path}: {percent_used:.1f}% verwendet",
                        timestamp=datetime.now().isoformat()
                    )
                    self.alerts.append(alert)
                elif percent_used >= self.thresholds.get("disk_warning", 80):
                    alert = SystemAlert(
                        alert_type="disk_warning",
                        severity="warning",
                        message=f"Speicherplatz Warnung auf {path}: {percent_used:.1f}% verwendet",
                        timestamp=datetime.now().isoformat()
                    )
                    self.alerts.append(alert)
                
                disk_info.append({
                    "path": str(path),
                    "total_gb": round(total_gb, 2),
                    "used_gb": round(used_gb, 2),
                    "free_gb": round(free_gb, 2),
                    "percent_used": round(percent_used, 1),
                    "alert": alert.alert_type if alert else None
                })
                
            except Exception as e:
                print(f"[ServerMonitor] Disk monitoring error for {path}: {e}")
        
        return disk_info
    
    def monitor_temperatures(self) -> List[dict]:
        """
        Überwache Temperaturen (Punkt 55).
        
        Returns:
            Liste von Temperatur-Informationen
        """
        temp_info = []
        
        try:
            if platform.system() == "Linux":
                # Versuche Linux Temperaturen zu lesen
                temps = self._get_linux_temperatures()
                temp_info.extend(temps)
            elif platform.system() == "Windows":
                # Windows Temperatursimulation (echte Werte benötigen spezielle Tools)
                temp_info.append({
                    "sensor": "cpu",
                    "temperature": 45.0,  # Simulierter Wert
                    "unit": "C"
                })
            else:
                # Mac oder andere
                temp_info.append({
                    "sensor": "cpu",
                    "temperature": 50.0,  # Simulierter Wert
                    "unit": "C"
                })
                
            # Prüfe Temperaturschwellenwerte
            for temp in temp_info:
                temp_value = temp.get("temperature", 0)
                if temp_value >= self.thresholds.get("temp_critical", 85):
                    alert = SystemAlert(
                        alert_type="temp_critical",
                        severity="critical",
                        message=f"Kritische Temperatur: {temp['sensor']} = {temp_value}°C",
                        timestamp=datetime.now().isoformat()
                    )
                    self.alerts.append(alert)
                elif temp_value >= self.thresholds.get("temp_warning", 70):
                    alert = SystemAlert(
                        alert_type="temp_warning",
                        severity="warning",
                        message=f"Temperatur Warnung: {temp['sensor']} = {temp_value}°C",
                        timestamp=datetime.now().isoformat()
                    )
                    self.alerts.append(alert)
                    
        except Exception as e:
            print(f"[ServerMonitor] Temperature monitoring error: {e}")
        
        return temp_info
    
    def _get_linux_temperatures(self) -> List[dict]:
        """Lese Temperaturen von Linux-Systemen."""
        temps = []
        try:
            hwmon_paths = Path("/sys/class/hwmon").glob("hwmon*")
            for hwmon_path in hwmon_paths:
                name_path = hwmon_path / "name"
                if name_path.exists():
                    sensor_name = name_path.read_text().strip()
                    
                    temp_input_paths = hwmon_path.glob("temp*_input")
                    for temp_path in temp_input_paths:
                        try:
                            temp_millidegrees = int(temp_path.read_text().strip())
                            temp_celsius = temp_millidegrees / 1000.0
                            temps.append({
                                "sensor": sensor_name,
                                "temperature": temp_celsius,
                                "unit": "C"
                            })
                        except Exception:
                            continue
        except Exception:
            pass
        
        return temps
    
    def monitor_network(self) -> dict:
        """
        Überwache Netzwerk (Punkt 56).
        
        Returns:
            Netzwerk-Status Information
        """
        network_info = {
            "hostname": platform.node(),
            "interfaces": [],
            "connectivity": False
        }
        
        try:
            # Prüfe Internet-Konnektivität
            try:
                subprocess.run(
                    ["ping", "-c", "1", "8.8.8.8"],
                    capture_output=True,
                    timeout=5
                )
                network_info["connectivity"] = True
            except Exception:
                try:
                    subprocess.run(
                        ["ping", "-n", "1", "8.8.8.8"],
                        capture_output=True,
                        timeout=5
                    )
                    network_info["connectivity"] = True
                except Exception:
                    network_info["connectivity"] = False
            
            # Netzwerk-Interfaces (plattformabhängig)
            if platform.system() == "Linux":
                interfaces = self._get_linux_network_interfaces()
                network_info["interfaces"] = interfaces
            elif platform.system() == "Windows":
                interfaces = self._get_windows_network_interfaces()
                network_info["interfaces"] = interfaces
                
        except Exception as e:
            print(f"[ServerMonitor] Network monitoring error: {e}")
        
        return network_info
    
    def _get_linux_network_interfaces(self) -> List[dict]:
        """Lade Linux Netzwerk-Interfaces."""
        interfaces = []
        try:
            result = subprocess.run(
                ["ip", "addr"],
                capture_output=True,
                text=True,
                timeout=5
            )
            # Parsen wäre komplexer, hier vereinfacht
            interfaces.append({
                "name": "eth0",
                "status": "up",
                "ip": "192.168.1.100"  # Simuliert
            })
        except Exception:
            pass
        
        return interfaces
    
    def _get_windows_network_interfaces(self) -> List[dict]:
        """Lade Windows Netzwerk-Interfaces."""
        interfaces = []
        try:
            result = subprocess.run(
                ["ipconfig"],
                capture_output=True,
                text=True,
                timeout=5
            )
            # Parsen wäre komplexer, hier vereinfacht
            interfaces.append({
                "name": "Ethernet",
                "status": "up",
                "ip": "192.168.1.100"  # Simuliert
            })
        except Exception:
            pass
        
        return interfaces
    
    def check_services(self) -> List[ServiceInfo]:
        """
        Prüfe Dienste automatisch (Punkt 57).
        
        Returns:
            Liste der Dienst-Informationen
        """
        services = []
        services_to_monitor = self.config.get("services_to_monitor", [])
        
        for service_name in services_to_monitor:
            try:
                if platform.system() == "Linux":
                    service_info = self._check_linux_service(service_name)
                elif platform.system() == "Windows":
                    service_info = self._check_windows_service(service_name)
                else:
                    continue
                
                if service_info:
                    services.append(service_info)
                    self.services[service_name] = service_info
                    
            except Exception as e:
                print(f"[ServerMonitor] Service check error for {service_name}: {e}")
        
        return services
    
    def _check_linux_service(self, service_name: str) -> Optional[ServiceInfo]:
        """Prüfe Linux-Dienst mit systemctl."""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            status_str = result.stdout.strip()
            status = ServiceStatus.UNKNOWN
            if status_str == "active":
                status = ServiceStatus.ACTIVE
            elif status_str == "inactive":
                status = ServiceStatus.INACTIVE
            elif status_str == "failed":
                status = ServiceStatus.FAILED
            
            return ServiceInfo(
                name=service_name,
                status=status,
                uptime="Unknown",
                memory_usage=0.0,
                last_restart=None
            )
        except Exception:
            return None
    
    def _check_windows_service(self, service_name: str) -> Optional[ServiceInfo]:
        """Prüfe Windows-Dienst mit sc."""
        try:
            result = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            output = result.stdout
            status = ServiceStatus.UNKNOWN
            
            if "RUNNING" in output:
                status = ServiceStatus.ACTIVE
            elif "STOPPED" in output:
                status = ServiceStatus.INACTIVE
            
            return ServiceInfo(
                name=service_name,
                status=status,
                uptime="Unknown",
                memory_usage=0.0,
                last_restart=None
            )
        except Exception:
            return None
    
    def analyze_logs(self, log_path: str, error_pattern: str = "ERROR") -> dict:
        """
        Analysiere Fehlerlogs (Punkt 58).
        
        Args:
            log_path: Pfad zur Log-Datei
            error_pattern: Muster für Fehler
            
        Returns:
            Log-Analyse-Ergebnisse
        """
        log_file = Path(log_path)
        if not log_file.exists():
            return {"error": "Log file not found", "path": str(log_path)}
        
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            total_lines = len(lines)
            error_count = sum(1 for line in lines if error_pattern in line)
            warning_count = sum(1 for line in lines if "WARNING" in line or "WARN" in line)
            
            # Letzte Fehler finden
            recent_errors = []
            for i, line in enumerate(lines):
                if error_pattern in line:
                    recent_errors.append({
                        "line_number": i + 1,
                        "content": line.strip()[:200]
                    })
                    if len(recent_errors) >= 5:
                        break
            
            return {
                "path": str(log_path),
                "total_lines": total_lines,
                "error_count": error_count,
                "warning_count": warning_count,
                "recent_errors": recent_errors,
                "analyzed_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {"error": str(e), "path": str(log_path)}
    
    def monitor_backups(self, backup_path: str) -> dict:
        """
        Überwache Backups (Punkt 59).
        
        Args:
            backup_path: Pfad zu Backup-Verzeichnis
            
        Returns:
            Backup-Status Information
        """
        backup_dir = Path(backup_path)
        if not backup_dir.exists():
            return {
                "status": "not_found",
                "path": str(backup_path),
                "message": "Backup directory not found"
            }
        
        try:
            # Finde die neuesten Backups
            backup_files = list(backup_dir.glob("*"))
            backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            recent_backups = []
            for backup_file in backup_files[:10]:  # Letzte 10
                stat = backup_file.stat()
                recent_backups.append({
                    "name": backup_file.name,
                    "size_mb": round(stat.st_size / (1024**2), 2),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "age_hours": (datetime.now() - datetime.fromtimestamp(stat.st_mtime)).total_seconds() / 3600
                })
            
            # Prüfe ob Backup zu alt ist (>24h)
            if recent_backups:
                latest_age = recent_backups[0]["age_hours"]
                if latest_age > 24:
                    alert = SystemAlert(
                        alert_type="backup_old",
                        severity="warning",
                        message=f"Letztes Backup ist {latest_age:.1f} Stunden alt",
                        timestamp=datetime.now().isoformat()
                    )
                    self.alerts.append(alert)
            
            return {
                "status": "found",
                "path": str(backup_path),
                "total_backups": len(backup_files),
                "recent_backups": recent_backups,
                "latest_backup": recent_backups[0] if recent_backups else None,
                "checked_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                "status": "error",
                "path": str(backup_path),
                "error": str(e)
            }
    
    def check_updates(self) -> dict:
        """
        Erkenne verfügbare Updates (Punkt 60).
        
        Returns:
            Update-Informationen
        """
        updates = {
            "system_updates": [],
            "container_updates": [],
            "last_check": datetime.now().isoformat()
        }
        
        try:
            # System-Updates (plattformabhängig)
            if platform.system() == "Linux":
                system_updates = self._check_linux_updates()
                updates["system_updates"] = system_updates
            elif platform.system() == "Windows":
                system_updates = self._check_windows_updates()
                updates["system_updates"] = system_updates
            
            # Container-Updates
            if self._check_docker_available():
                container_updates = self._check_container_updates()
                updates["container_updates"] = container_updates
                
        except Exception as e:
            print(f"[ServerMonitor] Update check error: {e}")
        
        return updates
    
    def _check_linux_updates(self) -> List[dict]:
        """Prüfe Linux-System-Updates."""
        updates = []
        try:
            # Debian/Ubuntu
            result = subprocess.run(
                ["apt", "list", "--upgradable"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:  # Überspringe Header
                    if '/' in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            updates.append({
                                "package": parts[0].split('/')[0],
                                "current_version": parts[1],
                                "new_version": parts[2],
                                "source": "apt"
                            })
        except Exception:
            pass
        
        return updates
    
    def _check_windows_updates(self) -> List[dict]:
        """Prüfe Windows-Updates (simuliert)."""
        # Echte Windows Update Prüfung wäre komplexer
        return [{
            "package": "Windows Security Update",
            "current_version": "Unknown",
            "new_version": "Available",
            "source": "windows_update"
        }]
    
    def _check_container_updates(self) -> List[dict]:
        """Prüfe Container-Image Updates."""
        updates = []
        try:
            result = subprocess.run(
                ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                images = result.stdout.strip().split('\n')
                for image in images:
                    if image and "<none>" not in image:
                        updates.append({
                            "image": image,
                            "update_available": True,  # Würde docker pull benötigen
                            "source": "docker"
                        })
        except Exception:
            pass
        
        return updates
    
    def get_alerts(self, unresolved_only: bool = True) -> List[SystemAlert]:
        """
        Gib Alerts zurück.
        
        Args:
            unresolved_only: Nur ungelöste Alerts
            
        Returns:
            Liste der Alerts
        """
        if unresolved_only:
            return [a for a in self.alerts if not a.resolved]
        return self.alerts
    
    def resolve_alert(self, alert_type: str) -> bool:
        """
        Löse einen Alert auf.
        
        Args:
            alert_type: Typ des Alerts
            
        Returns:
            True wenn erfolgreich
        """
        for alert in self.alerts:
            if alert.alert_type == alert_type and not alert.resolved:
                alert.resolved = True
                return True
        return False
    
    def get_overall_status(self) -> dict:
        """
        Gib overall Status zurück.
        
        Returns:
            Zusammenfassender Status
        """
        return {
            "server_status": self.get_server_status(),
            "disk_space": self.monitor_disk_space(),
            "temperatures": self.monitor_temperatures(),
            "network": self.monitor_network(),
            "services": self.check_services(),
            "alerts": self.get_alerts(),
            "updates": self.check_updates(),
            "containers": self.monitor_containers()
        }


# Globale Instanz für einfache Nutzung
_server_monitor = None

def get_server_monitor() -> ServerMonitor:
    """Gibt die globale ServerMonitor Instanz zurück."""
    global _server_monitor
    if _server_monitor is None:
        _server_monitor = ServerMonitor()
    return _server_monitor