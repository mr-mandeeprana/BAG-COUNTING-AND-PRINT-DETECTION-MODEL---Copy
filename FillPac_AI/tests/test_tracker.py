import numpy as np

from src.tracker import Tracker


class FakeTracks:
    def __init__(self, rows):
        self.tracker_id = np.array([row["track_id"] for row in rows])
        self.xyxy = np.array([row["bbox"] for row in rows], dtype=float)
        self.confidence = np.array([row["confidence"] for row in rows], dtype=float)

    def __len__(self):
        return len(self.tracker_id)


class FakeByteTrack:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0

    def update_with_detections(self, detections):
        if self.index >= len(self.frames):
            return FakeTracks([])

        rows = self.frames[self.index]
        self.index += 1
        return FakeTracks(rows)


def make_tracker(frames, **config):
    default_config = {
        "min_track_age": 1,
        "min_bbox_area": 0,
        "min_track_confidence": 0,
        "max_jump_distance": 250,
        "min_iou_warning": 0.1,
    }
    default_config.update(config)
    tracker = Tracker(default_config)
    tracker.tracker = FakeByteTrack(frames)
    return tracker


def bag_detection():
    return [{"bbox": (0, 0, 100, 100), "confidence": 0.9, "class_id": 0}]


def test_tracker_filters_until_track_reaches_min_age():
    tracker = make_tracker(
        frames=[
            [{"track_id": 1, "bbox": (0, 0, 100, 100), "confidence": 0.9}],
            [{"track_id": 1, "bbox": (0, 5, 100, 105), "confidence": 0.9}],
            [{"track_id": 1, "bbox": (0, 10, 100, 110), "confidence": 0.9}],
        ],
        min_track_age=3,
    )

    assert tracker.update(bag_detection()) == []
    assert tracker.update(bag_detection()) == []

    tracks = tracker.update(bag_detection())

    assert len(tracks) == 1
    assert tracks[0]["track_id"] == 1
    assert tracks[0]["center"] == (50, 60)
    assert tracks[0]["speed"] == 5
    assert tracks[0]["direction"] == "down"
    assert tracks[0]["distance"] == 10
    assert tracks[0]["unstable"] is False


def test_tracker_filters_low_confidence_and_small_boxes():
    tracker = make_tracker(
        frames=[
            [
                {"track_id": 1, "bbox": (0, 0, 100, 100), "confidence": 0.2},
                {"track_id": 2, "bbox": (0, 0, 20, 20), "confidence": 0.9},
                {"track_id": 3, "bbox": (0, 0, 100, 100), "confidence": 0.9},
            ]
        ],
        min_bbox_area=4000,
        min_track_confidence=0.45,
    )

    tracks = tracker.update(bag_detection())

    assert [track["track_id"] for track in tracks] == [3]


def test_tracker_supports_relative_bbox_area_filter():
    tracker = make_tracker(
        frames=[
            [
                {"track_id": 1, "bbox": (0, 0, 20, 20), "confidence": 0.9},
                {"track_id": 2, "bbox": (0, 0, 60, 60), "confidence": 0.9},
            ]
        ],
        frame_width=1000,
        frame_height=1000,
        min_bbox_area=0,
        min_bbox_area_ratio=0.002,
    )

    tracks = tracker.update(bag_detection())

    assert [track["track_id"] for track in tracks] == [2]


def test_tracker_records_single_position_jump_without_rejecting_track():
    tracker = make_tracker(
        frames=[
            [{"track_id": 1, "bbox": (0, 0, 100, 100), "confidence": 0.9}],
            [{"track_id": 1, "bbox": (300, 300, 400, 400), "confidence": 0.9}],
        ],
        max_jump_distance=50,
    )

    assert len(tracker.update(bag_detection())) == 1
    tracks = tracker.update(bag_detection())

    assert len(tracks) == 1
    assert tracker.track_last_center[1] == (350, 350)
    assert tracks[0]["motion_jump"] is True
    assert tracks[0]["unstable"] is False
    assert tracker.track_unstable_count[1] == 1
    assert tracks[0]["iou"] == 0.0


