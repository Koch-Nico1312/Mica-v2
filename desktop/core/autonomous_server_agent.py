"""
Autonomer Server-Agent für selbstständige Serverüberwachung und Diagnose.
Implementiert Punkt 95: Autonomer Server-Agent.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import sys

from core.ids import new_id


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
SERVER_AGENT_CONFIG_PATH = BASE_DIR / "config" / "server_agent.json"


class AgentState(Enum):
    """Agent-Zustände."""
    IDLE = "idle"
    MONITORING = "monitoring"
    DIAGNOSING = "diagnosing"
    FIXING = "fixing"
    REPORTING = "reporting"


class Severity(Enum):
    """Problem-Schwere."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Issue:
    """Erkanntes Problem."""
    issue_id: str = ""
    severity: Severity = Severity.INFO
    category: str = ""
    description: str = ""
    detected_at: str = ""
    resolved: bool = False
    resolution: str = ""
    resolved_at: Optional[str] = None
    target: Optional[str] = None   # Maschinenlesbares Ziel (z.B. Service-Name, Pfad)
    
    def __post_init__(self):
        if not self.issue_id:
            self.issue_id = new_id("issue")
        if not self.detected_at:
            self.detected_at = datetime.now().isoformat()


@dataclass
class DiagnosticAction:
    """Diagnostische Aktion."""
    action_id: str = ""
    description: str = ""
    command: str = ""
    expected_result: str = ""
    auto_fixable: bool = False
    
    def __post_init__(self):
        if not self.action_id:
            self.action_id = new_id("action")


