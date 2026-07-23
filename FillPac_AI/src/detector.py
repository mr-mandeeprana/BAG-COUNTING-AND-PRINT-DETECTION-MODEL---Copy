"""
==========================================================
FillPac AI
YOLO Detector
==========================================================

Purpose
-------
Loads ONE YOLO model and performs object detection.

Production Architecture
-----------------------
Application
    |
    v
Detector (ONE YOLO model)
    |
    v
InferenceManager
    |
    +---- Camera 1 detections
    +---- Camera 2 detections
    +---- Camera 3 detections
    +---- Camera 4 detections

Important
---------
Detector contains NO tracking or counting state.

Each camera must maintain its own:
- Tracker
- Counter
- Print history
==========================================================
"""

from pathlib import Path
import threading
import time
import os

import numpy as np
import torch
from ultralytics import YOLO

# Limit CPU threads to reduce contention on multi-core machines
torch.set_num_threads(max(1, (os.cpu_count() or 1) // 2))
torch.set_num_interop_threads(2)


class Detector:
    """
    Shared YOLO detector.

    Only one instance of this class should normally be created
    by the FillPac AI application.

    The shared InferenceManager uses this detector for all
    enabled camera pipelines.
    """

    def __init__(
        self,
        model_path: str,
        confidence: float = 0.5,
        iou: float = 0.45,
        device: str = "cpu",
        image_size: int = 640,
        half: bool = True,
        max_detections: int = 100,
        allowed_classes=None,
        min_bbox_area: float = 0.0,
        bag_confidence=None,
        print_confidence=None,
        class_confidence_thresholds=None,
        detection_roi=None,
        logger=None,
    ):
        # ==================================================
        # CONFIGURATION
        # ==================================================

        self.model_path = Path(model_path)

        self.confidence = float(
            confidence
        )

        self.iou = float(
            iou
        )

        self.image_size = int(
            image_size
        )

        self.max_detections = int(
            max_detections
        )

        self.logger = logger

        # ==================================================
        # ALLOWED CLASSES
        # ==================================================

        self.allowed_classes = (
            {
                int(class_id)
                for class_id
                in allowed_classes
            }
            if allowed_classes is not None
            else None
        )

        # ==================================================
        # DETECTION FILTERS
        # ==================================================

        self.min_bbox_area = max(
            float(
                min_bbox_area
            ),
            0.0,
        )

        self.class_confidence_thresholds = (
            self._build_class_confidence_thresholds(
                class_confidence_thresholds=
                    class_confidence_thresholds,
                bag_confidence=
                    bag_confidence,
                print_confidence=
                    print_confidence,
            )
        )

        self.detection_roi = (
            self._validate_detection_roi(
                detection_roi
            )
        )

        # ==================================================
        # DETECTOR STATE
        # ==================================================

        self.frame_index = 0

        # Additional protection around the shared model.
        #
        # In the intended architecture, only the single
        # InferenceManager worker calls detect().
        #
        # This lock protects the model if another thread
        # accidentally calls detect() directly.
        self._inference_lock = (
            threading.Lock()
        )

        # ==================================================
        # DEVICE
        # ==================================================

        requested_device = (
            str(
                device
            )
            .strip()
            .lower()
        )

        if (
            requested_device
            in {
                "cuda",
                "gpu",
            }
            and torch.cuda.is_available()
        ):
            self.device = "cuda"

        else:
            if (
                requested_device
                in {
                    "cuda",
                    "gpu",
                }
            ):
                self._log(
                    "warning",
                    "CUDA requested but unavailable. "
                    "Falling back to CPU.",
                )

            self.device = "cpu"

        # --------------------------------------------------
        # FP16 / Quantization
        # --------------------------------------------------
        #
        # Keep the existing "half" configuration parameter
        # for compatibility with config.yaml.
        #
        # We do NOT pass half= to Ultralytics predict().
        #
        # When CUDA is available and half=True, the newer
        # quantize="fp16" argument is used instead.
        #
        # CPU inference remains full precision.
        # --------------------------------------------------

        self.half = bool(
            half
            and self.device == "cuda"
        )

        # ==================================================
        # MODEL INITIALIZATION
        # ==================================================

        self._validate_model_file()

        self._log(
            "info",
            "Loading YOLO model: "
            f"{self.model_path}",
        )

        self._load_model()

        self._fuse_model()

        self._warm_up_model()

        self._log(
            "info",
            "YOLO model ready. "
            f"Device: {self.device}, "
            f"imgsz: {self.image_size}, "
            f"fp16: {self.half}",
        )

    # ======================================================
    # BUILD PREDICTION ARGUMENTS
    # ======================================================

    def _get_precision_kwargs(
        self,
    ):
        """
        Return optional Ultralytics precision arguments.

        Current behavior:

        CUDA + half=True:
            quantize="fp16"

        CPU:
            no quantization argument

        Keeping this logic in one method ensures that normal
        inference and warm-up use identical precision settings.
        """

        if (
            self.half
            and self.device == "cuda"
        ):
            return {
                "quantize": "fp16",
            }

        return {}

    # ======================================================
    # DETECT
    # ======================================================

    def detect(
        self,
        frame,
    ):
        """
        Run YOLO inference on one frame.

        Returns
        -------
        list
            List of detection dictionaries.
        """

        if frame is None:
            return []

        # --------------------------------------------------
        # Shared detector safety
        # --------------------------------------------------

        with self._inference_lock:
            self.frame_index += 1

            frame_index = (
                self.frame_index
            )

            timestamp = (
                time.time()
            )

            # ----------------------------------------------
            # Precision configuration
            # ----------------------------------------------

            predict_kwargs = (
                self._get_precision_kwargs()
            )

            # ----------------------------------------------
            # YOLO INFERENCE (timed)
            # ----------------------------------------------

            start = time.perf_counter()

            with torch.inference_mode():
                results = (
                    self.model.predict(
                        source=frame,
                        conf=self.confidence,
                        iou=self.iou,
                        imgsz=
                            self.image_size,
                        max_det=
                            self.max_detections,
                        device=
                            self.device,
                        verbose=False,
                        stream=False,
                        **predict_kwargs,
                    )
                )

            elapsed = time.perf_counter() - start

            if elapsed > 1:
                self._log(
                    "warning",
                    f"Inference time {elapsed:.2f}s",
                )

        # ==================================================
        # BUILD DETECTIONS
        # ==================================================

        detections = []

        for result in results:
            if result.boxes is None:
                continue

            for box in result.boxes:
                x1, y1, x2, y2 = map(
                    int,
                    box.xyxy[
                        0
                    ].tolist(),
                )

                class_id = int(
                    box.cls[
                        0
                    ]
                )

                confidence = float(
                    box.conf[
                        0
                    ]
                )

                detection = (
                    self._build_detection(
                        bbox=(
                            x1,
                            y1,
                            x2,
                            y2,
                        ),
                        confidence=
                            confidence,
                        class_id=
                            class_id,
                        frame_index=
                            frame_index,
                        timestamp=
                            timestamp,
                    )
                )

                if (
                    self._passes_detection_filters(
                        detection
                    )
                ):
                    detections.append(
                        detection
                    )

        return detections

    # ======================================================
    # CLASS NAME
    # ======================================================

    def get_class_name(
        self,
        class_id,
    ):
        """
        Return the YOLO class name for a class ID.
        """

        if isinstance(
            self.model.names,
            dict,
        ):
            return (
                self.model.names.get(
                    class_id,
                    str(
                        class_id
                    ),
                )
            )

        if (
            0
            <= class_id
            < len(
                self.model.names
            )
        ):
            return (
                self.model.names[
                    class_id
                ]
            )

        return str(
            class_id
        )

    # ======================================================
    # CLASS CONFIDENCE THRESHOLDS
    # ======================================================

    def _build_class_confidence_thresholds(
        self,
        class_confidence_thresholds,
        bag_confidence,
        print_confidence,
    ):
        """
        Build per-class confidence thresholds.

        Class 0:
            Bag

        Class 1:
            Print
        """

        thresholds = {}

        for (
            class_id,
            threshold,
        ) in (
            class_confidence_thresholds
            or {}
        ).items():
            thresholds[
                int(
                    class_id
                )
            ] = float(
                threshold
            )

        if bag_confidence is not None:
            thresholds[
                0
            ] = float(
                bag_confidence
            )

        if print_confidence is not None:
            thresholds[
                1
            ] = float(
                print_confidence
            )

        return thresholds

    # ======================================================
    # BUILD DETECTION
    # ======================================================

    def _build_detection(
        self,
        bbox,
        confidence,
        class_id,
        frame_index,
        timestamp,
    ):
        """
        Convert a raw YOLO box into the FillPac AI
        detection dictionary format.
        """

        (
            x1,
            y1,
            x2,
            y2,
        ) = bbox

        width = max(
            x2 - x1,
            0,
        )

        height = max(
            y2 - y1,
            0,
        )

        area = (
            width
            * height
        )

        center = (
            (
                x1
                + x2
            )
            // 2,
            (
                y1
                + y2
            )
            // 2,
        )

        return {
            "bbox":
                bbox,

            "center":
                center,

            "width":
                width,

            "height":
                height,

            "area":
                area,

            "confidence":
                confidence,

            "class_id":
                class_id,

            "class_name":
                self.get_class_name(
                    class_id
                ),

            "frame_index":
                frame_index,

            "timestamp":
                timestamp,
        }

    # ======================================================
    # DETECTION FILTERS
    # ======================================================

    def _passes_detection_filters(
        self,
        detection,
    ):
        """
        Apply FillPac-specific detection filtering.
        """

        class_id = (
            detection[
                "class_id"
            ]
        )

        # --------------------------------------------------
        # Allowed classes
        # --------------------------------------------------

        if (
            self.allowed_classes
            is not None
            and class_id
            not in self.allowed_classes
        ):
            return False

        # --------------------------------------------------
        # Per-class confidence
        # --------------------------------------------------

        confidence_threshold = (
            self.class_confidence_thresholds
            .get(
                class_id,
                self.confidence,
            )
        )

        if (
            detection[
                "confidence"
            ]
            < confidence_threshold
        ):
            return False

        # --------------------------------------------------
        # Bag minimum bounding-box area
        #
        # Only Bag class (0) uses the global minimum area.
        #
        # Print detections are normally much smaller and
        # should not be rejected by the bag-area threshold.
        # --------------------------------------------------

        if (
            self.min_bbox_area
            > 0
            and class_id == 0
            and detection[
                "area"
            ]
            < self.min_bbox_area
        ):
            return False

        # --------------------------------------------------
        # Detection ROI
        # --------------------------------------------------

        if (
            self.detection_roi
            and not self._inside_detection_roi(
                detection[
                    "center"
                ]
            )
        ):
            return False

        return True

    # ======================================================
    # DETECTION ROI CHECK
    # ======================================================

    def _inside_detection_roi(
        self,
        center,
    ):
        """
        Check whether a detection center is inside the
        configured detection ROI.
        """

        x, y = center

        x1 = self.detection_roi.get(
            "x1"
        )

        y1 = self.detection_roi.get(
            "y1"
        )

        x2 = self.detection_roi.get(
            "x2"
        )

        y2 = self.detection_roi.get(
            "y2"
        )

        if (
            x1 is not None
            and x < x1
        ):
            return False

        if (
            x2 is not None
            and x > x2
        ):
            return False

        if (
            y1 is not None
            and y < y1
        ):
            return False

        if (
            y2 is not None
            and y > y2
        ):
            return False

        return True

    # ======================================================
    # VALIDATE DETECTION ROI
    # ======================================================

    @staticmethod
    def _validate_detection_roi(
        detection_roi,
    ):
        """
        Validate configured detection ROI coordinates.
        """

        if not detection_roi:
            return detection_roi

        x1 = detection_roi.get(
            "x1"
        )

        y1 = detection_roi.get(
            "y1"
        )

        x2 = detection_roi.get(
            "x2"
        )

        y2 = detection_roi.get(
            "y2"
        )

        if (
            x1 is not None
            and x2 is not None
            and x1 > x2
        ):
            raise ValueError(
                "Invalid detection_roi: "
                f"x1 ({x1}) must be "
                "less than or equal to "
                f"x2 ({x2})."
            )

        if (
            y1 is not None
            and y2 is not None
            and y1 > y2
        ):
            raise ValueError(
                "Invalid detection_roi: "
                f"y1 ({y1}) must be "
                "less than or equal to "
                f"y2 ({y2})."
            )

        return detection_roi

    # ======================================================
    # VALIDATE MODEL FILE
    # ======================================================

    def _validate_model_file(
        self,
    ):
        """
        Validate YOLO model checkpoint.
        """

        if not self.model_path.exists():
            raise FileNotFoundError(
                "YOLO model file "
                "not found: "
                f"{self.model_path}"
            )

        if (
            self.model_path.stat()
            .st_size
            == 0
        ):
            raise ValueError(
                "YOLO model file "
                "is empty: "
                f"{self.model_path}. "
                "Replace it with a "
                "valid trained checkpoint."
            )

    # ======================================================
    # LOAD MODEL
    # ======================================================

    def _load_model(
        self,
    ):
        """
        Load the YOLO model.

        If CUDA loading fails, automatically fall back
        to CPU inference.
        """

        try:
            self.model = YOLO(
                str(
                    self.model_path
                )
            )

            self.model.to(
                self.device
            )

        except Exception as exc:
            if (
                self.device
                == "cuda"
            ):
                self._log(
                    "warning",
                    "Failed to load model "
                    "on CUDA: "
                    f"{exc}. "
                    "Falling back to CPU.",
                )

                self.device = "cpu"

                self.half = False

                self.model = YOLO(
                    str(
                        self.model_path
                    )
                )

                self.model.to(
                    self.device
                )

            else:
                raise

    # ======================================================
    # FUSE MODEL
    # ======================================================

    def _fuse_model(
        self,
    ):
        """
        Fuse compatible model layers when supported.
        """

        try:
            self.model.fuse()

        except Exception as exc:
            self._log(
                "warning",
                "Could not fuse "
                "YOLO model layers: "
                f"{exc}",
            )

    # ======================================================
    # WARM UP MODEL
    # ======================================================

    def _warm_up_model(
        self,
    ):
        """
        Run one dummy inference before processing camera frames.

        This helps initialize the model and CUDA kernels before
        production frames arrive.
        """

        dummy = np.zeros(
            (
                self.image_size,
                self.image_size,
                3,
            ),
            dtype=np.uint8,
        )

        predict_kwargs = (
            self._get_precision_kwargs()
        )

        try:
            with torch.inference_mode():
                self.model.predict(
                    source=dummy,
                    imgsz=
                        self.image_size,
                    device=
                        self.device,
                    verbose=False,
                    **predict_kwargs,
                )

        except Exception as exc:
            self._log(
                "warning",
                "Could not warm up "
                "YOLO model: "
                f"{exc}",
            )

    # ======================================================
    # LOGGER
    # ======================================================

    def _log(
        self,
        level,
        message,
    ):
        """
        Write detector log message.
        """

        if self.logger is not None:
            log_method = getattr(
                self.logger,
                level,
                None,
            )

            if log_method:
                log_method(
                    message
                )

            return

        print(
            f"[{level.upper()}] "
            f"{message}"
        )