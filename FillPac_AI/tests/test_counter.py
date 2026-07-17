from src.counter import Counter


def test_counter_counts_track_once_when_crossing_down():
    counter = Counter(roi_y=100, direction="down", duplicate_distance=40, line_tolerance=10)

    above_line = [
        {"bbox": (0, 60, 20, 80), "class_id": 0, "track_id": 7},
    ]
    crossing = [
        {"bbox": (0, 100, 20, 120), "class_id": 0, "track_id": 7},
    ]

    for _ in range(4):
        assert counter.update(above_line) == 0

    assert counter.update(crossing) == 1
    assert counter.update(crossing) == 1


def test_counter_waits_for_minimum_cross_distance_before_counting():
    counter = Counter(
        roi_y=100,
        direction="down",
        line_tolerance=10,
        minimum_cross_distance=15,
    )

    above_line = [
        {"bbox": (0, 60, 20, 80), "class_id": 0, "track_id": 7},
    ]
    shallow_crossing = [
        {"bbox": (0, 100, 20, 120), "class_id": 0, "track_id": 7},
    ]
    confirmed_crossing = [
        {"bbox": (0, 110, 20, 140), "class_id": 0, "track_id": 7},
    ]

    for _ in range(4):
        assert counter.update(above_line) == 0

    assert counter.update(shallow_crossing) == 0
    assert counter.update(confirmed_crossing) == 1


def test_counter_tracks_last_counted_bag_bboxes():
    counter = Counter(roi_y=100, direction="down", duplicate_distance=40, line_tolerance=10)

    detections = [
        {"bbox": (0, 60, 20, 80), "class_id": 0, "track_id": 1},
        {"bbox": (50, 60, 70, 80), "class_id": 0, "track_id": 2},
    ]
    crossing = [
        {"bbox": (0, 100, 20, 120), "class_id": 0, "track_id": 1},
        {"bbox": (50, 100, 70, 120), "class_id": 0, "track_id": 2},
    ]

    for _ in range(4):
        counter.update(detections)

    counter.update(crossing)

    assert [bag["bbox"] for bag in counter.last_counted_bags] == [
        (0, 100, 20, 120),
        (50, 100, 70, 120),
    ]


def test_counter_counts_when_track_moves_from_line_band_to_below():
    counter = Counter(roi_y=100, direction="down", line_tolerance=10)

    near_line = [
        {"bbox": (0, 85, 20, 105), "class_id": 0, "track_id": 5},
    ]
    below_line = [
        {"bbox": (0, 125, 20, 145), "class_id": 0, "track_id": 5},
    ]

    for _ in range(4):
        assert counter.update(near_line) == 0

    assert counter.update(below_line) == 1


def test_counter_waits_until_bbox_and_center_cross_roi():
    counter = Counter(roi_y=100, direction="down", line_tolerance=10)

    above_line = [
        {"bbox": (0, 50, 20, 80), "class_id": 0, "track_id": 9},
    ]
    edge_on_line = [
        {"bbox": (0, 70, 20, 92), "class_id": 0, "track_id": 9},
    ]
    center_crossing = [
        {"bbox": (0, 100, 20, 120), "class_id": 0, "track_id": 9},
    ]

    for _ in range(4):
        assert counter.update(above_line) == 0

    assert counter.update(edge_on_line) == 0
    assert counter.update(center_crossing) == 1


def test_counter_suppresses_nearby_id_switch_within_recent_window():
    counter = Counter(roi_y=100, direction="down", duplicate_distance=40, line_tolerance=10)

    first_above = [
        {"bbox": (0, 60, 20, 80), "class_id": 0, "track_id": 1},
    ]
    first_crossing = [
        {"bbox": (0, 100, 20, 120), "class_id": 0, "track_id": 1},
    ]
    switched_above = [
        {"bbox": (5, 60, 25, 80), "class_id": 0, "track_id": 99},
    ]
    switched_crossing = [
        {"bbox": (5, 100, 25, 120), "class_id": 0, "track_id": 99},
    ]

    for _ in range(4):
        counter.update(first_above)
    assert counter.update(first_crossing) == 1

    for _ in range(4):
        assert counter.update(switched_above) == 1
    assert counter.update(switched_crossing) == 1


def test_counter_allows_separate_tracks_outside_duplicate_distance_to_count():
    counter = Counter(roi_y=100, direction="down", duplicate_distance=40, line_tolerance=10)

    first_above = [
        {"bbox": (0, 60, 20, 80), "class_id": 0, "track_id": 1},
    ]
    first_crossing = [
        {"bbox": (0, 100, 20, 120), "class_id": 0, "track_id": 1},
    ]
    second_above = [
        {"bbox": (80, 60, 100, 80), "class_id": 0, "track_id": 2},
    ]
    second_crossing = [
        {"bbox": (80, 100, 100, 120), "class_id": 0, "track_id": 2},
    ]

    for _ in range(4):
        assert counter.update(first_above) == 0

    assert counter.update(first_crossing) == 1

    for _ in range(4):
        assert counter.update(second_above) == 1

    assert counter.update(second_crossing) == 2


