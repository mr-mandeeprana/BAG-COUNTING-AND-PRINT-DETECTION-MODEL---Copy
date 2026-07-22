"""
============================================================
FillPac AI
Camera Module
============================================================

Supports:
- Local video files
- RTSP streams
- USB / local cameras
- Automatic RTSP reconnection
- Configurable retry behavior
- OpenCV buffer configuration
- Camera metadata
- Graceful release

Production Behavior
-------------------
VIDEO:
    End of video -> return False

RTSP:
    Read failure -> attempt reconnect
    Reconnect success -> continue streaming
    Reconnect failure -> return False

CAMERA:
    Read failure -> attempt reconnect

Important
---------
RTSP reconnection is handled inside this module so the
Pipeline does not need to manage low-level stream recovery.
============================================================
"""

import threading
import time
from typing import Union

import cv2


class Camera:

    VALID_MODES = {
        "video",
        "rtsp",
        "camera",
    }

    def __init__(
        self,
        name: str,
        source: Union[str, int],
        mode: str = "video",
        buffer_size: int = 1,
        logger=None,
        reconnect_attempts: int = 5,
        reconnect_delay: float = 2.0,
        read_retry_attempts: int = 2,
        read_retry_delay: float = 0.05,
    ):

        # ==================================================
        # BASIC CONFIGURATION
        # ==================================================

        self.name = str(
            name
        )

        self.source = source

        self.mode = str(
            mode
        ).strip().lower()

        if self.mode not in self.VALID_MODES:

            raise ValueError(
                f"{self.name}: Invalid camera mode "
                f"'{self.mode}'. Expected one of "
                f"{sorted(self.VALID_MODES)}."
            )

        self.buffer_size = max(
            int(
                buffer_size
            ),
            1,
        )

        self.logger = logger

        # ==================================================
        # RECONNECTION CONFIGURATION
        # ==================================================

        self.reconnect_attempts = max(
            int(
                reconnect_attempts
            ),
            1,
        )

        self.reconnect_delay = max(
            float(
                reconnect_delay
            ),
            0.0,
        )

        # Short retries before declaring a stream failure.
        self.read_retry_attempts = max(
            int(
                read_retry_attempts
            ),
            1,
        )

        self.read_retry_delay = max(
            float(
                read_retry_delay
            ),
            0.0,
        )

        # ==================================================
        # CAMERA STATE
        # ==================================================

        self.cap = None

        self.connected = False

        self.width = 0

        self.height = 0

        self.fps = 0.0

        # ==================================================
        # THREAD SAFETY
        # ==================================================

        self._lock = threading.RLock()

        self._released = False

    # ======================================================
    # CONNECT
    # ======================================================

    def connect(
        self,
    ) -> bool:

        with self._lock:

            # ----------------------------------------------
            # Release previous capture safely
            # ----------------------------------------------

            self._release_capture()

            self._released = False

            self._log(
                "info",
                f"{self.name}: connecting "
                f"({self.mode})...",
            )

            try:

                self.cap = cv2.VideoCapture(
                    self.source
                )

            except Exception as error:

                self.connected = False

                self._log(
                    "error",
                    f"{self.name}: VideoCapture "
                    f"creation failed: {error}",
                )

                return False

            # ----------------------------------------------
            # Validate connection
            # ----------------------------------------------

            if (
                self.cap is None
                or not self.cap.isOpened()
            ):

                self.connected = False

                self._release_capture()

                self._log(
                    "error",
                    f"{self.name}: connection failed.",
                )

                return False

            # ----------------------------------------------
            # Configure capture buffer
            #
            # Note:
            # CAP_PROP_BUFFERSIZE support depends on the
            # OpenCV backend. Failure is not fatal.
            # ----------------------------------------------

            try:

                self.cap.set(
                    cv2.CAP_PROP_BUFFERSIZE,
                    self.buffer_size,
                )

            except Exception as error:

                self._log(
                    "warning",
                    f"{self.name}: could not set "
                    f"capture buffer size: {error}",
                )

            # ----------------------------------------------
            # Read camera metadata
            # ----------------------------------------------

            self._update_metadata()

            self.connected = True

            self._log(
                "info",
                f"{self.name}: connected "
                f"({self.width}x{self.height}, "
                f"{self.fps:.2f} FPS).",
            )

            return True

    # ======================================================
    # READ FRAME
    # ======================================================

    def read(
        self,
    ):

        # ----------------------------------------------
        # Not connected
        # ----------------------------------------------

        if not self.is_open():

            return (
                False,
                None,
            )

        # ----------------------------------------------
        # Try reading frame
        # ----------------------------------------------

        success, frame = (
            self._read_with_retry()
        )

        if (
            success
            and frame is not None
        ):

            return (
                True,
                frame,
            )

        # ==================================================
        # VIDEO FILE
        #
        # A failed read normally means EOF.
        #
        # Do NOT reconnect or restart automatically because
        # that would unexpectedly replay the video.
        # ==================================================

        if self.mode == "video":

            self._log(
                "info",
                f"{self.name}: video stream ended.",
            )

            self.connected = False

            return (
                False,
                None,
            )

        # ==================================================
        # RTSP / CAMERA
        #
        # A failed read may be temporary.
        # Attempt automatic reconnection.
        # ==================================================

        self._log(
            "warning",
            f"{self.name}: stream read failed. "
            "Attempting reconnection.",
        )

        self.connected = False

        if self.reconnect():

            # ----------------------------------------------
            # Try first frame after reconnection
            # ----------------------------------------------

            success, frame = (
                self._read_with_retry()
            )

            if (
                success
                and frame is not None
            ):

                return (
                    True,
                    frame,
                )

        self._log(
            "error",
            f"{self.name}: stream recovery failed.",
        )

        return (
            False,
            None,
        )

    # ======================================================
    # READ WITH SHORT RETRY
    # ======================================================

    def _read_with_retry(
        self,
    ):

        for attempt in range(
            self.read_retry_attempts
        ):

            with self._lock:

                if (
                    self.cap is None
                    or not self.cap.isOpened()
                ):

                    return (
                        False,
                        None,
                    )

                try:

                    success, frame = (
                        self.cap.read()
                    )

                except Exception as error:

                    self._log(
                        "warning",
                        f"{self.name}: frame read "
                        f"exception: {error}",
                    )

                    success = False

                    frame = None

            if (
                success
                and frame is not None
                and frame.size > 0
            ):

                return (
                    True,
                    frame,
                )

            if (
                attempt
                < self.read_retry_attempts - 1
            ):

                time.sleep(
                    self.read_retry_delay
                )

        return (
            False,
            None,
        )

    # ======================================================
    # RECONNECT
    # ======================================================

    def reconnect(
        self,
    ) -> bool:

        # Video files should never reconnect automatically.
        if self.mode == "video":

            return False

        for attempt in range(
            1,
            self.reconnect_attempts + 1,
        ):

            if self._released:

                return False

            self._log(
                "warning",
                f"{self.name}: reconnect attempt "
                f"{attempt}/{self.reconnect_attempts}.",
            )

            # ----------------------------------------------
            # Wait before reconnecting
            #
            # First attempt is immediate.
            # ----------------------------------------------

            if (
                attempt > 1
                and self.reconnect_delay > 0
            ):

                time.sleep(
                    self.reconnect_delay
                )

            if self.connect():

                self._log(
                    "info",
                    f"{self.name}: reconnected "
                    "successfully.",
                )

                return True

        self.connected = False

        return False

    # ======================================================
    # RESET
    # ======================================================

    def reset(
        self,
    ) -> bool:

        self._log(
            "info",
            f"{self.name}: resetting camera.",
        )

        self.release()

        # release() marks the camera as intentionally
        # released, but connect() clears that flag.

        return self.connect()

    # ======================================================
    # RELEASE
    # ======================================================

    def release(
        self,
    ):

        with self._lock:

            self._released = True

            self._release_capture()

            self.connected = False

    # ======================================================
    # INTERNAL CAPTURE RELEASE
    # ======================================================

    def _release_capture(
        self,
    ):

        if self.cap is not None:

            try:

                self.cap.release()

            except Exception as error:

                self._log(
                    "warning",
                    f"{self.name}: capture release "
                    f"failed: {error}",
                )

        self.cap = None

    # ======================================================
    # DISCONNECT
    # ======================================================

    def disconnect(
        self,
    ):

        self.release()

    # ======================================================
    # CONNECTION STATUS
    # ======================================================

    def is_open(
        self,
    ) -> bool:

        with self._lock:

            return bool(
                self.connected
                and self.cap is not None
                and self.cap.isOpened()
            )

    # ======================================================
    # UPDATE METADATA
    # ======================================================

    def _update_metadata(
        self,
    ):

        if self.cap is None:

            return

        try:

            self.width = int(
                self.cap.get(
                    cv2.CAP_PROP_FRAME_WIDTH
                )
                or 0
            )

            self.height = int(
                self.cap.get(
                    cv2.CAP_PROP_FRAME_HEIGHT
                )
                or 0
            )

            fps = float(
                self.cap.get(
                    cv2.CAP_PROP_FPS
                )
                or 0.0
            )

            # Some RTSP backends return NaN or unrealistic
            # values. Keep zero when FPS is unavailable.
            if (
                fps <= 0
                or fps != fps
            ):

                fps = 0.0

            self.fps = fps

        except Exception as error:

            self._log(
                "warning",
                f"{self.name}: failed to read "
                f"camera metadata: {error}",
            )

    # ======================================================
    # GETTERS
    # ======================================================

    def get_width(
        self,
    ):

        return self.width

    def get_height(
        self,
    ):

        return self.height

    def get_fps(
        self,
    ):

        return self.fps

    # ======================================================
    # CAMERA INFORMATION
    # ======================================================

    def info(
        self,
    ):

        return {
            "name":
                self.name,

            "source":
                self.source,

            "mode":
                self.mode,

            "connected":
                self.is_open(),

            "buffer_size":
                self.buffer_size,

            "width":
                self.width,

            "height":
                self.height,

            "fps":
                self.fps,

            "reconnect_attempts":
                self.reconnect_attempts,

            "reconnect_delay":
                self.reconnect_delay,
        }

    # ======================================================
    # LOGGING
    # ======================================================

    def _log(
        self,
        level,
        message,
    ):

        if self.logger is not None:

            log_method = getattr(
                self.logger,
                level,
                None,
            )

            if log_method is not None:

                log_method(
                    message
                )

                return

        print(
            f"[{level.upper()}] {message}"
        )