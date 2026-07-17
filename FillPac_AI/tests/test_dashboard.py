import json
from pathlib import Path

from src.dashboard import DashboardState


def test_dashboard_state_persists_snapshot(tmp_path):
    state_file = tmp_path / "state.json"
    dashboard = DashboardState(enabled=True, state_file=state_file)

    dashboard.set_system_status("running")
    dashboard.update_camera(
        "Camera 1",
        count=3,
        fps=12.5,
        status="online",
        print_status="ok",
        printed_count=2,
        missing_count=1,
    )

    with open(state_file, "r", encoding="utf-8") as file:
        state = json.load(file)

    assert state["system_status"] == "running"
    assert state["total_count"] == 3
    assert state["total_printed_count"] == 2
    assert state["total_missing_count"] == 1
    assert state["total_printed_bags_count"] == 2
    assert state["total_not_printed_bags_count"] == 1
    assert state["cameras"]["Camera 1"]["print_status"] == "ok"


def test_dashboard_state_includes_camera_status(tmp_path):
    state_file = tmp_path / "state.json"
    dashboard = DashboardState(enabled=True, state_file=state_file)

    dashboard.update_camera(
        "Camera 1",
        count=2,
        fps=8.5,
        status="online",
        print_status="ok",
        printed_count=1,
        missing_count=1,
        camera_status={
            "connected": True,
            "backend": "ffmpeg",
            "queue_occupancy": 1,
            "frames_read": 12,
            "frames_dropped": 0,

            {
                "system_status": "running",
                "total_count": 5,
                "total_printed_count": 3,
                "total_missing_count": 2,
                "cameras": {
                    "Camera 1": {
                        "count": 5,
                        "printed_count": 3,
                        "missing_count": 2,
                        "fps": 10.0,
                        "status": "online",
                        "print_status": "missing",
                        "updated_at": "2026-07-16T00:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    dashboard = DashboardState(enabled=True, state_file=state_file)

    snapshot = dashboard.snapshot()

    assert snapshot["cameras"]["Camera 1"]["count"] == 5
    assert snapshot["cameras"]["Camera 1"]["printed_count"] == 3
    assert snapshot["cameras"]["Camera 1"]["missing_count"] == 2


def test_dashboard_state_throttles_disk_writes_but_keeps_memory_current(tmp_path):
    state_file = tmp_path / "state.json"
    dashboard = DashboardState(
        enabled=True,
        state_file=state_file,
        persist_interval_seconds=60,
    )

    dashboard.update_camera("Camera 1", count=1, fps=10, status="online", print_status="ok")
    first_write = state_file.stat().st_mtime_ns

    dashboard.update_camera("Camera 1", count=1, fps=11, status="online", print_status="ok")
    second_write = state_file.stat().st_mtime_ns
    snapshot = dashboard.snapshot()

    assert snapshot["cameras"]["Camera 1"]["fps"] == 11.0
    assert second_write == first_write