def test_tracker_keeps_tracks_with_brief_reverse_motion_and_records_direction():
    tracker = make_tracker(
        frames=[
            [{"track_id": 1, "bbox": (0, 100, 100, 200), "confidence": 0.9}],
            [{"track_id": 1, "bbox": (0, 80, 100, 180), "confidence": 0.9}],
        ]
    )

    assert len(tracker.update(bag_detection())) == 1
    tracks = tracker.update(bag_detection())

    assert len(tracks) == 1
    assert tracker.track_last_center[1] == (50, 130)
    assert tracker.track_velocity[1] == (0, -20)
    assert tracker.track_speed[1] == 20
    assert tracker.track_direction[1] == "up"
    assert tracker.track_distance[1] == 20


def test_tracker_requires_consecutive_low_iou_updates_before_unstable():
    tracker = make_tracker(
        frames=[
            [{"track_id": 1, "bbox": (0, 0, 100, 100), "confidence": 0.9}],
            [{"track_id": 1, "bbox": (180, 0, 280, 100), "confidence": 0.9}],
            [{"track_id": 1, "bbox": (360, 0, 460, 100), "confidence": 0.9}],
            [{"track_id": 1, "bbox": (540, 0, 640, 100), "confidence": 0.9}],
        ],
        max_jump_distance=300,
        min_iou_warning=0.1,
    )

    assert len(tracker.update(bag_detection())) == 1
    tracks = tracker.update(bag_detection())
    assert len(tracks) == 1
    assert tracks[0]["iou"] == 0.0
    assert tracks[0]["unstable"] is False
    assert tracks[0]["motion_jump"] is False

    tracks = tracker.update(bag_detection())
    assert len(tracks) == 1
    assert tracks[0]["unstable"] is False

    tracks = tracker.update(bag_detection())

    assert len(tracks) == 1
    assert tracks[0]["iou"] == 0.0
    assert tracks[0]["unstable"] is True
    assert tracks[0]["motion_jump"] is False
    assert tracker.track_unstable_count[1] == 3


def test_tracker_resets_unstable_count_after_good_update():
    tracker = make_tracker(
        frames=[
            [{"track_id": 1, "bbox": (0, 0, 100, 100), "confidence": 0.9}],
            [{"track_id": 1, "bbox": (180, 0, 280, 100), "confidence": 0.9}],
            [{"track_id": 1, "bbox": (190, 0, 290, 100), "confidence": 0.9}],
        ],
        max_jump_distance=300,
        min_iou_warning=0.1,
    )

    assert len(tracker.update(bag_detection())) == 1
    assert tracker.update(bag_detection())[0]["unstable"] is False
    tracks = tracker.update(bag_detection())

    assert tracks[0]["iou"] > tracker.min_iou_warning
    assert tracks[0]["unstable"] is False
    assert tracker.track_unstable_count[1] == 0


def test_tracker_cleans_stale_history():
    tracker = make_tracker(frames=[], history_ttl_frames=2)
    tracker.frame_index = 10
    tracker.track_age = {1: 5, 2: 5}
    tracker.track_last_seen = {1: 7, 2: 9}
    tracker.track_last_center = {1: (10, 10), 2: (20, 20)}
    tracker.track_last_bbox = {1: (0, 0, 20, 20), 2: (10, 10, 30, 30)}
    tracker.track_velocity = {1: (0, 1), 2: (0, 1)}
    tracker.track_speed = {1: 1, 2: 1}
    tracker.track_direction = {1: "down", 2: "down"}
    tracker.track_distance = {1: 10, 2: 20}
    tracker.track_iou = {1: 0.0, 2: 0.8}
    tracker.track_unstable = {1: True, 2: False}
    tracker.track_unstable_count = {1: 3, 2: 0}
    tracker.track_motion_jump = {1: True, 2: False}

    tracker._trim_history(active_track_ids=set())

    assert set(tracker.track_age) == {2}
    assert set(tracker.track_last_seen) == {2}
    assert set(tracker.track_last_center) == {2}
    assert set(tracker.track_last_bbox) == {2}
    assert set(tracker.track_velocity) == {2}
    assert set(tracker.track_speed) == {2}
    assert set(tracker.track_direction) == {2}
    assert set(tracker.track_distance) == {2}
    assert set(tracker.track_iou) == {2}
    assert set(tracker.track_unstable) == {2}
    assert set(tracker.track_unstable_count) == {2}
    assert set(tracker.track_motion_jump) == {2}
