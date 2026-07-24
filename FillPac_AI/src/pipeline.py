"""
==========================================================
FillPac AI
Production Camera Pipeline
==========================================================

Each camera owns:
- Camera
- Tracker
- Counter
- PrintDetector
- JamDetector
- Print history
- Latest annotated frame

YOLO is NOT loaded inside this class.

All camera pipelines use ONE shared InferenceManager.

Counting Principle
------------------
The physical bag CENTER crossing the configured counting
line is the counting trigger.

Track ID is used only for:
- temporal movement history
- print-vote association
- jam movement analysis
- duplicate protection
- diagnostics

Track ID itself does NOT trigger a count.

Jam Detection
-------------
JamDetector operates independently from Counter.

Tracker
    |
    +---- Counter
    |
    +---- PrintDetector
    |
    +---- JamDetector

Jam detection NEVER changes the physical-center counting
logic.

Print Classification
--------------------
After a physical bag crossing is confirmed:

- Enough observations + print ratio >= threshold
    -> PRINTED

- Enough observations + print ratio < threshold
    -> MISSING

- Not enough observations
    -> UNKNOWN

UNKNOWN does not increase the missing count.
==========================================================
"""

from datetime import datetime, timezone

import threading
import time

import cv2

from src.camera import Camera
from src.counter import Counter
from src.jam_detector import JamDetector
from src.print_detector import PrintDetector
from src.tracker import Tracker
from src.visualizer import Visualizer


