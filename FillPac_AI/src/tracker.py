"""
==========================================================
FillPac AI
ByteTrack Tracker
==========================================================
"""

import math

import numpy as np
from supervision import ByteTrack, Detections


class Tracker:
    def __init__(self, tracker_config=None):
        tracker_config = tracker_config or {}
        self.min_track_age = max(int(tracker_config.get("min_track_age", 4)), 1)
        self.min_bbox_area = max(float(tracker_config.get("min_bbox_area", 4000)), 0.0)
        self.min_bbox_area_ratio = max(
            float(tracker_config.get("min_bbox_area_ratio", 0.0)), 0.0
        )
        self.frame_width = int(tracker_config.get("frame_width", 0) or 0)
        self.frame_height = int(tracker_config.get("frame_height", 0) or 0)
        self.min_track_confidence = float(
            tracker_config.get("min_track_confidence", 0.25)
        )
        self.max_jump_distance = max(
            float(tracker_config.get("max_jump_distance", 250)), 0.0
        )
        self.min_iou_warning = max(float(tracker_config.get("min_iou_warning", 0.1)), 0.0)
        self.unstable_frame_threshold = max(
            int(tracker_config.get("unstable_frame_threshold", 3)), 1
        )
        self.history_ttl_frames = max(
            int(tracker_config.get("history_ttl_frames", 120)), 1
        )
        self.frame_index = 0
        self.track_age = {}
        self.track_last_seen = {}
        self.track_last_center = {}
        self.track_last_bbox = {}
        self.track_velocity = {}
        self.track_speed = {}
        self.track_direction = {}
        self.track_distance = {}
        self.track_iou = {}
        self.track_unstable = {}
        self.track_unstable_count = {}
        self.track_motion_jump = {}
        self.tracker = ByteTrack(
            track_activation_threshold=tracker_config.get("track_high_thresh", 0.5),
            lost_track_buffer=tracker_config.get("track_buffer", 30),
            minimum_matching_threshold=tracker_config.get("match_thresh", 0.8),
        )

    def update(self, detections):
        self.frame_index += 1
        bags = [det for det in detections if det["class_id"] == 0]

        if not bags:
            self._trim_history(active_track_ids=set())
            return []

        xyxy = [bag["bbox"] for bag in bags]
        confidence = [bag.get("confidence", 0.0) for bag in bags]
        class_id = [bag["class_id"] for bag in bags]

        detections_sv = Detections(
            xyxy=np.array(xyxy),
            confidence=np.array(confidence),
            class_id=np.array(class_id),
        )

        tracks = self.tracker.update_with_detections(detections_sv)
        tracked_bags = []
        active_track_ids = set()

        for i in range(len(tracks)):
            track_id = int(tracks.tracker_id[i])
            bbox = tuple(tracks.xyxy[i].astype(int))
            confidence = float(tracks.confidence[i])
            center = self.get_center(bbox)
            active_track_ids.add(track_id)

            previous_center = self.track_last_center.get(track_id)
            self.track_age[track_id] = self.track_age.get(track_id, 0) + 1
            self.track_last_seen[track_id] = self.frame_index

            if not self._passes_quality_filters(bbox, confidence):
                continue

            previous_bbox = self.track_last_bbox.get(track_id)
            self._update_track_memory(
                track_id=track_id,
                bbox=bbox,
                center=center,
                previous_center=previous_center,
                previous_bbox=previous_bbox,
            )

            if self.track_age[track_id] < self.min_track_age:
                continue

            tracked_bags.append(
                {
                    "track_id": track_id,
                    "bbox": bbox,
                    "confidence": confidence,
                    "class_id": 0,
                    "center": center,
                    "speed": self.track_speed[track_id],
                    "direction": self.track_direction[track_id],
                    "distance": self.track_distance[track_id],
                    "iou": self.track_iou[track_id],
                    "unstable": self.track_unstable[track_id],
                    "motion_jump": self.track_motion_jump[track_id],
                }
            )

        self._trim_history(active_track_ids)
        return tracked_bags

    @staticmethod
    def get_center(bbox):
        x1, y1, x2, y2 = bbox
        center_x = int((x1 + x2) / 2)
        center_y = int((y1 + y2) / 2)
        return center_x, center_y

    def _passes_quality_filters(self, bbox, confidence):
        if confidence < self.min_track_confidence:
            return False

        x1, y1, x2, y2 = bbox
        area = max(x2 - x1, 0) * max(y2 - y1, 0)
        return area >= self._minimum_bbox_area()

    def _minimum_bbox_area(self):
        if self.frame_width > 0 and self.frame_height > 0:
            frame_area = self.frame_width * self.frame_height
            relative_area = frame_area * self.min_bbox_area_ratio
            return max(self.min_bbox_area, relative_area)

        return self.min_bbox_area

    def _is_motion_jump(self, previous_center, center):
        if previous_center is None or self.max_jump_distance <= 0:
            return False

        distance = math.hypot(
            center[0] - previous_center[0],
            center[1] - previous_center[1],
        )
        return distance > self.max_jump_distance

    def _update_track_memory(
        self,
        track_id,
        bbox,
        center,
        previous_center,
        previous_bbox,
    ):
        if previous_center is None:
            velocity = (0, 0)
            distance = 0.0
        else:
            velocity = (
                center[0] - previous_center[0],
                center[1] - previous_center[1],
            )
            distance = math.hypot(velocity[0], velocity[1])

        iou = self._bbox_iou(previous_bbox, bbox)
        motion_jump = self._is_motion_jump(previous_center, center)
        low_iou = previous_bbox is not None and iou < self.min_iou_warning

        self.track_last_center[track_id] = center
        self.track_last_bbox[track_id] = bbox
        self.track_velocity[track_id] = velocity
        self.track_speed[track_id] = distance
        self.track_direction[track_id] = self._motion_direction(velocity)
        self.track_distance[track_id] = (
            self.track_distance.get(track_id, 0.0) + distance
        )
        self.track_iou[track_id] = iou
        self.track_motion_jump[track_id] = motion_jump
        if motion_jump or low_iou:
            self.track_unstable_count[track_id] = (
                self.track_unstable_count.get(track_id, 0) + 1
            )
        else:
            self.track_unstable_count[track_id] = 0
        self.track_unstable[track_id] = (
            self.track_unstable_count[track_id] >= self.unstable_frame_threshold
        )

    @staticmethod
    def _bbox_iou(previous_bbox, bbox):
        if previous_bbox is None:
            return 1.0

        ax1, ay1, ax2, ay2 = previous_bbox
        bx1, by1, bx2, by2 = bbox
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_width = max(inter_x2 - inter_x1, 0)
        inter_height = max(inter_y2 - inter_y1, 0)
        intersection = inter_width * inter_height
        area_a = max(ax2 - ax1, 0) * max(ay2 - ay1, 0)
        area_b = max(bx2 - bx1, 0) * max(by2 - by1, 0)
        union = area_a + area_b - intersection

        if union <= 0:
            return 0.0

        return intersection / union

    @staticmethod
    def _motion_direction(velocity):
        dx, dy = velocity

        if dx == 0 and dy == 0:
            return "stationary"

        if abs(dy) >= abs(dx):
            return "down" if dy > 0 else "up"

        return "right" if dx > 0 else "left"

    def _trim_history(self, active_track_ids):
        fresh_ids = {
            track_id
            for track_id, last_seen in self.track_last_seen.items()
            if self.frame_index - last_seen <= self.history_ttl_frames
        }
        retained_ids = set(active_track_ids) | fresh_ids

        self.track_age = {
            track_id: age
            for track_id, age in self.track_age.items()
            if track_id in retained_ids
        }
        self.track_last_seen = {
            track_id: frame_index
            for track_id, frame_index in self.track_last_seen.items()
            if track_id in retained_ids
        }
        self.track_last_center = {
            track_id: center
            for track_id, center in self.track_last_center.items()
            if track_id in retained_ids
        }
        self.track_last_bbox = {
            track_id: bbox
            for track_id, bbox in self.track_last_bbox.items()
            if track_id in retained_ids
        }
        self.track_velocity = {
            track_id: velocity
            for track_id, velocity in self.track_velocity.items()
            if track_id in retained_ids
        }
        self.track_speed = {
            track_id: speed
            for track_id, speed in self.track_speed.items()
            if track_id in retained_ids
        }
        self.track_direction = {
            track_id: direction
            for track_id, direction in self.track_direction.items()
            if track_id in retained_ids
        }
        self.track_distance = {
            track_id: distance
            for track_id, distance in self.track_distance.items()
            if track_id in retained_ids
        }
        self.track_iou = {
            track_id: iou
            for track_id, iou in self.track_iou.items()
            if track_id in retained_ids
        }
        self.track_unstable = {
            track_id: unstable
            for track_id, unstable in self.track_unstable.items()
            if track_id in retained_ids
        }
        self.track_unstable_count = {
            track_id: count
            for track_id, count in self.track_unstable_count.items()
            if track_id in retained_ids
        }
        self.track_motion_jump = {
            track_id: motion_jump
            for track_id, motion_jump in self.track_motion_jump.items()
            if track_id in retained_ids
        }