"""
==========================================================
FillPac AI
Dashboard API + Socket.IO Server
==========================================================

Purpose
-------
Provides:

- REST API
- Socket.IO real-time communication
- Dashboard state file monitoring
- Automatic dashboard_state broadcasting

Architecture
------------
FillPac AI Application
        |
        v
dashboard/backend/state.json
        |
        v
Dashboard State Watcher
        |
        +---- REST API
        |
        +---- Socket.IO
                |
                v
        Dashboard Frontend

Important
---------
This server does NOT create another DashboardState instance.

The main FillPac AI application is the only writer.

This backend only reads state.json.
==========================================================
"""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import socketio


# ==========================================================
# CONFIGURATION
# ==========================================================

STATE_FILE = Path(
    "dashboard/backend/state.json"
)

STATE_WATCH_INTERVAL = 0.25

STATE_READ_RETRIES = 5

STATE_READ_RETRY_DELAY = 0.05


# ==========================================================
# LOGGER
# ==========================================================

logger = logging.getLogger(
    "fillpac.dashboard"
)

if not logger.handlers:

    logging.basicConfig(

        level=logging.INFO,

        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),

    )


# ==========================================================
# FASTAPI
# ==========================================================

api = FastAPI(

    title=
        "FillPac AI Dashboard API",

    version=
        "1.0.0",

)


# ==========================================================
# CORS
# ==========================================================

api.add_middleware(

    CORSMiddleware,

    allow_origins=[
        "*"
    ],

    allow_credentials=False,

    allow_methods=[
        "*"
    ],

    allow_headers=[
        "*"
    ],

)


# ==========================================================
# SOCKET.IO
# ==========================================================

sio = socketio.AsyncServer(

    async_mode=
        "asgi",

    cors_allowed_origins=
        "*",

)


# ==========================================================
# DEFAULT DASHBOARD STATE
# ==========================================================

def default_dashboard_state(
    system_status="offline",
):
    """
    Return a valid empty dashboard state.
    """

    return {

        "system_status":
            system_status,

        "startup_time":
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
    """
    Read state.json safely.

    Because the AI application writes directly to state.json,
    there may be a very small moment where the file contains
    incomplete JSON.

    Retry instead of immediately returning an error.
    """

    if (
        not STATE_FILE.exists()
    ):

        return (
            default_dashboard_state(
                "offline"
            )
        )

    last_error = None

    for attempt in range(
        STATE_READ_RETRIES
    ):

        try:

            # Reading this small JSON file synchronously is
            # acceptable because the file is tiny.

            with open(
                STATE_FILE,
                "r",
                encoding="utf-8",
            ) as file:

                state = json.load(
                    file
                )

            if not isinstance(
                state,
                dict,
            ):

                raise ValueError(
                    "Dashboard state root "
                    "must be a JSON object."
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
        "Could not read dashboard state "
        "after %s attempts: %s",
        STATE_READ_RETRIES,
        last_error,
    )

    return (
        default_dashboard_state(
            "error"
        )
    )


# ==========================================================
# ROOT
# ==========================================================

@api.get("/")
async def root():

    return {

        "service":
            "FillPac AI Dashboard API",

        "status":
            "running",

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
        }

    )

    return {

        "status":
            "ok",

        "system_status":
            snapshot.get(
                "system_status",
                "unknown",
            ),

        "camera_count":
            len(
                cameras
            ),

        "online_cameras":
            online_cameras,

        "total_count":
            snapshot.get(
                "total_count",
                0,
            ),

        "total_printed_count":
            snapshot.get(
                "total_printed_count",
                0,
            ),

        "total_missing_count":
            snapshot.get(
                "total_missing_count",
                0,
            ),

        "startup_time":
            snapshot.get(
                "startup_time"
            ),

        "service_status":
            snapshot.get(
                "service_status",
                {},
            ),
    }


# ==========================================================
# FULL DASHBOARD STATE
# ==========================================================

@api.get("/state")
async def state():

    return (
        await read_dashboard_state()
    )


# ==========================================================
# ALL CAMERAS
# ==========================================================

@api.get("/cameras")
async def cameras():

    snapshot = (
        await read_dashboard_state()
    )

    return (
        snapshot.get(
            "cameras",
            {},
        )
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

    cameras_data = (
        snapshot.get(
            "cameras",
            {},
        )
    )

    camera_data = (
        cameras_data.get(
            camera_name
        )
    )

    if (
        camera_data
        is None
    ):

        return JSONResponse(

            status_code=404,

            content={

                "error":
                    f"{camera_name} not found",

            },

        )

    return camera_data


# ==========================================================
# PRODUCTION SUMMARY
# ==========================================================

@api.get("/production")
async def production():

    snapshot = (
        await read_dashboard_state()
    )

    return {

        "total_bags":
            snapshot.get(
                "total_count",
                0,
            ),

        "printed_bags":
            snapshot.get(
                "total_printed_count",
                0,
            ),

        "not_printed_bags":
            snapshot.get(
                "total_missing_count",
                0,
            ),

    }


# ==========================================================
# SOCKET.IO CONNECT
# ==========================================================

@sio.event
async def connect(
    sid,
    environ,
    auth=None,
):
    """
    Send current dashboard state immediately when a
    dashboard client connects.
    """

    logger.info(
        "Dashboard client connected: %s",
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
# SOCKET.IO DISCONNECT
# ==========================================================

@sio.event
async def disconnect(
    sid,
):
    logger.info(
        "Dashboard client disconnected: %s",
        sid,
    )


# ==========================================================
# STATE WATCHER
# ==========================================================

async def dashboard_state_watcher():
    """
    Monitor state.json for changes.

    When the file changes, broadcast the latest state
    to all connected dashboard clients.
    """

    logger.info(
        "Dashboard state watcher started."
    )

    last_modified_time = None

    while True:

        try:

            if (
                STATE_FILE.exists()
            ):

                current_modified_time = (

                    STATE_FILE.stat()
                    .st_mtime_ns

                )

                if (

                    last_modified_time
                    is None

                    or

                    current_modified_time
                    != last_modified_time

                ):

                    snapshot = (
                        await read_dashboard_state()
                    )

                    # Do not broadcast temporary read errors.
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

                        last_modified_time = (
                            current_modified_time
                        )

        except Exception:

            logger.exception(
                "Dashboard state watcher error."
            )

        await asyncio.sleep(
            STATE_WATCH_INTERVAL
        )


# ==========================================================
# APPLICATION STARTUP
# ==========================================================

@api.on_event(
    "startup"
)
async def startup_event():
    """
    Start background state watcher.
    """

    logger.info(
        "Starting FillPac AI Dashboard API."
    )

    api.state.dashboard_watcher = (
        asyncio.create_task(
            dashboard_state_watcher()
        )
    )


# ==========================================================
# APPLICATION SHUTDOWN
# ==========================================================

@api.on_event(
    "shutdown"
)
async def shutdown_event():
    """
    Stop state watcher cleanly.
    """

    watcher = getattr(

        api.state,

        "dashboard_watcher",

        None,

    )

    if (
        watcher
        is not None
    ):

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
# ==========================================================

app = socketio.ASGIApp(

    sio,

    api,

)