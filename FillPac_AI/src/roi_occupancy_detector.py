"""
==========================================================
FillPac AI
ROI Occupancy Jam Detector
Condition C
==========================================================

Condition C declares a jam when the number of bags inside
the configured ROI exceeds max_allowed_bags.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2


class ROIOccupancyDetector:

    def __init__(self, config: dict):

        self.config = config or {}

        self.enabled = bool(
            self.config.get(
                "enabled",
                False,
            )
        )

        self.roi = dict(
            self.config.get(
                "roi",
                {},
            )
        )

        self.max_allowed_bags = max(
            int(
                self.config.get(
                    "max_allowed_bags",
                    1,
                )
            ),
            1,
        )

        self.min_track_age = max(
            int(
                self.config.get(
                    "min_track_age",
                    4,
                )
            ),
            1,
        )

        self.ignore_unstable_tracks = bool(
            self.config.get(
                "ignore_unstable_tracks",
                True,
            )
        )

        self.ignore_motion_jumps = bool(
            self.config.get(
                "ignore_motion_jumps",
                True,
            )
        )

        self.capture_cooldown = max(
            float(
                self.config.get(
                    "capture_cooldown_seconds",
                    5,
                )
            ),
            0.0,
        )

        self.save_roi_image = bool(
            self.config.get(
                "save_roi_image",
                True,
            )
        )

        self.save_logs = bool(
            self.config.get(
                "save_logs",
                True,
            )
        )

        self.save_distances = bool(
            self.config.get(
                "save_distances",
                True,
            )
        )

        self.camera_name = str(
            self.config.get(
                "camera_name",
                "unknown",
            )
        )

        self.image_directory = Path(
            self.config.get(
                "image_directory",
                "logs/condition_c/images",
            )
        )

        self.log_directory = Path(
            self.config.get(
                "log_directory",
                "logs/condition_c/events",
            )
        )

        self.image_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.log_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.last_capture_time = 0.0

        # =================================================
        # JAM EVENT LIFECYCLE STATE
        # =================================================

        self.previous_jam = False

        self.jam_start_time = None

        self.event_id = 0

    # =====================================================
    # PROCESS
    # =====================================================

    def process(
        self,
        frame,
        tracks,
        spacing_result=None,
        camera_name=None,
    ):

        empty = {
            "jam": False,
            "status": "disabled" if not self.enabled else "normal",
            "bag_count": 0,
            "track_ids": [],
            "track_centers": [],
            "minimum_gap_mm": None,
            "average_gap_mm": None,
            "distances": [],
            "spacing_threshold_mm": None,
            "roi": dict(self.roi) if self.roi else {},
            "max_allowed_bags": self.max_allowed_bags,
            "occupancy_percent": 0,
            "jam_duration": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": self.event_id,
            "image_path": None,
        }

        if not self.enabled:
            return empty

        if not self.roi:
            return empty

        try:

            x1 = int(self.roi["x1"])
            y1 = int(self.roi["y1"])
            x2 = int(self.roi["x2"])
            y2 = int(self.roi["y2"])

        except Exception:
            return empty

        roi_tracks = []

        for track in (tracks or []):

            if not isinstance(track, dict):
                continue

            # ------------------------------
            # Track age
            # ------------------------------

            track_age = int(
                track.get(
                    "track_age",
                    0,
                )
                or 0
            )

            if track_age < self.min_track_age:
                continue

            # ------------------------------
            # Ignore unstable tracks
            # ------------------------------

            if (
                self.ignore_unstable_tracks
                and
                track.get(
                    "unstable",
                    False,
                )
            ):
                continue

            # ------------------------------
            # Ignore motion jumps
            # ------------------------------

            if (
                self.ignore_motion_jumps
                and
                track.get(
                    "motion_jump",
                    False,
                )
            ):
                continue

            bbox = track.get("bbox")

            if (
                bbox is None
                or
                len(bbox) != 4
            ):
                continue

            x_min, y_min, x_max, y_max = bbox

            cx = int(
                (x_min + x_max) / 2
            )

            cy = int(
                (y_min + y_max) / 2
            )

            if (
                x1 <= cx <= x2
                and
                y1 <= cy <= y2
            ):
                roi_tracks.append(track)

        bag_count = len(
            roi_tracks
        )

        jam = (
            bag_count
            >
            self.max_allowed_bags
        )

        new_jam = (
            jam
            and
            not self.previous_jam
        )

        jam_cleared = (
            self.previous_jam
            and
            not jam
        )

        self.previous_jam = jam

        if new_jam:

            self.jam_start_time = (
                time.time()
            )

        elif jam_cleared:

            self.jam_start_time = None

        jam_duration = (
            (
                time.time()
                -
                self.jam_start_time
            )
            if (
                jam
                and
                self.jam_start_time is not None
            )
            else 0
        )

        track_ids = [
            t.get("track_id")
            for t in roi_tracks
            if t.get("track_id") is not None
        ]

        track_centers = []

        for t in roi_tracks:

            track_id = t.get("track_id")

            if track_id is None:
                continue

            t_bbox = t.get("bbox")

            if (
                t_bbox is None
                or
                len(t_bbox) != 4
            ):
                continue

            t_x_min, t_y_min, t_x_max, t_y_max = t_bbox

            track_centers.append(
                {
                    "id": track_id,
                    "center": [
                        int(
                            (t_x_min + t_x_max) / 2
                        ),
                        int(
                            (t_y_min + t_y_max) / 2
                        ),
                    ],
                }
            )

        roi_track_ids = set(track_ids)

        roi_distances = []

        minimum_gap = None

        gap_values = []

        spacing_threshold_mm = (
            spacing_result.get(
                "threshold_mm"
            )
            if spacing_result
            else None
        )

        if (
            spacing_result
            and
            self.save_distances
        ):

            for pair in (
                spacing_result.get(
                    "distances",
                    [],
                )
                or []
            ):

                if not isinstance(pair, dict):
                    continue

                if (
                    pair.get("track1") in roi_track_ids
                    and
                    pair.get("track2") in roi_track_ids
                ):

                    roi_distances.append(pair)

                    gap = pair.get("distance_mm")

                    if gap is not None:

                        gap_values.append(gap)

                        if (
                            minimum_gap is None
                            or
                            gap < minimum_gap
                        ):
                            minimum_gap = gap

        average_gap = (
            sum(gap_values) / len(gap_values)
            if gap_values
            else None
        )

        occupancy_percent = (
            (bag_count / self.max_allowed_bags)
            * 100
        )

        result = {

            "jam": jam,

            "status": "jam" if jam else "normal",

            "bag_count": bag_count,

            "track_ids": track_ids,

            "track_centers": track_centers,

            "minimum_gap_mm": minimum_gap,

            "average_gap_mm": average_gap,

            "distances": roi_distances,

            "spacing_threshold_mm": spacing_threshold_mm,

            "roi": {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            },

            "max_allowed_bags": self.max_allowed_bags,

            "occupancy_percent": occupancy_percent,

            "jam_duration": jam_duration,

            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),

            "event_id": self.event_id,

            "image_path": None,
        }

        should_capture = (
            new_jam
            or
            (
                jam
                and
                (
                    time.time()
                    -
                    self.last_capture_time
                )
                >
                self.capture_cooldown
            )
        )

        if should_capture:

            self.last_capture_time = (
                time.time()
            )

            image_path = self._save(
                frame,
                result,
                camera_name=camera_name,
            )

            result["image_path"] = image_path

        return result

    # =====================================================
    # SAVE
    # =====================================================

    def _save(
        self,
        frame,
        result,
        camera_name=None,
    ):

        self.event_id += 1

        result["event_id"] = self.event_id

        file_timestamp = time.strftime(
            "%Y%m%d_%H%M%S"
        )

        image_path = None

        if (
            self.save_roi_image
            and
            frame is not None
        ):

            try:

                x1 = int(self.roi["x1"])
                y1 = int(self.roi["y1"])
                x2 = int(self.roi["x2"])
                y2 = int(self.roi["y2"])

                roi_image = frame[
                    y1:y2,
                    x1:x2,
                ]

                if roi_image.size > 0:

                    candidate_path = (
                        self.image_directory
                        /
                        f"{file_timestamp}.jpg"
                    )

                    cv2.imwrite(
                        str(
                            candidate_path
                        ),
                        roi_image,
                    )

                    image_path = str(
                        candidate_path
                    )

            except Exception:
                pass

        if self.save_logs:

            try:

                log_payload = dict(
                    result
                )

                log_payload["camera"] = (
                    camera_name
                    or self.camera_name
                )

                log_payload["event"] = "condition_c"

                log_payload["image_path"] = image_path

                with open(
                    self.log_directory
                    /
                    f"{file_timestamp}.json",
                    "w",
                ) as fp:

                    json.dump(
                        log_payload,
                        fp,
                        indent=4,
                    )

            except Exception:
                pass

        return image_path