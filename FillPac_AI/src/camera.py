"""
============================================================
FillPac AI
Low-Latency Camera Module
============================================================

Supports:
- Local video files
- RTSP streams
- USB / local cameras
- Low-latency RTSP capture
- Latest-frame-only architecture
- Automatic RTSP reconnection
- Configurable retry behavior
- OpenCV / FFmpeg backend
- Camera metadata
- Thread-safe frame access
- Graceful release

Architecture
------------

VIDEO FILE:

    Pipeline
       |
       v
    cap.read()
       |
       v
    Frame

RTSP / CAMERA:

                       Camera Stream
                            |
                            v
                     Capture Thread
                     (reads every frame,
                      no frames skipped
                      at decode time)
                            |
              +-------------+-------------+
              |                           |
              v                           v
      Latest Frame Only            Display FIFO Queue
      (get_latest_frame() /        (read_display_frame())
       read())                            |
              |                           v
              v                     Your display loop:
      Your AI / YOLO thread:        shows every frame in
      always grabs the newest       order, so motion looks
      frame; if it falls behind     smooth (VLC-like) even
      the camera, it skips ahead    if the AI thread is
      instead of queuing up.        slower than the camera.

Two independent consumers, one capture thread:

- AI / inference consumers should call read() or
  get_latest_frame(). These intentionally drop old frames
  so processing never falls further and further behind the
  live camera.

- A display consumer should run in its own thread and call
  read_display_frame() in a loop. It pulls frames from a
  small FIFO queue in capture order, so nothing is skipped
  for the human watching the feed. If the display loop falls
  behind, the oldest queued frame is dropped to bound memory
  rather than growing without limit or blocking capture.

Example wiring:

    camera = Camera("line1", rtsp_url, mode="rtsp")
    camera.connect()

    def display_loop():
        while running:
            ok, frame = camera.read_display_frame(timeout=1.0)
            if ok:
                cv2.imshow("line1", frame)
                cv2.waitKey(1)

    def ai_loop():
        while running:
            ok, frame = camera.read()
            if ok:
                run_yolo(frame)

    threading.Thread(target=display_loop, daemon=True).start()
    threading.Thread(target=ai_loop, daemon=True).start()

============================================================
"""

import os
import queue
import threading
import time
from typing import Union

import cv2


# ==========================================================
# LOW-LATENCY FFMPEG OPTIONS
# ==========================================================

# These options are used by OpenCV's FFmpeg backend.
#
# TCP is preferred for production reliability.
#
# nobuffer / low_delay reduce unnecessary buffering.
#
# IMPORTANT:
# This environment variable should be configured before
# creating the RTSP VideoCapture object.

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|"
    "fflags;nobuffer|"
    "flags;low_delay|"
    "max_delay;0"
)


