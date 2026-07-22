"""
==========================================================
FillPac AI
Application
==========================================================

Main application orchestrator.

Production Architecture
-----------------------

Application
    |
    +-- DashboardState
    |
    +-- Elasticsearch
    |
    +-- ONE Detector / YOLO Model
    |
    +-- ONE InferenceManager
    |       |
    |       +-- Camera 1 Pipeline
    |       +-- Camera 2 Pipeline
    |       +-- Camera 3 Pipeline
    |       +-- Camera 4 Pipeline
    |
    +-- Each Pipeline owns:
            - Camera
            - Tracker
            - Counter
            - PrintDetector
            - Print history

Important
---------
YOLO model is loaded exactly ONCE.

All camera pipelines use the same InferenceManager.

Trackers and counters remain independent per camera.
==========================================================
"""

import threading
import time

import cv2

from src.count_logger import CountLogger
from src.config import Config
from src.dashboard import DashboardState
from src.detector import Detector
from src.elasticsearch import ElasticSearch
from src.inference_manager import InferenceManager
from src.logger import Logger
from src.pipeline import Pipeline


class Application:

    def __init__(self):

        # ==================================================
        # CONFIGURATION
        # ==================================================

        self.config = Config()
        self.config.validate()

        # ==================================================
        # LOGGER
        # ==================================================

        self.logger = Logger(
            log_file=self.config.get(
                "logging",
                "file",
                default="logs/application.log",
            ),
            level=self.config.get(
                "logging",
                "level",
                default="INFO",
            ),
        )

        self.logger.info(
            "Starting FillPac AI"
        )

        # ==================================================
        # APPLICATION STATE
        # ==================================================

        self.stopped = False

        self.stop_event = threading.Event()

        self.pipeline_threads = []

        self.pipelines = []

        self.detector = None

        self.inference_manager = None

        self.elasticsearch = None

        # ==================================================
        # DASHBOARD STATE
        #
        # This is the ONLY DashboardState writer used
        # by the main AI application.
        # ==================================================

        self.dashboard_state = DashboardState(
            enabled=self.config.get(
                "dashboard",
                "enabled",
                default=True,
            ),
            state_file=self.config.get(
                "dashboard",
                "state_file",
                default="dashboard/backend/state.json",
            ),
            persist_interval_seconds=self.config.get(
                "dashboard",
                "persist_interval_seconds",
                default=1.0,
            ),
            logger=self.logger,
        )

        self.dashboard_state.set_system_status(
            "starting"
        )

        # ==================================================
        # ELASTICSEARCH
        # ==================================================

        elasticsearch_config = self.config.get(
            "elasticsearch",
            default={},
        )

        self.elasticsearch = ElasticSearch(
            host=elasticsearch_config.get(
                "host",
                "localhost",
            ),
            port=elasticsearch_config.get(
                "port",
                9200,
            ),
            indices=elasticsearch_config.get(
                "indices",
            ),
            enabled=elasticsearch_config.get(
                "enabled",
                False,
            ),
            logger=self.logger,
        )

        # ==================================================
        # INITIAL DASHBOARD HEALTH
        # ==================================================

        self.dashboard_state.update_health(
            {
                "model_loaded": False,
                "inference_manager_running": False,
                "elasticsearch_connected":
                    self.elasticsearch.is_connected(),
                "dashboard_enabled":
                    self.dashboard_state.enabled,
            }
        )

        # ==================================================
        # COUNT EVENT LOGGER
        # ==================================================

        self.count_logger = CountLogger(
            log_file=self.config.get(
                "logging",
                "count_file",
                default="logs/count_events.jsonl",
            ),
            logger=self.logger,
        )

        # ==================================================
        # SHARED YOLO MODEL
        #
        # IMPORTANT:
        # Read model configuration ONCE.
        #
        # We use the first enabled camera's model config
        # because the current YAML references the same
        # default model for all cameras.
        # ==================================================

        try:

            enabled_cameras = [
                camera
                for camera in self.config.get(
                    "cameras",
                    default=[],
                )
                if camera.get(
                    "enabled",
                    True,
                )
            ]

            if not enabled_cameras:

                self.logger.warning(
                    "No enabled cameras found "
                    "in configuration."
                )

                self.dashboard_state.set_system_status(
                    "idle"
                )

                return

            # ----------------------------------------------
            # Shared model configuration
            # ----------------------------------------------

            model_config = enabled_cameras[
                0
            ].get(
                "model",
                {},
            )

            # ----------------------------------------------
            # Create ONE Detector
            #
            # This loads ONE YOLO model.
            # ----------------------------------------------

            self.detector = Detector(
                model_path=model_config[
                    "path"
                ],
                confidence=model_config.get(
                    "confidence",
                    0.5,
                ),
                iou=model_config.get(
                    "iou",
                    0.45,
                ),
                device=model_config.get(
                    "device",
                    "cpu",
                ),
                image_size=model_config.get(
                    "image_size",
                    640,
                ),
                half=model_config.get(
                    "half",
                    True,
                ),
                max_detections=model_config.get(
                    "max_detections",
                    100,
                ),
                allowed_classes=model_config.get(
                    "allowed_classes",
                ),
                min_bbox_area=model_config.get(
                    "min_bbox_area",
                    0,
                ),
                bag_confidence=model_config.get(
                    "bag_confidence",
                ),
                print_confidence=model_config.get(
                    "print_confidence",
                ),
                class_confidence_thresholds=
                    model_config.get(
                        "class_confidence_thresholds",
                    ),
                detection_roi=model_config.get(
                    "detection_roi",
                ),
                logger=self.logger,
            )

            self.logger.info(
                "Shared YOLO Detector initialized."
            )

            # ----------------------------------------------
            # Update health
            # ----------------------------------------------

            self.dashboard_state.update_health(
                {
                    "model_loaded": True
                }
            )

            # ==================================================
            # INFERENCE MANAGER
            #
            # ONE manager owns access to the shared Detector.
            # ==================================================

            self.inference_manager = (
                InferenceManager(
                    detector=self.detector,
                    logger=self.logger,
                )
            )

            self.inference_manager.start()

            self.logger.info(
                "Shared InferenceManager started."
            )

            self.dashboard_state.update_health(
                {
                    "inference_manager_running":
                        True
                }
            )

        except Exception as error:

            self.dashboard_state.update_health(
                {
                    "model_loaded": False,
                    "inference_manager_running": False,
                }
            )

            self.dashboard_state.set_system_status(
                "error"
            )

            self.logger.error(
                "Shared YOLO initialization "
                f"failed: {error}"
            )

            raise

        # ==================================================
        # PIPELINE CONFIGURATION
        # ==================================================

        tracker_config = self.config.get(
            "tracker",
            default={},
        )

        display_config = self.config.get(
            "display",
            default={},
        )

        # ==================================================
        # INITIALIZE CAMERA PIPELINES
        #
        # Every pipeline receives the SAME
        # InferenceManager.
        #
        # Every pipeline still creates its OWN:
        # - Camera
        # - Tracker
        # - Counter
        # - PrintDetector
        # ==================================================

        try:

            for camera in enabled_cameras:

                pipeline = Pipeline(
                    camera_config=camera,
                    tracker_config=tracker_config,
                    display_config=display_config,
                    logger=self.logger,

                    # --------------------------------------
                    # SAME inference manager for all cameras
                    # --------------------------------------
                    inference_manager=
                        self.inference_manager,

                    dashboard_state=
                        self.dashboard_state,

                    elasticsearch=
                        self.elasticsearch,

                    count_logger=
                        self.count_logger,
                )

                self.pipelines.append(
                    pipeline
                )

                self.logger.info(
                    f'{camera["name"]} '
                    "pipeline initialized."
                )

        except Exception as error:

            self.dashboard_state.set_system_status(
                "error"
            )

            self.logger.error(
                "Pipeline initialization failed: "
                f"{error}"
            )

            # ----------------------------------------------
            # Stop inference manager if pipeline
            # initialization fails.
            # ----------------------------------------------

            if self.inference_manager is not None:

                try:

                    self.inference_manager.stop()

                except Exception:

                    pass

            raise

    # ======================================================
    # RUN APPLICATION
    # ======================================================

    def run(self):

        self.logger.info(
            "Application running."
        )

        # --------------------------------------------------
        # Check pipelines
        # --------------------------------------------------

        if not self.pipelines:

            self.logger.warning(
                "No enabled camera pipelines "
                "available."
            )

            self.dashboard_state.set_system_status(
                "idle"
            )

            return

        # --------------------------------------------------
        # Verify InferenceManager
        # --------------------------------------------------

        if self.inference_manager is None:

            self.logger.error(
                "InferenceManager is not available."
            )

            self.dashboard_state.set_system_status(
                "error"
            )

            return

        # --------------------------------------------------
        # System Running
        # --------------------------------------------------

        self.dashboard_state.set_system_status(
            "running"
        )

        # --------------------------------------------------
        # Start Pipeline Threads
        # --------------------------------------------------

        for pipeline in self.pipelines:

            thread = threading.Thread(
                target=pipeline.run,
                args=(
                    self.stop_event,
                ),
                daemon=True,
                name=
                    f"Pipeline-{pipeline.name}",
            )

            thread.start()

            self.pipeline_threads.append(
                thread
            )

            self.logger.info(
                f"{pipeline.name} "
                "pipeline thread started."
            )

        # --------------------------------------------------
        # Main Loop
        # --------------------------------------------------

        try:

            while not self.stop_event.is_set():

                # ------------------------------------------
                # Publish latest annotated camera frames
                # ------------------------------------------

                for pipeline in self.pipelines:

                    try:

                        pipeline.publish()

                    except Exception as error:

                        self.logger.warning(
                            f"{pipeline.name} "
                            "publish failed: "
                            f"{error}"
                        )

                # ------------------------------------------
                # ESC key
                # ------------------------------------------

                if cv2.waitKey(
                    1
                ) == 27:

                    self.logger.info(
                        "Exit key pressed."
                    )

                    self.stop_event.set()

                    break

                time.sleep(
                    0.01
                )

        # --------------------------------------------------
        # Keyboard Interrupt
        # --------------------------------------------------

        except KeyboardInterrupt:

            self.logger.info(
                "Keyboard interrupt received, "
                "shutting down."
            )

            self.stop_event.set()

        # --------------------------------------------------
        # Unexpected Error
        # --------------------------------------------------

        except Exception as error:

            self.logger.error(
                "Unhandled exception in "
                f"application run: {error}"
            )

            self.dashboard_state.set_system_status(
                "error"
            )

            self.stop_event.set()

        # --------------------------------------------------
        # Shutdown
        # --------------------------------------------------

        finally:

            self.stop()

    # ======================================================
    # STOP APPLICATION
    # ======================================================

    def stop(self):

        if self.stopped:

            return

        self.stopped = True

        self.logger.info(
            "Stopping application."
        )

        # --------------------------------------------------
        # Dashboard status
        # --------------------------------------------------

        self.dashboard_state.set_system_status(
            "stopping"
        )

        # --------------------------------------------------
        # Tell pipeline loops to stop
        # --------------------------------------------------

        self.stop_event.set()

        # --------------------------------------------------
        # Release camera resources
        # --------------------------------------------------

        for pipeline in self.pipelines:

            try:

                pipeline.release()

            except Exception as error:

                self.logger.warning(
                    f"{pipeline.name} "
                    "release failed: "
                    f"{error}"
                )

        # --------------------------------------------------
        # Wait for pipeline threads
        #
        # Do this BEFORE stopping InferenceManager because
        # pipeline threads may currently be waiting inside
        # inference_manager.infer().
        # --------------------------------------------------

        for thread in self.pipeline_threads:

            thread.join(
                timeout=5
            )

            if thread.is_alive():

                self.logger.warning(
                    f"{thread.name} "
                    "did not stop within timeout."
                )

        # --------------------------------------------------
        # Stop shared InferenceManager
        # --------------------------------------------------

        if self.inference_manager is not None:

            try:

                self.inference_manager.stop(
                    timeout=5
                )

            except Exception as error:

                self.logger.warning(
                    "InferenceManager shutdown "
                    f"failed: {error}"
                )

        self.dashboard_state.update_health(
            {
                "inference_manager_running":
                    False
            }
        )

        # --------------------------------------------------
        # Release reference to Detector
        #
        # Python / PyTorch will release the model resources
        # when no longer referenced.
        # --------------------------------------------------

        self.detector = None

        self.dashboard_state.update_health(
            {
                "model_loaded":
                    False
            }
        )

        # --------------------------------------------------
        # Close Elasticsearch
        # --------------------------------------------------

        if self.elasticsearch is not None:

            try:

                self.elasticsearch.close()

            except Exception as error:

                self.logger.warning(
                    "Elasticsearch shutdown "
                    f"failed: {error}"
                )

        self.dashboard_state.update_health(
            {
                "elasticsearch_connected":
                    False
            }
        )

        # --------------------------------------------------
        # IMPORTANT
        #
        # Set STOPPED before DashboardState.close().
        #
        # DashboardState.close() performs final persistence.
        # --------------------------------------------------

        self.dashboard_state.set_system_status(
            "stopped"
        )

        self.dashboard_state.close()

        # --------------------------------------------------
        # Close OpenCV windows
        # --------------------------------------------------

        cv2.destroyAllWindows()

        self.logger.info(
            "Application closed."
        )