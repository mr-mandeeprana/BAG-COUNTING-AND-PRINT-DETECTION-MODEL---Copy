"""
==========================================================
FillPac AI
Production Dashboard API + Socket.IO Server
==========================================================

Dashboard responsibilities
--------------------------
- Read DashboardState from state.json
- Read count_events.jsonl
- Expose REST APIs
- Broadcast state through Socket.IO
- Calculate production analytics
- Expose jam monitoring information
- Serve optional processed live frames

IMPORTANT
---------
The dashboard backend does NOT perform:

- YOLO inference
- Tracking
- Counting
- Print detection
- Jam detection

Jam detection remains inside the camera Pipeline.

The dashboard only displays the jam state produced by
the AI pipeline.
==========================================================
"""

import asyncio
import csv
import io
import json
import logging
import math

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    StreamingResponse,
)

import socketio


# ==========================================================
# OPTIONAL DEPENDENCIES
# ==========================================================

try:
    import yaml
except ImportError:
    yaml = None


# ==========================================================
# PROJECT PATHS
# ==========================================================

BACKEND_DIR = Path(__file__).resolve().parent

DASHBOARD_DIR = BACKEND_DIR.parent

PROJECT_ROOT = DASHBOARD_DIR.parent

STATE_FILE = BACKEND_DIR / "state.json"

CONFIG_FILE = PROJECT_ROOT / "config.yaml"

COUNT_EVENTS_FILE = (
    PROJECT_ROOT
    / "logs"
    / "count_events.jsonl"
)

CONDITION_C_IMAGES_DIR = (
    PROJECT_ROOT
    / "logs"
    / "condition_c"
    / "images"
)

CONDITION_C_EVENTS_DIR = (
    PROJECT_ROOT
    / "logs"
    / "condition_c"
    / "events"
)


# ==========================================================
# SERVER CONFIGURATION
# ==========================================================

STATE_WATCH_INTERVAL = 0.20

STATE_READ_RETRIES = 10

STATE_READ_RETRY_DELAY = 0.03

EVENT_READ_RETRIES = 3

EVENT_READ_RETRY_DELAY = 0.02

LIVE_FRAME_INTERVAL = 0.10


# ==========================================================
# LOGGER
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    "fillpac.dashboard"
)


# ==========================================================
# FASTAPI
# ==========================================================

api = FastAPI(
    title="FillPac AI Dashboard API",
    description=(
        "Production monitoring API for "
        "FillPac AI Bag Counting, "
        "Print Detection and Jam Detection System."
    ),
    version="3.0.0",
)


# ==========================================================
# CORS
# ==========================================================

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================================
# SOCKET.IO
# ==========================================================

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)


# ==========================================================
# LIVE PIPELINES
# ==========================================================

LIVE_PIPELINES = {}


# ==========================================================
# BASIC HELPERS
# ==========================================================

def safe_int(value, default=0):

    try:
        return int(value)

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return default


def safe_float(value, default=0.0):

    try:

        result = float(value)

        if not math.isfinite(result):
            return default

        return result

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return default


def safe_round(value, digits=2):

    return round(
        safe_float(value),
        digits,
    )


def safe_bool(value, default=False):

    if isinstance(value, bool):
        return value

    if value is None:
        return default

    if isinstance(value, str):

        value = value.strip().lower()

        if value in {
            "true",
            "1",
            "yes",
            "on",
            "enabled",
        }:
            return True

        if value in {
            "false",
            "0",
            "no",
            "off",
            "disabled",
        }:
            return False

    return bool(value)


def utc_now():

    return datetime.now(
        timezone.utc
    )


def utc_now_iso():

    return utc_now().isoformat()


# ==========================================================
# JAM STATUS HELPERS
# ==========================================================

JAM_STATUS_PRIORITY = {

    "normal": 0,

    "recovering": 1,

    "slow": 2,

    "warning": 3,

    "jam": 4,
}


def normalize_jam_status(status):

    value = str(
        status or "normal"
    ).strip().lower()

    if value not in JAM_STATUS_PRIORITY:
        return "normal"

    return value


def get_highest_jam_status(
    cameras,
):

    """
    Determine overall plant jam status.

    Highest severity wins:

    NORMAL
       ↓
    RECOVERING
       ↓
    SLOW
       ↓
    WARNING
       ↓
    JAM
    """

    highest_status = "normal"

    highest_priority = 0

    for camera in cameras.values():

        status = normalize_jam_status(
            camera.get(
                "jam_status",
                "normal",
            )
        )

        priority = JAM_STATUS_PRIORITY.get(
            status,
            0,
        )

        if priority > highest_priority:

            highest_priority = priority

            highest_status = status

    return highest_status


# ==========================================================
# DEFAULT DASHBOARD STATE
# ==========================================================

def default_dashboard_state(
    system_status="offline",
):

    return {

        "system_status":
            system_status,

        "startup_time":
            None,

        "updated_at":
            None,

        "service_status":
            {},

        "total_count":
            0,

        "total_printed_count":
            0,

        "total_missing_count":
            0,

        "total_printed_bags_count":
            0,

        "total_not_printed_bags_count":
            0,

        "cameras":
            {},
    }


# ==========================================================
# READ DASHBOARD STATE
# ==========================================================

