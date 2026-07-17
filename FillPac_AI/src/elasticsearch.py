"""
==========================================================
FillPac AI
Elasticsearch Module
==========================================================
"""

from datetime import datetime

from elasticsearch import Elasticsearch


class ElasticSearch:
    def __init__(self, host, port, indices=None, enabled=True, logger=None):
        self.enabled = enabled
        self.logger = logger
        self.indices = indices or {
            "count": "fillpac-count",
            "print": "fillpac-print",
            "camera": "fillpac-camera",
        }

        if self.enabled:
            self.client = Elasticsearch(f"http://{host}:{port}")
            self._log("info", "Elasticsearch connected")

    def send(self, index_name: str, data: dict):
        if not self.enabled:
            return

        try:
            self.client.index(index=self.indices[index_name], document=data)
        except Exception as error:
            self._log("error", f"Elasticsearch error: {error}")

    def create_count_event(self, camera, count, center):
        document = {
            "timestamp": datetime.now(),
            "event": "bag_count",
            "camera": camera,
            "count": count,
            "center_x": center[0],
            "center_y": center[1],
        }
        self.send("count", document)

    def create_print_event(self, camera, status):
        document = {
            "timestamp": datetime.now(),
            "event": "print_detection",
            "camera": camera,
            "print_present": status,
        }
        self.send("print", document)

    def create_camera_event(self, camera, fps, status):
        document = {
            "timestamp": datetime.now(),
            "event": "camera_status",
            "camera": camera,
            "fps": fps,
            "status": status,
        }
        self.send("camera", document)

    def _log(self, level, message):
        if self.logger is not None:
            getattr(self.logger, level)(message)
            return

        print(f"[{level.upper()}] {message}")
