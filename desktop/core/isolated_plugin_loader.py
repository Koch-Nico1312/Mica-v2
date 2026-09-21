"""
Process-Isolated Plugin System

Runs plugins in isolated subprocesses for true crash isolation and security.
Each plugin runs in its own process with controlled resources and communication
via IPC (inter-process communication).
"""
from __future__ import annotations

import json
import multiprocessing
import os
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, Callable, Optional

# Import the existing plugin loader for discovery
from core.plugin_loader import PluginRecord, discover_plugins


@dataclass
class PluginMessage:
    """Message type for plugin IPC."""
    type: str  # "execute", "result", "error", "heartbeat"
    plugin_name: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class PluginProcess:
    """Represents a running plugin process."""
    plugin_name: str
    process: multiprocessing.Process
    parent_conn: Connection
    child_conn: Connection
    record: PluginRecord
    last_heartbeat: float = field(default_factory=time.time)
    restart_count: int = 0
    max_restarts: int = 3


class IsolatedPluginLoader:
    """
    Process-isolated plugin loader with true crash isolation.
    
    Features:
    - Each plugin runs in its own subprocess
    - Crash isolation - plugin crashes don't affect main process
    - Resource limits (CPU, memory, timeout)
    - Automatic restart on failure
    - Health monitoring via heartbeats
    - IPC-based communication
    """

    def __init__(
        self,
        plugins_dir: Path | str,
        core_tool_names: set[str],
        logger: Callable[[str], None] = print,
        max_plugin_memory_mb: int = 512,
        plugin_timeout_seconds: int = 30,
    ):
        self.plugins_dir = Path(plugins_dir)
        self.core_tool_names = core_tool_names
        self.logger = logger
        self.max_plugin_memory_mb = max_plugin_memory_mb
        self.plugin_timeout_seconds = plugin_timeout_seconds
        
        # Plugin processes registry
        self.plugin_processes: dict[str, PluginProcess] = {}
        
        # First, discover plugins using the existing loader
        self._discover_plugins()

    def _discover_plugins(self) -> None:
        """Discover available plugins using the existing loader."""
        self.logger("[IsolatedPluginLoader] Discovering plugins...")
        
        # Use existing plugin loader for discovery
        from core.plugin_loader import discover_plugins
        self.plugin_registry = discover_plugins(
            plugins_dir=self.plugins_dir,
            core_tool_names=self.core_tool_names,
            logger=self.logger,
        )

    def start_plugin(self, plugin_name: str) -> bool:
        """
        Start a plugin in an isolated process.
        
        Args:
            plugin_name: Name of the plugin to start
            
        Returns:
            True if started successfully
        """
        if plugin_name in self.plugin_processes:
            self.logger(f"[IsolatedPluginLoader] Plugin {plugin_name} already running")
            return True
        
        # Get plugin record
        plugin_record = None
        for rec in self.plugin_registry._all_records:
            if rec.name == plugin_name and rec.valid:
                plugin_record = rec
                break
        
        if not plugin_record:
            self.logger(f"[IsolatedPluginLoader] Plugin {plugin_name} not found or invalid")
            return False
        
        # Create IPC pipes
        parent_conn, child_conn = multiprocessing.Pipe()
        
        # Create plugin process
        process = multiprocessing.Process(
            target=self._run_plugin_process,
            args=(
                plugin_name,
                str(self.plugins_dir),
                child_conn,
                self.max_plugin_memory_mb,
                self.plugin_timeout_seconds,
            ),
            daemon=True,  # Daemon process - will be killed if main process exits
        )
        
        # Start process
        process.start()
        
        # Close child connection in parent
        child_conn.close()
        
        # Register plugin process
        self.plugin_processes[plugin_name] = PluginProcess(
            plugin_name=plugin_name,
            process=process,
            parent_conn=parent_conn,
            child_conn=child_conn,  # Keep reference but don't use
            record=plugin_record,
        )
        
        self.logger(f"[IsolatedPluginLoader] Started plugin: {plugin_name} (PID: {process.pid})")
        return True

    def stop_plugin(self, plugin_name: str) -> bool:
        """
        Stop a running plugin.
        
        Args:
            plugin_name: Name of the plugin to stop
            
        Returns:
            True if stopped successfully
        """
        if plugin_name not in self.plugin_processes:
            self.logger(f"[IsolatedPluginLoader] Plugin {plugin_name} not running")
            return False
        
        plugin_proc = self.plugin_processes[plugin_name]
        
        # Terminate process
        plugin_proc.process.terminate()
        plugin_proc.process.join(timeout=5)
        
        if plugin_proc.process.is_alive():
            # Force kill if terminate didn't work
            plugin_proc.process.kill()
            plugin_proc.process.join(timeout=2)
        
        # Close connection
        plugin_proc.parent_conn.close()
        
        # Remove from registry
        del self.plugin_processes[plugin_name]
        
        self.logger(f"[IsolatedPluginLoader] Stopped plugin: {plugin_name}")
        return True

    def _run_plugin_process(
        self,
        plugin_name: str,
        plugins_dir: str,
        conn: Connection,
        max_memory_mb: int,
        timeout_seconds: int,
    ) -> None:
        """
        Run a plugin in an isolated process.
        
        This function runs in the child process.
        """
        # Set resource limits
        try:
            import resource
            # Memory limit (convert MB to bytes)
            memory_limit = max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
        except (ImportError, AttributeError):
            # resource module not available on all platforms
            pass
        
        # Import and load the plugin
        try:
            import importlib.util
            
            plugin_path = Path(plugins_dir) / f"{plugin_name}.py"
            if not plugin_path.exists():
                conn.send(PluginMessage(
                    type="error",
                    plugin_name=plugin_name,
                    payload={"error": f"Plugin file not found: {plugin_path}"}
                ))
                return
            
            # Load plugin module
            spec = importlib.util.spec_from_file_location(plugin_name, plugin_path)
            if spec is None or spec.loader is None:
                conn.send(PluginMessage(
                    type="error",
                    plugin_name=plugin_name,
                    payload={"error": "Could not load plugin spec"}
                ))
                return
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Get run function
            run_fn = getattr(module, "run", None)
            if not callable(run_fn):
                conn.send(PluginMessage(
                    type="error",
                    plugin_name=plugin_name,
                    payload={"error": "Plugin has no callable run() function"}
                ))
                return
            
            # Send heartbeat and wait for commands
            conn.send(PluginMessage(
                type="heartbeat",
                plugin_name=plugin_name,
                payload={"status": "ready"}
            ))
            
            # Main loop - wait for execute commands
            while True:
                try:
                    # Wait for message with timeout
                    if conn.poll(timeout=1.0):
                        msg = conn.recv()
                        if not isinstance(msg, PluginMessage):
                            continue
                        
                        if msg.type == "execute":
                            # Execute plugin
                            try:
                                parameters = msg.payload.get("parameters", {})
                                result = run_fn(parameters)
                                
                                conn.send(PluginMessage(
                                    type="result",
                                    plugin_name=plugin_name,
                                    payload={"result": result}
                                ))
                            except Exception as e:
                                conn.send(PluginMessage(
                                    type="error",
                                    plugin_name=plugin_name,
                                    payload={"error": str(e), "traceback": traceback.format_exc()}
                                ))
                        
                        elif msg.type == "shutdown":
                            # Graceful shutdown
                            break
                    
                    # Send periodic heartbeat
                    conn.send(PluginMessage(
                        type="heartbeat",
                        plugin_name=plugin_name,
                        payload={"status": "running"}
                    ))
                
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    conn.send(PluginMessage(
                        type="error",
                        plugin_name=plugin_name,
                        payload={"error": f"Plugin loop error: {e}"}
                    ))
                    break
        
        except Exception as e:
            conn.send(PluginMessage(
                type="error",
                plugin_name=plugin_name,
                payload={"error": f"Plugin initialization failed: {e}", "traceback": traceback.format_exc()}
            ))
        finally:
            conn.close()

    def execute_plugin(
        self,
        plugin_name: str,
        parameters: dict[str, Any],
        player=None,
        session_memory=None,
    ) -> str:
        """
        Execute a plugin in its isolated process.
        
        Args:
            plugin_name: Name of the plugin to execute
            parameters: Parameters to pass to the plugin
            player: UI player (not passed to isolated process)
            session_memory: Session memory (not passed to isolated process)
            
        Returns:
            Result from plugin execution
        """
        # Ensure plugin is running
        if plugin_name not in self.plugin_processes:
            if not self.start_plugin(plugin_name):
                return f"Failed to start plugin: {plugin_name}"
        
        plugin_proc = self.plugin_processes[plugin_name]
        
        # Send execute command
        try:
            message = PluginMessage(
                type="execute",
                plugin_name=plugin_name,
                payload={"parameters": parameters}
            )
            
            plugin_proc.parent_conn.send(message)
            
            # Wait for result with timeout
            start_time = time.time()
            while time.time() - start_time < self.plugin_timeout_seconds:
                if plugin_proc.parent_conn.poll(timeout=0.1):
                    response = plugin_proc.parent_conn.recv()
                    if isinstance(response, PluginMessage):
                        if response.type == "result":
                            plugin_proc.last_heartbeat = time.time()
                            return str(response.payload.get("result", "Done."))
                        elif response.type == "error":
                            plugin_proc.last_heartbeat = time.time()
                            error_msg = response.payload.get("error", "Unknown error")
                            self.logger(f"[IsolatedPluginLoader] Plugin error: {plugin_name} - {error_msg}")
                            
                            # Attempt restart on error
                            if plugin_proc.restart_count < plugin_proc.max_restarts:
                                self.logger(f"[IsolatedPluginLoader] Restarting plugin: {plugin_name}")
                                self.stop_plugin(plugin_name)
                                plugin_proc.restart_count += 1
                                if self.start_plugin(plugin_name):
                                    return f"Plugin restarted after error: {error_msg}"
                            
                            return f"Plugin failed: {error_msg}"
                        elif response.type == "heartbeat":
                            plugin_proc.last_heartbeat = time.time()
            
            # Timeout
            self.logger(f"[IsolatedPluginLoader] Plugin timeout: {plugin_name}")
            self.stop_plugin(plugin_name)
            return f"Plugin execution timed out: {plugin_name}"
        
        except Exception as e:
            self.logger(f"[IsolatedPluginLoader] Plugin execution error: {plugin_name} - {e}")
            return f"Plugin execution failed: {e}"

    def health_check(self) -> dict[str, Any]:
        """
        Perform health check on all running plugins.
        
        Returns:
            Health status dictionary
        """
        current_time = time.time()
        health_status = {}
        
        for plugin_name, plugin_proc in self.plugin_processes.items():
            # Check if process is alive
            is_alive = plugin_proc.process.is_alive()
            
            # Check heartbeat (plugin should send heartbeat every 1-2 seconds)
            heartbeat_age = current_time - plugin_proc.last_heartbeat
            is_healthy = is_alive and heartbeat_age < 5.0
            
            health_status[plugin_name] = {
                "alive": is_alive,
                "healthy": is_healthy,
                "heartbeat_age": heartbeat_age,
                "restart_count": plugin_proc.restart_count,
                "pid": plugin_proc.process.pid if is_alive else None,
            }
            
            # Restart unhealthy plugins
            if not is_healthy and is_alive:
                self.logger(f"[IsolatedPluginLoader] Unhealthy plugin detected: {plugin_name}")
                self.stop_plugin(plugin_name)
                if plugin_proc.restart_count < plugin_proc.max_restarts:
                    plugin_proc.restart_count += 1
                    self.start_plugin(plugin_name)
        
        return health_status

    def get_tool_declarations(self) -> list[dict]:
        """Get tool declarations for enabled plugins."""
        # Use the existing registry's method
        return self.plugin_registry.get_tool_declarations()

    def list_for_ui(self) -> list[dict]:
        """List all plugins for UI display."""
        # Use the existing registry's method
        return self.plugin_registry.list_for_ui()

    def shutdown_all(self) -> None:
        """Stop all running plugins."""
        self.logger("[IsolatedPluginLoader] Shutting down all plugins...")
        
        for plugin_name in list(self.plugin_processes.keys()):
            self.stop_plugin(plugin_name)
        
        self.logger("[IsolatedPluginLoader] All plugins stopped")

    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.shutdown_all()
        except Exception:
            pass