async def read_dashboard_state():

    if not STATE_FILE.exists():

        return default_dashboard_state(
            "offline"
        )

    last_error = None

    for attempt in range(
        STATE_READ_RETRIES
    ):

        try:

            with open(
                STATE_FILE,
                "r",
                encoding="utf-8",
            ) as file:

                state = json.load(file)

            if not isinstance(
                state,
                dict,
            ):

                raise ValueError(
                    "Dashboard state must be "
                    "a JSON object."
                )

            state.setdefault(
                "system_status",
                "unknown",
            )

            state.setdefault(
                "service_status",
                {},
            )

            state.setdefault(
                "cameras",
                {},
            )

            state.setdefault(
                "total_count",
                0,
            )

            state.setdefault(
                "total_printed_count",
                state.get(
                    "total_printed_bags_count",
                    0,
                ),
            )

            state.setdefault(
                "total_missing_count",
                state.get(
                    "total_not_printed_bags_count",
                    0,
                ),
            )

            return state

        except (
            json.JSONDecodeError,
            OSError,
            ValueError,
        ) as error:

            last_error = error

            if (
                attempt
                <
                STATE_READ_RETRIES - 1
            ):

                await asyncio.sleep(
                    STATE_READ_RETRY_DELAY
                )

    logger.warning(
        "Could not read dashboard state: %s",
        last_error,
    )

    return default_dashboard_state(
        "error"
    )


# ==========================================================
# PARSE EVENT TIME
# ==========================================================

def parse_event_datetime(
    timestamp,
):

    if not timestamp:
        return None

    try:

        value = str(
            timestamp
        ).strip()

        if value.endswith("Z"):

            value = (
                value[:-1]
                + "+00:00"
            )

        parsed = datetime.fromisoformat(
            value
        )

        if parsed.tzinfo is None:

            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed

    except (
        TypeError,
        ValueError,
    ):

        return None


# ==========================================================
# SHIFT CALCULATION
# ==========================================================

def determine_shift(
    timestamp,
):

    event_time = parse_event_datetime(
        timestamp
    )

    if event_time is None:
        return "unknown"

    hour = event_time.hour

    if 6 <= hour < 14:
        return "shift-a"

    if 14 <= hour < 22:
        return "shift-b"

    return "shift-c"


# ==========================================================
# EVENT NORMALIZATION
# ==========================================================

def normalize_event(
    event,
):

    normalized = dict(event)

    print_status = normalized.get(
        "print_status"
    )

    if print_status is None:

        print_present = normalized.get(
            "print_present"
        )

        if print_present is True:

            print_status = "printed"

        elif print_present is False:

            print_status = "missing"

        else:

            print_status = "unknown"

    normalized[
        "print_status"
    ] = str(
        print_status
    ).lower()

    timestamp = normalized.get(
        "timestamp"
    )

    normalized[
        "timestamp"
    ] = timestamp

    normalized[
        "camera"
    ] = str(
        normalized.get(
            "camera",
            "Unknown",
        )
    )

    normalized[
        "total_count"
    ] = safe_int(
        normalized.get(
            "total_count"
        )
    )

    normalized[
        "printed_count"
    ] = safe_int(
        normalized.get(
            "printed_count"
        )
    )

    normalized[
        "missing_count"
    ] = safe_int(
        normalized.get(
            "missing_count"
        )
    )

    normalized[
        "shift"
    ] = (
        normalized.get(
            "shift"
        )
        or
        determine_shift(
            timestamp
        )
    )

    # Jam fields are optional because older count
    # events may not contain jam information.

    if "jam_status" in normalized:

        normalized[
            "jam_status"
        ] = normalize_jam_status(
            normalized.get(
                "jam_status"
            )
        )

    if "jam_detected" in normalized:

        normalized[
            "jam_detected"
        ] = safe_bool(
            normalized.get(
                "jam_detected"
            )
        )

    return normalized


# ==========================================================
# READ COUNT EVENTS
# ==========================================================

async def read_count_events():

    if not COUNT_EVENTS_FILE.exists():
        return []

    last_error = None

    for attempt in range(
        EVENT_READ_RETRIES
    ):

        try:

            events = []

            with open(
                COUNT_EVENTS_FILE,
                "r",
                encoding="utf-8",
            ) as file:

                for line in file:

                    line = line.strip()

                    if not line:
                        continue

                    try:

                        event = json.loads(
                            line
                        )

                    except json.JSONDecodeError:

                        continue

                    if not isinstance(
                        event,
                        dict,
                    ):
                        continue

                    events.append(
                        normalize_event(
                            event
                        )
                    )

            return events

        except OSError as error:

            last_error = error

            if (
                attempt
                <
                EVENT_READ_RETRIES - 1
            ):

                await asyncio.sleep(
                    EVENT_READ_RETRY_DELAY
                )

    logger.warning(
        "Could not read count events: %s",
        last_error,
    )

    return []


# ==========================================================
# READ CONDITION C EVENTS
# ==========================================================

async def read_condition_c_events():

    if not CONDITION_C_EVENTS_DIR.exists():
        return []

    try:

        files = sorted(
            CONDITION_C_EVENTS_DIR.glob(
                "*.json"
            )
        )

    except OSError as error:

        logger.warning(
            "Could not list Condition C "
            "events: %s",
            error,
        )

        return []

    events = []

    for file_path in files:

        try:

            with open(
                file_path,
                "r",
                encoding="utf-8",
            ) as file:

                event = json.load(
                    file
                )

        except (
            OSError,
            json.JSONDecodeError,
        ):
            continue

        if not isinstance(
            event,
            dict,
        ):
            continue

        events.append(event)

    return events


# ==========================================================
# PRINT QUALITY
# ==========================================================

def calculate_print_quality(
    printed,
    missing,
):

    printed = safe_int(
        printed
    )

    missing = safe_int(
        missing
    )

    inspected = (
        printed
        +
        missing
    )

    if inspected <= 0:
        return 0.0

    return round(
        (
            printed
            /
            inspected
        )
        * 100.0,
        2,
    )


