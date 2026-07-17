"""
==========================================================
FillPac AI
Application
==========================================================
"""

import cv2

from src.count_logger import CountLogger
from src.config import Config
from src.dashboard import DashboardState
from src.elasticsearch import ElasticSearch
from src.logger import Logger
from src.pipeline import Pipeline


class Application:
    def __init__(self):
        self.config = Config()
        self.config.validate()
        self.logger = Logger(
            log_file=self.config.get("logging", "file", default="logs/application.log")
        )
        self.logger.info("Starting FillPac AI")

        self.dashboard_state = DashboardState(
            enabled=self.config.get("dashboard", "enabled", default=False),
            persist_interval_seconds=self.config.get(
                "dashboard",
                "persist_interval_seconds",
                default=0.25,
            ),
            logger=self.logger,
        )
        self.dashboard_state.set_system_status("starting")

        elasticsearch_config = self.config.get("elasticsearch", default={})
        self.elasticsearch = ElasticSearch(
            host=elasticsearch_config.get("host", "localhost"),
            port=elasticsearch_config.get("port", 9200),
            indices=elasticsearch_config.get("indices"),
            enabled=elasticsearch_config.get("enabled", False),
            logger=self.logger,
        )
        self.count_logger = CountLogger(
            log_file=self.config.get("logging", "count_file", default="logs/count_events.jsonl"),
            logger=self.logger,
        )

        self.pipelines = []
        tracker_config = self.config.get("tracker", default={})
        display_config = self.config.get("display", default={})

        for camera in self.config.get("cameras", default=[]):
            if not camera.get("enabled", True):
                continue

            pipeline = Pipeline(
                camera_config=camera,
                tracker_config=tracker_config,
                display_config=display_config,
                logger=self.logger,
                dashboard_state=self.dashboard_state,
                elasticsearch=self.elasticsearch,
                count_logger=self.count_logger,
            )
            self.pipelines.append(pipeline)
            self.logger.info(f'{camera["name"]} initialized.')

    def run(self):
        self.logger.info("Application running.")

        if not self.pipelines:
            self.logger.warning("No enabled cameras found in configuration.")
            self.dashboard_state.set_system_status("idle")
            return

        self.dashboard_state.set_system_status("running")
        running = True

        while running:
            running = False

            for pipeline in self.pipelines:
                if pipeline.process():
                    running = True

            if cv2.waitKey(1) == 27:
                break

        self.stop()

    def stop(self):
        self.logger.info("Stopping application.")
        self.dashboard_state.set_system_status("stopping")

        for pipeline in self.pipelines:
            pipeline.release()

        cv2.destroyAllWindows()
        self.dashboard_state.set_system_status("stopped")
        self.logger.info("Application closed.")
