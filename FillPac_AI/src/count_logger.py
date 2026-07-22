"""
==========================================================
FillPac AI
Count Event Logger
==========================================================
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class CountLogger:
    def __init__(self, log_file="logs/count_events.jsonl", logger=None):
        self.log_file = Path(log_file)
        self.logger = logger
        self.lock = threading.Lock()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.touch(exist_ok=True)

    def log_count_event(
        self,
        camera_name,
        total_count,
        track_id,
        center,
        print_present=None,
        printed_count=0,
        missing_count=0,
    ):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "bag_count",
            "camera": camera_name,
            "total_count": total_count,
            "track_id": track_id,
            "center_x": center[0],
            "center_y": center[1],
            "print_present": print_present,
            "printed_count": printed_count,
            "missing_count": missing_count,
        }

        try:
            with self.lock:
                with open(self.log_file, "a", encoding="utf-8") as file:
                    file.write(json.dumps(event) + "\n")
        except OSError as error:
            self._log("warning", f"Count event write failed: {error}")

    def _log(self, level, message):
        if self.logger is not None:
            getattr(self.logger, level)(message)
            return

        print(f"[{level.upper()}] {message}")