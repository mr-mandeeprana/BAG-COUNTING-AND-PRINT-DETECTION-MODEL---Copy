"""
==========================================================
FillPac AI
Production Count Event Logger
==========================================================

Purpose
-------
Stores one persistent JSONL record whenever a physical
bag crossing event is confirmed.

Architecture
------------
Camera
   |
   v
Detection
   |
   v
Tracking
   |
   v
Physical Bag Center Crossing
   |
   v
Counter
   |
   v
CountLogger
   |
   +----> logs/count_events.jsonl
   |
   +----> Dashboard Events
   |
   +----> Analytics
   |
   +----> CSV Export


Important
---------
This logger does NOT perform counting.

Counting remains the responsibility of the existing
physical-center crossing logic.

The logger only records confirmed events.
==========================================================
"""

import json
import logging
import os
import threading
import uuid

from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger(
    "fillpac.count_logger"
)


# ==========================================================
# DEFAULT EVENT FILE
# ==========================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DEFAULT_EVENT_FILE = (
    PROJECT_ROOT
    / "logs"
    / "count_events.jsonl"
)


# ==========================================================
# HELPERS
# ==========================================================

def safe_int(
    value,
    default=0,
):
    """
    Safely convert a value to integer.
    """

    try:
        return int(value)

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return default


def safe_float(
    value,
    default=None,
):
    """
    Safely convert a value to float.
    """

    if value is None:
        return default

    try:
        return float(value)

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return default


def utc_now():
    """
    Return current UTC datetime.
    """

    return datetime.now(
        timezone.utc
    )


def utc_now_iso():
    """
    Return ISO-8601 UTC timestamp.
    """

    return (
        utc_now()
        .isoformat()
    )


# ==========================================================
# SHIFT CALCULATION
#
# Default production shifts:
#
# Shift A : 06:00 - 14:00
# Shift B : 14:00 - 22:00
# Shift C : 22:00 - 06:00
#
# This can later be moved into config.yaml if your factory
# uses different shift timings.
# ==========================================================

def determine_shift(
    timestamp=None,
):
    """
    Determine production shift from timestamp.

    Parameters
    ----------
    timestamp:
        datetime instance or None.

    Returns
    -------
    str
        shift-a
        shift-b
        shift-c
    """

    if timestamp is None:

        timestamp = utc_now()

    if not isinstance(
        timestamp,
        datetime,
    ):

        timestamp = utc_now()

    hour = timestamp.hour

    if 6 <= hour < 14:
        return "shift-a"

    if 14 <= hour < 22:
        return "shift-b"

    return "shift-c"


# ==========================================================
# PRINT STATUS NORMALIZATION
# ==========================================================

def determine_print_status(
    print_present,
    print_detection_enabled=True,
):
    """
    Convert print result into dashboard-friendly status.

    Returns
    -------
    printed
    missing
    disabled
    unknown
    """

    if not print_detection_enabled:
        return "disabled"

    if print_present is True:
        return "printed"

    if print_present is False:
        return "missing"

    return "unknown"


# ==========================================================
# COUNT LOGGER
# ==========================================================