class Pipeline:

    # ======================================================
    # INITIALIZATION
    # ======================================================

    def __init__(
        self,
        camera_config,
        tracker_config,
        display_config,
        logger,
        inference_manager,
        dashboard_state=None,
        elasticsearch=None,
        count_logger=None,
    ):

        # ==================================================
        # BASIC CONFIGURATION
        # ==================================================

        self.camera_config = camera_config
        self.logger = logger
        self.inference_manager = inference_manager
        self.dashboard_state = dashboard_state
        self.elasticsearch = elasticsearch
        self.count_logger = count_logger

        self.name = camera_config["name"]

        self.camera_id = camera_config.get(
            "id"
        )

        self.roi = camera_config["roi"]

        self.window_name = self.name

        if self.inference_manager is None:

            raise ValueError(
                f"{self.name}: Pipeline requires "
                "a valid InferenceManager."
            )

        # ==================================================
        # CAMERA MODE
        # ==================================================

        self.camera_mode = camera_config.get(
            "mode",
            "video",
        )

        # ==================================================
        # RUNTIME STATE
        # ==================================================

        self.connected = False

        self.previous_time = (
            time.perf_counter()
        )

        self.last_count = 0
        self.last_print_status = None

        self.printed_count = 0
        self.missing_count = 0

        self.frame_index = 0
        self.processed_frame_count = 0

        self.last_error = None

        # ==================================================
        # DASHBOARD UPDATE CONTROL
        # ==================================================

        self.last_dashboard_publish_time = 0.0

        self.dashboard_publish_interval = max(
            float(
                camera_config.get(
                    "dashboard_publish_interval",
                    0.5,
                )
            ),
            0.0,
        )

        # ==================================================
        # INFERENCE CONFIGURATION
        # ==================================================

        self.inference_timeout = max(
            float(
                camera_config.get(
                    "inference_timeout",
                    5.0,
                )
            ),
            0.1,
        )

        # ==================================================
        # CONFIGURATION
        # ==================================================

        counting_config = (
            camera_config.get(
                "counting",
                {},
            )
            or {}
        )

        print_config = (
            camera_config.get(
                "print_detection",
                {},
            )
            or {}
        )

        jam_config = (
            camera_config.get(
                "jam_detection",
                {},
            )
            or {}
        )

        # ==================================================
        # DISPLAY CONFIGURATION
        # ==================================================

        self.display_config = dict(
            display_config or {}
        )

        self.display_config.update(
            camera_config.get(
                "display",
                {},
            )
            or {}
        )

        # ==================================================
        # CAMERA
        # ==================================================

        self.camera = Camera(
            name=self.name,
            source=camera_config.get(
                "source"
            ),
            mode=self.camera_mode,
            buffer_size=camera_config.get(
                "buffer_size",
                1,
            ),
            reconnect_attempts=camera_config.get(
                "reconnect_attempts",
                5,
            ),
            reconnect_delay=camera_config.get(
                "reconnect_delay",
                2.0,
            ),
            logger=self.logger,
        )

        # ==================================================
        # TRACKER
        # ==================================================

        self.tracker = Tracker(
            tracker_config=tracker_config,
        )

        # ==================================================
        # COUNTER
        #
        # Physical bag CENTER crossing is the counting
        # trigger.
        # ==================================================

        if isinstance(self.roi, dict):

            if self.roi.get("y") is not None:
                counting_line_y = self.roi["y"]

            elif self.roi.get("roi_y") is not None:
                counting_line_y = self.roi["roi_y"]

            elif self.roi.get("y1") is not None:
                counting_line_y = self.roi["y1"]

            elif self.roi.get("y2") is not None:
                counting_line_y = self.roi["y2"]

            else:
                counting_line_y = None

        else:
            counting_line_y = self.roi

        if counting_line_y is None:

            raise ValueError(
                f"{self.name}: counting ROI Y coordinate "
                f"is missing. ROI={self.roi}"
            )

        self.counter = Counter(

            roi_y=int(counting_line_y),

            direction=counting_config.get(
                "direction",
                "down",
            ),

            duplicate_distance=counting_config.get(
                "duplicate_distance",
                40,
            ),

            duplicate_time=counting_config.get(
                "duplicate_time",
                0.8,
            ),

            max_history=counting_config.get(
                "max_history",
                200,
            ),

            line_tolerance=counting_config.get(
                "line_tolerance",
                20,
            ),

            late_start_margin=counting_config.get(
                "late_start_margin",
                40,
            ),

            min_track_frames=counting_config.get(
                "min_track_frames",
                4,
            ),

            stale_track_frames=counting_config.get(
                "stale_track_frames",
                120,
            ),

            minimum_cross_distance=counting_config.get(
                "minimum_cross_distance",
                counting_config.get(
                    "min_cross_distance",
                    0,
                ),
            ),
        )

        # ==================================================
        # PRINT DETECTION
        # ==================================================

        self.print_detection_enabled = bool(
            print_config.get(
                "enabled",
                False,
            )
        )

        self.print_detector = PrintDetector(
            confidence_threshold=print_config.get(
                "confidence_threshold",
                print_config.get("confidence", 0.4),
            ),
            iou_threshold=print_config.get(
                "iou_threshold",
                0.0,
            ),
            min_overlap_ratio=print_config.get(
                "min_overlap_ratio",
                0.3,
            ),
            min_print_area=print_config.get(
                "min_print_area",
                0.0,
            ),
            max_print_area=print_config.get(
                "max_print_area",
                0.0,
            ),
            min_aspect_ratio=print_config.get(
                "min_aspect_ratio",
                0.0,
            ),
            max_aspect_ratio=print_config.get(
                "max_aspect_ratio",
                0.0,
            ),
            max_center_distance=print_config.get(
                "max_center_distance",
                0.0,
            ),
        )

        # ==================================================
        # JAM DETECTION V1
        #
        # One JamDetector per camera.
        #
        # It receives tracker output only.
        # It does NOT modify Counter.
        # ==================================================

        self.jam_detector = JamDetector(
            config=jam_config,
        )

        self.jam_detection_enabled = bool(
            self.jam_detector.enabled
        )

        self.jam_roi = dict(
            self.jam_detector.roi
        )

        self.jam_result = (
            self.jam_detector._empty_result()
        )

        # ==================================================
        # VISUALIZER
        # ==================================================

        self.visualizer = Visualizer()

        # ==================================================
        # PRINT CLASSIFICATION CONFIG
        # ==================================================

        self.print_vote_threshold = float(
            print_config.get(
                "vote_threshold",
                print_config.get(
                    "required_ratio",
                    0.5,
                ),
            )
        )

        self.print_vote_threshold = min(
            max(
                self.print_vote_threshold,
                0.0,
            ),
            1.0,
        )

        self.min_print_observations = max(
            int(
                print_config.get(
                    "min_observations",
                    1,
                )
            ),
            1,
        )

        self.print_history_size = max(
            int(
                print_config.get(
                    "history_size",
                    30,
                )
            ),
            1,
        )

        self.print_history_ttl_frames = max(
            int(
                print_config.get(
                    "history_ttl_frames",
                    120,
                )
            ),
            1,
        )

        # ==================================================
        # PRINT OBSERVATION FILTERING
        # ==================================================

        self.min_print_observation_speed = max(
            float(
                print_config.get(
                    "min_observation_speed",
                    0.0,
                )
            ),
            0.0,
        )

        self.skip_motion_jump_print_observations = bool(
            print_config.get(
                "skip_motion_jump_observations",
                True,
            )
        )

        # ==================================================
        # PRINT TRACK HISTORY
        # ==================================================

        self.track_print_votes = {}
        self.track_print_last_seen = {}

        # ==================================================
        # FRAME SHARING
        # ==================================================

        self._frame_lock = threading.Lock()

        self._latest_frame = None

        # ==================================================
        # RESTORE PREVIOUS COUNTS
        # ==================================================

        self._restore_persisted_counts()

        # ==================================================
        # REGISTER CAMERA
        # ==================================================

        self._register_dashboard_camera()

    # ======================================================
    # RESTORE PERSISTED COUNTS
    # ======================================================

    def _restore_persisted_counts(
        self,
    ):

        if self.dashboard_state is None:
            return

        try:

            snapshot = (
                self.dashboard_state.snapshot()
            )

            cameras = snapshot.get(
                "cameras",
                {},
            )

            camera_state = cameras.get(
                self.name,
                {},
            )

            restored_count = int(
                camera_state.get(
                    "total_count",
                    camera_state.get(
                        "count",
                        0,
                    ),
                )
                or 0
            )

            restored_printed = int(
                camera_state.get(
                    "printed_count",
                    camera_state.get(
                        "printed_bags_count",
                        0,
                    ),
                )
                or 0
            )

            restored_missing = int(
                camera_state.get(
                    "missing_count",
                    camera_state.get(
                        "not_printed_bags_count",
                        0,
                    ),
                )
                or 0
            )

            if restored_count > 0:

                self.counter.total_count = (
                    restored_count
                )

                self.last_count = (
                    restored_count
                )

            self.printed_count = max(
                restored_printed,
                0,
            )

            self.missing_count = max(
                restored_missing,
                0,
            )

        except Exception as error:

            self.logger.warning(
                f"{self.name}: persisted count "
                f"restore failed: {error}"
            )

    # ======================================================
    # REGISTER CAMERA
    # ======================================================

    def _register_dashboard_camera(
        self,
    ):

        if self.dashboard_state is None:
            return

        try:

            self.dashboard_state.register_camera(

                camera_name=self.name,

                camera_id=self.camera_id,

                enabled=self.camera_config.get(
                    "enabled",
                    True,
                ),

                configured=True,

                mode=self.camera_mode,

                print_detection_enabled=(
                    self.print_detection_enabled
                ),

                # --------------------------------------
                # JAM DETECTION
                # --------------------------------------

                jam_detection_enabled=(
                    self.jam_detection_enabled
                ),

                source_type=self.camera_mode,

                metadata={

                    "roi":
                        self.roi,

                    "counting_method":
                        "physical_center",

                    "counting_direction":
                        self.camera_config
                        .get(
                            "counting",
                            {},
                        )
                        .get(
                            "direction",
                            "down",
                        ),

                    # --------------------------------------
                    # JAM V1
                    # --------------------------------------

                    "jam_detection_enabled":
                        self.jam_detection_enabled,

                    "jam_roi":
                        self.jam_roi,
                },
            )

            self.dashboard_state.update_camera(

                camera_name=self.name,

                count=self.counter.total_count,

                total_count=(
                    self.counter.total_count
                ),

                printed_count=self.printed_count,

                missing_count=self.missing_count,

                print_detection_enabled=(
                    self.print_detection_enabled
                ),

                print_status=(
                    "unknown"
                    if self.print_detection_enabled
                    else "disabled"
                ),

                status="offline",

                fps=0.0,

                frame_count=0,

                # --------------------------------------
                # JAM V1
                # --------------------------------------

                jam_detection_enabled=(
                    self.jam_detection_enabled
                ),

                jam_status=(
                    "normal"
                    if self.jam_detection_enabled
                    else "disabled"
                ),

                jam_detected=False,

                jam_warning=False,

                active_jam_count=0,

                active_jam_track_ids=[],
            )

        except Exception as error:

            self.logger.warning(
                f"{self.name}: dashboard camera "
                f"registration failed: {error}"
            )

    # ======================================================
    # PROCESS FRAME
    # ======================================================

    def process(
        self,
    ):

        try:

            # ==============================================
            # CONNECT CAMERA
            # ==============================================

            if not self.connected:

                self.connected = (
                    self.camera.connect()
                )

                if not self.connected:

                    self._publish_runtime_status(
                        fps=0.0,
                        print_status="offline",
                        runtime_status="offline",
                        force=True,
                    )

                    return False

                self.previous_time = (
                    time.perf_counter()
                )

                self.last_error = None

                self._publish_runtime_status(
                    fps=0.0,
                    print_status=(
                        "unknown"
                        if self.print_detection_enabled
                        else "disabled"
                    ),
                    runtime_status="online",
                    force=True,
                )

            # ==============================================
            # READ FRAME
            # ==============================================

            frame = self.read_frame()

            if frame is None:

                self.release()

                self._publish_runtime_status(
                    fps=0.0,
                    print_status="offline",
                    runtime_status="offline",
                    force=True,
                )

                return False

            self.frame_index += 1

            # ==============================================
            # CPU OPTIMIZATION
            #
            # Process every second frame.
            # ==============================================

            if self.frame_index % 2 != 0:
                return True

            self.processed_frame_count += 1

            # ==============================================
            # YOLO INFERENCE
            # ==============================================

            detections = self.detect(
                frame
            )

            # ==============================================
            # TRACKER FRAME SIZE
            # ==============================================

            height, width = (
                frame.shape[:2]
            )

            self.tracker.set_frame_size(
                width=width,
                height=height,
            )

            # ==============================================
            # TRACK BAGS
            # ==============================================

            tracks = self.track(
                detections
            )

            # ==============================================
            # PRINT DETECTION
            # ==============================================

            print_results = (
                self.print_detection(
                    tracks,
                    detections,
                )
            )

            # ==============================================
            # RECORD PRINT VOTES
            # ==============================================

            self.record_print_observations(
                print_results,
                tracks,
            )

            # ==============================================
            # JAM DETECTION V1
            #
            # IMPORTANT:
            # This branch is completely independent from
            # physical-center counting.
            # ==============================================

            self.jam_result = (
                self.jam_detector.update(
                    tracks,
                    timestamp=time.perf_counter(),
                )
            )

            # ==============================================
            # FILTER UNSTABLE TRACKS FOR COUNTING
            # ==============================================

            countable_tracks = (
                self.countable_tracks(
                    tracks
                )
            )

            # ==============================================
            # COUNT PHYSICAL BAG CENTER CROSSING
            #
            # JAM STATE DOES NOT BLOCK COUNTING.
            # ==============================================

            count = self.count(
                countable_tracks
            )

            # ==============================================
            # FPS
            # ==============================================

            fps = self.calculate_fps()

            # ==============================================
            # VISUALIZATION
            # ==============================================

            self.draw(
                frame,
                tracks,
                detections,
                print_results,
                count,
                fps,
            )

            # ==============================================
            # STORE LATEST ANNOTATED FRAME
            # ==============================================

            self._set_latest_frame(
                frame
            )

            # ==============================================
            # DASHBOARD / ELASTICSEARCH EVENTS
            # ==============================================

            self._publish_events(
                count,
                fps,
                print_results,
            )

            self.last_error = None

            return True

        except TimeoutError as error:

            self.last_error = str(
                error
            )

            self.logger.warning(
                f"{self.name} inference timeout: "
                f"{error}"
            )

            self._publish_runtime_status(
                fps=0.0,
                print_status="inference_timeout",
                runtime_status="online",
                force=True,
            )

            return True

        except Exception as error:

            self.last_error = str(
                error
            )

            self.logger.error(
                f"Unhandled exception in pipeline "
                f"{self.name}: {error}"
            )

            self.release()

            self._publish_runtime_status(
                fps=0.0,
                print_status="error",
                runtime_status="error",
                force=True,
            )

            return False

    # ======================================================
    # PIPELINE THREAD
    # ======================================================

    def run(
        self,
        stop_event,
    ):

        self.logger.info(
            f"{self.name} pipeline thread started."
        )

        while not stop_event.is_set():

            active = self.process()

            if not active:

                time.sleep(
                    0.1
                )

        self.logger.info(
            f"{self.name} pipeline thread stopping."
        )

        self.release()

        self._publish_runtime_status(
            fps=0.0,
            print_status="offline",
            runtime_status="offline",
            force=True,
        )

    # ======================================================
    # READ FRAME
    # ======================================================

    def read_frame(
        self,
    ):

        success, frame = (
            self.camera.read()
        )

        if not success:

            self.logger.warning(
                f"{self.name} frame read failed "
                "or stream ended."
            )

            return None

        return frame

    # ======================================================
    # DETECT
    # ======================================================

    def detect(
        self,
        frame,
    ):

        return self.inference_manager.infer(

            camera_name=self.name,

            frame=frame,

            timeout=self.inference_timeout,
        )

    # ======================================================
    # TRACKING
    # ======================================================

    def track(
        self,
        detections,
    ):

        bag_detections = [

            detection

            for detection in detections

            if detection.get(
                "class_id"
            ) == 0
        ]

        return self.tracker.update(
            bag_detections
        )

    # ======================================================
    # COUNTABLE TRACKS
    # ======================================================

    @staticmethod
    def countable_tracks(
        tracks,
    ):

        return [

            track

            for track in tracks

            if not track.get(
                "unstable",
                False,
            )
        ]

    # ======================================================
    # COUNT
    # ======================================================

    def count(
        self,
        tracks,
    ):

        return self.counter.update(
            tracks
        )

    # ======================================================
    # PRINT DETECTION
    # ======================================================

    def print_detection(
        self,
        tracks,
        detections,
    ):

        if not self.print_detection_enabled:

            return []

        return self.print_detector.update(
            tracks,
            detections,
        )

    # ======================================================
    # RECORD PRINT OBSERVATIONS
    # ======================================================

    def record_print_observations(
        self,
        print_results,
        tracks,
    ):

        if not self.print_detection_enabled:
            return

        track_lookup = {

            track.get(
                "track_id"
            ):
                track

            for track in tracks

            if track.get(
                "track_id"
            ) is not None
        }

        for result in print_results:

            track_id = result.get(
                "track_id"
            )

            if track_id is None:
                continue

            track = track_lookup.get(
                track_id,
                {},
            )

            if not self._is_valid_print_observation(
                track
            ):

                continue

            print_present = result.get(
                "print_present"
            )

            if print_present is None:
                continue

            votes = (
                self.track_print_votes.setdefault(
                    track_id,
                    [],
                )
            )

            votes.append(
                bool(
                    print_present
                )
            )

            if len(votes) > self.print_history_size:

                del votes[
                    :-self.print_history_size
                ]

            self.track_print_last_seen[
                track_id
            ] = self.frame_index

        self._trim_print_history(
            active_track_ids=set(
                track_lookup
            )
        )

    # ======================================================
    # VALID PRINT OBSERVATION
    # ======================================================

    def _is_valid_print_observation(
        self,
        track,
    ):

        if track.get(
            "unstable",
            False,
        ):

            return False

        if (
            self.skip_motion_jump_print_observations
            and
            track.get(
                "motion_jump",
                False,
            )
        ):

            return False

        if (
            float(
                track.get(
                    "speed",
                    0.0,
                )
                or 0.0
            )
            <
            self.min_print_observation_speed
        ):

            return False

        return True

    # ======================================================
    # TRIM PRINT HISTORY
    # ======================================================

    def _trim_print_history(
        self,
        active_track_ids=None,
    ):

        active_track_ids = (
            active_track_ids
            or set()
        )

        stale_ids = []

        for (
            track_id,
            last_seen,
        ) in self.track_print_last_seen.items():

            age = (
                self.frame_index
                -
                last_seen
            )

            if (
                track_id not in active_track_ids
                and
                age > self.print_history_ttl_frames
            ):

                stale_ids.append(
                    track_id
                )

        for track_id in stale_ids:

            self.track_print_votes.pop(
                track_id,
                None,
            )

            self.track_print_last_seen.pop(
                track_id,
                None,
            )

    # ======================================================
    # CLASSIFY PRINT HISTORY
    # ======================================================

    def _classify_print_history(
        self,
        track_id,
    ):

        if not self.print_detection_enabled:

            return None

        votes = (
            self.track_print_votes.get(
                track_id,
                [],
            )
        )

        observation_count = len(
            votes
        )

        if (
            observation_count
            <
            self.min_print_observations
        ):

            return None

        positive_count = sum(
            1
            for vote in votes
            if vote
        )

        ratio = (
            positive_count
            /
            max(
                observation_count,
                1,
            )
        )

        return (
            ratio
            >=
            self.print_vote_threshold
        )

    # ======================================================
    # DRAW
    # ======================================================

    def draw(
        self,
        frame,
        tracks,
        detections,
        print_results,
        count,
        fps,
    ):

        self.visualizer.visualize(

            frame=frame,

            camera_name=self.name,

            count=count,

            printed_count=self.printed_count,

            missing_count=self.missing_count,

            fps=fps,

            roi=self.roi,

            bag_tracks=tracks,

            all_detections=detections,

            print_results=print_results,

            display_config=self.display_config,

            counted_bags=(
                self.counter.last_counted_bags
            ),

            # ==========================================
            # JAM V1
            # ==========================================

            jam_result=self.jam_result,

            jam_roi=self.jam_roi,
        )

    # ======================================================
    # DISPLAY
    # ======================================================

    def publish(
        self,
    ):

        frame = self.get_latest_frame()

        if frame is None:
            return

        cv2.imshow(
            self.window_name,
            frame,
        )

    # ======================================================
    # FRAME STORAGE
    # ======================================================

    def _set_latest_frame(
        self,
        frame,
    ):

        with self._frame_lock:

            self._latest_frame = (

                frame.copy()

                if frame is not None

                else None
            )

    # ======================================================
    # PUBLIC LATEST FRAME
    # ======================================================

    def get_latest_frame(
        self,
    ):

        with self._frame_lock:

            return (

                self._latest_frame.copy()

                if self._latest_frame is not None

                else None
            )

    # ======================================================
    # BACKWARD COMPATIBILITY
    # ======================================================

    def _get_latest_frame(
        self,
    ):

        return self.get_latest_frame()

    # ======================================================
    # FPS
    # ======================================================

    def calculate_fps(
        self,
    ):

        current_time = (
            time.perf_counter()
        )

        elapsed = max(
            current_time
            -
            self.previous_time,
            1e-6,
        )

        self.previous_time = (
            current_time
        )

        return (
            1.0
            /
            elapsed
        )

    # ======================================================
    # RELEASE
    # ======================================================

    def release(
        self,
    ):

        try:

            self.camera.release()

        except Exception:

            self.logger.warning(
                f"{self.name}: camera release failed."
            )

        self.connected = False

        # ----------------------------------------------
        # Reset jam temporal memory when stream ends.
        # ----------------------------------------------

        try:

            self.jam_detector.reset()

            self.jam_result = (
                self.jam_detector._empty_result()
            )

        except Exception:

            self.logger.warning(
                f"{self.name}: JamDetector reset failed."
            )

        with self._frame_lock:

            self._latest_frame = None

    # ======================================================
    # PUBLISH EVENTS
    # ======================================================

    def _publish_events(
        self,
        count,
        fps,
        print_results,
    ):

        # --------------------------------------------------
        # Finalize print result ONLY for bags that crossed
        # during this frame.
        # --------------------------------------------------

        counted_results = (
            self._update_print_totals()
        )

        # --------------------------------------------------
        # Current live print status
        # --------------------------------------------------

        live_print_status = (
            self._summarize_print_status(
                print_results
            )
        )

        # --------------------------------------------------
        # Count-event print status
        # --------------------------------------------------

        counted_print_status = (

            self._summarize_counted_print_status(
                counted_results
            )

            if counted_results

            else None
        )

        # ==================================================
        # DASHBOARD
        # ==================================================

        self._publish_runtime_status(

            fps=fps,

            print_status=live_print_status,

            runtime_status="online",

            frame_processed=True,

            count_event=bool(
                counted_results
            ),
        )

        # ==================================================
        # ELASTICSEARCH CAMERA EVENT
        # ==================================================

        if self.elasticsearch is not None:

            try:

                self.elasticsearch.create_camera_event(
                    self.name,
                    fps,
                    "online",
                )

            except Exception:

                self.logger.warning(
                    f"{self.name}: failed publishing "
                    "camera event to Elasticsearch."
                )

        # ==================================================
        # ELASTICSEARCH PRINT EVENT
        # ==================================================

        if (
            self.elasticsearch is not None
            and
            counted_print_status
            in {
                "printed",
                "missing",
            }
            and
            counted_print_status
            != self.last_print_status
        ):

            try:

                self.elasticsearch.create_print_event(

                    self.name,

                    counted_print_status
                    == "printed",
                )

            except Exception:

                self.logger.warning(
                    f"{self.name}: failed publishing "
                    "print event to Elasticsearch."
                )

        # ==================================================
        # COUNT EVENTS
        # ==================================================

        for counted_bag in counted_results:

            # ----------------------------------------------
            # ELASTICSEARCH COUNT EVENT
            # ----------------------------------------------

            if self.elasticsearch is not None:

                try:

                    self.elasticsearch.create_count_event(

                        self.name,

                        counted_bag[
                            "total_count"
                        ],

                        counted_bag[
                            "center"
                        ],
                    )

                except Exception:

                    self.logger.warning(
                        f"{self.name}: failed publishing "
                        "count event to Elasticsearch."
                    )

            # ----------------------------------------------
            # JSONL COUNT EVENT
            # ----------------------------------------------

            if self.count_logger is not None:

                try:

                    self.count_logger.log_count(

                        camera_name=self.name,

                        total_count=counted_bag[
                            "total_count"
                        ],

                        track_id=counted_bag[
                            "track_id"
                        ],

                        center=counted_bag[
                            "center"
                        ],

                        print_present=counted_bag[
                            "print_present"
                        ],

                        printed_count=counted_bag[
                            "printed_count"
                        ],

                        missing_count=counted_bag[
                            "missing_count"
                        ],

                        print_detection_enabled=(
                            self.print_detection_enabled
                        ),
                    )

                except Exception:

                    self.logger.warning(
                        f"{self.name}: failed writing "
                        "count event."
                    )

        self.last_count = count

        if counted_print_status is not None:

            self.last_print_status = (
                counted_print_status
            )

    # ======================================================
    # UPDATE PRINT TOTALS
    # ======================================================

    def _update_print_totals(
        self,
    ):

        counted_results = []

        counted_bags = (
            self.counter.last_counted_bags
            or []
        )

        for counted_bag in counted_bags:

            track_id = counted_bag.get(
                "track_id"
            )

            print_present = None

            if self.print_detection_enabled:

                print_present = (
                    self._classify_print_history(
                        track_id
                    )
                )

                if print_present is True:

                    self.printed_count += 1

                elif print_present is False:

                    self.missing_count += 1

            result = dict(
                counted_bag
            )

            result[
                "print_present"
            ] = print_present

            result[
                "printed_count"
            ] = self.printed_count

            result[
                "missing_count"
            ] = self.missing_count

            counted_results.append(
                result
            )

            # ----------------------------------------------
            # This bag is already finalized.
            # Its print-vote history is no longer needed.
            # ----------------------------------------------

            if track_id is not None:

                self.track_print_votes.pop(
                    track_id,
                    None,
                )

                self.track_print_last_seen.pop(
                    track_id,
                    None,
                )

        return counted_results

    # ======================================================
    # SUMMARIZE LIVE PRINT STATUS
    # ======================================================

    def _summarize_print_status(
        self,
        print_results,
    ):

        if not self.print_detection_enabled:

            return "disabled"

        if not print_results:

            return "unknown"

        statuses = []

        for result in print_results:

            value = result.get(
                "print_present"
            )

            if value is True:

                statuses.append(
                    "printed"
                )

            elif value is False:

                statuses.append(
                    "missing"
                )

        if not statuses:

            return "unknown"

        if "missing" in statuses:

            return "missing"

        return "printed"

    # ======================================================
    # SUMMARIZE COUNTED PRINT STATUS
    # ======================================================

    @staticmethod
    def _summarize_counted_print_status(
        counted_results,
    ):

        if not counted_results:
            return None

        statuses = []

        for result in counted_results:

            value = result.get(
                "print_present"
            )

            if value is True:

                statuses.append(
                    "printed"
                )

            elif value is False:

                statuses.append(
                    "missing"
                )

            else:

                statuses.append(
                    "unknown"
                )

        if "missing" in statuses:

            return "missing"

        if "printed" in statuses:

            return "printed"

        return "unknown"

    # ======================================================
    # PUBLISH RUNTIME STATUS
    # ======================================================

    def _publish_runtime_status(
        self,
        fps,
        print_status,
        runtime_status=None,
        force=False,
        frame_processed=False,
        count_event=False,
    ):

        if self.dashboard_state is None:
            return

        current_time = (
            time.monotonic()
        )

        # --------------------------------------------------
        # Throttle ordinary dashboard updates.
        #
        # Count events, state transitions, startup/shutdown
        # and explicit force updates bypass throttling.
        # --------------------------------------------------

        if (
            not force
            and
            not count_event
            and
            (
                current_time
                -
                self.last_dashboard_publish_time
            )
            <
            self.dashboard_publish_interval
        ):

            return

        self.last_dashboard_publish_time = (
            current_time
        )

        now_iso = (
            datetime.now(
                timezone.utc
            )
            .isoformat()
        )

        runtime_status = (
            runtime_status
            or
            (
                "online"
                if self.connected
                else "offline"
            )
        )

        jam_result = (
            self.jam_result
            if isinstance(
                self.jam_result,
                dict,
            )
            else {}
        )

        jam_status = (
            jam_result.get(
                "status",
                "normal",
            )
            if self.jam_detection_enabled
            else "disabled"
        )

        jam_detected = bool(
            jam_result.get(
                "jam_detected",
                False,
            )
        )

        jam_warning = bool(
            jam_result.get(
                "warning",
                False,
            )
        )

        active_jam_track_ids = (
            jam_result.get(
                "active_jam_track_ids",
                [],
            )
            or []
        )

        active_jam_count = int(
            jam_result.get(
                "active_jam_count",
                0,
            )
            or 0
        )

        jam_tracks = (
            jam_result.get(
                "tracks",
                [],
            )
            or []
        )

        try:

            self.dashboard_state.update_camera(

                camera_name=self.name,

                count=self.counter.total_count,

                total_count=(
                    self.counter.total_count
                ),

                fps=fps,

                status=runtime_status,

                print_status=print_status,

                printed_count=self.printed_count,

                missing_count=self.missing_count,

                printed_bags_count=(
                    self.printed_count
                ),

                not_printed_bags_count=(
                    self.missing_count
                ),

                print_detection_enabled=(
                    self.print_detection_enabled
                ),

                frame_count=(
                    self.processed_frame_count
                ),

                last_frame_at=(
                    now_iso
                    if frame_processed
                    else None
                ),

                last_count_at=(
                    now_iso
                    if count_event
                    else None
                ),

                last_error=(
                    self.last_error
                    if self.last_error
                    else ""
                ),

                # ==========================================
                # JAM V1 DASHBOARD STATE
                # ==========================================

                jam_detection_enabled=(
                    self.jam_detection_enabled
                ),

                jam_status=jam_status,

                jam_detected=jam_detected,

                jam_warning=jam_warning,

                active_jam_count=(
                    active_jam_count
                ),

                active_jam_track_ids=(
                    active_jam_track_ids
                ),

                jam_tracks=jam_tracks,
            )

        except Exception:

            self.logger.warning(
                f"{self.name}: dashboard runtime "
                "update failed."
            )