class AutonomousServerAgent:
    """Autonomer Server-Agent."""
    
    def __init__(self):
        self.state = AgentState.IDLE
        self.issues: List[Issue] = []
        self.actions_history: List[dict] = []
        self.config = self._load_config()
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.diagnostic_callbacks: Dict[str, Callable] = {}
        self._register_diagnostics()
        
    def _load_config(self) -> dict:
        """Lade Server-Agent Konfiguration."""
        default_config = {
            "monitoring_interval": 300,  # 5 Minuten
            "auto_fix_enabled": False,
            "alert_threshold": Severity.WARNING,
            "monitored_services": [],
            "log_paths": [],
            "performance_thresholds": {
                "cpu_percent": 80,
                "memory_percent": 85,
                "disk_percent": 90
            }
        }
        
        try:
            if SERVER_AGENT_CONFIG_PATH.exists():
                loaded = json.loads(SERVER_AGENT_CONFIG_PATH.read_text(encoding="utf-8"))
                return {**default_config, **loaded}
        except Exception:
            pass
        
        return default_config
    
    def _save_config(self) -> None:
        """Speichere Server-Agent Konfiguration."""
        SERVER_AGENT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        SERVER_AGENT_CONFIG_PATH.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def _register_diagnostics(self) -> None:
        """Registriere Diagnostik-Callbacks."""
        self.diagnostic_callbacks = {
            "check_disk_space": self._diagnose_disk_space,
            "check_memory": self._diagnose_memory,
            "check_cpu": self._diagnose_cpu,
            "check_services": self._diagnose_services,
            "check_logs": self._diagnose_logs
        }
    
    def start(self) -> bool:
        """Starte den autonomen Agent."""
        if self.running:
            return False
        
        self.running = True
        self.state = AgentState.MONITORING
        self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitor_thread.start()
        return True
    
    def stop(self) -> bool:
        """Stoppe den autonomen Agent."""
        if not self.running:
            return False
        
        self.running = False
        self.state = AgentState.IDLE
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        return True
    
    def _monitoring_loop(self) -> None:
        """Haupt-Monitoring Loop."""
        while self.running:
            try:
                self._perform_monitoring()
                time.sleep(self.config.get("monitoring_interval", 300))
            except Exception as e:
                print(f"[ServerAgent] Monitoring error: {e}")
                time.sleep(60)  # Warte vor Retry
    
    def _perform_monitoring(self) -> None:
        """Führe Monitoring durch."""
        self.state = AgentState.MONITORING
        
        # Führe alle Diagnostiken aus
        for diag_name, diag_func in self.diagnostic_callbacks.items():
            try:
                new_issues = diag_func()
                for issue in new_issues:
                    self._handle_issue(issue)
            except Exception as e:
                print(f"[ServerAgent] Diagnostic {diag_name} error: {e}")
        
        # Auto-Fix wenn aktiviert
        if self.config.get("auto_fix_enabled", False):
            self._attempt_auto_fix()
    
    def _handle_issue(self, issue: Issue) -> None:
        """Behandle erkanntes Problem."""
        # Prüfe ob Problem bereits bekannt
        for existing in self.issues:
            if (existing.category == issue.category and 
                existing.description == issue.description and 
                not existing.resolved):
                return  # Bereits bekannt und nicht gelöst
        
        self.issues.append(issue)
        
        # Wenn Schweregrad Threshold erreicht, erstelle Alert
        alert_threshold = self.config.get("alert_threshold", Severity.WARNING)
        severity_order = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2, Severity.CRITICAL: 3}
        
        if severity_order.get(issue.severity, 0) >= severity_order.get(alert_threshold, 1):
            self._create_alert(issue)
    
    def _create_alert(self, issue: Issue) -> None:
        """Erstelle Alert für Problem."""
        alert = {
            "alert_id": new_id("alert"),
            "issue_id": issue.issue_id,
            "severity": issue.severity.value,
            "category": issue.category,
            "description": issue.description,
            "detected_at": issue.detected_at,
            "auto_fixable": self._is_auto_fixable(issue)
        }
        
        self.actions_history.append({
            "action": "alert_created",
            "timestamp": datetime.now().isoformat(),
            "details": alert
        })
        
        print(f"[ServerAgent] ALERT: {issue.severity.value.upper()} - {issue.description}")
    
    def _is_auto_fixable(self, issue: Issue) -> bool:
        """Prüfe ob Problem automatisch fixbar ist."""
        auto_fixable_categories = {
            "disk_space": True,
            "memory": False,
            "cpu": False,
            "service_down": True,
            "log_errors": False
        }
        return auto_fixable_categories.get(issue.category, False)
    
    def _attempt_auto_fix(self) -> None:
        """Versuche Probleme automatisch zu beheben."""
        for issue in self.issues:
            if issue.resolved or not self._is_auto_fixable(issue):
                continue
            
            self.state = AgentState.FIXING
            success = self._auto_fix_issue(issue)
            
            if success:
                issue.resolved = True
                issue.resolved_at = datetime.now().isoformat()
                issue.resolution = "Auto-fixed by agent"
    
    def _auto_fix_issue(self, issue: Issue) -> bool:
        """Versuche einzelnes Problem automatisch zu beheben."""
        try:
            if issue.category == "disk_space":
                return self._fix_disk_space(issue)
            elif issue.category == "service_down":
                return self._fix_service(issue)
            return False
        except Exception as e:
            print(f"[ServerAgent] Auto-fix error: {e}")
            return False
    
    def _fix_disk_space(self, issue: Issue) -> bool:
        """Automatische Disk-Space Bereinigung.
        
        Plattformkorrekt: Windows-Temp-Pfade auf Windows, POSIX-Pfade auf
        POSIX. Löscht ausschließlich Dateien (keine Verzeichnisse) älter
        als 7 Tage.
        """
        try:
            if sys.platform == "win32":
                temp_dirs = [
                    str(Path(os.environ.get("TEMP", r"C:\\Windows\\Temp"))),
                    str(Path(os.environ.get("TMP", r"C:\\Windows\\Temp"))),
                ]
            else:
                temp_dirs = ["/tmp", "/var/tmp"]
            
            cache_dir = Path.home() / ".cache"
            if cache_dir.exists():
                temp_dirs.append(str(cache_dir))
            
            for temp_dir in temp_dirs:
                temp_path = Path(temp_dir)
                if not temp_path.exists():
                    continue
                # Alte Dateien löschen (>7 Tage)
                cutoff = datetime.now() - timedelta(days=7)
                for item in temp_path.iterdir():
                    try:
                        if not item.is_file():
                            continue
                        stat = item.stat()
                        file_time = datetime.fromtimestamp(stat.st_mtime)
                        if file_time < cutoff:
                            try:
                                item.unlink()
                            except Exception:
                                pass
                    except (OSError, ValueError):
                        continue
            
            return True
        except Exception:
            return False
    
    def _fix_service(self, issue: Issue) -> bool:
        """Automatischer Service-Restart.
        
        Nutzt das maschinenlesbare `target`-Feld statt den Service-Namen
        aus der Freitext-Beschreibung zu parsen.
        """
        import subprocess
        
        try:
            service_name = (issue.target or "").strip()
            if not service_name or any(ch.isspace() for ch in service_name):
                print(f"[ServerAgent] Refusing restart: no valid service target")
                return False
            
            # Versuche Service zu restarten
            result = subprocess.run(
                ["systemctl", "restart", service_name],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            return result.returncode == 0
        except Exception:
            return False
    
    # ── Diagnostik-Methoden ────────────────────────────────────────────────────
    
    def _diagnose_disk_space(self) -> List[Issue]:
        """Diagnostiziere Disk-Space."""
        issues = []
        
        try:
            import shutil
            paths_to_check = [Path.home(), Path("/")]
            
            for path in paths_to_check:
                if not path.exists():
                    continue
                
                usage = shutil.disk_usage(path)
                percent_used = (usage.used / usage.total) * 100
                
                threshold = self.config.get("performance_thresholds", {}).get("disk_percent", 90)
                
                if percent_used >= threshold:
                    severity = Severity.CRITICAL if percent_used >= 95 else Severity.ERROR
                    issues.append(Issue(
                        issue_id=new_id("disk"),
                        severity=severity,
                        category="disk_space",
                        description=f"Disk space {percent_used:.1f}% used on {path}",
                        detected_at=datetime.now().isoformat()
                    ))
                    
        except Exception as e:
            print(f"[ServerAgent] Disk diagnostic error: {e}")
        
        return issues
    
    def _diagnose_memory(self) -> List[Issue]:
        """Diagnostiziere Memory."""
        issues = []
        
        try:
            import psutil
            mem = psutil.virtual_memory()
            percent_used = mem.percent
            
            threshold = self.config.get("performance_thresholds", {}).get("memory_percent", 85)
            
            if percent_used >= threshold:
                severity = Severity.CRITICAL if percent_used >= 95 else Severity.ERROR
                issues.append(Issue(
                    issue_id=new_id("memory"),
                    severity=severity,
                    category="memory",
                    description=f"Memory {percent_used:.1f}% used",
                    detected_at=datetime.now().isoformat()
                ))
                    
        except ImportError:
            # Fallback ohne psutil
            pass
        except Exception as e:
            print(f"[ServerAgent] Memory diagnostic error: {e}")
        
        return issues
    
    def _diagnose_cpu(self) -> List[Issue]:
        """Diagnostiziere CPU."""
        issues = []
        
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=1)
            
            threshold = self.config.get("performance_thresholds", {}).get("cpu_percent", 80)
            
            if cpu_percent >= threshold:
                severity = Severity.CRITICAL if cpu_percent >= 95 else Severity.ERROR
                issues.append(Issue(
                    issue_id=new_id("cpu"),
                    severity=severity,
                    category="cpu",
                    description=f"CPU {cpu_percent:.1f}% used",
                    detected_at=datetime.now().isoformat()
                ))
                    
        except ImportError:
            pass
        except Exception as e:
            print(f"[ServerAgent] CPU diagnostic error: {e}")
        
        return issues
    
    def _diagnose_services(self) -> List[Issue]:
        """Diagnostiziere Services."""
        issues = []
        
        services_to_check = self.config.get("monitored_services", [])
        
        for service_name in services_to_check:
            try:
                import subprocess
                result = subprocess.run(
                    ["systemctl", "is-active", service_name],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.stdout.strip() != "active":
                    issues.append(Issue(
                        issue_id=new_id("service"),
                        severity=Severity.ERROR,
                        category="service_down",
                        description=f"Service {service_name} is not active",
                        detected_at=datetime.now().isoformat(),
                        target=service_name,
                    ))
                    
            except Exception:
                pass
        
        return issues
    
    def _diagnose_logs(self) -> List[Issue]:
        """Diagnostiziere Logs."""
        issues = []
        
        log_paths = self.config.get("log_paths", [])
        
        for log_path in log_paths:
            try:
                log_file = Path(log_path)
                if not log_file.exists():
                    continue
                
                # Suche nach ERROR Patterns
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                error_count = content.count("ERROR")
                
                if error_count > 10:  # Threshold
                    issues.append(Issue(
                        issue_id=new_id("log"),
                        severity=Severity.WARNING,
                        category="log_errors",
                        description=f"Found {error_count} errors in {log_path}",
                        detected_at=datetime.now().isoformat()
                    ))
                    
            except Exception:
                pass
        
        return issues
    
    # ── Manuelles Diagnose ───────────────────────────────────────────────────
    
    def diagnose_specific(self, diagnostic_name: str) -> List[Issue]:
        """
        Führe spezifische Diagnose aus.
        
        Args:
            diagnostic_name: Name der Diagnose
            
        Returns:
            Liste der erkannten Probleme
        """
        diag_func = self.diagnostic_callbacks.get(diagnostic_name)
        if diag_func:
            self.state = AgentState.DIAGNOSING
            issues = diag_func()
            self.state = AgentState.MONITORING
            return issues
        return []
    
    def get_status(self) -> dict:
        """Gib aktuellen Agent-Status zurück."""
        unresolved_issues = [i for i in self.issues if not i.resolved]
        
        return {
            "state": self.state.value,
            "running": self.running,
            "total_issues": len(self.issues),
            "unresolved_issues": len(unresolved_issues),
            "auto_fix_enabled": self.config.get("auto_fix_enabled", False),
            "monitoring_interval": self.config.get("monitoring_interval", 300),
            "last_activity": self.actions_history[-1] if self.actions_history else None
        }
    
    def get_issues(self, unresolved_only: bool = True) -> List[dict]:
        """Gib Probleme zurück."""
        issues = self.issues if not unresolved_only else [i for i in self.issues if not i.resolved]
        return [asdict(i) for i in issues]
    
    def get_action_history(self, limit: int = 20) -> List[dict]:
        """Gib Aktions-Historie zurück."""
        return self.actions_history[-limit:]


# Globale Instanz für einfache Nutzung
_autonomous_server_agent = None

def get_autonomous_server_agent() -> AutonomousServerAgent:
    """Gibt die globale AutonomousServerAgent Instanz zurück."""
    global _autonomous_server_agent
    if _autonomous_server_agent is None:
        _autonomous_server_agent = AutonomousServerAgent()
    return _autonomous_server_agent
