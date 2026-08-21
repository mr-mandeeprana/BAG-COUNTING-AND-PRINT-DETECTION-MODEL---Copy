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
- JamDetector              -> Condition A
- BagSpacingDetector       -> Condition B
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
- spacing pair association
- duplicate protection
- diagnostics

Track ID itself does NOT trigger a count.

Jam Detection
-------------
Condition A:
    Movement-based JamDetector.

Condition B:
    Calibrated physical edge-to-edge bag spacing.

Final Jam:
    Condition A OR Condition B

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
from database.repository import (
    save_production_event,
    save_print_event,
    start_jam_event,
    end_jam_event,
)
from datetime import datetime, timezone

import threading
import time

import cv2

from src.bag_spacing_detector import BagSpacingDetector
from src.camera import Camera
from src.counter import Counter
from src.entry_roi_counter import EntryROICounter
from src.jam_detector import JamDetector
from src.roi_occupancy_detector import ROIOccupancyDetector
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

        # Separate ROI-entry count
        self.entry_roi_count = 0

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

        # ==================================================
        # ENTRY ROI COUNTING CONFIGURATION
        # ==================================================

        entry_roi_counting_config = (
            camera_config.get(
                "entry_roi_counting",
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

        spacing_config = (
            camera_config.get(
                "bag_spacing",
                {},
            )
            or {}
        )

        condition_c_config = (
            camera_config.get(
                "condition_c",
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
        # ==================================================

        counting_roi = camera_config.get(
            "roi"
        )

        if not isinstance(counting_roi, dict):
            raise ValueError(
                f"{self.name}: counting ROI must be a "
                f"dictionary with x1,y1,x2,y2. "
                f"Got: {counting_roi}"
            )

        required_roi_keys = {
            "x1",
            "y1",
            "x2",
            "y2",
        }

        missing_keys = (
            required_roi_keys
            - set(counting_roi.keys())
        )

        if missing_keys:
            raise ValueError(
                f"{self.name}: counting ROI is missing "
                f"{sorted(missing_keys)}"
            )

        self.counter = Counter(

            roi=counting_roi,

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
        # SEPARATE ENTRY ROI BAG COUNTER
        # ==================================================

        self.entry_roi_counting_enabled = bool(
            entry_roi_counting_config.get(
                "enabled",
                False,
            )
        )

        entry_roi = (
            entry_roi_counting_config.get(
                "roi",
                {},
            )
            or {}
        )

        if self.entry_roi_counting_enabled:

            self.entry_roi_counter = EntryROICounter(
                roi=entry_roi,

                min_track_frames=entry_roi_counting_config.get(
                    "min_track_frames",
                    4,
                ),

                duplicate_distance=entry_roi_counting_config.get(
                    "duplicate_distance",
                    50,
                ),

                max_history=entry_roi_counting_config.get(
                    "max_history",
                    300,
                ),
            )

        else:

            self.entry_roi_counter = None

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
                print_config.get(
                    "confidence",
                    0.4,
                ),
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
        # JAM DETECTION - CONDITION A
        #
        # Existing movement/time based detector.
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
        # BAG SPACING - CONDITION B
        #
        # No timer.
        #
        # Physical calibrated edge-to-edge distance:
        #
        # gap <= threshold -> JAM
        # ==================================================

        self.bag_spacing_detector = (
            BagSpacingDetector(
                config=spacing_config,
            )
        )

        self.bag_spacing_enabled = bool(
            self.bag_spacing_detector.enabled
        )

        self.spacing_roi = dict(
            self.bag_spacing_detector.roi
        )

        self.spacing_result = (
            self.bag_spacing_detector._empty_result()
        )

        # ==================================================
        # CONDITION C - ROI OCCUPANCY JAM
        # ==================================================

        self.condition_c_detector = (
            ROIOccupancyDetector(
                config=condition_c_config,
            )
        )

        self.condition_c_enabled = bool(
            self.condition_c_detector.enabled
        )

        self.condition_c_roi = dict(
            self.condition_c_detector.roi
        )

        self.condition_c_result = {

            "jam": False,

            "status": "normal",

            "bag_count": 0,

            "track_ids": [],

            "minimum_gap_mm": None,

            "distances": [],

            "image_path": None,
        }

        self.condition_c_start_time = None

        # ==================================================
        # FINAL JAM RESULT
        #
        # Condition A OR Condition B
        # ==================================================

        self.final_jam_result = (
            self._build_final_jam_result()
        )

        # ==================================================
        # JAM EVENT LOGGING STATE
        # ==================================================

        self.previous_jam_detected = False
        self.previous_jam_types = set()

        self.previous_condition_a_jam = False
        self.previous_condition_b_jam = False
        self.previous_condition_c_jam = False

        # SQL Server jam event tracking
        self.condition_a_sql_jam_id = None
        self.condition_a_sql_jam_start = None

        self.condition_b_sql_jam_id = None
        self.condition_b_sql_jam_start = None

        self.condition_c_sql_jam_id = None
        self.condition_c_sql_jam_start = None

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

        # Backward-compatible alias — some call sites and tests
        # refer to this configuration value by this name.
        self.min_print_votes = self.min_print_observations

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

                    # Condition A
                    "jam_detection_enabled":
                        self.jam_detection_enabled,

                    "jam_roi":
                        self.jam_roi,

                    # Condition B
                    "bag_spacing_enabled":
                        self.bag_spacing_enabled,

                    "spacing_roi":
                        self.spacing_roi,

                    "spacing_threshold_mm":
                        self.bag_spacing_detector
                        .jam_threshold_mm,

                    "condition_c_enabled":
                        self.condition_c_enabled,

                    "condition_c_roi":
                        self.condition_c_roi,
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

                # Condition A
                movement_jam_enabled=(
                    self.jam_detection_enabled
                ),

                movement_jam_status=(
                    "normal"
                    if self.jam_detection_enabled
                    else "disabled"
                ),

                movement_jam_detected=False,

                movement_jam_warning=False,

                movement_jam_track_ids=[],

                # Condition B
                spacing_detection_enabled=(
                    self.bag_spacing_enabled
                ),

                spacing_status=(
                    "normal"
                    if self.bag_spacing_enabled
                    else "disabled"
                ),

                spacing_jam_detected=False,

                spacing_threshold_mm=(
                    self.bag_spacing_detector
                    .jam_threshold_mm
                ),

                minimum_gap_mm=None,

                spacing_pairs=[],

                spacing_jam_pairs=[],

                spacing_jam_track_ids=[],

                # ==========================================
                # CONDITION C
                #
                # ROI Occupancy Detector
                #
                # Publishes:
                # - ROI Bag Count
                # - Track IDs
                # - Minimum Gap
                # - Distances
                # - ROI Image
                # - ROI Coordinates
                # - Max Allowed Bags / Occupancy %
                # - Jam Timestamp / Duration
                # ==========================================
                condition_c_enabled=(
                    self.condition_c_enabled
                ),

                condition_c_status=(
                    "normal"
                    if self.condition_c_enabled
                    else "disabled"
                ),

                condition_c_detected=False,

                condition_c_bag_count=0,

                condition_c_track_ids=[],

                condition_c_minimum_gap_mm=None,

                condition_c_distances=[],

                condition_c_image_path=None,

                condition_c_roi=(
                    self.condition_c_roi
                ),

                condition_c_max_allowed_bags=(
                    self.condition_c_detector
                    .max_allowed_bags
                ),

                condition_c_roi_occupancy=0,

                condition_c_timestamp=None,

                condition_c_duration=0,

                # Final combined jam
                jam_detection_enabled=bool(
                    self.jam_detection_enabled
                    or
                    self.bag_spacing_enabled
                    or
                    self.condition_c_enabled
                ),

                jam_status="normal",

                jam_detected=False,

                jam_warning=False,

                jam_types=[],

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
            # ==============================================

            if self.frame_index % 2 != 0:
                return True

            self.processed_frame_count += 1

            # ==============================================
            # YOLO
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

            self.record_print_observations(
                print_results,
                tracks,
            )

            # ==============================================
            # CONDITION A - MOVEMENT JAM
            # ==============================================

            self.jam_result = (
                self.jam_detector.update(
                    tracks,
                    timestamp=time.perf_counter(),
                )
            )

            # ==============================================
            # CONDITION B - BAG SPACING JAM
            #
            # No timer.
            # Uses current live tracks.
            # ==============================================

            self.spacing_result = (
                self.bag_spacing_detector.update(
                    tracks
                )
            )

            # ==============================================
            # CONDITION C
            # ==============================================

            try:

                self.condition_c_result = (
                    self.condition_c_detector.process(
                        frame=frame,
                        tracks=tracks,
                        spacing_result=self.spacing_result,
                        camera_name=self.name,
                    )
                )

            except Exception as error:

                import traceback

                self.logger.error(
                    f"{self.name}: Condition C failed: {error}"
                )

                traceback.print_exc()

                self.condition_c_result = {

                    "jam": False,

                    "status": "normal",

                    "bag_count": 0,

                    "track_ids": [],

                    "minimum_gap_mm": None,

                    "distances": [],

                    "image_path": None,
                }

            if self.condition_c_result.get("jam", False):

                if self.condition_c_start_time is None:

                    self.condition_c_start_time = (
                        time.perf_counter()
                    )

            else:

                self.condition_c_start_time = None

            # ==============================================
            # FINAL JAM
            #
            # A OR B OR C
            # ==============================================

            self.final_jam_result = (
                self._build_final_jam_result()
            )

            # ==============================================
            # PERSIST JAM EVENTS
            # ==============================================

            self._log_jam_events()

            # ==============================================
            # FILTER COUNTING TRACKS
            # ==============================================

            countable_tracks = (
                self.countable_tracks(
                    tracks
                )
            )

            # ==============================================
            # EXISTING PHYSICAL-CENTER LINE COUNTING
            # ==============================================

            count = self.count(
                countable_tracks
            )

            # ==============================================
            # NEW ENTRY ROI COUNTING
            #
            # OUTSIDE → INSIDE ROI = +1
            # ==============================================

            if (
                self.entry_roi_counter is not None
            ):

                self.entry_roi_count = (
                    self.entry_roi_counter.update(
                        countable_tracks
                    )
                )

            # ==============================================
            # ENTRY ROI COUNT EVENTS
            # ==============================================

            if (
                self.entry_roi_counter is not None
                and self.entry_roi_counter.last_counted_bags
            ):

                for roi_bag in (
                    self.entry_roi_counter.last_counted_bags
                ):

                    track_id = roi_bag.get("track_id")
                    center = roi_bag.get("center")

                    print(
                        f"[ENTRY ROI COUNT +1] "
                        f"Track ID={track_id} "
                        f"Center={center} "
                        f"TOTAL={self.entry_roi_count}"
                    )

                    # ------------------------------------------
                    # PERSIST ROI EVENT
                    # ------------------------------------------
                    if self.count_logger is not None:

                        try:

                            self.count_logger.log_event(
                                event_type="roi_entry",
                                camera_name=self.name,
                                track_id=track_id,
                                center=center,
                                roi=self.entry_roi_counter.roi,
                                roi_count=self.entry_roi_count,
                            )

                        except Exception as error:

                            self.logger.warning(
                                f"{self.name}: "
                                f"failed to log ROI entry event: "
                                f"{error}"
                            )

            entry_roi_count = (
                self.entry_roi_counter.total_count
                if self.entry_roi_counter is not None
                else 0
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
                entry_roi_count,
            )

            self._set_latest_frame(
                frame
            )

            # ==============================================
            # EVENTS
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
    # CONDITION C RESULT ACCESSOR
    # ======================================================

    def _condition_c(
        self,
    ):

        return (
            self.condition_c_result
            if isinstance(
                self.condition_c_result,
                dict,
            )
            else {}
        )

    # ======================================================
    # ENTRY ROI STATE
    # ======================================================

    def _get_entry_roi_state(self):
        """
        Return current bags whose physical center
        is inside the Entry ROI.
        """

        if self.entry_roi_counter is None:
            return {
                "count": 0,
                "track_ids": [],
                "bags": [],
            }

        bags = []

        for track_id, inside in (
            self.entry_roi_counter.track_inside_roi.items()
        ):

            if not inside:
                continue

            center = (
                self.entry_roi_counter.track_centers.get(
                    track_id
                )
            )

            if center is None:
                continue

            bags.append(
                {
                    "track_id": track_id,
                    "center": [
                        float(center[0]),
                        float(center[1]),
                    ],
                }
            )

        return {
            "count": len(bags),
            "track_ids": [
                bag["track_id"]
                for bag in bags
            ],
            "bags": bags,
        }

    # ======================================================
    # BUILD FINAL JAM RESULT
    # ======================================================

    def _build_final_jam_result(
        self,
    ):

        movement = (
            self.jam_result
            if isinstance(
                self.jam_result,
                dict,
            )
            else {}
        )

        spacing = (
            self.spacing_result
            if isinstance(
                self.spacing_result,
                dict,
            )
            else {}
        )

        condition_c = self._condition_c()

        movement_detected = bool(
            movement.get(
                "jam_detected",
                False,
            )
        )

        movement_warning = bool(
            movement.get(
                "warning",
                False,
            )
        )

        spacing_detected = bool(
            spacing.get(
                "jam_detected",
                False,
            )
        )

        condition_c_detected = bool(
            condition_c.get(
                "jam",
                False,
            )
        )

        jam_detected = bool(
            movement_detected
            or
            spacing_detected
            or
            condition_c_detected
        )

        jam_types = []

        if movement_detected:

            jam_types.append(
                "movement"
            )

        if spacing_detected:

            jam_types.append(
                "bag_spacing"
            )

        if condition_c_detected:

            jam_types.append(
                "roi_occupancy"
            )

        movement_ids = (
            movement.get(
                "active_jam_track_ids",
                [],
            )
            or []
        )

        spacing_ids = (
            spacing.get(
                "active_jam_track_ids",
                [],
            )
            or []
        )

        condition_c_ids = (
            condition_c.get(
                "track_ids",
                [],
            )
            or []
        )

        active_ids = sorted(
            {
                int(track_id)
                for track_id
                in (
                    list(movement_ids)
                    +
                    list(spacing_ids)
                    +
                    list(condition_c_ids)
                )
                if track_id is not None
            }
        )

        if jam_detected:

            status = "jam"

        elif movement_warning:

            status = "warning"

        elif (
            self.jam_detection_enabled
            or
            self.bag_spacing_enabled
            or
            self.condition_c_enabled
        ):

            status = "normal"

        else:

            status = "disabled"

        return {

            "status":
                status,

            "jam_detected":
                jam_detected,

            "warning":
                (
                    movement_warning
                    and
                    not jam_detected
                ),

            "jam_types":
                jam_types,

            "movement_jam_detected":
                movement_detected,

            "spacing_jam_detected":
                spacing_detected,

            "active_jam_count":
                len(active_ids),

            "active_jam_track_ids":
                active_ids,

            "minimum_gap_mm":
                spacing.get(
                    "minimum_gap_mm"
                ),

            "spacing_threshold_mm":
                spacing.get(
                    "threshold_mm",
                    self.bag_spacing_detector
                    .jam_threshold_mm,
                ),

            "spacing_jam_pairs":
                spacing.get(
                    "jam_pairs",
                    [],
                )
                or [],

            "condition_c_bag_count":
                condition_c.get(
                    "bag_count",
                    0,
                ),

            "condition_c_track_ids":
                condition_c.get(
                    "track_ids",
                    [],
                )
                or [],

            "condition_c_minimum_gap_mm":
                condition_c.get(
                    "minimum_gap_mm"
                ),

            "condition_c_distances":
                condition_c.get(
                    "distances",
                    [],
                )
                or [],

            "condition_c_image_path":
                condition_c.get(
                    "image_path"
                ),
        }

    # ======================================================
    # JAM EVENT LOGGER
    # ======================================================

    def _log_jam_events(self):

        if self.count_logger is None:
            return

        try:

            # ==================================================
            # CONDITION A - MOVEMENT JAM
            # ==================================================

            condition_a_jam = bool(
                self.jam_result.get(
                    "jam",
                    False,
                )
            )

            if condition_a_jam != self.previous_condition_a_jam:

                # --------------------------------------------------
                # JAM START
                # --------------------------------------------------

                if condition_a_jam:

                    try:

                        self.condition_a_sql_jam_start = (
                            datetime.now(timezone.utc)
                        )

                        self.condition_a_sql_jam_id = (
                            start_jam_event(
                                camera_id=self.name,
                                condition_code="A",
                                jam_type="movement",
                                track_ids=(
                                    self.jam_result.get(
                                        "active_jam_track_ids",
                                        [],
                                    )
                                ),
                                reason=(
                                    self.jam_result.get(
                                        "reason"
                                    )
                                ),
                                metadata={
                                    "condition_code": "A",
                                    "condition_name": "MOVEMENT_JAM",
                                    "jam_type": "movement",
                                    "jam_result": self.jam_result,
                                    "roi": self.jam_roi,
                                    "track_ids": (
                                        self.jam_result.get(
                                            "active_jam_track_ids",
                                            [],
                                        )
                                        or []
                                    ),
                                },
                            )
                        )

                    except Exception as error:

                        self.condition_a_sql_jam_id = None
                        self.condition_a_sql_jam_start = None

                        self.logger.warning(
                            f"{self.name}: failed to start "
                            f"SQL Condition A jam event: {error}"
                        )

                # --------------------------------------------------
                # JAM RECOVERY
                # --------------------------------------------------

                else:

                    if self.condition_a_sql_jam_id is not None:

                        start_time = (
                            self.condition_a_sql_jam_start
                        )

                        if start_time is not None:

                            duration_seconds = (
                                datetime.now(timezone.utc)
                                - start_time
                            ).total_seconds()

                        else:

                            duration_seconds = 0.0

                        try:

                            end_jam_event(
                                jam_event_id=(
                                    self.condition_a_sql_jam_id
                                ),
                                duration_seconds=(
                                    duration_seconds
                                ),
                                status="RECOVERED",
                            )

                        except Exception as error:

                            self.logger.warning(
                                f"{self.name}: failed to end "
                                f"SQL Condition A jam event: {error}"
                            )

                    self.condition_a_sql_jam_id = None
                    self.condition_a_sql_jam_start = None

                # --------------------------------------------------
                # EXISTING COUNT LOGGER
                # --------------------------------------------------

                try:

                    self.count_logger.log_event(
                        event_type=(
                            "jam_condition_a"
                            if condition_a_jam
                            else "jam_condition_a_recovered"
                        ),
                        camera_name=self.name,
                        status=(
                            "jam"
                            if condition_a_jam
                            else "normal"
                        ),
                        jam_result=self.jam_result,
                        roi=self.jam_roi,
                    )

                except Exception as error:

                    self.logger.warning(
                        f"{self.name}: failed CountLogger "
                        f"Condition A event: {error}"
                    )

                self.previous_condition_a_jam = (
                    condition_a_jam
                )

            # ==================================================
            # CONDITION B - BAG SPACING JAM
            # ==================================================

            condition_b_jam = bool(
                self.spacing_result.get(
                    "jam",
                    False,
                )
            )

            if condition_b_jam != self.previous_condition_b_jam:

                # --------------------------------------------------
                # JAM START
                # --------------------------------------------------

                if condition_b_jam:

                    try:

                        self.condition_b_sql_jam_start = (
                            datetime.now(timezone.utc)
                        )

                        self.condition_b_sql_jam_id = (
                            start_jam_event(
                                camera_id=self.name,
                                condition_code="B",
                                jam_type="spacing",
                                track_ids=(
                                    self.spacing_result.get(
                                        "active_jam_track_ids",
                                        [],
                                    )
                                ),
                                reason=(
                                    self.spacing_result.get(
                                        "reason"
                                    )
                                ),
                                roi_snapshot_id=None,
                                metadata={
                                    "condition_code": "B",
                                    "condition_name": "BAG_SPACING_JAM",
                                    "jam_type": "spacing",
                                    "spacing_result": (
                                        self.spacing_result
                                    ),
                                    "roi": self.spacing_roi,
                                    "track_ids": (
                                        self.spacing_result.get(
                                            "active_jam_track_ids",
                                            [],
                                        )
                                        or []
                                    ),
                                },
                            )
                        )

                    except Exception as error:

                        self.condition_b_sql_jam_id = None
                        self.condition_b_sql_jam_start = None

                        self.logger.warning(
                            f"{self.name}: failed to start "
                            f"SQL Condition B jam event: {error}"
                        )

                # --------------------------------------------------
                # JAM RECOVERY
                # --------------------------------------------------

                else:

                    if self.condition_b_sql_jam_id is not None:

                        start_time = (
                            self.condition_b_sql_jam_start
                        )

                        if start_time is not None:

                            duration_seconds = (
                                datetime.now(timezone.utc)
                                - start_time
                            ).total_seconds()

                        else:

                            duration_seconds = 0.0

                        try:

                            end_jam_event(
                                jam_event_id=(
                                    self.condition_b_sql_jam_id
                                ),
                                duration_seconds=(
                                    duration_seconds
                                ),
                                status="RECOVERED",
                            )

                        except Exception as error:

                            self.logger.warning(
                                f"{self.name}: failed to end "
                                f"SQL Condition B jam event: {error}"
                            )

                    self.condition_b_sql_jam_id = None
                    self.condition_b_sql_jam_start = None

                # --------------------------------------------------
                # EXISTING COUNT LOGGER
                # --------------------------------------------------

                try:

                    self.count_logger.log_event(
                        event_type=(
                            "jam_condition_b"
                            if condition_b_jam
                            else "jam_condition_b_recovered"
                        ),
                        camera_name=self.name,
                        status=(
                            "jam"
                            if condition_b_jam
                            else "normal"
                        ),
                        spacing_result=self.spacing_result,
                        roi=self.spacing_roi,
                    )

                except Exception as error:

                    self.logger.warning(
                        f"{self.name}: failed CountLogger "
                        f"Condition B event: {error}"
                    )

                self.previous_condition_b_jam = (
                    condition_b_jam
                )

            # ==================================================
            # CONDITION C - ROI OCCUPANCY JAM
            # ==================================================

            condition_c_result = (
                self._condition_c()
            )

            condition_c_jam = bool(
                condition_c_result.get(
                    "jam",
                    False,
                )
            )

            if condition_c_jam != self.previous_condition_c_jam:

                # --------------------------------------------------
                # JAM START
                # --------------------------------------------------

                if condition_c_jam:

                    try:

                        self.condition_c_sql_jam_start = (
                            datetime.now(timezone.utc)
                        )

                        self.condition_c_sql_jam_id = (
                            start_jam_event(
                                camera_id=self.name,
                                condition_code="C",
                                jam_type="roi_occupancy",
                                track_ids=(
                                    condition_c_result.get(
                                        "track_ids",
                                        [],
                                    )
                                ),
                                reason=(
                                    condition_c_result.get(
                                        "reason",
                                        "ROI occupancy exceeded limit",
                                    )
                                ),
                                metadata={
                                    "condition_code": "C",
                                    "condition_name": "ROI_OCCUPANCY_JAM",
                                    "jam_type": "roi_occupancy",
                                    "condition_c_result": (
                                        condition_c_result
                                    ),
                                    "roi": (
                                        self.condition_c_roi
                                    ),
                                    "track_ids": (
                                        condition_c_result.get(
                                            "track_ids",
                                            [],
                                        )
                                        or []
                                    ),
                                },
                            )
                        )

                    except Exception as error:

                        self.condition_c_sql_jam_id = None
                        self.condition_c_sql_jam_start = None

                        self.logger.warning(
                            f"{self.name}: failed to start "
                            f"SQL Condition C jam event: {error}"
                        )

                # --------------------------------------------------
                # JAM RECOVERY
                # --------------------------------------------------

                else:

                    if self.condition_c_sql_jam_id is not None:

                        start_time = (
                            self.condition_c_sql_jam_start
                        )

                        if start_time is not None:

                            duration_seconds = (
                                datetime.now(timezone.utc)
                                - start_time
                            ).total_seconds()

                        else:

                            duration_seconds = 0.0

                        try:

                            end_jam_event(
                                jam_event_id=(
                                    self.condition_c_sql_jam_id
                                ),
                                duration_seconds=(
                                    duration_seconds
                                ),
                                status="RECOVERED",
                            )

                        except Exception as error:

                            self.logger.warning(
                                f"{self.name}: failed to end "
                                f"SQL Condition C jam event: {error}"
                            )

                    self.condition_c_sql_jam_id = None
                    self.condition_c_sql_jam_start = None

                # --------------------------------------------------
                # EXISTING COUNT LOGGER
                # --------------------------------------------------

                try:

                    self.count_logger.log_event(
                        event_type=(
                            "jam_condition_c"
                            if condition_c_jam
                            else "jam_condition_c_recovered"
                        ),
                        camera_name=self.name,
                        status=(
                            "jam"
                            if condition_c_jam
                            else "normal"
                        ),
                        condition_c_result=(
                            condition_c_result
                        ),
                        roi=self.condition_c_roi,
                    )

                except Exception as error:

                    self.logger.warning(
                        f"{self.name}: failed CountLogger "
                        f"Condition C event: {error}"
                    )

                self.previous_condition_c_jam = (
                    condition_c_jam
                )

        except Exception as error:

            self.logger.warning(
                f"{self.name}: failed to log jam events: "
                f"{error}"
            )

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
    # TRACK
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

        min_print_votes = getattr(
            self,
            "min_print_votes",
            getattr(
                self,
                "min_print_observations",
                1,
            ),
        )

        if observation_count < int(min_print_votes):

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
    # FINALIZE PRINT STATUS
    # ======================================================

    def _finalize_print_status(
        self,
        track_id,
    ):
        """
        Finalize print classification for one track.

        Unlike _classify_print_history(), this does not wait
        for a minimum observation count: it is called once a
        track's physical bag crossing has already been
        confirmed, so no further observations will arrive.
        Whatever votes have been accumulated are classified
        immediately using the configured vote threshold, and
        the track's temporary print history is then removed.

        Returns
        -------
        bool | None
            True  -> printed
            False -> missing / not printed
            None  -> no observations recorded, or disabled
        """

        if not self.print_detection_enabled:
            return None

        votes = self.track_print_votes.get(
            track_id,
            [],
        )

        if not votes:
            self.track_print_last_seen.pop(
                track_id,
                None,
            )
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
                len(votes),
                1,
            )
        )

        result = (
            ratio
            >=
            self.print_vote_threshold
        )

        self.track_print_votes.pop(
            track_id,
            None,
        )

        self.track_print_last_seen.pop(
            track_id,
            None,
        )

        return result

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
        entry_roi_count=0,
    ):

        self.visualizer.visualize(

            frame=frame,

            camera_name=self.name,

            count=count,

            entry_roi_count=entry_roi_count,

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

            # Condition A
            jam_result=self.jam_result,

            jam_roi=self.jam_roi,

            # Condition B
            spacing_result=self.spacing_result,

            spacing_roi=self.spacing_roi,

            # Final A OR B
            final_jam_result=(
                self.final_jam_result
            ),

            condition_c_result=(
                self.condition_c_result
            ),

            condition_c_roi=(
                self.condition_c_roi
            ),
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

    def get_latest_frame(
        self,
    ):

        with self._frame_lock:

            return (

                self._latest_frame.copy()

                if self._latest_frame is not None

                else None
            )

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
        # Reset Condition A
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

        # ----------------------------------------------
        # Reset Condition B result
        #
        # BagSpacingDetector has no temporal jam state.
        # ----------------------------------------------

        try:

            self.spacing_result = (
                self.bag_spacing_detector
                ._empty_result()
            )

        except Exception:

            self.logger.warning(
                f"{self.name}: BagSpacingDetector "
                "reset failed."
            )

        # ----------------------------------------------
        # Reset Condition C result
        #
        # ROIOccupancyDetector has no temporal jam state.
        # ----------------------------------------------

        try:

            self.condition_c_result = {

                "jam": False,

                "status": "normal",

                "bag_count": 0,

                "track_ids": [],

                "minimum_gap_mm": None,

                "distances": [],

                "image_path": None,
            }

            self.condition_c_start_time = None

        except Exception:

            self.logger.warning(
                f"{self.name}: ROIOccupancyDetector "
                "reset failed."
            )

        try:

            self.final_jam_result = (
                self._build_final_jam_result()
            )

        except Exception:

            self.final_jam_result = {
                "status": "disabled",
                "jam_detected": False,
                "warning": False,
                "jam_types": [],
                "active_jam_count": 0,
                "active_jam_track_ids": [],
            }

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

        counted_results = (
            self._update_print_totals()
        )

        live_print_status = (
            self._summarize_print_status(
                print_results
            )
        )

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

            entry_roi_count=(
                self.entry_roi_counter.total_count
                if self.entry_roi_counter is not None
                else 0
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
            # SQL SERVER PRINT EVENT
            # ==================================================

            try:

                save_print_event(
                    camera_id=self.name,
                    result=counted_print_status,
                    timestamp=None,
                    metadata={
                        "print_present": (
                            counted_print_status == "printed"
                        ),
                    },
                )

            except Exception as e:

                self.logger.error(
                    f"{self.name}: failed saving "
                    f"print event to SQL Server: {e}"
                )

        # ==================================================
        # COUNT EVENTS
        # ==================================================

        for counted_bag in counted_results:

            if self.elasticsearch is not None:

                try:

                    self.elasticsearch.create_count_event(

                        self.name,

                        counted_bag.get(
                            "total_count",
                            self.counter.total_count,
                        ),

                        counted_bag.get(
                            "center"
                        ),
                    )

                except Exception:

                    self.logger.warning(
                        f"{self.name}: failed publishing "
                        "count event to Elasticsearch."
                    )

            # ==================================================
            # SQL SERVER PRODUCTION EVENT
            # ==================================================

            try:

                save_production_event(
                    camera_id=self.name,

                    bag_count=self.counter.total_count,

                    printed_count=self.printed_count,

                    unprinted_count=self.missing_count,

                    line_count=self.counter.total_count,

                    frame_roi_count=(
                        self.entry_roi_count
                        if self.entry_roi_counter is not None
                        else 0
                    ),

                    bags_inside_roi=(
                        len(
                            getattr(
                                self.entry_roi_counter,
                                "active_track_ids",
                                []
                            )
                        )
                        if self.entry_roi_counter is not None
                        else 0
                    ),

                    metadata={
                        "track_id": counted_bag.get("track_id"),
                        "center": counted_bag.get("center"),
                        "print_present": counted_bag.get("print_present"),
                        "printed_count_event": counted_bag.get("printed_count"),
                        "missing_count_event": counted_bag.get("missing_count"),
                    },
                )

            except Exception as e:

                self.logger.error(
                    f"{self.name}: failed saving "
                    f"production event to SQL Server: {e}"
                )

            if self.count_logger is not None:

                import traceback

                print("=" * 80)
                print(counted_bag)
                print("=" * 80)

                try:

                    self.count_logger.log_count(

                        camera_name=self.name,

                        total_count=count,

                        track_id=counted_bag.get(
                            "track_id"
                        ),

                        center=counted_bag.get(
                            "center"
                        ),

                        print_present=counted_bag.get(
                            "print_present"
                        ),

                        printed_count=counted_bag.get(
                            "printed_count"
                        ),

                        missing_count=counted_bag.get(
                            "missing_count"
                        ),

                        print_detection_enabled=(
                            self.print_detection_enabled
                        ),
                    )

                except Exception as e:

                    self.logger.error(
                        f"{self.name}: failed writing count event: {e}"
                    )

                    traceback.print_exc()

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
        entry_roi_count=None,
    ):

        if self.dashboard_state is None:
            return

        current_time = (
            time.monotonic()
        )

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

        # ==================================================
        # CONDITION A
        # ==================================================

        movement = (
            self.jam_result
            if isinstance(
                self.jam_result,
                dict,
            )
            else {}
        )

        movement_status = (
            movement.get(
                "status",
                "normal",
            )
            if self.jam_detection_enabled
            else "disabled"
        )

        movement_detected = bool(
            movement.get(
                "jam_detected",
                False,
            )
        )

        movement_warning = bool(
            movement.get(
                "warning",
                False,
            )
        )

        movement_ids = (
            movement.get(
                "active_jam_track_ids",
                [],
            )
            or []
        )

        movement_tracks = (
            movement.get(
                "tracks",
                [],
            )
            or []
        )

        # ==================================================
        # CONDITION B
        # ==================================================

        spacing = (
            self.spacing_result
            if isinstance(
                self.spacing_result,
                dict,
            )
            else {}
        )

        spacing_status = (
            spacing.get(
                "status",
                "normal",
            )
            if self.bag_spacing_enabled
            else "disabled"
        )

        spacing_detected = bool(
            spacing.get(
                "jam_detected",
                False,
            )
        )

        spacing_pairs = (
            spacing.get(
                "pairs",
                [],
            )
            or []
        )

        spacing_jam_pairs = (
            spacing.get(
                "jam_pairs",
                [],
            )
            or []
        )

        spacing_ids = (
            spacing.get(
                "active_jam_track_ids",
                [],
            )
            or []
        )

        minimum_gap_mm = (
            spacing.get(
                "minimum_gap_mm"
            )
        )

        spacing_threshold_mm = (
            spacing.get(
                "threshold_mm",
                self.bag_spacing_detector
                .jam_threshold_mm,
            )
        )

        # ==================================================
        # CONDITION C
        #
        # ROI Occupancy Detector
        #
        # Publishes:
        # - ROI Bag Count
        # - Track IDs
        # - Minimum Gap
        # - Distances
        # - ROI Image
        # - ROI Coordinates
        # - Max Allowed Bags / Occupancy %
        # - Jam Timestamp / Duration
        # ==================================================

        condition_c = self._condition_c()

        condition_c_status = (
            condition_c.get(
                "status",
                "normal",
            )
            if self.condition_c_enabled
            else "disabled"
        )

        condition_c_max_allowed_bags = (
            self.condition_c_detector.max_allowed_bags
        )

        condition_c_roi_occupancy = (
            condition_c.get(
                "bag_count",
                0,
            )
            /
            condition_c_max_allowed_bags
            if condition_c_max_allowed_bags
            else 0
        )

        condition_c_timestamp = (
            datetime.now(
                timezone.utc
            ).isoformat()
            if condition_c.get(
                "jam",
                False,
            )
            else None
        )

        condition_c_duration = (
            round(
                time.perf_counter()
                -
                self.condition_c_start_time,
                1,
            )
            if self.condition_c_start_time is not None
            else 0
        )

        # ==================================================
        # FINAL A OR B
        # ==================================================

        final_jam = (
            self.final_jam_result
            if isinstance(
                self.final_jam_result,
                dict,
            )
            else {}
        )

        final_status = (
            final_jam.get(
                "status",
                "normal",
            )
        )

        final_detected = bool(
            final_jam.get(
                "jam_detected",
                False,
            )
        )

        final_warning = bool(
            final_jam.get(
                "warning",
                False,
            )
        )

        final_ids = (
            final_jam.get(
                "active_jam_track_ids",
                [],
            )
            or []
        )

        final_types = (
            final_jam.get(
                "jam_types",
                [],
            )
            or []
        )

        # ==================================================
        # ENTRY ROI STATE
        # ==================================================

        entry_roi_state = (
            self._get_entry_roi_state()
        )

        try:

            self.dashboard_state.update_camera(

                camera_name=self.name,

                count=self.counter.total_count,

                total_count=(
                    self.counter.total_count
                ),

                # ==========================================
                # ENTRY ROI COUNT
                # ==========================================

                entry_roi_count=(
                    entry_roi_count
                    if entry_roi_count is not None
                    else (
                        self.entry_roi_counter.total_count
                        if self.entry_roi_counter is not None
                        else 0
                    )
                ),

                entry_roi_active_count=(
                    entry_roi_state["count"]
                ),

                entry_roi_active_track_ids=(
                    entry_roi_state["track_ids"]
                ),

                entry_roi_active_bags=(
                    entry_roi_state["bags"]
                ),

                entry_roi=(
                    self.entry_roi_counter.roi
                    if self.entry_roi_counter is not None
                    else None
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
                # CONDITION A
                # ==========================================

                movement_jam_enabled=(
                    self.jam_detection_enabled
                ),

                movement_jam_status=(
                    movement_status
                ),

                movement_jam_detected=(
                    movement_detected
                ),

                movement_jam_warning=(
                    movement_warning
                ),

                movement_jam_track_ids=(
                    movement_ids
                ),

                movement_jam_tracks=(
                    movement_tracks
                ),

                # ==========================================
                # CONDITION B
                # ==========================================

                spacing_detection_enabled=(
                    self.bag_spacing_enabled
                ),

                spacing_status=(
                    spacing_status
                ),

                spacing_jam_detected=(
                    spacing_detected
                ),

                spacing_threshold_mm=(
                    spacing_threshold_mm
                ),

                minimum_gap_mm=(
                    minimum_gap_mm
                ),

                spacing_pairs=(
                    spacing_pairs
                ),

                spacing_jam_pairs=(
                    spacing_jam_pairs
                ),

                spacing_jam_track_ids=(
                    spacing_ids
                ),

                # ==========================================
                # CONDITION C
                #
                # ROI Occupancy Detector
                #
                # Publishes:
                # - ROI Bag Count
                # - Track IDs
                # - Minimum Gap
                # - Distances
                # - ROI Image
                # - ROI Coordinates
                # - Max Allowed Bags / Occupancy %
                # - Jam Timestamp / Duration
                # ==========================================

                condition_c_enabled=(
                    self.condition_c_enabled
                ),

                condition_c_status=(
                    condition_c_status
                ),

                condition_c_detected=(
                    condition_c.get(
                        "jam",
                        False,
                    )
                ),

                condition_c_bag_count=(
                    condition_c.get(
                        "bag_count",
                        0,
                    )
                ),

                condition_c_track_ids=(
                    condition_c.get(
                        "track_ids",
                        [],
                    )
                ),

                condition_c_minimum_gap_mm=(
                    condition_c.get(
                        "minimum_gap_mm"
                    )
                ),

                condition_c_distances=(
                    condition_c.get(
                        "distances",
                        [],
                    )
                ),

                condition_c_image_path=(
                    condition_c.get(
                        "image_path"
                    )
                ),

                condition_c_roi=(
                    self.condition_c_roi
                ),

                condition_c_max_allowed_bags=(
                    condition_c_max_allowed_bags
                ),

                condition_c_roi_occupancy=(
                    condition_c_roi_occupancy
                ),

                condition_c_timestamp=(
                    condition_c_timestamp
                ),

                condition_c_duration=(
                    condition_c_duration
                ),

                # ==========================================
                # FINAL JAM
                #
                # Keep existing field names so dashboard
                # code remains backward-compatible.
                # ==========================================

                jam_detection_enabled=bool(
                    self.jam_detection_enabled
                    or
                    self.bag_spacing_enabled
                    or
                    self.condition_c_enabled
                ),

                jam_status=(
                    final_status
                ),

                jam_detected=(
                    final_detected
                ),

                jam_warning=(
                    final_warning
                ),

                jam_types=(
                    final_types
                ),

                active_jam_count=len(
                    final_ids
                ),

                active_jam_track_ids=(
                    final_ids
                ),

                # Preserve old V1 field for compatibility.
                jam_tracks=(
                    movement_tracks
                ),
            )

        except Exception as error:

            self.logger.warning(
                f"{self.name}: dashboard runtime "
                f"update failed: {error}"
            )