# ==========================================================
# PRODUCTION RATE
# ==========================================================

def calculate_production_rate(
    snapshot,
):

    total_count = safe_int(
        snapshot.get(
            "total_count"
        )
    )

    startup_time = snapshot.get(
        "startup_time"
    )

    if not startup_time:
        return 0.0

    start = parse_event_datetime(
        startup_time
    )

    if start is None:
        return 0.0

    try:

        elapsed_seconds = (
            utc_now()
            -
            start
        ).total_seconds()

    except TypeError:
        return 0.0

    if elapsed_seconds <= 0:
        return 0.0

    elapsed_hours = (
        elapsed_seconds
        /
        3600.0
    )

    return round(
        total_count
        /
        elapsed_hours,
        2,
    )


# ==========================================================
# CONDITION C - IMAGE URL
# ==========================================================

def build_condition_c_image_url(
    image_path,
):

    if not image_path:
        return None

    filename = Path(
        str(image_path)
    ).name

    if not filename:
        return None

    return (
        "/condition-c/image/"
        f"{filename}"
    )


# ==========================================================
# CAMERA PRODUCTION DATA
#
# JAM-AWARE VERSION
# ==========================================================

def build_camera_production(
    cameras,
):

    result = {}

    for (
        camera_name,
        camera,
    ) in cameras.items():

        count = safe_int(
            camera.get(
                "count"
            )
        )

        printed = safe_int(
            camera.get(
                "printed_count",
                camera.get(
                    "printed_bags_count",
                    0,
                ),
            )
        )

        missing = safe_int(
            camera.get(
                "missing_count",
                camera.get(
                    "not_printed_bags_count",
                    0,
                ),
            )
        )

        jam_status = normalize_jam_status(
            camera.get(
                "jam_status",
                "normal",
            )
        )

        active_jam_track_ids = (
            camera.get(
                "active_jam_track_ids",
                [],
            )
            or []
        )

        result[
            camera_name
        ] = {

            # ==============================================
            # PRODUCTION
            # ==============================================

            "count":
                count,

            "printed_count":
                printed,

            "missing_count":
                missing,

            "print_quality":
                calculate_print_quality(
                    printed,
                    missing,
                ),

            # ==============================================
            # CAMERA
            # ==============================================

            "fps":
                safe_round(
                    camera.get(
                        "fps"
                    )
                ),

            "status":
                camera.get(
                    "status",
                    "offline",
                ),

            "print_status":
                camera.get(
                    "print_status"
                ),

            "updated_at":
                camera.get(
                    "updated_at"
                ),

            # ==============================================
            # JAM DETECTION
            # ==============================================

            "jam_detection_enabled":
                safe_bool(
                    camera.get(
                        "jam_detection_enabled",
                        False,
                    )
                ),

            "jam_status":
                jam_status,

            "jam_detected":
                safe_bool(
                    camera.get(
                        "jam_detected",
                        False,
                    )
                ),

            "jam_warning":
                safe_bool(
                    camera.get(
                        "jam_warning",
                        False,
                    )
                ),

            "active_jam_count":
                safe_int(
                    camera.get(
                        "active_jam_count",
                        0,
                    )
                ),

            "active_jam_track_ids":
                active_jam_track_ids,

            # ==============================================
            # CONDITION C - ROI OCCUPANCY
            # ==============================================

            "condition_c_enabled":
                safe_bool(
                    camera.get(
                        "condition_c_enabled",
                        False,
                    )
                ),

            "condition_c_detected":
                safe_bool(
                    camera.get(
                        "condition_c_detected",
                        False,
                    )
                ),

            "condition_c_status":
                camera.get(
                    "condition_c_status",
                    "normal",
                ),

            "condition_c_bag_count":
                safe_int(
                    camera.get(
                        "condition_c_bag_count",
                        0,
                    )
                ),

            "condition_c_track_ids":
                camera.get(
                    "condition_c_track_ids",
                    [],
                )
                or [],

            "condition_c_minimum_gap_mm":
                camera.get(
                    "condition_c_minimum_gap_mm"
                ),

            "condition_c_image_path":
                camera.get(
                    "condition_c_image_path"
                ),

            "condition_c_image_exists":
                bool(
                    camera.get(
                        "condition_c_image_path"
                    )
                ),

            "condition_c_image_url":
                build_condition_c_image_url(
                    camera.get(
                        "condition_c_image_path"
                    )
                ),

            "condition_c_distances":
                camera.get(
                    "condition_c_distances",
                    [],
                )
                or [],

            "condition_c_spacing_pairs":
                camera.get(
                    "condition_c_spacing_pairs",
                    [],
                )
                or [],

            "condition_c_roi":
                camera.get(
                    "condition_c_roi",
                    {},
                ),

            "condition_c_timestamp":
                camera.get(
                    "condition_c_timestamp"
                ),

            "condition_c_duration":
                camera.get(
                    "condition_c_duration",
                    0,
                ),

        }

    return result


# ==========================================================
# JAM SUMMARY
# ==========================================================