class Camera:

    VALID_MODES = {
        "video",
        "rtsp",
        "camera",
    }

    # ======================================================
    # INITIALIZATION
    # ======================================================

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

        self.name = str(name)

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
            int(buffer_size),
            1,
        )

        self.logger = logger

        # ==================================================
        # RECONNECTION CONFIGURATION
        # ==================================================

        self.reconnect_attempts = max(
            int(reconnect_attempts),
            1,
        )

        self.reconnect_delay = max(
            float(reconnect_delay),
            0.0,
        )

        self.read_retry_attempts = max(
            int(read_retry_attempts),
            1,
        )

        self.read_retry_delay = max(
            float(read_retry_delay),
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

        self._frame_lock = threading.Lock()

        self._released = False

        # ==================================================
        # LATEST FRAME
        # ==================================================

        self._latest_frame = None

        self._latest_frame_time = 0.0

        self._frame_sequence = 0

        self._last_read_sequence = -1

        # ==================================================
        # DISPLAY FRAME QUEUE
        #
        # Separate from _latest_frame.
        #
        # _latest_frame is "latest only" (AI consumers skip
        # ahead and drop old frames on purpose).
        #
        # This queue is FIFO and bounded, so a dedicated
        # display loop can drain it and show every frame the
        # camera produced, in order, for smooth motion.
        #
        # If a display consumer falls behind, the oldest
        # queued frame is dropped to bound memory use rather
        # than growing without limit.
        # ==================================================

        self._display_queue = queue.Queue(
            maxsize=5
        )

        # ==================================================
        # CAPTURE THREAD
        # ==================================================

        self._capture_thread = None

        self._capture_stop_event = (
            threading.Event()
        )

        # ==================================================
        # RECONNECT STATE
        # ==================================================

        self._reconnecting = False

    # ======================================================
    # CONNECT
    # ======================================================

    def connect(self) -> bool:

        # Stop any old capture thread first.
        self._stop_capture_thread()

        with self._lock:

            self._release_capture()

            self._released = False

            self._clear_latest_frame()

            self._log(
                "info",
                f"{self.name}: connecting "
                f"({self.mode})...",
            )

            self._log(
                "info",
                f"{self.name}: Opening RTSP source: {self.source}"
            )

            if not self._open_capture():

                self.connected = False

                return False

            self._configure_capture()

            self._update_metadata()

            self.connected = True

            self._log(
                "info",
                f"{self.name}: connected "
                f"({self.width}x{self.height}, "
                f"{self.fps:.2f} FPS).",
            )

        # ==================================================
        # START BACKGROUND CAPTURE
        #
        # RTSP and physical camera streams continuously
        # capture frames.
        #
        # VIDEO files remain synchronous so offline video
        # testing processes every frame normally.
        # ==================================================

        if self.mode in {
            "rtsp",
            "camera",
        }:

            self._start_capture_thread()

        return True

    # ======================================================
    # OPEN CAPTURE
    # ======================================================

    def _open_capture(self) -> bool:

        try:

            # ------------------------------------------------
            # RTSP
            # ------------------------------------------------

            self._log(
                "info",
                f"{self.name}: Creating VideoCapture (backend=FFMPEG)"
            )

            t0 = time.perf_counter()

            if self.mode == "rtsp":

                self.cap = cv2.VideoCapture(
                    self.source,    
                    cv2.CAP_FFMPEG,
                )
                self._log(
                    "info",
                    f"{self.name}: VideoCapture object created"
                )
            
            # ------------------------------------------------
            # VIDEO / USB CAMERA
            # ------------------------------------------------

            else:

                self.cap = cv2.VideoCapture(
                    self.source
                )

            self._log(
                "info",
                f"{self.name}: Open took "
                f"{(time.perf_counter() - t0):.3f}s",
            )

            if self.cap is not None:

                self._log(
                    "info",
                    f"{self.name}: Backend="
                    f"{self.cap.getBackendName()}",
                )

        except Exception as error:

            self.cap = None

            self._log(
                "error",
                f"{self.name}: VideoCapture "
                f"creation failed: {error}",
            )

            return False

        if (
            self.cap is None
            or not self.cap.isOpened()
        ):

            self._log(
                "error",
                f"{self.name}: connection failed.",
            )

            self._release_capture()

            return False

        return True

    # ======================================================
    # CONFIGURE CAPTURE
    # ======================================================

    def _configure_capture(self):

        if self.cap is None:
            return

        # --------------------------------------------------
        # BUFFER SIZE
        # --------------------------------------------------

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

        # --------------------------------------------------
        # RGB CONVERSION
        #
        # Explicitly keep BGR conversion on. Setting this
        # to 0 returns the decoder's native pixel format
        # (often YUV), which shows up as grayscale/incorrect
        # colors depending on the FFmpeg/OpenCV build.
        # --------------------------------------------------

        try:

            self.cap.set(
                cv2.CAP_PROP_CONVERT_RGB,
                1,
            )

        except Exception:

            pass

        # --------------------------------------------------
        # OPEN TIMEOUT
        # --------------------------------------------------

        if hasattr(
            cv2,
            "CAP_PROP_OPEN_TIMEOUT_MSEC",
        ):

            try:

                self.cap.set(
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    5000,
                )

            except Exception:

                pass

        # --------------------------------------------------
        # READ TIMEOUT
        # --------------------------------------------------

        if hasattr(
            cv2,
            "CAP_PROP_READ_TIMEOUT_MSEC",
        ):

            try:

                self.cap.set(
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    1000,
                )

            except Exception:

                pass

    # ======================================================
    # START CAPTURE THREAD
    # ======================================================

    def _start_capture_thread(self):

        if self.mode == "video":
            return

        if (
            self._capture_thread is not None
            and self._capture_thread.is_alive()
        ):

            return

        self._capture_stop_event.clear()

        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name=f"{self.name}-Capture",
            daemon=True,
        )

        self._capture_thread.start()

        self._log(
            "info",
            f"{self.name}: low-latency "
            "capture thread started.",
        )

    # ======================================================
    # CAPTURE LOOP
    # ======================================================

    def _capture_loop(self):

        """
        Continuously read the RTSP/camera stream.

        Only the newest frame is retained.

        If the AI pipeline is slower than the camera,
        intermediate frames are automatically discarded
        because _latest_frame is overwritten.
        """

        consecutive_failures = 0

        while not self._capture_stop_event.is_set():

            if self._released:
                break

            # ------------------------------------------------
            # CHECK CAPTURE
            # ------------------------------------------------

            with self._lock:

                cap = self.cap

                capture_available = bool(
                    cap is not None
                    and cap.isOpened()
                )

            if not capture_available:

                self.connected = False

                if not self._thread_reconnect():

                    time.sleep(
                        self.reconnect_delay
                        or 0.5
                    )

                continue

            # ------------------------------------------------
            # READ FRAME
            # ------------------------------------------------

            try:

                with self._lock:

                    if (
                        self.cap is None
                        or not self.cap.isOpened()
                    ):

                        success = False
                        frame = None

                    else:

                        start = time.perf_counter()

                        # Read every frame. Do not skip
                        # ahead with grab(); CAP_PROP_BUFFERSIZE
                        # is already set to 1 above, so this
                        # does not build up latency the way an
                        # unbounded internal buffer would.
                        success, frame = (
                            self.cap.read()
                        )

                        elapsed = (
                            time.perf_counter() - start
                        ) * 1000

                        self._log(
                            "debug",
                            f"{self.name}: Frame read took "
                            f"{elapsed:.1f} ms",
                        )

            except Exception as error:

                success = False

                frame = None

                self._log(
                    "warning",
                    f"{self.name}: capture "
                    f"exception: {error}",
                )

            # ------------------------------------------------
            # VALID FRAME
            # ------------------------------------------------

            if (
                success
                and frame is not None
                and frame.size > 0
            ):

                consecutive_failures = 0

                self.connected = True

                with self._frame_lock:

                    # Replace previous frame.
                    #
                    # There is intentionally NO queue.

                    self._latest_frame = frame

                    self._latest_frame_time = (
                        time.time()
                    )

                    self._frame_sequence += 1

                self._log(
                    "debug",
                    f"{self.name}: Latest frame timestamp "
                    f"{self._latest_frame_time}",
                )

                # ----------------------------------------
                # DISPLAY QUEUE
                #
                # FIFO, separate from _latest_frame, so a
                # display loop can show every frame in order.
                # If the display consumer is behind, drop the
                # oldest queued frame rather than growing
                # unbounded or blocking the capture thread.
                # ----------------------------------------

                try:

                    self._display_queue.put_nowait(
                        frame.copy()
                    )

                except queue.Full:

                    try:

                        self._display_queue.get_nowait()

                    except queue.Empty:

                        pass

                    try:

                        self._display_queue.put_nowait(
                            frame.copy()
                        )

                    except queue.Full:

                        pass

                continue

            # ------------------------------------------------
            # READ FAILURE
            # ------------------------------------------------

            consecutive_failures += 1

            if (
                consecutive_failures
                <
                self.read_retry_attempts
            ):

                if self.read_retry_delay > 0:

                    time.sleep(
                        self.read_retry_delay
                    )

                continue

            consecutive_failures = 0

            self.connected = False

            self._log(
                "warning",
                f"{self.name}: stream read failed. "
                "Attempting background reconnection.",
            )

            self._thread_reconnect()

        self._log(
            "info",
            f"{self.name}: capture thread stopped.",
        )

    # ======================================================
    # READ FRAME
    # ======================================================

    def read(self):

        # ==================================================
        # VIDEO FILE
        #
        # Video files remain synchronous.
        # ==================================================

        if self.mode == "video":

            if not self.is_open():

                return (
                    False,
                    None,
                )

            success, frame = (
                self._read_video_frame()
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
        # Return latest available frame.
        # ==================================================

        return self._read_latest_frame()

    # ======================================================
    # READ VIDEO FRAME
    # ======================================================

    def _read_video_frame(self):

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
                        f"{self.name}: video frame "
                        f"read exception: {error}",
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
                <
                self.read_retry_attempts - 1
            ):

                time.sleep(
                    self.read_retry_delay
                )

        return (
            False,
            None,
        )

    # ======================================================
    # READ LATEST FRAME
    # ======================================================

    def _read_latest_frame(self):

        """
        Return the newest frame captured by the background
        thread.

        The frame is copied so the pipeline cannot modify
        the capture thread's internal frame.
        """

        # Wait briefly for the first frame after connection.
        deadline = (
            time.monotonic()
            + 0.2
        )

        while (
            time.monotonic()
            <
            deadline
        ):

            if self._released:

                return (
                    False,
                    None,
                )

            with self._frame_lock:

                if self._latest_frame is not None:

                    frame = (
                        self._latest_frame.copy()
                    )

                    age = (
                        time.time()
                        - self._latest_frame_time
                    )

                    self._log(
                        "debug",
                        f"{self.name}: Frame age "
                        f"{age:.3f} sec",
                    )

                    sequence = (
                        self._frame_sequence
                    )

                    self._last_read_sequence = (
                        sequence
                    )

                    return (
                        True,
                        frame,
                    )

            time.sleep(
                0.005
            )

        return (
            False,
            None,
        )

    # ======================================================
    # READ DISPLAY FRAME
    # ======================================================

    def read_display_frame(
        self,
        timeout: float = 1.0,
        target_size=None,
    ):

        """
        Blocking read for a dedicated DISPLAY thread.

        Unlike read() / get_latest_frame(), which always
        return the newest frame and intentionally drop older
        ones (so an AI pipeline never falls behind), this pulls
        frames from a small FIFO queue in the order they were
        captured. A loop that only calls this method sees every
        frame the camera produced and stays smooth, the way
        VLC would look.

        Meant to be called from its own thread, separate from
        whatever thread calls read() / get_latest_frame() for
        AI processing. The two consumers do not interfere with
        each other.

        RTSP / camera modes only. For "video" mode, use read()
        for both, since file playback is already synchronous.

        target_size: optional (width, height) tuple. If given,
        the frame is resized here before being returned. Useful
        for a browser/JPEG streaming endpoint, which typically
        doesn't need the camera's full decode resolution (e.g.
        a 2560x1440 source encoded for a small dashboard tile).
        Resizing here means the caller doesn't need its own
        cv2.resize() step before cv2.imencode().
        """

        if self.mode == "video":

            success, frame = self.read()

        else:

            try:

                frame = self._display_queue.get(
                    timeout=timeout
                )

                success = True

            except queue.Empty:

                success = False

                frame = None

        if (
            success
            and frame is not None
            and target_size is not None
        ):

            frame = cv2.resize(
                frame,
                target_size,
                interpolation=cv2.INTER_AREA,
            )

        return (
            success,
            frame,
        )

    # ======================================================
    # GET LATEST FRAME
    # ======================================================

    def get_latest_frame(self):

        with self._frame_lock:

            if self._latest_frame is None:

                return None

            return (
                self._latest_frame.copy()
            )

    # ======================================================
    # FRAME AGE
    # ======================================================

    def get_frame_age(self):

        with self._frame_lock:

            timestamp = (
                self._latest_frame_time
            )

        if timestamp <= 0:

            return None

        return max(
            0.0,
            time.time()
            -
            timestamp,
        )

    # ======================================================
    # CLEAR LATEST FRAME
    # ======================================================

    def _clear_latest_frame(self):

        with self._frame_lock:

            self._latest_frame = None

            self._latest_frame_time = 0.0

            self._frame_sequence = 0

            self._last_read_sequence = -1

        while True:

            try:

                self._display_queue.get_nowait()

            except queue.Empty:

                break

    # ======================================================
    # BACKGROUND RECONNECT
    # ======================================================

    def _thread_reconnect(self) -> bool:

        if self._released:

            return False

        if self._reconnecting:

            return False

        self._reconnecting = True

        try:

            for attempt in range(
                1,
                self.reconnect_attempts + 1,
            ):

                if (
                    self._released
                    or
                    self._capture_stop_event.is_set()
                ):

                    return False

                self._log(
                    "warning",
                    f"{self.name}: reconnect attempt "
                    f"{attempt}/"
                    f"{self.reconnect_attempts}.",
                )

                if (
                    attempt > 1
                    and self.reconnect_delay > 0
                ):

                    time.sleep(
                        self.reconnect_delay
                    )

                with self._lock:

                    self._release_capture()

                    if not self._open_capture():

                        continue

                    self._configure_capture()

                    self._update_metadata()

                    self.connected = True

                self._clear_latest_frame()

                self._log(
                    "info",
                    f"{self.name}: reconnected "
                    "successfully.",
                )

                return True

            self.connected = False

            return False

        finally:

            self._reconnecting = False

    # ======================================================
    # PUBLIC RECONNECT
    # ======================================================

    def reconnect(self) -> bool:

        if self.mode == "video":

            return False

        return self._thread_reconnect()

    # ======================================================
    # RESET
    # ======================================================

    def reset(self) -> bool:

        self._log(
            "info",
            f"{self.name}: resetting camera.",
        )

        self.release()

        return self.connect()

    # ======================================================
    # STOP CAPTURE THREAD
    # ======================================================

    def _stop_capture_thread(self):

        self._capture_stop_event.set()

        thread = (
            self._capture_thread
        )

        # Avoid joining ourselves.
        if (
            thread is not None
            and thread.is_alive()
            and thread
            is not threading.current_thread()
        ):

            thread.join(
                timeout=2.0
            )

        self._capture_thread = None

    # ======================================================
    # RELEASE
    # ======================================================

    def release(self):

        self._released = True

        self.connected = False

        self._capture_stop_event.set()

        # Release capture first. This helps unblock
        # cap.read() if the stream is waiting for data.

        with self._lock:

            self._release_capture()

        self._stop_capture_thread()

        self._clear_latest_frame()

        self._log(
            "info",
            f"{self.name}: camera released.",
        )

    # ======================================================
    # INTERNAL CAPTURE RELEASE
    # ======================================================

    def _release_capture(self):

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

    def disconnect(self):

        self.release()

    # ======================================================
    # CONNECTION STATUS
    # ======================================================

    def is_open(self) -> bool:

        with self._lock:

            return bool(
                self.connected
                and
                self.cap is not None
                and
                self.cap.isOpened()
            )

    # ======================================================
    # UPDATE METADATA
    # ======================================================

    def _update_metadata(self):

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

            # RTSP backends occasionally report invalid
            # FPS values.

            if (
                fps <= 0
                or fps != fps
                or fps > 240
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

    def get_width(self):

        return self.width

    def get_height(self):

        return self.height

    def get_fps(self):

        return self.fps

    # ======================================================
    # CAMERA INFORMATION
    # ======================================================

    def info(self):

        frame_age = (
            self.get_frame_age()
        )

        capture_thread_alive = bool(
            self._capture_thread is not None
            and
            self._capture_thread.is_alive()
        )

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

            "capture_thread_alive":
                capture_thread_alive,

            "latest_frame_age_seconds":
                (
                    round(
                        frame_age,
                        3,
                    )
                    if frame_age is not None
                    else None
                ),

            "frame_sequence":
                self._frame_sequence,
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