def test_counter_suppresses_nearby_same_frame_duplicate():
    counter = Counter(roi_y=100, direction="down", duplicate_distance=40, line_tolerance=10)

    detections = [
        {"bbox": (0, 60, 20, 80), "class_id": 0, "track_id": 1},
        {"bbox": (20, 60, 40, 80), "class_id": 0, "track_id": 2},
    ]
    crossing = [
        {"bbox": (0, 100, 20, 120), "class_id": 0, "track_id": 1},
        {"bbox": (20, 100, 40, 120), "class_id": 0, "track_id": 2},
    ]

    for _ in range(4):
        assert counter.update(detections) == 0

    assert counter.update(crossing) == 1


def test_counter_allows_nearby_new_track_after_recent_window_expires():
    counter = Counter(roi_y=100, direction="down", duplicate_distance=40, line_tolerance=10)
    counter.recent_count_frames = 2

    first_above = [
        {"bbox": (0, 60, 20, 80), "class_id": 0, "track_id": 1},
    ]
    first_crossing = [
        {"bbox": (0, 100, 20, 120), "class_id": 0, "track_id": 1},
    ]
    second_above = [
        {"bbox": (5, 60, 25, 80), "class_id": 0, "track_id": 2},
    ]
    second_crossing = [
        {"bbox": (5, 100, 25, 120), "class_id": 0, "track_id": 2},
    ]

    for _ in range(4):
        assert counter.update(first_above) == 0

    assert counter.update(first_crossing) == 1

    for _ in range(4):
        assert counter.update(second_above) == 1

    assert counter.update(second_crossing) == 2


def test_counter_trim_history_cleans_all_track_state():
    counter = Counter(roi_y=100, max_history=2)
    counter.track_centers = {1: (10, 10), 2: (20, 20), 3: (30, 30)}
    counter.track_zones = {1: "above", 2: "below", 3: "above"}
    counter.track_start_zones = {1: "above", 2: "above", 3: "above"}
    counter.track_start_centers = {1: (10, 10), 2: (20, 20), 3: (30, 30)}
    counter.track_states = {1: "BEFORE_LINE", 2: "COUNTED", 3: "BEFORE_LINE"}
    counter.track_previous_centers = {1: (10, 5), 2: (20, 15), 3: (30, 25)}
    counter.track_frame_count = {1: 1, 2: 5, 3: 2}
    counter.track_last_seen = {1: 1, 2: 2, 3: 3}
    counter.duplicate_time = {1: 1, 2: 2, 3: 3}
    counter.recent_counts = [
        {"center": (20, 20), "frame": 2},
        {"center": (30, 30), "frame": 3},
    ]
    counter.counted_track_ids = {2}

    counter._trim_history(active_track_ids={3})

    assert set(counter.track_centers) == {2, 3}
    assert set(counter.track_zones) == {2, 3}
    assert set(counter.track_start_zones) == {2, 3}
    assert set(counter.track_start_centers) == {2, 3}
    assert set(counter.track_states) == {2, 3}
    assert set(counter.track_previous_centers) == {2, 3}
    assert set(counter.track_frame_count) == {2, 3}
    assert set(counter.track_last_seen) == {2, 3}
    assert set(counter.duplicate_time) == {2, 3}
    assert [item["frame"] for item in counter.recent_counts] == [2, 3]
    assert counter.counted_track_ids == {2}


def test_counter_removes_stale_track_state():
    counter = Counter(roi_y=100, stale_track_frames=2)
    counter.recent_count_frames = 2
    counter.frame_index = 10
    counter.track_centers = {1: (10, 10), 2: (20, 20)}
    counter.track_zones = {1: "above", 2: "above"}
    counter.track_start_zones = {1: "above", 2: "above"}
    counter.track_start_centers = {1: (10, 10), 2: (20, 20)}
    counter.track_states = {1: "BEFORE_LINE", 2: "BEFORE_LINE"}
    counter.track_previous_centers = {1: (10, 5), 2: (20, 15)}
    counter.track_frame_count = {1: 1, 2: 1}
    counter.track_last_seen = {1: 7, 2: 9}
    counter.duplicate_time = {1: 7, 2: 9}
    counter.recent_counts = [
        {"center": (10, 10), "frame": 7},
        {"center": (20, 20), "frame": 9},
    ]
    counter.counted_track_ids = {1, 2}

    counter._trim_history(active_track_ids=set())

    assert set(counter.track_centers) == {2}
    assert set(counter.track_zones) == {2}
    assert set(counter.track_start_zones) == {2}
    assert set(counter.track_start_centers) == {2}
    assert set(counter.track_states) == {2}
    assert set(counter.track_previous_centers) == {2}
    assert set(counter.track_frame_count) == {2}
    assert set(counter.track_last_seen) == {2}
    assert set(counter.duplicate_time) == {2}
    assert [item["frame"] for item in counter.recent_counts] == [9]
    assert counter.counted_track_ids == {2}
