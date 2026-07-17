"""
==========================================================
FillPac AI
Configuration Manager
==========================================================
"""

from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

import yaml


class Config:
    """Loads and provides access to configuration values."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)

        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_path}"
            )

        self.data = self._load()
        self.validate()

    def _load(self) -> dict:
        with open(self.config_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}

        return self._normalize(data)

    def _normalize(self, data: dict) -> dict:
        """Normalize legacy `camera1` config into `cameras` list format."""

        global_model = deepcopy(data.get("model", {}))
        global_counting = deepcopy(data.get("counting", {}))
        global_print_detection = deepcopy(data.get("print_detection", {}))
        global_display = deepcopy(data.get("display", {}))

        if "cameras" in data:
            normalized = dict(data)
            normalized["cameras"] = [
                self._normalize_camera(
                    camera,
                    global_model,
                    global_counting,
                    global_print_detection,
                    global_display,
                )
                for camera in data.get("cameras", [])
            ]
            return normalized

        cameras = []

        for key in sorted(data):
            if not key.startswith("camera"):
                continue

            camera_data = dict(data[key] or {})
            camera_id = key.removeprefix("camera")
            camera_data.setdefault(
                "id",
                int(camera_id) if camera_id.isdigit() else camera_id,
            )
            camera_data.setdefault("name", f"Camera {camera_id}")
            camera_data.setdefault("enabled", True)

            cameras.append(
                self._normalize_camera(
                    camera_data,
                    global_model,
                    global_counting,
                    global_print_detection,
                    global_display,
                )
            )

        normalized = dict(data)
        normalized["cameras"] = cameras
        return normalized

    def _normalize_camera(
        self,
        camera_data,
        global_model,
        global_counting,
        global_print_detection,
        global_display,
    ):
        camera = deepcopy(camera_data or {})
        roi = camera.get("roi", {})

        camera["roi"] = {
            "x1": self._to_int(roi.get("x1", 0), "roi.x1"),
            "y1": self._to_int(roi.get("y1", 0), "roi.y1"),
            "x2": self._to_int(roi.get("x2", 0), "roi.x2"),
            "y2": self._to_int(roi.get("y2", 0), "roi.y2"),
        }
        camera["model"] = self._merge_dicts(global_model, camera.get("model", {}))
        camera["counting"] = self._merge_dicts(
            global_counting,
            camera.get("counting", {}),
        )
        camera["display"] = self._merge_dicts(global_display, camera.get("display", {}))

        print_detection = camera.get("print_detection", global_print_detection)
        if isinstance(print_detection, bool):
            print_detection = {
                "enabled": print_detection,
                "confidence": global_print_detection.get("confidence", 0.4),
            }

        camera["print_detection"] = self._merge_dicts(
            global_print_detection,
            print_detection,
        )

        return camera

    @staticmethod
    def _merge_dicts(base, override):
        merged = deepcopy(base or {})
        merged.update(override or {})
        return merged

    def get(self, *keys, default=None):
        value = self.data

        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default

    def __getitem__(self, item):
        return self.data[item]

    def reload(self):
        self.data = self._load()
        self.validate()

    def validate(self):
        cameras = self.get("cameras", default=[])

        if not isinstance(cameras, list) or not cameras:
            raise ValueError("Configuration must define at least one camera in 'cameras'.")

        if not self.get("model", "path") and not all(
            camera.get("model", {}).get("path") for camera in cameras
        ):
            raise ValueError("Configuration must define 'model.path' or per-camera 'model.path'.")

        self._validate_model_config(self.get("model", default={}), "model")
        self._validate_counting_config(self.get("counting", default={}), "counting")
        self._validate_tracker_config(self.get("tracker", default={}), "tracker")
        self._validate_print_detection_config(
            self.get("print_detection", default={}),
            "print_detection",
        )

        camera_ids = set()
        camera_names = set()

        for camera in cameras:
            missing = [key for key in ("name", "source", "mode", "roi") if key not in camera]
            if missing:
                raise ValueError(
                    f"Camera configuration is missing required keys: {', '.join(missing)}"
                )

            camera_id = camera.get("id")
            camera_name = camera.get("name")
            camera_label = f"camera '{camera_name}'"

            if camera_id in camera_ids:
                raise ValueError(f"Duplicate camera id found: {camera_id}")
            camera_ids.add(camera_id)

            if camera_name in camera_names:
                raise ValueError(f"Duplicate camera name found: {camera_name}")
            camera_names.add(camera_name)

            self._validate_source(camera["source"], camera_label)
            self._validate_roi(camera["roi"], camera_label)
            self._validate_model_config(camera.get("model", {}), f"{camera_label}.model")
            self._validate_counting_config(
                camera.get("counting", {}),
                f"{camera_label}.counting",
            )
            self._validate_print_detection_config(
                camera.get("print_detection", {}),
                f"{camera_label}.print_detection",
            )
            self._validate_positive_int(
                camera.get("buffer_size", 1),
                f"{camera_label}.buffer_size",
            )

    def __str__(self):
        return f"Config({self.config_path})"

    @staticmethod
    def _to_int(value, field_name):
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Configuration value '{field_name}' must be an integer.") from exc

    def _validate_roi(self, roi, context):
        if not isinstance(roi, dict):
            raise ValueError(f"{context}.roi must be a mapping.")

        for key in ("x1", "y1", "x2", "y2"):
            self._validate_int(roi.get(key), f"{context}.roi.{key}", minimum=0)

        if roi["x1"] > roi["x2"]:
            raise ValueError(
                f"{context}.roi is invalid: x1 ({roi['x1']}) must be less "
                f"than or equal to x2 ({roi['x2']})."
            )

        if roi["y1"] > roi["y2"]:
            raise ValueError(
                f"{context}.roi is invalid: y1 ({roi['y1']}) must be less "
                f"than or equal to y2 ({roi['y2']})."
            )

    def _validate_source(self, source, context):
        if isinstance(source, int):
            if source < 0:
                raise ValueError(f"{context}.source camera index must be zero or greater.")
            return

        if not isinstance(source, str) or not source.strip():
            raise ValueError(
                f"{context}.source must be a camera index, video file path, or stream URL."
            )

        source = source.strip()
        if source.isdigit():
            return

        parsed = urlparse(source)
        if parsed.scheme in {"rtsp", "http", "https"} and parsed.netloc:
            return

        if self._resolve_path(source).exists():
            return

        raise ValueError(
            f"{context}.source does not exist and is not a valid stream URL: {source}"
        )

    def _validate_model_config(self, model_config, context):
        if not model_config:
            return

        model_path = model_config.get("path")
        if model_path:
            resolved_path = self._resolve_path(model_path)
            if not resolved_path.exists():
                raise FileNotFoundError(f"{context}.path not found: {model_path}")

        self._validate_probability(model_config.get("confidence"), f"{context}.confidence")
        self._validate_probability(model_config.get("iou"), f"{context}.iou")
        self._validate_probability(
            model_config.get("bag_confidence"),
            f"{context}.bag_confidence",
        )
        self._validate_probability(
            model_config.get("print_confidence"),
            f"{context}.print_confidence",
        )
        self._validate_positive_int(model_config.get("image_size"), f"{context}.image_size")
        self._validate_positive_int(
            model_config.get("max_detections"),
            f"{context}.max_detections",
        )
        self._validate_number(
            model_config.get("min_bbox_area"),
            f"{context}.min_bbox_area",
            minimum=0,
        )

        for class_id, threshold in (
            model_config.get("class_confidence_thresholds") or {}
        ).items():
            self._validate_probability(
                threshold,
                f"{context}.class_confidence_thresholds.{class_id}",
            )

        if model_config.get("detection_roi"):
            roi = {
                key: self._to_int(value, f"{context}.detection_roi.{key}")
                for key, value in model_config["detection_roi"].items()
            }
            self._validate_optional_roi(roi, f"{context}.detection_roi")

    def _validate_counting_config(self, counting_config, context):
        if not counting_config:
            return

        self._validate_number(
            counting_config.get("duplicate_distance"),
            f"{context}.duplicate_distance",
            minimum=0,
            inclusive_min=False,
        )
        self._validate_number(
            counting_config.get("duplicate_time"),
            f"{context}.duplicate_time",
            minimum=0,
        )
        self._validate_number(
            counting_config.get("line_tolerance"),
            f"{context}.line_tolerance",
            minimum=0,
        )
        self._validate_number(
            counting_config.get("late_start_margin"),
            f"{context}.late_start_margin",
            minimum=0,
        )
        self._validate_number(
            counting_config.get("minimum_cross_distance"),
            f"{context}.minimum_cross_distance",
            minimum=0,
        )
        self._validate_positive_int(
            counting_config.get("min_track_frames"),
            f"{context}.min_track_frames",
        )
        self._validate_positive_int(
            counting_config.get("stale_track_frames"),
            f"{context}.stale_track_frames",
        )

    def _validate_tracker_config(self, tracker_config, context):
        if not tracker_config:
            return

        for key in (
            "track_high_thresh",
            "track_low_thresh",
            "new_track_thresh",
            "match_thresh",
            "min_track_confidence",
            "min_iou_warning",
        ):
            self._validate_probability(tracker_config.get(key), f"{context}.{key}")

        for key in (
            "track_buffer",
            "frame_rate",
            "minimum_consecutive_frames",
            "min_track_age",
            "unstable_frame_threshold",
            "history_ttl_frames",
        ):
            self._validate_positive_int(tracker_config.get(key), f"{context}.{key}")

        self._validate_number(
            tracker_config.get("min_bbox_area"),
            f"{context}.min_bbox_area",
            minimum=0,
        )
        self._validate_probability(
            tracker_config.get("min_bbox_area_ratio"),
            f"{context}.min_bbox_area_ratio",
        )
        self._validate_number(
            tracker_config.get("max_jump_distance"),
            f"{context}.max_jump_distance",
            minimum=0,
        )

    def _validate_print_detection_config(self, print_config, context):
        if not print_config:
            return

        for key in ("confidence", "iou_threshold", "min_overlap_ratio", "vote_threshold"):
            self._validate_probability(print_config.get(key), f"{context}.{key}")

        for key in (
            "min_print_area",
            "max_print_area",
            "min_aspect_ratio",
            "max_aspect_ratio",
            "max_center_distance",
            "min_observation_speed",
        ):
            self._validate_number(print_config.get(key), f"{context}.{key}", minimum=0)

        for key in ("min_votes", "history_size", "history_ttl_frames"):
            self._validate_positive_int(print_config.get(key), f"{context}.{key}")

        min_area = print_config.get("min_print_area")
        max_area = print_config.get("max_print_area")
        if max_area and min_area and float(max_area) < float(min_area):
            raise ValueError(f"{context}.max_print_area must be greater than min_print_area.")

        min_ratio = print_config.get("min_aspect_ratio")
        max_ratio = print_config.get("max_aspect_ratio")
        if max_ratio and min_ratio and float(max_ratio) < float(min_ratio):
            raise ValueError(
                f"{context}.max_aspect_ratio must be greater than min_aspect_ratio."
            )

    def _validate_optional_roi(self, roi, context):
        for key in ("x1", "y1", "x2", "y2"):
            if key in roi:
                self._validate_int(roi[key], f"{context}.{key}", minimum=0)

        if "x1" in roi and "x2" in roi and roi["x1"] > roi["x2"]:
            raise ValueError(f"{context}.x1 must be less than or equal to {context}.x2.")

        if "y1" in roi and "y2" in roi and roi["y1"] > roi["y2"]:
            raise ValueError(f"{context}.y1 must be less than or equal to {context}.y2.")

    def _validate_probability(self, value, field_name):
        self._validate_number(value, field_name, minimum=0, maximum=1)

    def _validate_positive_int(self, value, field_name):
        self._validate_int(value, field_name, minimum=0, inclusive_min=False)

    @staticmethod
    def _validate_int(value, field_name, minimum=None, inclusive_min=True):
        if value is None:
            return

        try:
            int_value = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Configuration value '{field_name}' must be an integer.") from exc

        if int_value != value and not (isinstance(value, str) and str(int_value) == value):
            raise ValueError(f"Configuration value '{field_name}' must be an integer.")

        Config._validate_minimum(int_value, field_name, minimum, inclusive_min)

    @staticmethod
    def _validate_number(
        value,
        field_name,
        minimum=None,
        maximum=None,
        inclusive_min=True,
        inclusive_max=True,
    ):
        if value is None:
            return

        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Configuration value '{field_name}' must be numeric.") from exc

        Config._validate_minimum(number, field_name, minimum, inclusive_min)

        if maximum is None:
            return

        if inclusive_max and number > maximum:
            raise ValueError(f"Configuration value '{field_name}' must be <= {maximum}.")

        if not inclusive_max and number >= maximum:
            raise ValueError(f"Configuration value '{field_name}' must be < {maximum}.")

    @staticmethod
    def _validate_minimum(value, field_name, minimum, inclusive_min):
        if minimum is None:
            return

        if inclusive_min and value < minimum:
            raise ValueError(f"Configuration value '{field_name}' must be >= {minimum}.")

        if not inclusive_min and value <= minimum:
            raise ValueError(f"Configuration value '{field_name}' must be > {minimum}.")

    def _resolve_path(self, path):
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate

        return self.config_path.parent / candidate
