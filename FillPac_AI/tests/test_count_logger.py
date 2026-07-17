import json

from src.count_logger import CountLogger


def test_count_logger_appends_jsonl_event(tmp_path):
    log_file = tmp_path / "count_events.jsonl"
    logger = CountLogger(log_file=log_file)

    logger.log_count_event(
        camera_name="Camera 1",
        total_count=3,
        track_id=42,
        center=(100, 200),
        print_present=True,
        printed_count=2,
        missing_count=1,
    )

    lines = log_file.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["camera"] == "Camera 1"
    assert event["total_count"] == 3
    assert event["track_id"] == 42
    assert event["print_present"] is True
