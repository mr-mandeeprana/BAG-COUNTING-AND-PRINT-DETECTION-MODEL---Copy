"""
==========================================================
FillPac AI
Dashboard Broadcast Module
==========================================================
"""

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import time


class DashboardState:
    def __init__(
        self,
        enabled=True,
        state_file="dashboard/backend/state.json",
        logger=None,
        persist_interval_seconds=0.25,
    ):
        self.enabled = enabled
        self.logger = logger
        self.state_file = Path(state_file)
        self.persist_interval_seconds = max(float(persist_interval_seconds), 0.0)
        self.system_status = "idle"
        self.cameras = {}
        self.last_persist_time = 0.0

        if self.enabled:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing_state()

    def set_system_status(self, status):
        self.system_status = status
        self._persist(force=True)

    def update_camera(
        self,
        camera_name,
        count,
        fps,
        status,
        print_status=None,
        printed_count=0,
        missing_count=0,
        printed_bags_count=0,
        not_printed_bags_count=0,
    ):
        previous_state = self.cameras.get(camera_name)
        self.cameras[camera_name] = {
            "count": count,
            "printed_count": printed_count,
            "missing_count": missing_count,
            "printed_bags_count": printed_bags_count,
            "not_printed_bags_count": not_printed_bags_count,
            "fps": round(float(fps), 2),
            "status": status,
            "print_status": print_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        state_changed = previous_state is None or any(
            previous_state.get(key) != self.cameras[camera_name].get(key)
            for key in (
                "count",
                "printed_count",
                "missing_count",
                "printed_bags_count",
                "not_printed_bags_count",
                "status",
                "print_status",
            )
        )
        self._persist(force=state_changed)

    def snapshot(self):
        return self._snapshot_in_memory()

    def _persist(self, force=False):
        if not self.enabled:
            return

        now = time.monotonic()
        if not force and (now - self.last_persist_time) < self.persist_interval_seconds:
            return

        try:
            with open(self.state_file, "w", encoding="utf-8") as file:
                json.dump(self._snapshot_in_memory(), file, indent=2)
            self.last_persist_time = now
        except OSError as error:
            self._log("warning", f"Dashboard state write failed: {error}")

    def _snapshot_in_memory(self):
        total_count = sum(camera["count"] for camera in self.cameras.values())
        total_printed_count = sum(camera.get("printed_count", 0) for camera in self.cameras.values())
        total_missing_count = sum(camera.get("missing_count", 0) for camera in self.cameras.values())
        return {
            "system_status": self.system_status,
            "total_count": total_count,
            "total_printed_count": total_printed_count,
            "total_missing_count": total_missing_count,
            "total_printed_bags_count": total_printed_count,
            "total_not_printed_bags_count": total_missing_count,
            "cameras": deepcopy(self.cameras),
        }

    def _load_existing_state(self):
        if not self.state_file.exists():
            self._persist(force=True)
            return

        try:
            with open(self.state_file, "r", encoding="utf-8") as file:
                state = json.load(file)
        except (json.JSONDecodeError, OSError) as error:
            self._log("warning", f"Dashboard state read failed: {error}")
            self._persist(force=True)
            return

        self.system_status = state.get("system_status", self.system_status)

        cameras = state.get("cameras", {})
        if isinstance(cameras, dict):
            self.cameras = cameras
        self.last_persist_time = time.monotonic()

    def _log(self, level, message):
        if self.logger is not None:
            getattr(self.logger, level)(message)
            return

        print(f"[{level.upper()}] {message}")