def build_jam_summary(
    cameras,
):

    overall_status = (
        get_highest_jam_status(
            cameras
        )
    )

    jam_camera_count = 0

    warning_camera_count = 0

    slow_camera_count = 0

    recovering_camera_count = 0

    normal_camera_count = 0

    total_active_jams = 0

    condition_c_jam_camera_count = 0

    condition_c_active_tracks = 0

    condition_c_total_bags = 0

    camera_result = {}

    for (
        camera_name,
        camera,
    ) in cameras.items():

        status = normalize_jam_status(
            camera.get(
                "jam_status",
                "normal",
            )
        )

        active_count = safe_int(
            camera.get(
                "active_jam_count",
                0,
            )
        )

        total_active_jams += active_count

        condition_c_detected = safe_bool(
            camera.get(
                "condition_c_detected",
                False,
            )
        )

        condition_c_track_ids = (
            camera.get(
                "condition_c_track_ids",
                [],
            )
            or []
        )

        condition_c_bag_count = safe_int(
            camera.get(
                "condition_c_bag_count",
                0,
            )
        )

        if condition_c_detected:

            condition_c_jam_camera_count += 1

        condition_c_active_tracks += len(
            condition_c_track_ids
        )

        condition_c_total_bags += (
            condition_c_bag_count
        )

        if status == "jam":

            jam_camera_count += 1

        elif status == "warning":

            warning_camera_count += 1

        elif status == "slow":

            slow_camera_count += 1

        elif status == "recovering":

            recovering_camera_count += 1

        else:

            normal_camera_count += 1

        camera_result[
            camera_name
        ] = {

            "enabled":
                safe_bool(
                    camera.get(
                        "jam_detection_enabled",
                        False,
                    )
                ),

            "status":
                status,

            "jam_detected":
                safe_bool(
                    camera.get(
                        "jam_detected",
                        False,
                    )
                ),

            "warning":
                safe_bool(
                    camera.get(
                        "jam_warning",
                        False,
                    )
                ),

            "active_jam_count":
                active_count,

            "active_jam_track_ids":
                camera.get(
                    "active_jam_track_ids",
                    [],
                )
                or [],

            "condition_c_enabled":
                safe_bool(
                    camera.get(
                        "condition_c_enabled",
                        False,
                    )
                ),

            "condition_c_detected":
                condition_c_detected,

            "condition_c_bag_count":
                condition_c_bag_count,

            "condition_c_track_ids":
                condition_c_track_ids,

            "condition_c_minimum_gap_mm":
                camera.get(
                    "condition_c_minimum_gap_mm"
                ),

            "updated_at":
                camera.get(
                    "updated_at"
                ),

        }

    return {

        "overall_status":
            overall_status,

        "camera_count":
            len(cameras),

        "normal_cameras":
            normal_camera_count,

        "slow_cameras":
            slow_camera_count,

        "warning_cameras":
            warning_camera_count,

        "jam_cameras":
            jam_camera_count,

        "recovering_cameras":
            recovering_camera_count,

        "active_jams":
            total_active_jams,

        "condition_c_jam_cameras":
            condition_c_jam_camera_count,

        "condition_c_active_tracks":
            condition_c_active_tracks,

        "condition_c_total_tracks":
            condition_c_active_tracks,

        "condition_c_total_bags":
            condition_c_total_bags,

        "cameras":
            camera_result,

    }


# ==========================================================
# SAFE CONFIGURATION
# ==========================================================

