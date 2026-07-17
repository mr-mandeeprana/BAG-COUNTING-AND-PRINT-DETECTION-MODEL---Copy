"""
==========================================================
FillPac AI
Dashboard Broadcast Module
==========================================================
"""

import json
import os
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import threading
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
        self.service_status = {}
        self.start_time = datetime.now(timezone.utc)
        self.last_persist_time = 0.0
        self._lock = threading.RLock()
        self._dirty = False
        self._stop_event = threading.Event()
        self._persist_event = threading.Event()
        self._persistence_thread = None

        if self.enabled:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing_state()
            self._start_background_persistence()

    def set_system_status(self, status):
        with self._lock:
            self.system_status = status
            self._dirty = True
        self._persist_event.set()
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
        with self._lock:
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
            if state_changed:
                self._dirty = True
        if state_changed:
            self._persist_event.set()
            self._persist(force=True)

    def update_health(self, health_info):
        if not health_info:
            return

        with self._lock:
            self.service_status.update(health_info)
            self._dirty = True
        self._persist_event.set()

    def snapshot(self):
        with self._lock:
            return self._snapshot_in_memory()

    def _persist(self, force=False):
        if not self.enabled:
            return

        with self._lock:
            now = time.monotonic()
            if not force and not self._dirty and (now - self.last_persist_time) < self.persist_interval_seconds:
                return
            snapshot = self._snapshot_in_memory()
            self._dirty = False

        try:
            self._write_state(snapshot)
            self.last_persist_time = now
        except OSError as error:
            self._log("warning", f"Dashboard state write failed: {error}")
            with self._lock:
                self._dirty = True

    def _write_state(self, data):
        temp_file = self.state_file.with_suffix(self.state_file.suffix + f".{uuid.uuid4().hex}.tmp")
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

        try:
            temp_file.replace(self.state_file)
        except OSError as error:
            if error.errno in {13, 32}:
                self._write_state_fallback(data, temp_file)
            else:
                raise

    def _write_state_fallback(self, data, temp_file):
        try:
            if self.state_file.exists():
                os.remove(self.state_file)
            temp_file.replace(self.state_file)
        except OSError:
            with open(self.state_file, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
        finally:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)

    def _snapshot_in_memory(self):
        total_count = sum(camera["count"] for camera in self.cameras.values())
        total_printed_count = sum(camera.get("printed_count", 0) for camera in self.cameras.values())
        total_missing_count = sum(camera.get("missing_count", 0) for camera in self.cameras.values())
        return {
            "system_status": self.system_status,
            "startup_time": self.start_time.isoformat(),
            "service_status": deepcopy(self.service_status),
            "total_count": total_count,
            "total_printed_count": total_printed_count,
            "total_missing_count": total_missing_count,
            "total_printed_bags_count": total_printed_count,
            "total_not_printed_bags_count": total_missing_count,
            "cameras": deepcopy(self.cameras),
        }

    def _start_background_persistence(self):
        self._persistence_thread = threading.Thread(
            target=self._persistence_worker,
            daemon=True,
            name="DashboardPersistence",
        )
        self._persistence_thread.start()

    def _persistence_worker(self):
        while not self._stop_event.is_set():
            self._persist()
            self._persist_event.wait(timeout=self.persist_interval_seconds)
            self._persist_event.clear()

        self._persist(force=True)

    def close(self):
        if not self.enabled:
            return

        self._stop_event.set()
        self._persist_event.set()
        if self._persistence_thread is not None:
            self._persistence_thread.join(timeout=5)

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
        self.start_time = datetime.fromisoformat(state.get("startup_time", self.start_time.isoformat()))
        self.service_status = state.get("service_status", self.service_status)

        cameras = state.get("cameras", {})
        if isinstance(cameras, dict):
            self.cameras = cameras
        self.last_persist_time = time.monotonic()

    def _log(self, level, message):
        if self.logger is not None:
            getattr(self.logger, level)(message)
            return

        print(f"[{level.upper()}] {message}")