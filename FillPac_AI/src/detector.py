"""
==========================================================
FillPac AI
YOLO Detector
==========================================================
"""

from pathlib import Path
import time

import numpy as np
import torch
from ultralytics import YOLO


class Detector:
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
        self.model_path = Path(model_path)
        self.confidence = float(confidence)
        self.iou = iou
        self.image_size = image_size
        self.max_detections = max_detections
        self.allowed_classes = (
            {int(class_id) for class_id in allowed_classes}
            if allowed_classes is not None
            else None
        )
        self.min_bbox_area = max(float(min_bbox_area), 0.0)
        self.class_confidence_thresholds = self._build_class_confidence_thresholds(
            class_confidence_thresholds=class_confidence_thresholds,
            bag_confidence=bag_confidence,
            print_confidence=print_confidence,
        )
        self.detection_roi = self._validate_detection_roi(detection_roi)
        self.frame_index = 0
        self.logger = logger

        requested_device = str(device).strip().lower()
        if requested_device in {"cuda", "gpu"} and torch.cuda.is_available():
            self.device = "cuda"
        else:
            if requested_device in {"cuda", "gpu"}:
                self._log(
                    "warning",
                    "CUDA requested but unavailable, falling back to CPU.",
                )
            self.device = "cpu"

        self.half = bool(half and self.device == "cuda")

        self._validate_model_file()
        self._log("info", f"Loading YOLO model: {self.model_path}")
        self._load_model()
        self._fuse_model()
        self._warm_up_model()
        self._log(
            "info",
            f"Using device: {self.device}, imgsz: {self.image_size}, half: {self.half}",
        )

    def detect(self, frame):
        self.frame_index += 1
        timestamp = time.time()

        predict_kwargs = {"quantize": "fp16"} if self.half else {}
        with torch.inference_mode():
            results = self.model.predict(
                source=frame,
                conf=self.confidence,
                iou=self.iou,
                imgsz=self.image_size,
                max_det=self.max_detections,
                device=self.device,
                verbose=False,
                **predict_kwargs,
            )

        detections = []

        for result in results:
            if result.boxes is None:
                continue

            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                class_id = int(box.cls[0])
                confidence = float(box.conf[0])
                detection = self._build_detection(
                    bbox=(x1, y1, x2, y2),
                    confidence=confidence,
                    class_id=class_id,
                    frame_index=self.frame_index,
                    timestamp=timestamp,
                )

                if self._passes_detection_filters(detection):
                    detections.append(detection)

        return detections

    def get_class_name(self, class_id):
        if isinstance(self.model.names, dict):
            return self.model.names.get(class_id, str(class_id))

        if 0 <= class_id < len(self.model.names):
            return self.model.names[class_id]

        return str(class_id)

    def _build_class_confidence_thresholds(
        self,
        class_confidence_thresholds,
        bag_confidence,
        print_confidence,
    ):
        thresholds = {}
        for class_id, threshold in (class_confidence_thresholds or {}).items():
            thresholds[int(class_id)] = float(threshold)

        if bag_confidence is not None:
            thresholds[0] = float(bag_confidence)

        if print_confidence is not None:
            thresholds[1] = float(print_confidence)

        return thresholds

    def _build_detection(self, bbox, confidence, class_id, frame_index, timestamp):
        x1, y1, x2, y2 = bbox
        width = max(x2 - x1, 0)
        height = max(y2 - y1, 0)
        area = width * height
        center = ((x1 + x2) // 2, (y1 + y2) // 2)

        return {
            "bbox": bbox,
            "center": center,
            "width": width,
            "height": height,
            "area": area,
            "confidence": confidence,
            "class_id": class_id,
            "class_name": self.get_class_name(class_id),
            "frame_index": frame_index,
            "timestamp": timestamp,
        }

    def _passes_detection_filters(self, detection):
        class_id = detection["class_id"]
        if self.allowed_classes is not None and class_id not in self.allowed_classes:
            return False

        confidence_threshold = self.class_confidence_thresholds.get(
            class_id,
            self.confidence,
        )
        if detection["confidence"] < confidence_threshold:
            return False

        if detection["area"] < self.min_bbox_area:
            return False

        if self.detection_roi and not self._inside_detection_roi(detection["center"]):
            return False

        return True

    def _inside_detection_roi(self, center):
        x, y = center
        x1 = self.detection_roi.get("x1")
        y1 = self.detection_roi.get("y1")
        x2 = self.detection_roi.get("x2")
        y2 = self.detection_roi.get("y2")

        if x1 is not None and x < x1:
            return False
        if x2 is not None and x > x2:
            return False
        if y1 is not None and y < y1:
            return False
        if y2 is not None and y > y2:
            return False

        return True

    def _validate_detection_roi(self, detection_roi):
        if not detection_roi:
            return detection_roi

        x1 = detection_roi.get("x1")
        y1 = detection_roi.get("y1")
        x2 = detection_roi.get("x2")
        y2 = detection_roi.get("y2")

        if x1 is not None and x2 is not None and x1 > x2:
            raise ValueError(
                f"Invalid detection_roi: x1 ({x1}) must be less than or equal to x2 ({x2})."
            )

        if y1 is not None and y2 is not None and y1 > y2:
            raise ValueError(
                f"Invalid detection_roi: y1 ({y1}) must be less than or equal to y2 ({y2})."
            )

        return detection_roi

    def _validate_model_file(self):
        if not self.model_path.exists():
            raise FileNotFoundError(f"YOLO model file not found: {self.model_path}")

        if self.model_path.stat().st_size == 0:
            raise ValueError(
                f"YOLO model file is empty: {self.model_path}. "
                "Replace it with a valid trained checkpoint before running the app."
            )

    def _load_model(self):
        try:
            self.model = YOLO(str(self.model_path))
            self.model.to(self.device)
        except Exception as exc:
            if self.device == "cuda":
                self._log(
                    "warning",
                    f"Failed to load model on CUDA: {exc}. Falling back to CPU.",
                )
                self.device = "cpu"
                self.half = False
                self.model = YOLO(str(self.model_path))
                self.model.to(self.device)
            else:
                raise

    def _fuse_model(self):
        try:
            self.model.fuse()
        except Exception as exc:
            self._log("warning", f"Could not fuse YOLO model layers: {exc}")

    def _warm_up_model(self):
        dummy = np.zeros(
            (self.image_size, self.image_size, 3),
            dtype=np.uint8,
        )

        predict_kwargs = {"quantize": "fp16"} if self.half else {}
        try:
            with torch.inference_mode():
                self.model.predict(
                    source=dummy,
                    imgsz=self.image_size,
                    device=self.device,
                    verbose=False,
                    **predict_kwargs,
                )
        except Exception as exc:
            self._log("warning", f"Could not warm up YOLO model: {exc}")

    def _log(self, level, message):
        if self.logger is not None:
            getattr(self.logger, level)(message)
            return

        print(f"[{level.upper()}] {message}")