def read_safe_config():

    if yaml is None:

        return {
            "available": False,
            "error": (
                "PyYAML is not installed."
            ),
        }

    if not CONFIG_FILE.exists():

        return {
            "available": False,
            "error": (
                "config.yaml not found."
            ),
        }

    try:

        with open(
            CONFIG_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            config = (
                yaml.safe_load(file)
                or {}
            )

    except (
        OSError,
        yaml.YAMLError,
    ) as error:

        logger.warning(
            "Could not read config: %s",
            error,
        )

        return {
            "available": False,
            "error": str(error),
        }

    cameras = []

    for camera in config.get(
        "cameras",
        [],
    ):

        if not isinstance(
            camera,
            dict,
        ):
            continue

        cameras.append(
            {
                "id":
                    camera.get(
                        "id"
                    ),

                "name":
                    camera.get(
                        "name"
                    ),

                "enabled":
                    bool(
                        camera.get(
                            "enabled",
                            True,
                        )
                    ),

                "mode":
                    camera.get(
                        "mode"
                    ),

                "roi":
                    camera.get(
                        "roi",
                        {},
                    ),

                "counting":
                    camera.get(
                        "counting",
                        {},
                    ),

                "print_detection":
                    camera.get(
                        "print_detection",
                        {},
                    ),

                # ==========================================
                # JAM CONFIGURATION
                # ==========================================

                "jam_detection":
                    camera.get(
                        "jam_detection",
                        {},
                    ),

                "bag_spacing":
                    camera.get(
                        "bag_spacing",
                        {},
                    ),

                "condition_c":
                    camera.get(
                        "condition_c",
                        {},
                    ),

                "dashboard_publish_interval":
                    camera.get(
                        "dashboard_publish_interval"
                    ),

                "inference_timeout":
                    camera.get(
                        "inference_timeout"
                    ),
            }
        )

    return {

        "available":
            True,

        "dashboard":
            config.get(
                "dashboard",
                {},
            ),

        "counting":
            config.get(
                "counting",
                {},
            ),

        "print_detection":
            config.get(
                "print_detection",
                {},
            ),

        "jam_detection":
            config.get(
                "jam_detection",
                {},
            ),

        "bag_spacing":
            config.get(
                "bag_spacing",
                {},
            ),

        "condition_c":
            config.get(
                "condition_c",
                {},
            ),

        "tracker":
            config.get(
                "tracker",
                {},
            ),

        "cameras":
            cameras,
    }


# ==========================================================
# ROOT
# ==========================================================

@api.get("/")
async def root():

    return {

        "service":
            "FillPac AI Dashboard API",

        "version":
            "3.0.0",

        "status":
            "running",

        "features": [
            "bag-counting",
            "print-detection",
            "jam-monitoring",
            "analytics",
            "live-monitor",
        ],

        "timestamp":
            utc_now_iso(),

        "state_file":
            str(
                STATE_FILE
            ),

        "events_file":
            str(
                COUNT_EVENTS_FILE
            ),
    }


# ==========================================================
# HEALTH
# ==========================================================

@api.get("/health")
async def health():

    snapshot = (
        await read_dashboard_state()
    )

    cameras = (
        snapshot.get(
            "cameras",
            {},
        )
        or {}
    )

    service_status = (
        snapshot.get(
            "service_status",
            {},
        )
        or {}
    )

    online_cameras = sum(

        1

        for camera
        in cameras.values()

        if str(
            camera.get(
                "status",
                "",
            )
        ).lower()

        in {
            "online",
            "running",
            "active",
        }
    )

    jam_summary = (
        build_jam_summary(
            cameras
        )
    )

    return {

        "status":
            "ok",

        "system_status":
            snapshot.get(
                "system_status",
                "unknown",
            ),

        "model_loaded":
            safe_bool(
                service_status.get(
                    "model_loaded",
                    False,
                )
            ),

        "inference_manager_running":
            safe_bool(
                service_status.get(
                    "inference_manager_running",
                    False,
                )
            ),

        "elasticsearch_connected":
            safe_bool(
                service_status.get(
                    "elasticsearch_connected",
                    False,
                )
            ),

        "dashboard_enabled":
            safe_bool(
                service_status.get(
                    "dashboard_enabled",
                    True,
                )
            ),

        "camera_count":
            len(cameras),

        "online_cameras":
            online_cameras,

        "total_count":
            safe_int(
                snapshot.get(
                    "total_count"
                )
            ),

        "total_printed_count":
            safe_int(
                snapshot.get(
                    "total_printed_count"
                )
            ),

        "total_missing_count":
            safe_int(
                snapshot.get(
                    "total_missing_count"
                )
            ),

        # ==============================================
        # JAM HEALTH
        # ==============================================

        "jam_status":
            jam_summary[
                "overall_status"
            ],

        "active_jams":
            jam_summary[
                "active_jams"
            ],

        "jam_cameras":
            jam_summary[
                "jam_cameras"
            ],

        "warning_cameras":
            jam_summary[
                "warning_cameras"
            ],

        "startup_time":
            snapshot.get(
                "startup_time"
            ),

        "updated_at":
            snapshot.get(
                "updated_at"
            ),

        "service_status":
            service_status,

        "state_file":
            str(
                STATE_FILE
            ),
    }


# ==========================================================
# STATE
# ==========================================================

@api.get("/state")
async def state():

    return (
        await read_dashboard_state()
    )


# ==========================================================
# CAMERAS
# ==========================================================

@api.get("/cameras")
async def cameras():

    snapshot = (
        await read_dashboard_state()
    )

    return snapshot.get(
        "cameras",
        {},
    )


# ==========================================================
# SINGLE CAMERA
# ==========================================================

@api.get(
    "/cameras/{camera_name}"
)
async def camera(
    camera_name: str,
):

    snapshot = (
        await read_dashboard_state()
    )

    cameras_data = snapshot.get(
        "cameras",
        {},
    )

    camera_data = cameras_data.get(
        camera_name
    )

    if camera_data is None:

        return JSONResponse(

            status_code=404,

            content={
                "error":
                    f"{camera_name} not found",
            },
        )

    return camera_data


# ==========================================================
# PRODUCTION
# ==========================================================

@api.get("/production")
async def production():

    snapshot = (
        await read_dashboard_state()
    )

    cameras_data = (
        snapshot.get(
            "cameras",
            {},
        )
        or {}
    )

    total = safe_int(
        snapshot.get(
            "total_count"
        )
    )

    printed = safe_int(
        snapshot.get(
            "total_printed_count",
            snapshot.get(
                "total_printed_bags_count",
                0,
            ),
        )
    )

    missing = safe_int(
        snapshot.get(
            "total_missing_count",
            snapshot.get(
                "total_not_printed_bags_count",
                0,
            ),
        )
    )

    jam_summary = (
        build_jam_summary(
            cameras_data
        )
    )

    return {

        "total_bags":
            total,

        "printed_bags":
            printed,

        "not_printed_bags":
            missing,

        "print_quality":
            calculate_print_quality(
                printed,
                missing,
            ),

        "production_rate_per_hour":
            calculate_production_rate(
                snapshot
            ),

        # ==============================================
        # JAM SUMMARY
        # ==============================================

        "jam_status":
            jam_summary[
                "overall_status"
            ],

        "active_jams":
            jam_summary[
                "active_jams"
            ],

        "jam_cameras":
            jam_summary[
                "jam_cameras"
            ],

        "warning_cameras":
            jam_summary[
                "warning_cameras"
            ],

        "cameras":
            build_camera_production(
                cameras_data
            ),

        "updated_at":
            snapshot.get(
                "updated_at"
            ),
    }


# ==========================================================
# JAM MONITORING API
#
# NEW ENDPOINT:
#
# GET /jams
# ==========================================================

@api.get("/jams")
async def jams():

    snapshot = (
        await read_dashboard_state()
    )

    cameras_data = (
        snapshot.get(
            "cameras",
            {},
        )
        or {}
    )

    summary = (
        build_jam_summary(
            cameras_data
        )
    )

    return {

        **summary,

        "generated_at":
            utc_now_iso(),
    }


# ==========================================================
# EVENTS
# ==========================================================

@api.get("/events")
async def events(
    limit: int = Query(
        default=100,
        ge=1,
        le=10000,
    ),
    camera: str | None = Query(
        default=None
    ),
    print_status: str | None = Query(
        default=None
    ),
    shift: str | None = Query(
        default=None
    ),
    start: str | None = Query(
        default=None
    ),
    end: str | None = Query(
        default=None
    ),
):

    all_events = (
        await read_count_events()
    )

    # "all" / "" mean "no filter" - both the UI's default
    # option value and an empty string should be treated
    # as not filtering at all.

    def _is_wildcard(value):

        return (
            value is None
            or value.strip() == ""
            or value.strip().lower() == "all"
        )

    if not _is_wildcard(camera):

        camera_lower = (
            camera
            .strip()
            .lower()
        )

        all_events = [

            event

            for event in all_events

            if str(
                event.get(
                    "camera",
                    "",
                )
            ).lower()
            ==
            camera_lower
        ]

    if not _is_wildcard(print_status):

        requested_status = (
            print_status
            .strip()
            .lower()
        )

        all_events = [

            event

            for event in all_events

            if str(
                event.get(
                    "print_status",
                    "",
                )
            ).lower()
            ==
            requested_status
        ]

    if not _is_wildcard(shift):

        requested_shift = (
            shift
            .strip()
            .lower()
        )

        all_events = [

            event

            for event in all_events

            if str(
                event.get(
                    "shift",
                    "",
                )
            ).lower()
            ==
            requested_shift
        ]

    start_time = (
        parse_event_datetime(start)
        if not _is_wildcard(start)
        else None
    )

    end_time = (
        parse_event_datetime(end)
        if not _is_wildcard(end)
        else None
    )

    if start_time is not None or end_time is not None:

        filtered_events = []

        for event in all_events:

            event_time = parse_event_datetime(
                event.get("timestamp")
            )

            if event_time is None:
                continue

            if (
                start_time is not None
                and event_time < start_time
            ):
                continue

            if (
                end_time is not None
                and event_time > end_time
            ):
                continue

            filtered_events.append(event)

        all_events = filtered_events

    all_events.reverse()

    limited_events = (
        all_events[
            :limit
        ]
    )

    return {

        "count":
            len(
                limited_events
            ),

        "events":
            limited_events,
    }


# ==========================================================
# EVENTS CSV EXPORT
# ==========================================================

@api.get("/events/export")
async def export_events():

    events_data = (
        await read_count_events()
    )

    output = io.StringIO()

    fieldnames = [

        "timestamp",

        "event",

        "camera",

        "total_count",

        "track_id",

        "center_x",

        "center_y",

        "print_present",

        "print_status",

        "printed_count",

        "missing_count",

        "shift",

        "jam_status",

        "jam_detected",
    ]

    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        extrasaction="ignore",
    )

    writer.writeheader()

    for event in events_data:

        writer.writerow(
            event
        )

    csv_data = (
        output.getvalue()
    )

    output.close()

    filename = (
        "fillpac_events_"
        +
        utc_now().strftime(
            "%Y%m%d_%H%M%S"
        )
        +
        ".csv"
    )

    return StreamingResponse(

        iter(
            [
                csv_data
            ]
        ),

        media_type="text/csv",

        headers={
            "Content-Disposition":
                (
                    "attachment; "
                    f'filename="{filename}"'
                )
        },
    )


