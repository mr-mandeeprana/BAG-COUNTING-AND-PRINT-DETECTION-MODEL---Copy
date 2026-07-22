"""
==========================================================
FillPac AI
Pipeline
==========================================================

Each camera owns:
- Camera
- Tracker
- Counter
- PrintDetector
- Print history

YOLO model is NOT loaded here.

All camera pipelines use ONE shared InferenceManager.
==========================================================
"""

import threading
import time

import cv2

from src.camera import Camera
from src.counter import Counter
from src.print_detector import PrintDetector
from src.tracker import Tracker
from src.visualizer import Visualizer


class Pipeline:
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
        self.roi = camera_config["roi"]
        self.window_name = self.name

        if self.inference_manager is None:
            raise ValueError(
                f"{self.name}: Pipeline requires a valid InferenceManager."
            )

        # ==================================================
        # RUNTIME STATE
        # ==================================================

        self.connected = False
        self.previous_time = time.time()

        self.last_count = 0
        self.last_print_status = None

        self.printed_count = 0
        self.missing_count = 0

        self.frame_index = 0

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

        counting_config = camera_config.get(
            "counting",
            {},
        )

        print_config = camera_config.get(
            "print_detection",
            {},
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
        )

        # ==================================================
        # CAMERA
        # ==================================================

        self.camera = Camera(
            name=self.name,
            source=camera_config["source"],
            mode=camera_config.get(
                "mode",
                "video",
            ),
            buffer_size=camera_config.get(
                "buffer_size",
                1,
            ),
            logger=logger,
        )

        # ==================================================
        # TRACKER
        #
        # Each camera owns an independent ByteTrack instance.
        # ==================================================

        self.tracker = Tracker(
            tracker_config=tracker_config
        )

        # ==================================================
        # COUNTER
        #
        # Each camera owns an independent physical bag
        # center counter.
        # ==================================================

        self.counter = Counter(
            roi_y=self.roi["y1"],
            direction=counting_config.get(
                "direction",
                "down",
            ),
            duplicate_distance=counting_config.get(
                "duplicate_distance",
                30,
            ),
            duplicate_time=counting_config.get(
                "duplicate_time",
                0.8,
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
                0,
            ),
        )

        # ==================================================
        # PRINT DETECTOR
        # ==================================================

        self.print_detector = PrintDetector(
            confidence_threshold=print_config.get(
                "confidence",
                0.4,
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
        # VISUALIZER
        # ==================================================

        self.visualizer = Visualizer()

        # ==================================================
        # PRINT DETECTION CONFIGURATION
        # ==================================================

        self.print_detection_enabled = bool(
            print_config.get(
                "enabled",
                True,
            )
        )

        self.print_vote_threshold = min(
            max(
                float(
                    print_config.get(
                        "vote_threshold",
                        0.5,
                    )
                ),
                0.0,
            ),
            1.0,
        )

        self.min_print_votes = max(
            int(
                print_config.get(
                    "min_votes",
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

    # ======================================================
    # PROCESS FRAME
    # ======================================================

    def process(self):
        try:
            # ----------------------------------------------
            # CONNECT CAMERA
            # ----------------------------------------------

            if not self.connected:
                self.connected = self.camera.connect()

                if not self.connected:
                    self._publish_runtime_status(
                        fps=0.0,
                        print_status="offline",
                        force=True,
                    )
                    return False

            # ----------------------------------------------
            # READ FRAME
            # ----------------------------------------------

            frame = self.read_frame()

            if frame is None:
                self.release()

                self._publish_runtime_status(
                    fps=0.0,
                    print_status="offline",
                    force=True,
                )

                return False

            self.frame_index += 1

            # ----------------------------------------------
            # SHARED YOLO INFERENCE
            # ----------------------------------------------

            detections = self.detect(
                frame
            )

            # ----------------------------------------------
            # UPDATE TRACKER FRAME SIZE
            #
            # Required for min_bbox_area_ratio.
            # ----------------------------------------------

            height, width = frame.shape[:2]

            self.tracker.set_frame_size(
                width=width,
                height=height,
            )

            # ----------------------------------------------
            # CAMERA-SPECIFIC TRACKING
            # ----------------------------------------------

            tracks = self.track(
                detections
            )

            # ----------------------------------------------
            # PRINT DETECTION
            # ----------------------------------------------

            print_results = self.print_detection(
                tracks,
                detections,
            )

            # ----------------------------------------------
            # STORE PRINT OBSERVATIONS
            # ----------------------------------------------

            self.record_print_observations(
                print_results,
                tracks,
            )

            # ----------------------------------------------
            # FILTER UNSTABLE TRACKS
            # ----------------------------------------------

            countable_tracks = self.countable_tracks(
                tracks
            )

            # ----------------------------------------------
            # COUNT PHYSICAL BAG CENTER CROSSING
            # ----------------------------------------------

            count = self.count(
                countable_tracks
            )

            # ----------------------------------------------
            # FPS
            # ----------------------------------------------

            fps = self.calculate_fps()

            # ----------------------------------------------
            # VISUALIZATION
            # ----------------------------------------------

            self.draw(
                frame,
                tracks,
                detections,
                print_results,
                count,
                fps,
            )

            # ----------------------------------------------
            # STORE LATEST ANNOTATED FRAME
            # ----------------------------------------------

            self._set_latest_frame(
                frame
            )

            # ----------------------------------------------
            # DASHBOARD / ELASTICSEARCH EVENTS
            # ----------------------------------------------

            self._publish_events(
                count,
                fps,
                print_results,
            )

            return True

        except TimeoutError as error:
            self.logger.warning(
                f"{self.name} inference timeout: {error}"
            )

            self._publish_runtime_status(
                fps=0.0,
                print_status="inference_timeout",
                force=True,
            )

            return False

        except Exception:
            self.logger.error(
                f"Unhandled exception in pipeline {self.name}.",
                exc_info=True,
            )

            self.release()

            self._publish_runtime_status(
                fps=0.0,
                print_status="error",
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

    # ======================================================
    # READ FRAME
    # ======================================================

    def read_frame(self):
        success, frame = self.camera.read()

        if not success:
            self.logger.warning(
                f"{self.name} frame read failed or stream ended."
            )
            return None

        return frame

    # ======================================================
    # SHARED DETECTION
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
            )
            == 0
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
            ): track
            for track in tracks
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

            votes = self.track_print_votes.setdefault(
                track_id,
                [],
            )

            votes.append(
                bool(
                    result.get(
                        "print_present",
                        False,
                    )
                )
            )

            if len(
                votes
            ) > self.print_history_size:
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
            and track.get(
                "motion_jump",
                False,
            )
        ):
            return False

        if (
            track.get(
                "speed",
                0.0,
            )
            < self.min_print_observation_speed
        ):
            return False

        return True

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
            counted_bags=self.counter.last_counted_bags,
        )

    # ======================================================
    # DISPLAY FRAME
    # ======================================================

    def publish(self):
        frame = self._get_latest_frame()

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

    def _get_latest_frame(
        self,
    ):
        with self._frame_lock:
            return (
                self._latest_frame.copy()
                if self._latest_frame is not None
                else None
            )

    # ======================================================
    # FPS
    # ======================================================

    def calculate_fps(
        self,
    ):
        current_time = time.time()

        fps = (
            1.0
            / max(
                current_time
                - self.previous_time,
                1e-6,
            )
        )

        self.previous_time = current_time

        return fps

    # ======================================================
    # RELEASE CAMERA
    # ======================================================

    def release(
        self,
    ):
        self.camera.release()

        self.connected = False

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
            self._summarize_print_status(
                counted_results
            )
            if counted_results
            else None
        )

        # ----------------------------------------------
        # DASHBOARD
        # ----------------------------------------------

        self._publish_runtime_status(
            fps=fps,
            print_status=live_print_status,
        )

        # ----------------------------------------------
        # ELASTICSEARCH
        # ----------------------------------------------

        if self.elasticsearch is not None:
            self.elasticsearch.create_camera_event(
                self.name,
                fps,
                "online",
            )

            if (
                counted_print_status is not None
                and counted_print_status
                != self.last_print_status
            ):
                self.elasticsearch.create_print_event(
                    self.name,
                    counted_print_status == "ok",
                )

        # ----------------------------------------------
        # COUNT EVENTS
        # ----------------------------------------------

        for counted_bag in counted_results:
            if self.elasticsearch is not None:
                self.elasticsearch.create_count_event(
                    self.name,
                    counted_bag[
                        "total_count"
                    ],
                    counted_bag[
                        "center"
                    ],
                )

            if self.count_logger is not None:
                self.count_logger.log_count_event(
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
                    printed_count=self.printed_count,
                    missing_count=self.missing_count,
                )

        self.last_count = count

        if counted_print_status is not None:
            self.last_print_status = (
                counted_print_status
            )

    # ======================================================
    # DASHBOARD RUNTIME STATUS
    # ======================================================

    def _publish_runtime_status(
        self,
        fps,
        print_status,
        force=False,
    ):
        if self.dashboard_state is None:
            return

        current_time = time.monotonic()

        if (
            not force
            and (
                current_time
                - self.last_dashboard_publish_time
            )
            < self.dashboard_publish_interval
        ):
            return

        status = (
            "online"
            if self.connected
            else "offline"
        )

        self.dashboard_state.update_camera(
            camera_name=self.name,
            count=self.counter.total_count,
            fps=fps,
            status=status,
            print_status=print_status,
            printed_count=self.printed_count,
            missing_count=self.missing_count,
            printed_bags_count=self.printed_count,
            not_printed_bags_count=self.missing_count,
        )

        self.last_dashboard_publish_time = (
            current_time
        )

    # ======================================================
    # SUMMARIZE PRINT STATUS
    # ======================================================

    def _summarize_print_status(
        self,
        print_results,
    ):
        if not self.print_detection_enabled:
            return "disabled"

        if not print_results:
            return "no_bag"

        print_values = [
            result.get(
                "print_present"
            )
            for result in print_results
            if result.get(
                "print_present"
            )
            is not None
        ]

        if not print_values:
            return "unknown"

        if all(
            print_values
        ):
            return "ok"

        return "missing"

    # ======================================================
    # UPDATE PRINT TOTALS
    # ======================================================

    def _update_print_totals(
        self,
    ):
        if not self.counter.last_counted_bags:
            return []

        # ----------------------------------------------
        # PRINT DETECTION DISABLED
        # ----------------------------------------------

        if not self.print_detection_enabled:
            return [
                {
                    "track_id":
                        counted_bag[
                            "track_id"
                        ],
                    "center":
                        counted_bag[
                            "center"
                        ],
                    "print_present":
                        None,
                    "total_count":
                        self.last_count
                        + index
                        + 1,
                }
                for index, counted_bag
                in enumerate(
                    self.counter.last_counted_bags
                )
            ]

        counted_results = []

        # ----------------------------------------------
        # PRINT DETECTION ENABLED
        # ----------------------------------------------

        for index, counted_bag in enumerate(
            self.counter.last_counted_bags
        ):
            print_present = (
                self._finalize_print_status(
                    counted_bag[
                        "track_id"
                    ]
                )
            )

            if print_present is True:
                self.printed_count += 1

            elif print_present is False:
                self.missing_count += 1

            counted_results.append(
                {
                    "track_id":
                        counted_bag[
                            "track_id"
                        ],
                    "center":
                        counted_bag[
                            "center"
                        ],
                    "print_present":
                        print_present,
                    "total_count":
                        self.last_count
                        + index
                        + 1,
                }
            )

        return counted_results

    # ======================================================
    # FINALIZE PRINT STATUS
    # ======================================================

    def _finalize_print_status(
        self,
        track_id,
    ):
        votes = self.track_print_votes.get(
            track_id,
            [],
        )

        self.track_print_votes.pop(
            track_id,
            None,
        )

        self.track_print_last_seen.pop(
            track_id,
            None,
        )

        # Insufficient observations = unknown.
        if len(
            votes
        ) < self.min_print_votes:
            return None

        positive_votes = sum(
            1
            for vote in votes
            if vote
        )

        positive_ratio = (
            positive_votes
            / len(
                votes
            )
        )

        return (
            positive_ratio
            >= self.print_vote_threshold
        )

    # ======================================================
    # TRIM PRINT HISTORY
    # ======================================================

    def _trim_print_history(
        self,
        active_track_ids,
    ):
        fresh_ids = {
            track_id
            for (
                track_id,
                last_seen,
            )
            in self.track_print_last_seen.items()
            if (
                self.frame_index
                - last_seen
                <= self.print_history_ttl_frames
            )
        }

        retained_ids = (
            set(
                active_track_ids
            )
            | fresh_ids
        )

        self.track_print_votes = {
            track_id: votes
            for (
                track_id,
                votes,
            )
            in self.track_print_votes.items()
            if track_id in retained_ids
        }

        self.track_print_last_seen = {
            track_id: last_seen
            for (
                track_id,
                last_seen,
            )
            in self.track_print_last_seen.items()
            if track_id in retained_ids
        }

    # ======================================================
    # RESTORE PERSISTED COUNTS
    # ======================================================

    def _restore_persisted_counts(
        self,
    ):
        if self.dashboard_state is None:
            return

        snapshot = (
            self.dashboard_state.snapshot()
        )

        camera_state = (
            snapshot
            .get(
                "cameras",
                {},
            )
            .get(
                self.name,
                {},
            )
        )

        self.counter.total_count = int(
            camera_state.get(
                "count",
                0,
            )
            or 0
        )

        # Print totals are restored only for
        # print-enabled cameras.
        if self.print_detection_enabled:
            self.printed_count = int(
                camera_state.get(
                    "printed_count",
                    0,
                )
                or 0
            )

            self.missing_count = int(
                camera_state.get(
                    "missing_count",
                    0,
                )
                or 0
            )

        else:
            self.printed_count = 0
            self.missing_count = 0