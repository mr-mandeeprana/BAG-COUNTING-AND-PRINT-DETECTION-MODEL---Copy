"""
==========================================================
FillPac AI
Application
==========================================================
"""

import threading
import time

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
            log_file=self.config.get("logging", "file", default="logs/application.log"),
            level=self.config.get("logging", "level", default="INFO"),
        )
        self.logger.info("Starting FillPac AI")
        self.stopped = False

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

        self.dashboard_state.update_health(
            {
                "model_loaded": True,
                "elasticsearch_connected": self.elasticsearch.is_connected(),
                "dashboard_enabled": self.dashboard_state.enabled,
            }
        )
        self.count_logger = CountLogger(
            log_file=self.config.get("logging", "count_file", default="logs/count_events.jsonl"),
            logger=self.logger,
        )

        self.stop_event = threading.Event()
        self.pipeline_threads = []

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

        for pipeline in self.pipelines:
            thread = threading.Thread(
                target=pipeline.run,
                args=(self.stop_event,),
                daemon=True,
                name=f"Pipeline-{pipeline.name}",
            )
            thread.start()
            self.pipeline_threads.append(thread)

        try:
            while not self.stop_event.is_set():
                for pipeline in self.pipelines:
                    pipeline.publish()

                if cv2.waitKey(1) == 27:
                    self.logger.info("Exit key pressed.")
                    self.stop_event.set()
                    break
                time.sleep(0.01)
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received, shutting down.")
            self.stop_event.set()
        except Exception:
            self.logger.error("Unhandled exception in application run.", exc_info=True)
            self.stop_event.set()
        finally:
            self.stop()

    def stop(self):
        if self.stopped:
            return

        self.stopped = True
        self.logger.info("Stopping application.")
        self.stop_event.set()
        self.dashboard_state.set_system_status("stopping")

        for pipeline in self.pipelines:
            pipeline.release()

        for thread in self.pipeline_threads:
            thread.join(timeout=5)

        if self.elasticsearch is not None:
            self.elasticsearch.close()

        self.dashboard_state.close()

        cv2.destroyAllWindows()
        self.dashboard_state.set_system_status("stopped")
        self.logger.info("Application closed.")
