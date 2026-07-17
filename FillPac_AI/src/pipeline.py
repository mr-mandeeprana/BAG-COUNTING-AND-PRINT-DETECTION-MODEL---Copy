"""
==========================================================
FillPac AI
Pipeline
==========================================================
"""

import time

import cv2

from src.camera import Camera
from src.counter import Counter
from src.detector import Detector
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
        dashboard_state=None,
        elasticsearch=None,
        count_logger=None,
    ):
        self.camera_config = camera_config
        self.logger = logger
        self.dashboard_state = dashboard_state
        self.elasticsearch = elasticsearch
        self.count_logger = count_logger
        self.name = camera_config["name"]
        self.roi = camera_config["roi"]
        self.window_name = self.name
        self.connected = False
        self.previous_time = time.time()
        self.last_count = 0
        self.last_print_status = None
        self.printed_count = 0
        self.missing_count = 0
        self.frame_index = 0

        model_config = camera_config.get("model", {})
        counting_config = camera_config.get("counting", {})
        print_config = camera_config.get("print_detection", {})

        self.display_config = dict(display_config or {})
        self.display_config.update(camera_config.get("display", {}))

        self.camera = Camera(
            name=self.name,
            source=camera_config["source"],
            mode=camera_config.get("mode", "video"),
            buffer_size=camera_config.get("buffer_size", 1),
            logger=logger,
        )
        self.detector = Detector(
            model_path=model_config.get("path", "models/yolo26n.pt"),
            confidence=model_config.get("confidence", 0.5),
            iou=model_config.get("iou", 0.45),
            device=model_config.get("device", "cpu"),
            image_size=model_config.get("image_size", 640),
            half=model_config.get("half", True),
            max_detections=model_config.get("max_detections", 100),
            allowed_classes=model_config.get("allowed_classes"),
            min_bbox_area=model_config.get("min_bbox_area", 0.0),
            bag_confidence=model_config.get("bag_confidence"),
            print_confidence=model_config.get("print_confidence"),
            class_confidence_thresholds=model_config.get(
                "class_confidence_thresholds"
            ),
            detection_roi=model_config.get("detection_roi"),
            logger=logger,
        )
        self.tracker = Tracker(tracker_config=tracker_config)
        self.counter = Counter(
            roi_y=self.roi["y1"],
            direction=counting_config.get("direction", "down"),
            duplicate_distance=counting_config.get("duplicate_distance", 40),
            line_tolerance=counting_config.get("line_tolerance", 20),
            late_start_margin=counting_config.get("late_start_margin", 40),
            min_track_frames=counting_config.get("min_track_frames", 4),
            stale_track_frames=counting_config.get("stale_track_frames", 120),
            minimum_cross_distance=counting_config.get(
                "minimum_cross_distance",
                0,
            ),
        )
        self.print_detector = PrintDetector(
            confidence_threshold=print_config.get("confidence", 0.4),
            iou_threshold=print_config.get("iou_threshold", 0.0),
            min_overlap_ratio=print_config.get("min_overlap_ratio", 0.3),
            min_print_area=print_config.get("min_print_area", 0.0),
            max_print_area=print_config.get("max_print_area", 0.0),
            min_aspect_ratio=print_config.get("min_aspect_ratio", 0.0),
            max_aspect_ratio=print_config.get("max_aspect_ratio", 0.0),
            max_center_distance=print_config.get("max_center_distance", 0.0),
        )
        self.visualizer = Visualizer()
        self.print_detection_enabled = print_config.get("enabled", True)
        self.print_vote_threshold = min(
            max(float(print_config.get("vote_threshold", 0.5)), 0.0), 1.0
        )
        self.min_print_votes = max(int(print_config.get("min_votes", 1)), 1)
        self.print_history_size = max(int(print_config.get("history_size", 30)), 1)
        self.print_history_ttl_frames = max(
            int(print_config.get("history_ttl_frames", 120)), 1
        )
        self.min_print_observation_speed = max(
            float(print_config.get("min_observation_speed", 0.0)), 0.0
        )
        self.skip_motion_jump_print_observations = print_config.get(
            "skip_motion_jump_observations", True
        )
        self.track_print_votes = {}
        self.track_print_last_seen = {}
        self._restore_persisted_counts()

    def process(self):
        if not self.connected:
            self.connected = self.camera.connect()
            if not self.connected:
                self._publish_runtime_status(fps=0.0, print_status="offline")
                return False

        frame = self.read_frame()
        if frame is None:
            self.release()
            self._publish_runtime_status(fps=0.0, print_status="offline")
            return False

        self.frame_index += 1
        detections = self.detect(frame)
        tracks = self.track(detections)
        print_results = self.print_detection(tracks, detections)
        self.record_print_observations(print_results, tracks)
        countable_tracks = self.countable_tracks(tracks)
        count = self.count(countable_tracks)
        fps = self.calculate_fps()
        self.draw(frame, tracks, detections, print_results, count, fps)
        self.publish(frame)
        self._publish_events(count, fps, print_results)
        return True

    def read_frame(self):
        success, frame = self.camera.read()
        if not success:
            self.logger.warning(f"{self.name} frame read failed or stream ended.")
            return None

        return frame

    def detect(self, frame):
        return self.detector.detect(frame)

    def track(self, detections):
        bag_detections = [det for det in detections if det["class_id"] == 0]
        return self.tracker.update(bag_detections)

    @staticmethod
    def countable_tracks(tracks):
        return [track for track in tracks if not track.get("unstable", False)]

    def count(self, tracks):
        return self.counter.update(tracks)

    def print_detection(self, tracks, detections):
        if not self.print_detection_enabled:
            return []

        return self.print_detector.update(tracks, detections)

    def record_print_observations(self, print_results, tracks):
        if not self.print_detection_enabled:
            return

        track_lookup = {track.get("track_id"): track for track in tracks}

        for result in print_results:
            track_id = result.get("track_id")
            if track_id is None:
                continue

            track = track_lookup.get(track_id, {})
            if not self._is_valid_print_observation(track):
                continue

            votes = self.track_print_votes.setdefault(track_id, [])
            votes.append(bool(result["print_present"]))
            if len(votes) > self.print_history_size:
                del votes[:-self.print_history_size]
            self.track_print_last_seen[track_id] = self.frame_index

        self._trim_print_history(active_track_ids=set(track_lookup))

    def _is_valid_print_observation(self, track):
        if track.get("unstable", False):
            return False

        if (
            self.skip_motion_jump_print_observations
            and track.get("motion_jump", False)
        ):
            return False

        if track.get("speed", 0.0) < self.min_print_observation_speed:
            return False

        return True

    def draw(self, frame, tracks, detections, print_results, count, fps):
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

    def publish(self, frame):
        cv2.imshow(self.window_name, frame)

    def calculate_fps(self):
        current_time = time.time()
        fps = 1 / max(current_time - self.previous_time, 1e-6)
        self.previous_time = current_time
        return fps

    def release(self):
        self.camera.release()
        self.connected = False

    def _publish_events(self, count, fps, print_results):
        counted_results = self._update_print_totals()
        live_print_status = self._summarize_print_status(print_results)
        counted_print_status = (
            self._summarize_print_status(counted_results)
            if counted_results
            else None
        )
        self._publish_runtime_status(fps=fps, print_status=live_print_status)

        if self.elasticsearch is not None:
            self.elasticsearch.create_camera_event(self.name, fps, "online")
            if (
                counted_print_status is not None
                and counted_print_status != self.last_print_status
            ):
                self.elasticsearch.create_print_event(
                    self.name,
                    counted_print_status == "ok",
                )

        for counted_bag in counted_results:
            if self.elasticsearch is not None:
                self.elasticsearch.create_count_event(
                    self.name,
                    counted_bag["total_count"],
                    counted_bag["center"],
                )
            if self.count_logger is not None:
                self.count_logger.log_count_event(
                    camera_name=self.name,
                    total_count=counted_bag["total_count"],
                    track_id=counted_bag["track_id"],
                    center=counted_bag["center"],
                    print_present=counted_bag["print_present"],
                    printed_count=self.printed_count,
                    missing_count=self.missing_count,
                )

        self.last_count = count
        if counted_print_status is not None:
            self.last_print_status = counted_print_status

    def _publish_runtime_status(self, fps, print_status):
        if self.dashboard_state is None:
            return

        self.dashboard_state.update_camera(
            camera_name=self.name,
            count=self.counter.total_count,
            fps=fps,
            status="online" if self.connected else "offline",
            print_status=print_status,
            printed_count=self.printed_count,
            missing_count=self.missing_count,
            printed_bags_count=self.printed_count,
            not_printed_bags_count=self.missing_count,
        )

    def _summarize_print_status(self, print_results):
        if not self.print_detection_enabled:
            return "disabled"

        if not print_results:
            return "no_bag"

        if all(result["print_present"] for result in print_results):
            return "ok"

        return "missing"

    def _update_print_totals(self):
        if not self.print_detection_enabled or not self.counter.last_counted_bags:
            return [
                {
                    "track_id": counted_bag["track_id"],
                    "center": counted_bag["center"],
                    "print_present": None,
                    "total_count": self.last_count + index + 1,
                }
                for index, counted_bag in enumerate(self.counter.last_counted_bags)
            ]

        counted_results = []

        for index, counted_bag in enumerate(self.counter.last_counted_bags):
            print_present = self._finalize_print_status(counted_bag["track_id"])
            if print_present:
                self.printed_count += 1
            else:
                self.missing_count += 1
            counted_results.append(
                {
                    "track_id": counted_bag["track_id"],
                    "center": counted_bag["center"],
                    "print_present": print_present,
                    "total_count": self.last_count + index + 1,
                }
            )

        return counted_results

    def _finalize_print_status(self, track_id):
        votes = self.track_print_votes.get(track_id, [])
        self.track_print_votes.pop(track_id, None)
        self.track_print_last_seen.pop(track_id, None)

        if not votes:
            return False

        positive_votes = sum(1 for vote in votes if vote)
        positive_ratio = positive_votes / len(votes)
        return (
            positive_votes >= self.min_print_votes
            and positive_ratio >= self.print_vote_threshold
        )

    def _trim_print_history(self, active_track_ids):
        fresh_ids = {
            track_id
            for track_id, last_seen in self.track_print_last_seen.items()
            if self.frame_index - last_seen <= self.print_history_ttl_frames
        }
        retained_ids = set(active_track_ids) | fresh_ids

        self.track_print_votes = {
            track_id: votes
            for track_id, votes in self.track_print_votes.items()
            if track_id in retained_ids
        }
        self.track_print_last_seen = {
            track_id: last_seen
            for track_id, last_seen in self.track_print_last_seen.items()
            if track_id in retained_ids
        }

    def _restore_persisted_counts(self):
        if self.dashboard_state is None:
            return

        snapshot = self.dashboard_state.snapshot()
        camera_state = snapshot.get("cameras", {}).get(self.name, {})
        self.counter.total_count = int(camera_state.get("count", 0) or 0)
        self.printed_count = int(camera_state.get("printed_count", 0) or 0)
        self.missing_count = int(camera_state.get("missing_count", 0) or 0)