# ==========================================================
# ANALYTICS
# ==========================================================

@api.get("/analytics")
async def analytics():

    events_data = (
        await read_count_events()
    )

    total_events = len(
        events_data
    )

    printed_events = 0

    missing_events = 0

    unknown_events = 0

    hourly = defaultdict(
        lambda: {
            "total": 0,
            "printed": 0,
            "missing": 0,
        }
    )

    by_camera = defaultdict(
        lambda: {
            "total": 0,
            "printed": 0,
            "missing": 0,
        }
    )

    by_shift = defaultdict(
        lambda: {
            "total": 0,
            "printed": 0,
            "missing": 0,
        }
    )

    for event in events_data:

        status = str(
            event.get(
                "print_status",
                "unknown",
            )
        ).lower()

        camera_name = str(
            event.get(
                "camera",
                "Unknown",
            )
        )

        shift = str(
            event.get(
                "shift",
                "unknown",
            )
        )

        event_time = (
            parse_event_datetime(
                event.get(
                    "timestamp"
                )
            )
        )

        if status == "printed":

            printed_events += 1

        elif status in {
            "missing",
            "not_printed",
            "not-printed",
        }:

            missing_events += 1

        else:

            unknown_events += 1

        camera_bucket = (
            by_camera[
                camera_name
            ]
        )

        camera_bucket[
            "total"
        ] += 1

        if status == "printed":

            camera_bucket[
                "printed"
            ] += 1

        elif status in {
            "missing",
            "not_printed",
            "not-printed",
        }:

            camera_bucket[
                "missing"
            ] += 1

        shift_bucket = (
            by_shift[
                shift
            ]
        )

        shift_bucket[
            "total"
        ] += 1

        if status == "printed":

            shift_bucket[
                "printed"
            ] += 1

        elif status in {
            "missing",
            "not_printed",
            "not-printed",
        }:

            shift_bucket[
                "missing"
            ] += 1

        if event_time is not None:

            hour_key = (
                event_time.strftime(
                    "%Y-%m-%d %H:00"
                )
            )

            hour_bucket = (
                hourly[
                    hour_key
                ]
            )

            hour_bucket[
                "total"
            ] += 1

            if status == "printed":

                hour_bucket[
                    "printed"
                ] += 1

            elif status in {
                "missing",
                "not_printed",
                "not-printed",
            }:

                hour_bucket[
                    "missing"
                ] += 1

    hourly_result = []

    for hour in sorted(
        hourly.keys()
    ):

        bucket = hourly[
            hour
        ]

        hourly_result.append(
            {
                "hour":
                    hour,

                "total":
                    bucket[
                        "total"
                    ],

                "printed":
                    bucket[
                        "printed"
                    ],

                "missing":
                    bucket[
                        "missing"
                    ],

                "print_quality":
                    calculate_print_quality(
                        bucket[
                            "printed"
                        ],
                        bucket[
                            "missing"
                        ],
                    ),
            }
        )

    camera_result = []

    for camera_name in sorted(
        by_camera.keys()
    ):

        bucket = (
            by_camera[
                camera_name
            ]
        )

        camera_result.append(
            {
                "camera":
                    camera_name,

                "total":
                    bucket[
                        "total"
                    ],

                "printed":
                    bucket[
                        "printed"
                    ],

                "missing":
                    bucket[
                        "missing"
                    ],

                "print_quality":
                    calculate_print_quality(
                        bucket[
                            "printed"
                        ],
                        bucket[
                            "missing"
                        ],
                    ),
            }
        )

    shift_result = []

    for shift in [
        "shift-a",
        "shift-b",
        "shift-c",
        "unknown",
    ]:

        if shift not in by_shift:
            continue

        bucket = (
            by_shift[
                shift
            ]
        )

        shift_result.append(
            {
                "shift":
                    shift,

                "total":
                    bucket[
                        "total"
                    ],

                "printed":
                    bucket[
                        "printed"
                    ],

                "missing":
                    bucket[
                        "missing"
                    ],

                "print_quality":
                    calculate_print_quality(
                        bucket[
                            "printed"
                        ],
                        bucket[
                            "missing"
                        ],
                    ),
            }
        )

    # ------------------------------------------------------
    # Current jam information comes from state.json,
    # NOT count event history.
    # ------------------------------------------------------

    snapshot = (
        await read_dashboard_state()
    )

    jam_summary = (
        build_jam_summary(
            snapshot.get(
                "cameras",
                {},
            )
            or {}
        )
    )

    # ------------------------------------------------------
    # CONDITION C ANALYTICS
    #
    # Each saved event file represents one ROI occupancy
    # jam capture (ROIOccupancyDetector only saves on jam).
    # ------------------------------------------------------

    condition_c_events = (
        await read_condition_c_events()
    )

    roi_jam_events = len(
        condition_c_events
    )

    roi_bag_counts = [
        safe_int(
            event.get(
                "bag_count",
                0,
            )
        )
        for event in condition_c_events
    ]

    roi_gap_values = [
        event.get(
            "minimum_gap_mm"
        )
        for event in condition_c_events
        if event.get(
            "minimum_gap_mm"
        )
        is not None
    ]

    average_roi_bag_count = (
        safe_round(
            sum(roi_bag_counts)
            /
            len(roi_bag_counts)
        )
        if roi_bag_counts
        else 0.0
    )

    average_roi_gap_mm = (
        safe_round(
            sum(roi_gap_values)
            /
            len(roi_gap_values)
        )
        if roi_gap_values
        else None
    )

    return {

        "total_events":
            total_events,

        "printed_events":
            printed_events,

        "missing_events":
            missing_events,

        "unknown_events":
            unknown_events,

        "print_quality":
            calculate_print_quality(
                printed_events,
                missing_events,
            ),

        "hourly":
            hourly_result,

        "by_camera":
            camera_result,

        "by_shift":
            shift_result,

        # ==============================================
        # CURRENT JAM ANALYTICS
        # ==============================================

        "jam":
            jam_summary,

        # ==============================================
        # CONDITION C ANALYTICS
        # ==============================================

        "roi_jam_events":
            roi_jam_events,

        "average_roi_bag_count":
            average_roi_bag_count,

        "average_roi_gap_mm":
            average_roi_gap_mm,

        "generated_at":
            utc_now_iso(),
    }