class CountLogger:
    """
    Thread-safe persistent bag count event logger.

    Each confirmed bag crossing is stored as one JSON object
    per line in count_events.jsonl.
    """

    def __init__(
        self,
        file_path=None,
        enabled=True,
        flush_immediately=True,
    ):

        self.enabled = bool(
            enabled
        )

        self.flush_immediately = bool(
            flush_immediately
        )

        if file_path is None:

            self.file_path = (
                DEFAULT_EVENT_FILE
            )

        else:

            self.file_path = Path(
                file_path
            )

            if not self.file_path.is_absolute():

                self.file_path = (
                    PROJECT_ROOT
                    /
                    self.file_path
                )

        self.file_path = (
            self.file_path.resolve()
        )

        self._lock = (
            threading.Lock()
        )

        self._events_written = 0

        self._write_errors = 0

        self._last_event = None

        self._last_error = None


        # --------------------------------------------------
        # Create event directory
        # --------------------------------------------------

        try:

            self.file_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

        except OSError as error:

            logger.exception(
                "Unable to create count event directory: %s",
                self.file_path.parent,
            )

            self._last_error = str(
                error
            )

            raise


        logger.info(
            "CountLogger initialized."
        )

        logger.info(
            "Count event file: %s",
            self.file_path,
        )

        logger.info(
            "Count event logging enabled: %s",
            self.enabled,
        )


    # ======================================================
    # MAIN EVENT LOGGING API
    # ======================================================

    def log_count(
        self,
        camera_name,
        total_count,
        track_id=None,
        center=None,
        print_present=None,
        printed_count=0,
        missing_count=0,
        print_detection_enabled=True,
        timestamp=None,
        **extra_fields,
    ):
        """
        Persist one confirmed physical bag crossing event.

        This signature intentionally keeps compatibility with
        the existing FillPac pipeline.

        Parameters
        ----------
        camera_name:
            Camera that produced the confirmed count.

        total_count:
            Current camera count after crossing.

        track_id:
            Tracker ID associated with the detection.
            This is diagnostic metadata only.
            It is NOT the counting method.

        center:
            Physical bounding-box center used during
            crossing detection.

        print_present:
            True  -> print detected
            False -> print missing
            None  -> no classification / unknown

        printed_count:
            Camera cumulative printed count.

        missing_count:
            Camera cumulative missing-print count.

        print_detection_enabled:
            Whether print inspection is enabled for camera.

        timestamp:
            Optional datetime. Current UTC time is used
            when omitted.

        extra_fields:
            Additional future metadata can be written without
            breaking the logger API.

        Returns
        -------
        dict | None
            Persisted event dictionary or None if disabled/
            write failed.
        """

        if not self.enabled:
            return None


        # --------------------------------------------------
        # Timestamp
        # --------------------------------------------------

        if timestamp is None:

            event_time = (
                utc_now()
            )

        elif isinstance(
            timestamp,
            datetime,
        ):

            event_time = timestamp

            if event_time.tzinfo is None:

                event_time = (
                    event_time.replace(
                        tzinfo=timezone.utc
                    )
                )

        else:

            event_time = (
                utc_now()
            )


        timestamp_iso = (
            event_time.isoformat()
        )


        # --------------------------------------------------
        # Physical center
        # --------------------------------------------------

        center_x = None
        center_y = None

        if center is not None:

            try:

                if len(center) >= 2:

                    center_x = safe_float(
                        center[0]
                    )

                    center_y = safe_float(
                        center[1]
                    )

            except (
                TypeError,
                IndexError,
            ):

                center_x = None
                center_y = None


        # --------------------------------------------------
        # Print status
        # --------------------------------------------------

        print_status = (
            determine_print_status(
                print_present=
                    print_present,

                print_detection_enabled=
                    print_detection_enabled,
            )
        )


        # --------------------------------------------------
        # Shift
        # --------------------------------------------------

        shift = (
            determine_shift(
                event_time
            )
        )


        # --------------------------------------------------
        # Build event
        # --------------------------------------------------

        event = {

            # ----------------------------------------------
            # Identity
            # ----------------------------------------------

            "event_id":
                uuid.uuid4().hex,

            "event":
                "bag_count",


            # ----------------------------------------------
            # Time
            # ----------------------------------------------

            "timestamp":
                timestamp_iso,

            "shift":
                shift,


            # ----------------------------------------------
            # Camera
            # ----------------------------------------------

            "camera":
                str(
                    camera_name
                ),


            # ----------------------------------------------
            # Production
            # ----------------------------------------------

            "total_count":
                safe_int(
                    total_count
                ),

            # Alias used by some dashboard components.
            "count":
                safe_int(
                    total_count
                ),


            # ----------------------------------------------
            # Tracking metadata
            #
            # Track ID is recorded for diagnostics only.
            # Physical center crossing remains the actual
            # counting trigger.
            # ----------------------------------------------

            "track_id":
                (
                    safe_int(
                        track_id
                    )
                    if track_id is not None
                    else None
                ),


            # ----------------------------------------------
            # Physical bag center
            # ----------------------------------------------

            "center_x":
                center_x,

            "center_y":
                center_y,


            # ----------------------------------------------
            # Print inspection
            # ----------------------------------------------

            "print_detection_enabled":
                bool(
                    print_detection_enabled
                ),

            "print_present":
                (
                    bool(
                        print_present
                    )
                    if print_present is not None
                    else None
                ),

            "print_status":
                print_status,

            "printed_count":
                safe_int(
                    printed_count
                ),

            "missing_count":
                safe_int(
                    missing_count
                ),
        }


        # --------------------------------------------------
        # Optional metadata
        # --------------------------------------------------

        if extra_fields:

            for (
                key,
                value,
            ) in extra_fields.items():

                # Protect important standard event fields.
                if key in event:
                    continue

                event[key] = (
                    self._json_safe(
                        value
                    )
                )


        # --------------------------------------------------
        # Write
        # --------------------------------------------------

        success = (
            self._write_event(
                event
            )
        )

        if not success:
            return None


        self._last_event = (
            event.copy()
        )

        return event


    # ======================================================
    # COMPATIBILITY ALIAS
    # ======================================================

    def log(
        self,
        camera_name,
        total_count,
        track_id=None,
        center=None,
        print_present=None,
        printed_count=0,
        missing_count=0,
        print_detection_enabled=True,
        **kwargs,
    ):
        """
        Compatibility wrapper.

        Allows existing code to call:

            count_logger.log(...)

        while new code may use:

            count_logger.log_count(...)
        """

        return self.log_count(

            camera_name=
                camera_name,

            total_count=
                total_count,

            track_id=
                track_id,

            center=
                center,

            print_present=
                print_present,

            printed_count=
                printed_count,

            missing_count=
                missing_count,

            print_detection_enabled=
                print_detection_enabled,

            **kwargs,
        )


    # ======================================================
    # WRITE EVENT
    # ======================================================

    def _write_event(
        self,
        event,
    ):
        """
        Append one JSON object to JSONL file.
        """

        try:

            serialized = json.dumps(
                event,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
                default=str,
            )

            with self._lock:

                with open(
                    self.file_path,
                    "a",
                    encoding="utf-8",
                    buffering=1,
                ) as file:

                    file.write(
                        serialized
                    )

                    file.write(
                        "\n"
                    )

                    if self.flush_immediately:

                        file.flush()

                        try:

                            os.fsync(
                                file.fileno()
                            )

                        except OSError:

                            # fsync failure should not
                            # invalidate an otherwise
                            # successful JSONL append.
                            pass


                self._events_written += 1


            logger.debug(
                (
                    "Count event persisted | "
                    "camera=%s | "
                    "count=%s | "
                    "print=%s"
                ),
                event.get(
                    "camera"
                ),
                event.get(
                    "total_count"
                ),
                event.get(
                    "print_status"
                ),
            )

            return True


        except (
            OSError,
            TypeError,
            ValueError,
        ) as error:

            self._write_errors += 1

            self._last_error = str(
                error
            )

            logger.exception(
                (
                    "Failed writing count event | "
                    "camera=%s | "
                    "count=%s"
                ),
                event.get(
                    "camera"
                ),
                event.get(
                    "total_count"
                ),
            )

            return False


    # ======================================================
    # GENERIC EVENT
    # ======================================================

    def log_event(
        self,
        event_type,
        camera_name=None,
        **data,
    ):
        """
        Write a generic FillPac event.

        This is available for future events such as:

        camera_online
        camera_offline
        inference_timeout
        model_error
        print_alert

        Bag counting should continue using log_count().
        """

        if not self.enabled:
            return None

        event_time = (
            utc_now()
        )

        event = {

            "event_id":
                uuid.uuid4().hex,

            "event":
                str(
                    event_type
                ),

            "timestamp":
                event_time.isoformat(),

            "shift":
                determine_shift(
                    event_time
                ),

            "camera":
                (
                    str(
                        camera_name
                    )
                    if camera_name is not None
                    else None
                ),
        }


        for (
            key,
            value,
        ) in data.items():

            if key in event:
                continue

            event[key] = (
                self._json_safe(
                    value
                )
            )


        success = (
            self._write_event(
                event
            )
        )

        if not success:
            return None


        self._last_event = (
            event.copy()
        )

        return event


    # ======================================================
    # JSON SAFE CONVERSION
    # ======================================================

    @staticmethod
    def _json_safe(
        value,
    ):
        """
        Convert common values into JSON-safe values.
        """

        if value is None:
            return None

        if isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
            ),
        ):
            return value

        if isinstance(
            value,
            datetime,
        ):

            return value.isoformat()

        if isinstance(
            value,
            Path,
        ):

            return str(
                value
            )

        if isinstance(
            value,
            dict,
        ):

            return {

                str(key):
                    CountLogger._json_safe(
                        item
                    )

                for (
                    key,
                    item,
                )
                in value.items()

            }

        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):

            return [

                CountLogger._json_safe(
                    item
                )

                for item in value

            ]


        # NumPy scalar compatibility
        item_method = getattr(
            value,
            "item",
            None,
        )

        if callable(
            item_method
        ):

            try:

                return (
                    item_method()
                )

            except Exception:

                pass


        return str(
            value
        )


    # ======================================================
    # STATUS
    # ======================================================

    def get_status(
        self,
    ):
        """
        Return CountLogger runtime information.
        """

        return {

            "enabled":
                self.enabled,

            "file":
                str(
                    self.file_path
                ),

            "events_written":
                self._events_written,

            "write_errors":
                self._write_errors,

            "last_error":
                self._last_error,

            "last_event":
                (
                    self._last_event.copy()
                    if self._last_event
                    else None
                ),
        }


    # ======================================================
    # ENABLE
    # ======================================================

    def enable(
        self,
    ):

        self.enabled = True

        logger.info(
            "Count event logging enabled."
        )


    # ======================================================
    # DISABLE
    # ======================================================

    def disable(
        self,
    ):

        self.enabled = False

        logger.info(
            "Count event logging disabled."
        )


    # ======================================================
    # EVENT FILE PATH
    # ======================================================

    def get_file_path(
        self,
    ):

        return self.file_path