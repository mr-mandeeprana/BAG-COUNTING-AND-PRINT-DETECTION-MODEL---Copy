"""
==========================================================
FillPac AI
Dashboard API + Socket.IO Server
==========================================================

Architecture
------------
FillPac AI
    |
    v
state.json
    |
    +------ REST API
    |
    +------ Socket.IO
             |
             v
          Browser
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
# ABSOLUTE STATE FILE
# ==========================================================

BACKEND_DIR = (
    Path(__file__)
    .resolve()
    .parent
)

STATE_FILE = (
    BACKEND_DIR
    / "state.json"
)

STATE_WATCH_INTERVAL = 0.20

STATE_READ_RETRIES = 10

STATE_READ_RETRY_DELAY = 0.03


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

    title=
        "FillPac AI Dashboard API",

    version=
        "1.1.0",

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

    logger=False,

    engineio_logger=False,

)


# ==========================================================
# DEFAULT STATE
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
# READ STATE
# ==========================================================

async def read_dashboard_state():

    if not STATE_FILE.exists():

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
                    "Dashboard state must be an object."
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

        "state_file":
            str(
                STATE_FILE
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

    cameras = snapshot.get(
        "cameras",
        {},
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

        "updated_at":
            snapshot.get(
                "updated_at"
            ),

        "service_status":
            snapshot.get(
                "service_status",
                {},
            ),

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
                    f"{camera_name} not found"

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

                # Using both modification time and size
                # gives a more reliable Windows file-change
                # signature.
                signature = (

                    stat.st_mtime_ns,

                    stat.st_size,

                )

                if (
                    last_signature is None
                    or
                    signature != last_signature
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
        "State file: %s",
        STATE_FILE,
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
# ASGI
# ==========================================================

app = socketio.ASGIApp(

    sio,

    api,

)