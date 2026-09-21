"""Headless room satellite node daemon for Raspberry Pi or secondary Linux/Windows hosts.

Registers as a physical hardware presence anchor for MICA, periodically sending
telemetry heartbeats and polling for room-level announcements.
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import time
from datetime import UTC, datetime
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


class SatelliteNodeClient:
    """Satellite client daemon connecting to MICA Core API."""

    def __init__(
        self,
        core_url: str,
        satellite_id: str,
        name: str,
        room: str,
        heartbeat_interval: int = 10,
    ):
        self.core_url = core_url.rstrip("/")
        self.satellite_id = satellite_id
        self.name = name
        self.room = room
        self.heartbeat_interval = heartbeat_interval
        self._running = False

    def collect_local_telemetry(self) -> dict[str, Any]:
        """Collect local host metrics (CPU temp, load, uptime)."""
        telem: dict[str, Any] = {
            "platform": platform.platform(),
            "hostname": platform.node(),
            "python_version": platform.python_version(),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        # Try reading Raspberry Pi thermal zone
        thermal_path = "/sys/class/thermal/thermal_zone0/temp"
        if os.path.exists(thermal_path):
            try:
                with open(thermal_path, "r") as f:
                    temp_millidegrees = int(f.read().strip())
                    telem["cpu_temp_celsius"] = round(temp_millidegrees / 1000.0, 1)
            except Exception:
                pass
        return telem

    def register(self) -> bool:
        if not httpx:
            print("[SatelliteNode] Warning: httpx is not installed. Running in mock mode.")
            return True
        try:
            url = f"{self.core_url}/v1/satellites/register"
            payload = {
                "satellite_id": self.satellite_id,
                "name": self.name,
                "room": self.room,
                "capabilities": ["mic", "speaker", "led_ring"],
            }
            res = httpx.post(url, json=payload, timeout=10.0)
            res.raise_for_status()
            print(f"[SatelliteNode] Successfully registered satellite '{self.name}' in room '{self.room}'.")
            return True
        except Exception as err:
            print(f"[SatelliteNode] Registration failed: {err}")
            return False

    def send_heartbeat(self) -> list[dict[str, Any]]:
        if not httpx:
            return []
        try:
            url = f"{self.core_url}/v1/satellites/{self.satellite_id}/heartbeat"
            payload = self.collect_local_telemetry()
            res = httpx.post(url, json={"telemetry": payload}, timeout=10.0)
            res.raise_for_status()
            data = res.json()
            return data.get("announcements", [])
        except Exception as err:
            print(f"[SatelliteNode] Heartbeat failed: {err}")
            return []

    def run_loop(self) -> None:
        self._running = True
        print(f"[SatelliteNode] Starting heartbeat loop for {self.satellite_id} (interval={self.heartbeat_interval}s)")
        self.register()
        while self._running:
            try:
                announcements = self.send_heartbeat()
                for ann in announcements:
                    print(f"[SatelliteNode] Received room announcement: {ann.get('message')}")
                    # Acknowledge announcement
                    ann_id = ann.get("id")
                    if ann_id and httpx:
                        try:
                            httpx.post(f"{self.core_url}/v1/satellites/announcements/{ann_id}/delivered", timeout=5.0)
                        except Exception:
                            pass
            except Exception as loop_err:
                print(f"[SatelliteNode] Unexpected loop error: {loop_err}")
            time.sleep(self.heartbeat_interval)

    def stop(self) -> None:
        self._running = False


def main() -> None:
    parser = argparse.ArgumentParser(description="MICA Hardware Anchor Satellite Node")
    parser.add_argument("--core-url", default=os.getenv("MICA_CORE_URL", "http://localhost:8000"))
    parser.add_argument("--id", default=os.getenv("MICA_SATELLITE_ID", "satellite-pi-room1"))
    parser.add_argument("--name", default=os.getenv("MICA_SATELLITE_NAME", "Room Anchor"))
    parser.add_argument("--room", default=os.getenv("MICA_SATELLITE_ROOM", "Labor"))
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()

    client = SatelliteNodeClient(
        core_url=args.core_url,
        satellite_id=args.id,
        name=args.name,
        room=args.room,
        heartbeat_interval=args.interval,
    )
    try:
        client.run_loop()
    except KeyboardInterrupt:
        print("\n[SatelliteNode] Shutting down cleanly.")
        client.stop()


if __name__ == "__main__":
    main()
