"""
==========================================================
FillPac AI
Dashboard State Module
==========================================================

Purpose
-------
Thread-safe central state manager for the FillPac AI dashboard.

Architecture
------------
AI Application
    |
    v
DashboardState (in-memory)
    |
    | Single persistence worker
    v
dashboard/backend/state.json
    |
    v
Dashboard Backend
    |
    v
FastAPI + Socket.IO
    |
    v
Dashboard Frontend

Important
---------
- Pipeline threads update in-memory state only.
- Pipeline threads NEVER write state.json directly.
- Only one background persistence thread writes state.json.
- The dashboard backend reads state.json with retry handling.
==========================================================
"""

import json
import threading
import time

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


class DashboardState:
    """
    Thread-safe dashboard state manager.

    Pipeline threads update the in-memory state.

    A dedicated persistence thread periodically writes
    the latest state to disk.
    """

    def __init__(
        self,
        enabled=True,
        state_file="dashboard/backend/state.json",
        logger=None,
        persist_interval_seconds=0.5,
    ):
        # ==================================================
        # CONFIGURATION
        # ==================================================

        self.enabled = bool(enabled)

        self.logger = logger

        self.state_file = Path(
            state_file
        )

        # Prevent excessive disk writes.
        self.persist_interval_seconds = max(
            float(
                persist_interval_seconds
            ),
            0.25,
        )

        # ==================================================
        # RUNTIME STATE
        # ==================================================

        self.system_status = "idle"

        self.cameras = {}

        self.service_status = {}

        # New startup timestamp for every application run.
        self.start_time = datetime.now(
            timezone.utc
        )

        # ==================================================
        # PERSISTENCE STATE
        # ==================================================

        self.last_persist_time = 0.0

        self._dirty = False

        # ==================================================
        # THREADING
        # ==================================================

        self._lock = threading.RLock()

        self._stop_event = threading.Event()

        self._persist_event = threading.Event()

        self._persistence_thread = None

        # ==================================================
        # INITIALIZATION
        # ==================================================

        if self.enabled:

            self.state_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            self._load_existing_state()

            self._start_background_persistence()

    # ======================================================
    # SYSTEM STATUS
    # ======================================================

    def set_system_status(
        self,
        status,
    ):
        """
        Update global FillPac AI system status.

        Expected values may include:
        - starting
        - running
        - idle
        - stopping
        - stopped
        - error
        """

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
        """
        Update one camera's current dashboard state.

        This updates memory only.

        The background persistence worker writes the state
        to disk.
        """

        camera_name = str(
            camera_name
        )

        camera_state = {

            "count":
                self._safe_int(
                    count
                ),

            "printed_count":
                self._safe_int(
                    printed_count
                ),

            "missing_count":
                self._safe_int(
                    missing_count
                ),

            # Compatibility aliases
            "printed_bags_count":
                self._safe_int(
                    printed_bags_count
                ),

            "not_printed_bags_count":
                self._safe_int(
                    not_printed_bags_count
                ),

            "fps":
                round(
                    self._safe_float(
                        fps
                    ),
                    2,
                ),

            "status":
                str(
                    status
                ),

            "print_status":
                print_status,

            "updated_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),
        }

        with self._lock:

            previous_state = (
                self.cameras.get(
                    camera_name
                )
            )

            self.cameras[
                camera_name
            ] = camera_state

            state_changed = (

                previous_state
                is None

                or

                self._camera_state_changed(
                    previous_state,
                    camera_state,
                )

            )

            if state_changed:

                self._dirty = True

        if state_changed:

            self._persist_event.set()

    # ======================================================
    # CAMERA CHANGE DETECTION
    # ======================================================

    @staticmethod
    def _camera_state_changed(
        previous_state,
        current_state,
    ):
        """
        Check whether meaningful camera data changed.

        updated_at is ignored so timestamps alone do not
        continuously trigger disk writes.
        """

        fields = (

            "count",

            "printed_count",

            "missing_count",

            "printed_bags_count",

            "not_printed_bags_count",

            "fps",

            "status",

            "print_status",

        )

        return any(

            previous_state.get(
                field
            )

            !=

            current_state.get(
                field
            )

            for field
            in fields

        )

    # ======================================================
    # HEALTH UPDATE
    # ======================================================

    def update_health(
        self,
        health_info,
    ):
        """
        Update FillPac AI service health information.
        """

        if (
            not health_info
            or not isinstance(
                health_info,
                dict,
            )
        ):
            return

        changed = False

        with self._lock:

            for (
                key,
                value,
            ) in health_info.items():

                if (
                    self.service_status.get(
                        key
                    )
                    != value
                ):

                    self.service_status[
                        key
                    ] = value

                    changed = True

            if changed:

                self._dirty = True

        if changed:

            self._persist_event.set()

    # ======================================================
    # SNAPSHOT
    # ======================================================

    def snapshot(
        self,
    ):
        """
        Return a thread-safe dashboard state snapshot.
        """

        with self._lock:

            return (
                self._snapshot_in_memory()
            )

    # ======================================================
    # BUILD SNAPSHOT
    # ======================================================

    def _snapshot_in_memory(
        self,
    ):
        """
        Build the complete dashboard state.

        Caller must hold self._lock.
        """

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

        total_printed_count = sum(

            self._safe_int(
                camera.get(
                    "printed_count",
                    0,
                )
            )

            for camera
            in self.cameras.values()

        )

        total_missing_count = sum(

            self._safe_int(
                camera.get(
                    "missing_count",
                    0,
                )
            )

            for camera
            in self.cameras.values()

        )

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

            # Dashboard compatibility aliases

            "total_printed_bags_count":
                total_printed_count,

            "total_not_printed_bags_count":
                total_missing_count,

            "cameras":
                deepcopy(
                    self.cameras
                ),
        }

    # ======================================================
    # START PERSISTENCE THREAD
    # ======================================================

    def _start_background_persistence(
        self,
    ):
        """
        Start one dashboard persistence worker.
        """

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

    # ======================================================
    # PERSISTENCE WORKER
    # ======================================================

    def _persistence_worker(
        self,
    ):
        """
        Single worker responsible for writing state.json.
        """

        while (
            not self._stop_event.is_set()
        ):

            self._persist_event.wait(

                timeout=
                    self.persist_interval_seconds

            )

            self._persist_event.clear()

            if (
                self._stop_event.is_set()
            ):
                break

            self._persist()

        # Final write before thread exits.
        self._persist(
            force=True
        )

    # ======================================================
    # PERSIST STATE
    # ======================================================

    def _persist(
        self,
        force=False,
    ):
        """
        Persist current dashboard state.

        State remains dirty if writing fails.
        """

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

        try:

            self._write_state(
                snapshot
            )

        except OSError as error:

            self._log(
                "warning",
                "Dashboard state write failed: "
                f"{error}",
            )

            # Keep state dirty so next cycle retries.
            with self._lock:

                self._dirty = True

            return

        except Exception as error:

            self._log(
                "warning",
                "Unexpected dashboard state "
                "write failure: "
                f"{error}",
            )

            with self._lock:

                self._dirty = True

            return

        # Only mark clean after successful write.
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
        """
        Write dashboard state directly to state.json.

        There is only one writer:
        DashboardPersistence.

        The dashboard backend handles temporary incomplete
        JSON reads using retry logic.

        This avoids Windows/OneDrive os.replace() errors.
        """

        self.state_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(
            self.state_file,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                indent=2,
            )

            file.flush()

    # ======================================================
    # LOAD EXISTING STATE
    # ======================================================

    def _load_existing_state(
        self,
    ):
        """
        Restore existing camera counters and service state.

        startup_time is intentionally reset because every
        application launch is considered a new runtime session.
        """

        if (
            not self.state_file.exists()
        ):

            self._dirty = True

            return

        state = None

        # Retry because another process may temporarily
        # interact with the file.

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
                        "Dashboard state read failed: "
                        f"{error}",
                    )

        if (
            not isinstance(
                state,
                dict,
            )
        ):

            self._dirty = True

            return

        # --------------------------------------------------
        # Restore previous system status
        # --------------------------------------------------

        self.system_status = str(
            state.get(
                "system_status",
                self.system_status,
            )
        )

        # --------------------------------------------------
        # Restore service state
        # --------------------------------------------------

        service_status = (
            state.get(
                "service_status",
                {},
            )
        )

        if isinstance(
            service_status,
            dict,
        ):

            self.service_status = (
                service_status
            )

        # --------------------------------------------------
        # Restore camera counters
        # --------------------------------------------------

        cameras = (
            state.get(
                "cameras",
                {},
            )
        )

        if isinstance(
            cameras,
            dict,
        ):

            self.cameras = cameras

        # Always use current runtime startup time.
        self.start_time = datetime.now(
            timezone.utc
        )

        self.last_persist_time = (
            time.monotonic()
        )

    # ======================================================
    # CLOSE
    # ======================================================

    def close(
        self,
    ):
        """
        Stop persistence worker gracefully.

        The worker performs one final state write.
        """

        if not self.enabled:
            return

        self._stop_event.set()

        self._persist_event.set()

        if (
            self._persistence_thread
            is not None
        ):

            self._persistence_thread.join(
                timeout=5
            )

            if (
                self._persistence_thread.is_alive()
            ):

                self._log(
                    "warning",
                    "Dashboard persistence thread "
                    "did not stop within timeout.",
                )

        self._persistence_thread = None

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

            return float(
                value
            )

        except (
            TypeError,
            ValueError,
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
        """
        Log dashboard messages.
        """

        if (
            self.logger
            is not None
        ):

            log_method = getattr(
                self.logger,
                level,
                None,
            )

            if log_method:

                log_method(
                    message
                )

                return

        print(
            f"[{level.upper()}] "
            f"{message}"
        )