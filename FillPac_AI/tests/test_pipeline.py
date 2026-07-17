from src.pipeline import Pipeline


class FakeCounter:
    def __init__(self, counted_bags):
        self.last_counted_bags = counted_bags


class FakePrintDetector:
    def __init__(self):
        self.seen_tracks = None

    def update(self, tracks, detections):
        self.seen_tracks = tracks
        return []


def make_pipeline():
    pipeline = Pipeline.__new__(Pipeline)
    pipeline.print_detection_enabled = True
    pipeline.print_vote_threshold = 0.5
    pipeline.min_print_votes = 1
    pipeline.print_history_size = 30
    pipeline.print_history_ttl_frames = 120
    pipeline.min_print_observation_speed = 0.0
    pipeline.skip_motion_jump_print_observations = True
    pipeline.track_print_votes = {}
    pipeline.track_print_last_seen = {}
    pipeline.frame_index = 10
    pipeline.last_count = 0
    pipeline.printed_count = 0
    pipeline.missing_count = 0
    return pipeline


def test_pipeline_filters_unstable_tracks_from_counting_inputs():
    stable_track = {"track_id": 1, "unstable": False}
    missing_metadata_track = {"track_id": 2}
    unstable_track = {"track_id": 3, "unstable": True}

    assert Pipeline.countable_tracks(
        [stable_track, missing_metadata_track, unstable_track]
    ) == [stable_track, missing_metadata_track]


def test_pipeline_print_detection_receives_all_tracks():
    pipeline = make_pipeline()
    pipeline.print_detector = FakePrintDetector()
    tracks = [
        {"track_id": 1, "unstable": False},
        {"track_id": 2, "unstable": True},
    ]

    pipeline.print_detection(tracks, detections=[])

    assert pipeline.print_detector.seen_tracks == tracks


def test_pipeline_records_print_history_and_finalizes_counted_bag():
    pipeline = make_pipeline()
    pipeline.counter = FakeCounter(
        [{"track_id": 7, "bbox": (0, 0, 100, 100), "center": (50, 50)}]
    )
    tracks = [{"track_id": 7, "speed": 4, "motion_jump": False}]

    pipeline.record_print_observations(
        [{"track_id": 7, "print_present": True}],
        tracks,
    )
    pipeline.record_print_observations(
        [{"track_id": 7, "print_present": False}],
        tracks,
    )

    counted_results = pipeline._update_print_totals()

    assert counted_results[0]["print_present"] is True
    assert pipeline.printed_count == 1
    assert pipeline.missing_count == 0
    assert pipeline.track_print_votes == {}
    assert pipeline.track_print_last_seen == {}


def test_pipeline_finalizes_printed_with_limited_positive_observations():
    pipeline = make_pipeline()
    pipeline.min_print_votes = 2
    pipeline.print_vote_threshold = 0.5
    pipeline.track_print_votes = {7: [True]}
    pipeline.track_print_last_seen = {7: 10}

    assert pipeline._finalize_print_status(7) is True
    assert pipeline.track_print_votes == {}
    assert pipeline.track_print_last_seen == {}


def test_pipeline_finalizes_missing_with_only_negative_observations():
    pipeline = make_pipeline()
    pipeline.min_print_votes = 2
    pipeline.print_vote_threshold = 0.5
    pipeline.track_print_votes = {7: [False]}
    pipeline.track_print_last_seen = {7: 10}

    assert pipeline._finalize_print_status(7) is False
    assert pipeline.track_print_votes == {}
    assert pipeline.track_print_last_seen == {}


def test_pipeline_ignores_motion_jump_print_observations():
    pipeline = make_pipeline()
    tracks = [{"track_id": 7, "speed": 4, "motion_jump": True}]

    pipeline.record_print_observations(
        [{"track_id": 7, "print_present": True}],
        tracks,
    )

    assert pipeline.track_print_votes == {}


def test_pipeline_ignores_unstable_print_observations():
    pipeline = make_pipeline()
    tracks = [{"track_id": 7, "speed": 4, "motion_jump": False, "unstable": True}]

    pipeline.record_print_observations(
        [{"track_id": 7, "print_present": True}],
        tracks,
    )

    assert pipeline.track_print_votes == {}