# ==========================================================
# CONFIG
# ==========================================================

@api.get("/config")
async def config():

    return (
        read_safe_config()
    )


# ==========================================================
# LIVE PIPELINE REGISTRATION
# ==========================================================

def register_live_pipeline(
    camera_name,
    pipeline,
):

    if not camera_name:
        return

    if pipeline is None:
        return

    LIVE_PIPELINES[
        str(
            camera_name
        )
    ] = pipeline

    logger.info(
        "Registered live pipeline: %s",
        camera_name,
    )


def unregister_live_pipeline(
    camera_name,
):

    LIVE_PIPELINES.pop(
        str(
            camera_name
        ),
        None,
    )


# ==========================================================
# GET PIPELINE FRAME
# ==========================================================

def get_pipeline_frame(
    pipeline,
):

    if pipeline is None:
        return None

    getter = getattr(
        pipeline,
        "get_latest_frame",
        None,
    )

    if callable(
        getter
    ):

        try:

            frame = getter()

            if frame is None:
                return None

            return frame.copy()

        except Exception:
            return None

    frame_lock = getattr(
        pipeline,
        "_frame_lock",
        None,
    )

    if frame_lock is None:
        return None

    try:

        with frame_lock:

            frame = getattr(
                pipeline,
                "_latest_frame",
                None,
            )

            if frame is None:
                return None

            return frame.copy()

    except Exception:

        return None


# ==========================================================
# LIVE FRAME GENERATOR
# ==========================================================

