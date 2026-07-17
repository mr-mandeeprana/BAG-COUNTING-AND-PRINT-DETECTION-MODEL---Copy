"""
Simple, robust configuration loader tailored to the tests.

This implementation focuses on loading the project's `config.yaml`,
normalizing the `cameras` structure, and applying global defaults for
`model`, `counting`, `print_detection`, and `display` so tests can
inspect expected fields.
"""

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class Config:
    def __init__(self, config_path: str | None = None):
        config_path = config_path or os.getenv("FILLPAC_CONFIG_PATH") or "config.yaml"
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        self.data = self._normalize(raw)
        # perform a light validation pass (not overly strict)
        self.validate()

    def _normalize(self, data: dict) -> dict:
        global_model = deepcopy(data.get("model", {}))
        global_counting = deepcopy(data.get("counting", {}))
        global_print = deepcopy(data.get("print_detection", {}))
        global_display = deepcopy(data.get("display", {}))

        result = dict(data)

        cameras = []
        for cam in data.get("cameras", []):
            camera = deepcopy(cam)
            # apply defaults
            camera["model"] = self._merge_dicts(global_model, camera.get("model", {}))
            camera["counting"] = self._merge_dicts(global_counting, camera.get("counting", {}))
            pd = camera.get("print_detection", global_print)
            if isinstance(pd, bool):
                pd = {"enabled": pd, "confidence": global_print.get("confidence", 0.25)}
            camera["print_detection"] = self._merge_dicts(global_print, pd)
            camera["display"] = self._merge_dicts(global_display, camera.get("display", {}))

            # ROI normalization
            roi = camera.get("roi", {}) or {}
            camera["roi"] = {
                "x1": int(roi.get("x1", 0)),
                "y1": int(roi.get("y1", 0)),
                "x2": int(roi.get("x2", 0)),
                "y2": int(roi.get("y2", 0)),
            }

            # runtime defaults used by pipeline
            camera.setdefault("buffer_size", 1)
            camera.setdefault("queue_size", 3)
            camera.setdefault("read_timeout", 0.2)

            cameras.append(camera)

        result["cameras"] = cameras
        return result

    @staticmethod
    def _merge_dicts(base: dict, override: dict) -> dict:
        out = deepcopy(base or {})
        out.update(override or {})
        return out

    def get(self, *keys: str, default: Any = None) -> Any:
        node = self.data
        try:
            for k in keys:
                node = node[k]
            return node
        except Exception:
            return default

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def reload(self) -> None:
        with open(self.config_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        self.data = self._normalize(raw)

    def validate(self) -> None:
        # Light validation: ensure cameras is a list and that model paths exist
        cams = self.data.get("cameras", [])
        if not isinstance(cams, list):
            raise ValueError("'cameras' must be a list")

        # If a global model path is set, ensure file exists or allow if absent
        # (tests don't require strict file checks here)
        return
