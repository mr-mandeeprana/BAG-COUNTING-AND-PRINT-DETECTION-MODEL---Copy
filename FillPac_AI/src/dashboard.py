"""
==========================================================
FillPac AI
Dashboard State Module
==========================================================

Purpose
-------
Thread-safe dashboard state manager.

Architecture
------------
Pipeline
    |
    v
DashboardState
    |
    v
dashboard/backend/state.json
    |
    v
FastAPI Dashboard Backend
    |
    +---- REST API
    |
    +---- Socket.IO
    |
    v
Dashboard Frontend

Features
--------
- Thread-safe camera updates
- Global production totals
- Printed / not-printed totals
- Camera FPS/status
- Service health
- Background persistence
- Graceful shutdown
- Existing-state restoration
- Absolute project-relative state path
==========================================================
"""

import json
import threading
import time

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


# ==========================================================
# PROJECT PATHS
# ==========================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DEFAULT_STATE_FILE = (
    PROJECT_ROOT
    / "dashboard"
    / "backend"
    / "state.json"
)


# ==========================================================
# DASHBOARD STATE
# ==========================================================

class DashboardState:

    def __init__(
        self,
        enabled=True,
        state_file=None,
        logger=None,
        persist_interval_seconds=0.25,
    ):

        # ==================================================
        # CONFIGURATION
        # ==================================================

        self.enabled = bool(enabled)

        self.logger = logger

        self.persist_interval_seconds = max(
            float(persist_interval_seconds),
            0.1,
        )

        # ==================================================
        # STATE FILE
        # ==================================================

        if state_file:

            state_path = Path(
                state_file
            )

            if state_path.is_absolute():

                self.state_file = (
                    state_path.resolve()
                )

            else:

                self.state_file = (
                    PROJECT_ROOT
                    / state_path
                ).resolve()

        else:

            self.state_file = (
                DEFAULT_STATE_FILE.resolve()
            )

        # ==================================================
        # APPLICATION STATE
        # ==================================================

        self.system_status = "idle"

        self.cameras = {}

        self.service_status = {}

        self.start_time = datetime.now(
            timezone.utc
        )

        # ==================================================
        # THREADING
        # ==================================================

        self._lock = threading.RLock()

        self._stop_event = threading.Event()

        self._persist_event = threading.Event()

        self._persistence_thread = None

        self._dirty = False

        self._closed = False

        self.last_persist_time = 0.0

        # ==================================================
        # INITIALIZATION
        # ==================================================

        if self.enabled:

            self.state_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            self._log(
                "info",
                (
                    "Dashboard state file: "
                    f"{self.state_file}"
                ),
            )

            # Restore previous counts if state exists.
            self._load_existing_state()

            # Start single persistence worker.
            self._start_background_persistence()

            # Force initial state write.
            self._mark_dirty()

    # ======================================================
    # SYSTEM STATUS
    # ======================================================

    def set_system_status(
        self,
        status,
    ):

        if not self.enabled:
            return

        status = str(
            status
        )

        with self._lock:

            if (
                self.system_status
                == status
            ):
                return

            self.system_status = status

            self._dirty = True

        self._persist_event.set()

    # ======================================================
    # CAMERA UPDATE
    # ======================================================

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

        if not self.enabled:
            return

        if self._closed:
            return

        camera_name = str(
            camera_name
        )

        # ==================================================
        # NORMALIZE VALUES
        # ==================================================

        count = self._safe_int(
            count
        )

        fps = self._safe_float(
            fps
        )

        printed_count = self._safe_int(
            printed_count
        )

        missing_count = self._safe_int(
            missing_count
        )

        printed_bags_count = self._safe_int(
            printed_bags_count
        )

        not_printed_bags_count = self._safe_int(
            not_printed_bags_count
        )

        # ==================================================
        # COMPATIBILITY ALIASES
        # ==================================================

        if (
            printed_count == 0
            and printed_bags_count > 0
        ):

            printed_count = (
                printed_bags_count
            )

        if (
            missing_count == 0
            and not_printed_bags_count > 0
        ):

            missing_count = (
                not_printed_bags_count
            )

        # ==================================================
        # BUILD CAMERA STATE
        # ==================================================

        camera_state = {

            "count":
                count,

            "printed_count":
                printed_count,

            "missing_count":
                missing_count,

            # Backward-compatible names
            "printed_bags_count":
                printed_count,

            "not_printed_bags_count":
                missing_count,

            "fps":
                round(
                    fps,
                    2,
                ),

            "status":
                str(
                    status
                    or
                    "offline"
                ),

            "print_status":
                print_status,

            "updated_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

        }

        # ==================================================
        # STORE CAMERA STATE
        # ==================================================

        with self._lock:

            previous_state = (
                self.cameras.get(
                    camera_name
                )
            )

            self.cameras[
                camera_name
            ] = camera_state

            self._dirty = True

        # Wake persistence worker.
        self._persist_event.set()

        # ==================================================
        # COUNT CHANGE LOGGING
        # ==================================================

        if previous_state is not None:

            old_count = self._safe_int(

                previous_state.get(
                    "count",
                    0,
                )

            )

            if count != old_count:

                self._log(
                    "info",
                    (
                        f"Dashboard {camera_name}: "
                        f"{old_count} -> {count}"
                    ),
                )

    # ======================================================
    # SERVICE HEALTH
    # ======================================================

    def update_health(
        self,
        health_info,
    ):

        if not self.enabled:
            return

        if self._closed:
            return

        if not isinstance(
            health_info,
            dict,
        ):
            return

        with self._lock:

            self.service_status.update(
                health_info
            )

            self._dirty = True

        self._persist_event.set()

    # ======================================================
    # SNAPSHOT
    # ======================================================

    def snapshot(
        self,
    ):

        with self._lock:

            return self._snapshot_in_memory()

    # ======================================================
    # BUILD SNAPSHOT
    # ======================================================

    def _snapshot_in_memory(
        self,
    ):

        # ==================================================
        # TOTAL BAG COUNT
        # ==================================================

        total_count = sum(

            self._safe_int(

                camera.get(
                    "count",
                    0,
                )

            )

            for camera
            in self.cameras.values()

        )

        # ==================================================
        # TOTAL PRINTED
        # ==================================================

        total_printed_count = sum(

            self._safe_int(

                camera.get(

                    "printed_count",

                    camera.get(
                        "printed_bags_count",
                        0,
                    ),

                )

            )

            for camera
            in self.cameras.values()

        )

        # ==================================================
        # TOTAL NOT PRINTED
        # ==================================================

        total_missing_count = sum(

            self._safe_int(

                camera.get(

                    "missing_count",

                    camera.get(
                        "not_printed_bags_count",
                        0,
                    ),

                )

            )

            for camera
            in self.cameras.values()

        )

        # ==================================================
        # FINAL SNAPSHOT
        # ==================================================

        return {

            "system_status":
                self.system_status,

            "startup_time":
                self.start_time.isoformat(),

            "service_status":
                deepcopy(
                    self.service_status
                ),

            "total_count":
                total_count,

            "total_printed_count":
                total_printed_count,

            "total_missing_count":
                total_missing_count,

            # Compatibility fields

            "total_printed_bags_count":
                total_printed_count,

            "total_not_printed_bags_count":
                total_missing_count,

            "cameras":
                deepcopy(
                    self.cameras
                ),

            "updated_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

        }

    # ======================================================
    # MARK DIRTY
    # ======================================================

    def _mark_dirty(
        self,
    ):

        with self._lock:

            self._dirty = True

        self._persist_event.set()

    # ======================================================
    # START BACKGROUND PERSISTENCE
    # ======================================================

    def _start_background_persistence(
        self,
    ):

        if (

            self._persistence_thread
            is not None

            and

            self._persistence_thread.is_alive()

        ):

            return

        self._persistence_thread = (
            threading.Thread(

                target=
                    self._persistence_worker,

                daemon=True,

                name=
                    "DashboardPersistence",

            )
        )

        self._persistence_thread.start()

        self._log(
            "info",
            (
                "Dashboard persistence "
                "worker started."
            ),
        )

    # ======================================================
    # PERSISTENCE WORKER
    # ======================================================

    def _persistence_worker(
        self,
    ):

        while (
            not self._stop_event.is_set()
        ):

            self._persist_event.wait(
                timeout=
                    self.persist_interval_seconds
            )

            self._persist_event.clear()

            if self._stop_event.is_set():
                break

            self._persist()

        # ==================================================
        # FINAL WRITE
        # ==================================================

        self._persist(
            force=True
        )

    # ======================================================
    # PERSIST
    # ======================================================

    def _persist(
        self,
        force=False,
    ):

        if not self.enabled:
            return

        with self._lock:

            if (
                not force
                and
                not self._dirty
            ):

                return

            snapshot = (
                self._snapshot_in_memory()
            )

        # ==================================================
        # WRITE
        # ==================================================

        try:

            self._write_state(
                snapshot
            )

        except Exception as error:

            self._log(
                "warning",
                (
                    "Dashboard state write failed: "
                    f"{error}"
                ),
            )

            # Keep dirty so next persistence cycle retries.
            with self._lock:

                self._dirty = True

            return

        # ==================================================
        # SUCCESS
        # ==================================================

        with self._lock:

            self._dirty = False

            self.last_persist_time = (
                time.monotonic()
            )

    # ======================================================
    # WRITE STATE FILE
    # ======================================================

    def _write_state(
        self,
        data,
    ):

        self.state_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Direct write is intentionally used here.
        #
        # Previous os.replace() implementation caused
        # WinError 5 on Windows/OneDrive when the backend
        # simultaneously accessed state.json.
        #
        # The dashboard backend uses retry logic when
        # reading this file.

        with open(
            self.state_file,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            )

            file.flush()

    # ======================================================
    # LOAD EXISTING STATE
    # ======================================================

    def _load_existing_state(
        self,
    ):

        if not self.state_file.exists():

            self._dirty = True

            return

        state = None

        # ==================================================
        # RETRY READ
        # ==================================================

        for attempt in range(
            3
        ):

            try:

                with open(
                    self.state_file,
                    "r",
                    encoding="utf-8",
                ) as file:

                    state = json.load(
                        file
                    )

                break

            except (
                json.JSONDecodeError,
                OSError,
            ) as error:

                if attempt < 2:

                    time.sleep(
                        0.05
                    )

                else:

                    self._log(
                        "warning",
                        (
                            "Could not restore "
                            "dashboard state: "
                            f"{error}"
                        ),
                    )

        if not isinstance(
            state,
            dict,
        ):

            self._dirty = True

            return

        # ==================================================
        # RESTORE CAMERA COUNTS
        # ==================================================

        cameras = state.get(
            "cameras",
            {},
        )

        if isinstance(
            cameras,
            dict,
        ):

            self.cameras = deepcopy(
                cameras
            )

        # ==================================================
        # RESTORE SERVICE STATUS
        # ==================================================

        service_status = state.get(
            "service_status",
            {},
        )

        if isinstance(
            service_status,
            dict,
        ):

            self.service_status = deepcopy(
                service_status
            )

        # ==================================================
        # DO NOT RESTORE OLD SYSTEM STATUS
        # ==================================================
        #
        # A previous run may have ended with:
        #
        # stopped
        # error
        # running
        #
        # New Application controls current status.

        self.system_status = "idle"

        # New run gets new startup time.

        self.start_time = datetime.now(
            timezone.utc
        )

        self._dirty = True

        self._log(
            "info",
            (
                "Previous dashboard camera "
                "state restored."
            ),
        )

    # ======================================================
    # FLUSH
    # ======================================================

    def flush(
        self,
    ):

        if not self.enabled:
            return

        self._persist(
            force=True
        )

    # ======================================================
    # STOP
    # ======================================================

    def stop(
        self,
    ):

        if not self.enabled:
            return

        # Prevent duplicate shutdown.
        if self._closed:
            return

        self._log(
            "info",
            "Stopping DashboardState.",
        )

        # ==================================================
        # SIGNAL WORKER
        # ==================================================

        self._stop_event.set()

        self._persist_event.set()

        # ==================================================
        # WAIT FOR WORKER
        # ==================================================

        thread = (
            self._persistence_thread
        )

        if (

            thread is not None

            and

            thread.is_alive()

            and

            thread
            is not
            threading.current_thread()

        ):

            thread.join(
                timeout=2.0
            )

        # ==================================================
        # FINAL WRITE
        # ==================================================

        self._persist(
            force=True
        )

        self._closed = True

        self._log(
            "info",
            "DashboardState stopped.",
        )

    # ======================================================
    # CLOSE
    # ======================================================

    def close(
        self,
    ):
        """
        Compatibility shutdown method.

        Application.stop() calls:

            self.dashboard_state.close()

        DashboardState internally performs shutdown using
        stop(). Keeping close() prevents Application and
        DashboardState interfaces from becoming inconsistent.
        """

        self.stop()

    # ======================================================
    # SAFE INTEGER
    # ======================================================

    @staticmethod
    def _safe_int(
        value,
    ):

        try:

            return int(
                value
            )

        except (
            TypeError,
            ValueError,
            OverflowError,
        ):

            return 0

    # ======================================================
    # SAFE FLOAT
    # ======================================================

    @staticmethod
    def _safe_float(
        value,
    ):

        try:

            value = float(
                value
            )

            # NaN check
            if value != value:

                return 0.0

            # Infinity check
            if value in (
                float("inf"),
                float("-inf"),
            ):

                return 0.0

            return value

        except (
            TypeError,
            ValueError,
            OverflowError,
        ):

            return 0.0

    # ======================================================
    # LOGGER
    # ======================================================

    def _log(
        self,
        level,
        message,
    ):

        if self.logger is None:

            return

        try:

            method = getattr(
                self.logger,
                level,
                None,
            )

            if callable(
                method
            ):

                method(
                    message
                )

        except Exception:

            # Logging must never crash the production
            # application.
            pass