async def live_frame_generator(
    camera_name,
):

    try:

        import cv2

    except ImportError:

        logger.error(
            "OpenCV unavailable for live monitor."
        )

        return

    while True:

        pipeline = (
            LIVE_PIPELINES.get(
                camera_name
            )
        )

        if pipeline is None:

            await asyncio.sleep(
                1.0
            )

            continue

        frame = (
            get_pipeline_frame(
                pipeline
            )
        )

        if frame is None:

            await asyncio.sleep(
                LIVE_FRAME_INTERVAL
            )

            continue

        try:

            success, encoded = (
                cv2.imencode(
                    ".jpg",
                    frame,
                    [
                        cv2.IMWRITE_JPEG_QUALITY,
                        75,
                    ],
                )
            )

        except Exception:

            success = False

            encoded = None

        if not success:

            await asyncio.sleep(
                LIVE_FRAME_INTERVAL
            )

            continue

        frame_bytes = (
            encoded.tobytes()
        )

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            +
            frame_bytes
            +
            b"\r\n"
        )

        await asyncio.sleep(
            LIVE_FRAME_INTERVAL
        )


# ==========================================================
# LIVE CAMERA
# ==========================================================

@api.get(
    "/live/{camera_name}"
)
async def live_camera(
    camera_name: str,
):

    if (
        camera_name
        not in LIVE_PIPELINES
    ):

        return JSONResponse(

            status_code=404,

            content={
                "error":
                    (
                        "Live pipeline is not "
                        "registered for "
                        f"{camera_name}."
                    ),

                "camera":
                    camera_name,

                "live_available":
                    False,
            },
        )

    return StreamingResponse(

        live_frame_generator(
            camera_name
        ),

        media_type=(
            "multipart/x-mixed-replace; "
            "boundary=frame"
        ),
    )


# ==========================================================
# CONDITION C - ROI SNAPSHOT IMAGE
# ==========================================================

@api.get(
    "/condition-c/image/{filename}"
)
async def condition_c_image(
    filename: str,
):

    safe_name = Path(
        filename
    ).name

    if not safe_name:

        return JSONResponse(

            status_code=404,

            content={
                "error":
                    "Invalid image filename."
            },
        )

    file_path = (
        CONDITION_C_IMAGES_DIR
        /
        safe_name
    )

    if (
        not file_path.exists()
        or
        not file_path.is_file()
    ):

        return JSONResponse(

            status_code=404,

            content={
                "error":
                    "ROI snapshot not found.",

                "filename":
                    safe_name,
            },
        )

    return FileResponse(
        file_path,
        media_type="image/jpeg",
    )


# ==========================================================
# SOCKET CONNECT
# ==========================================================

@sio.event
async def connect(
    sid,
    environ,
    auth=None,
):

    logger.info(
        "Dashboard connected: %s",
        sid,
    )

    snapshot = (
        await read_dashboard_state()
    )

    await sio.emit(
        "dashboard_state",
        snapshot,
        to=sid,
    )


# ==========================================================
# SOCKET DISCONNECT
# ==========================================================

@sio.event
async def disconnect(
    sid,
):

    logger.info(
        "Dashboard disconnected: %s",
        sid,
    )


# ==========================================================
# STATE WATCHER
# ==========================================================

async def dashboard_state_watcher():

    logger.info(
        "Dashboard state watcher started."
    )

    logger.info(
        "Watching state file: %s",
        STATE_FILE,
    )

    last_signature = None

    while True:

        try:

            if STATE_FILE.exists():

                stat = (
                    STATE_FILE.stat()
                )

                signature = (

                    stat.st_mtime_ns,

                    stat.st_size,
                )

                if (
                    last_signature is None
                    or
                    signature
                    !=
                    last_signature
                ):

                    snapshot = (
                        await read_dashboard_state()
                    )

                    if (
                        snapshot.get(
                            "system_status"
                        )
                        != "error"
                    ):

                        await sio.emit(
                            "dashboard_state",
                            snapshot,
                        )

                        last_signature = (
                            signature
                        )

        except asyncio.CancelledError:

            raise

        except Exception:

            logger.exception(
                "Dashboard watcher error."
            )

        await asyncio.sleep(
            STATE_WATCH_INTERVAL
        )


# ==========================================================
# STARTUP
# ==========================================================

@api.on_event(
    "startup"
)
async def startup_event():

    logger.info(
        "Starting FillPac AI Dashboard API."
    )

    logger.info(
        "Project root: %s",
        PROJECT_ROOT,
    )

    logger.info(
        "State file: %s",
        STATE_FILE,
    )

    logger.info(
        "Events file: %s",
        COUNT_EVENTS_FILE,
    )

    logger.info(
        "Config file: %s",
        CONFIG_FILE,
    )

    api.state.dashboard_watcher = (
        asyncio.create_task(
            dashboard_state_watcher()
        )
    )


# ==========================================================
# SHUTDOWN
# ==========================================================

@api.on_event(
    "shutdown"
)
async def shutdown_event():

    watcher = getattr(
        api.state,
        "dashboard_watcher",
        None,
    )

    if watcher is not None:

        watcher.cancel()

        try:

            await watcher

        except asyncio.CancelledError:

            pass

    logger.info(
        "FillPac AI Dashboard API stopped."
    )


# ==========================================================
# ASGI APPLICATION
#
# Start with:
#
# uvicorn dashboard.backend.server:app
#
# NOT:
#
# uvicorn dashboard.backend.server:api
# ==========================================================

app = socketio.ASGIApp(
    sio,
    api,
)