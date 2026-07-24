"""
==========================================================
FillPac AI
Configuration Loader
==========================================================

Purpose
-------
Loads config.yaml and normalizes configuration for:

- Model
- Tracker
- Physical-center counting
- Print detection
- Bag jam detection
- Display
- Cameras

Jam Detection
-------------
Each camera receives its own jam_detection configuration.

Global jam_detection values act as defaults.

Camera-specific values override the global defaults.

Example:

jam_detection:
    enabled: true
    history_seconds: 1.0
    ...

camera:
    jam_detection:
        enabled: true
        roi:
            x1: 0
            y1: 150
            x2: 477
            y2: 500

The final camera configuration contains the merged values.
==========================================================
"""

import os

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class Config:

    # ======================================================
    # INITIALIZATION
    # ======================================================

    def __init__(
        self,
        config_path: str | None = None,
    ):

        config_path = (
            config_path
            or os.getenv(
                "FILLPAC_CONFIG_PATH"
            )
            or "config.yaml"
        )

        self.config_path = Path(
            config_path
        )

        if not self.config_path.exists():

            raise FileNotFoundError(
                "Configuration file not found: "
                f"{self.config_path}"
            )

        self.data = {}

        self._load()

    # ======================================================
    # LOAD
    # ======================================================

    def _load(
        self,
    ) -> None:

        with open(
            self.config_path,
            "r",
            encoding="utf-8",
        ) as fh:

            raw = (
                yaml.safe_load(
                    fh
                )
                or {}
            )

        if not isinstance(
            raw,
            dict,
        ):

            raise ValueError(
                "Root YAML configuration must be "
                "a dictionary/object."
            )

        self.data = (
            self._normalize(
                raw
            )
        )

        self.validate()

    # ======================================================
    # NORMALIZATION
    # ======================================================

    def _normalize(
        self,
        data: dict,
    ) -> dict:

        # --------------------------------------------------
        # GLOBAL DEFAULTS
        # --------------------------------------------------

        global_model = deepcopy(
            data.get(
                "model",
                {},
            )
            or {}
        )

        global_counting = deepcopy(
            data.get(
                "counting",
                {},
            )
            or {}
        )

        global_print = deepcopy(
            data.get(
                "print_detection",
                {},
            )
            or {}
        )

        global_jam = deepcopy(
            data.get(
                "jam_detection",
                {},
            )
            or {}
        )

        global_display = deepcopy(
            data.get(
                "display",
                {},
            )
            or {}
        )

        result = deepcopy(
            data
        )

        # --------------------------------------------------
        # CAMERAS
        # --------------------------------------------------

        raw_cameras = (
            data.get(
                "cameras",
                [],
            )
            or []
        )

        if not isinstance(
            raw_cameras,
            list,
        ):

            raise ValueError(
                "'cameras' must be a list"
            )

        cameras = []

        for cam in raw_cameras:

            if not isinstance(
                cam,
                dict,
            ):

                raise ValueError(
                    "Each camera configuration "
                    "must be a dictionary."
                )

            camera = deepcopy(
                cam
            )

            # ==============================================
            # MODEL
            # ==============================================

            camera[
                "model"
            ] = self._merge_dicts(
                global_model,
                camera.get(
                    "model",
                    {},
                ),
            )

            # ==============================================
            # COUNTING
            # ==============================================

            camera[
                "counting"
            ] = self._merge_dicts(
                global_counting,
                camera.get(
                    "counting",
                    {},
                ),
            )

            # ==============================================
            # PRINT DETECTION
            # ==============================================

            pd = camera.get(
                "print_detection",
                global_print,
            )

            # Support:
            #
            # print_detection: true
            #
            # or
            #
            # print_detection:
            #     enabled: true

            if isinstance(
                pd,
                bool,
            ):

                pd = {
                    "enabled":
                        pd,

                    "confidence":
                        global_print.get(
                            "confidence",
                            0.25,
                        ),
                }

            elif not isinstance(
                pd,
                dict,
            ):

                pd = {}

            camera[
                "print_detection"
            ] = self._merge_dicts(
                global_print,
                pd,
            )

            # ==============================================
            # JAM DETECTION
            # ==============================================

            jd = camera.get(
                "jam_detection",
                global_jam,
            )

            # Support:
            #
            # jam_detection: true
            #
            # or:
            #
            # jam_detection:
            #     enabled: true

            if isinstance(
                jd,
                bool,
            ):

                jd = {
                    "enabled":
                        jd
                }

            elif not isinstance(
                jd,
                dict,
            ):

                jd = {}

            camera_jam = (
                self._merge_dicts(
                    global_jam,
                    jd,
                )
            )

            # ----------------------------------------------
            # JAM ROI
            #
            # Important:
            # _merge_dicts is shallow.
            #
            # Therefore normalize ROI separately.
            # ----------------------------------------------

            global_jam_roi = (
                global_jam.get(
                    "roi",
                    {},
                )
                or {}
            )

            camera_jam_roi = (
                jd.get(
                    "roi",
                    {},
                )
                or {}
            )

            merged_jam_roi = (
                self._merge_dicts(
                    global_jam_roi,
                    camera_jam_roi,
                )
            )

            camera_jam[
                "roi"
            ] = self._normalize_roi(
                merged_jam_roi
            )

            camera[
                "jam_detection"
            ] = camera_jam

            # ==============================================
            # DISPLAY
            # ==============================================

            camera[
                "display"
            ] = self._merge_dicts(
                global_display,
                camera.get(
                    "display",
                    {},
                ),
            )

            # ==============================================
            # COUNTING ROI
            # ==============================================

            camera[
                "roi"
            ] = self._normalize_roi(
                camera.get(
                    "roi",
                    {},
                )
            )

            # ==============================================
            # RUNTIME DEFAULTS
            # ==============================================

            camera.setdefault(
                "buffer_size",
                1,
            )

            camera.setdefault(
                "queue_size",
                3,
            )

            camera.setdefault(
                "read_timeout",
                0.2,
            )

            camera.setdefault(
                "inference_timeout",
                5.0,
            )

            camera.setdefault(
                "dashboard_publish_interval",
                0.5,
            )

            camera.setdefault(
                "enabled",
                True,
            )

            camera.setdefault(
                "mode",
                "video",
            )

            cameras.append(
                camera
            )

        result[
            "cameras"
        ] = cameras

        return result

    # ======================================================
    # ROI NORMALIZATION
    # ======================================================

    @staticmethod
    def _normalize_roi(
        roi,
    ) -> dict:

        if not isinstance(
            roi,
            dict,
        ):

            roi = {}

        return {

            "x1":
                Config._safe_int(
                    roi.get(
                        "x1",
                        0,
                    )
                ),

            "y1":
                Config._safe_int(
                    roi.get(
                        "y1",
                        0,
                    )
                ),

            "x2":
                Config._safe_int(
                    roi.get(
                        "x2",
                        0,
                    )
                ),

            "y2":
                Config._safe_int(
                    roi.get(
                        "y2",
                        0,
                    )
                ),
        }

    # ======================================================
    # DICTIONARY MERGE
    # ======================================================

    @staticmethod
    def _merge_dicts(
        base: dict,
        override: dict,
    ) -> dict:

        if not isinstance(
            base,
            dict,
        ):

            base = {}

        if not isinstance(
            override,
            dict,
        ):

            override = {}

        out = deepcopy(
            base
        )

        out.update(
            deepcopy(
                override
            )
        )

        return out

    # ======================================================
    # SAFE INTEGER
    # ======================================================

    @staticmethod
    def _safe_int(
        value,
        default=0,
    ) -> int:

        try:

            return int(
                value
            )

        except (
            TypeError,
            ValueError,
            OverflowError,
        ):

            return int(
                default
            )

    # ======================================================
    # GET
    # ======================================================

    def get(
        self,
        *keys: str,
        default: Any = None,
    ) -> Any:

        node = self.data

        try:

            for key in keys:

                node = node[
                    key
                ]

            return node

        except (
            KeyError,
            TypeError,
            IndexError,
        ):

            return default

    # ======================================================
    # ITEM ACCESS
    # ======================================================

    def __getitem__(
        self,
        key: str,
    ) -> Any:

        return self.data[
            key
        ]

    # ======================================================
    # CONTAINS
    # ======================================================

    def __contains__(
        self,
        key: str,
    ) -> bool:

        return key in self.data

    # ======================================================
    # RELOAD
    # ======================================================

    def reload(
        self,
    ) -> None:

        self._load()

    # ======================================================
    # VALIDATION
    # ======================================================

    def validate(
        self,
    ) -> None:

        # --------------------------------------------------
        # CAMERAS
        # --------------------------------------------------

        cameras = self.data.get(
            "cameras",
            [],
        )

        if not isinstance(
            cameras,
            list,
        ):

            raise ValueError(
                "'cameras' must be a list"
            )

        camera_ids = set()

        camera_names = set()

        for index, camera in enumerate(
            cameras
        ):

            if not isinstance(
                camera,
                dict,
            ):

                raise ValueError(
                    f"Camera #{index + 1} must "
                    "be a dictionary."
                )

            # ==============================================
            # CAMERA ID
            # ==============================================

            camera_id = camera.get(
                "id"
            )

            if camera_id is not None:

                if camera_id in camera_ids:

                    raise ValueError(
                        "Duplicate camera ID: "
                        f"{camera_id}"
                    )

                camera_ids.add(
                    camera_id
                )

            # ==============================================
            # CAMERA NAME
            # ==============================================

            camera_name = camera.get(
                "name"
            )

            if not camera_name:

                raise ValueError(
                    f"Camera #{index + 1} "
                    "is missing 'name'."
                )

            if camera_name in camera_names:

                raise ValueError(
                    "Duplicate camera name: "
                    f"{camera_name}"
                )

            camera_names.add(
                camera_name
            )

            # ==============================================
            # COUNTING ROI
            # ==============================================

            roi = camera.get(
                "roi",
                {},
            )

            if not isinstance(
                roi,
                dict,
            ):

                raise ValueError(
                    f"{camera_name}: "
                    "counting ROI must be "
                    "a dictionary."
                )

            # ==============================================
            # JAM DETECTION
            # ==============================================

            jam = camera.get(
                "jam_detection",
                {},
            )

            if not isinstance(
                jam,
                dict,
            ):

                raise ValueError(
                    f"{camera_name}: "
                    "jam_detection must be "
                    "a dictionary."
                )

            jam_enabled = bool(
                jam.get(
                    "enabled",
                    False,
                )
            )

            if jam_enabled:

                self._validate_jam_config(
                    camera_name,
                    jam,
                )

    # ======================================================
    # JAM VALIDATION
    # ======================================================

    @staticmethod
    def _validate_jam_config(
        camera_name,
        jam,
    ) -> None:

        # --------------------------------------------------
        # TIMING
        # --------------------------------------------------

        try:

            history_seconds = float(
                jam.get(
                    "history_seconds",
                    1.0,
                )
            )

            min_history_seconds = float(
                jam.get(
                    "min_history_seconds",
                    0.5,
                )
            )

            warning_time = float(
                jam.get(
                    "warning_time_seconds",
                    2.0,
                )
            )

            jam_time = float(
                jam.get(
                    "jam_time_seconds",
                    5.0,
                )
            )

            recovery_time = float(
                jam.get(
                    "recovery_time_seconds",
                    1.0,
                )
            )

        except (
            TypeError,
            ValueError,
        ) as error:

            raise ValueError(
                f"{camera_name}: invalid "
                "jam timing configuration."
            ) from error

        if history_seconds <= 0:

            raise ValueError(
                f"{camera_name}: "
                "jam history_seconds must "
                "be > 0."
            )

        if min_history_seconds <= 0:

            raise ValueError(
                f"{camera_name}: "
                "min_history_seconds must "
                "be > 0."
            )

        if (
            min_history_seconds
            >
            history_seconds
        ):

            raise ValueError(
                f"{camera_name}: "
                "min_history_seconds cannot "
                "exceed history_seconds."
            )

        if warning_time < 0:

            raise ValueError(
                f"{camera_name}: "
                "warning_time_seconds cannot "
                "be negative."
            )

        if jam_time < warning_time:

            raise ValueError(
                f"{camera_name}: "
                "jam_time_seconds must be >= "
                "warning_time_seconds."
            )

        if recovery_time < 0:

            raise ValueError(
                f"{camera_name}: "
                "recovery_time_seconds cannot "
                "be negative."
            )

        # --------------------------------------------------
        # SPEED
        # --------------------------------------------------

        try:

            stationary_speed = float(
                jam.get(
                    "stationary_speed_threshold",
                    10.0,
                )
            )

            slow_speed = float(
                jam.get(
                    "slow_speed_threshold",
                    30.0,
                )
            )

        except (
            TypeError,
            ValueError,
        ) as error:

            raise ValueError(
                f"{camera_name}: invalid "
                "jam speed thresholds."
            ) from error

        if stationary_speed < 0:

            raise ValueError(
                f"{camera_name}: "
                "stationary_speed_threshold "
                "cannot be negative."
            )

        if slow_speed < stationary_speed:

            raise ValueError(
                f"{camera_name}: "
                "slow_speed_threshold must be "
                ">= stationary_speed_threshold."
            )

        # --------------------------------------------------
        # JAM ROI
        # --------------------------------------------------

        roi = jam.get(
            "roi",
            {},
        )

        if not isinstance(
            roi,
            dict,
        ):

            raise ValueError(
                f"{camera_name}: "
                "jam ROI must be a dictionary."
            )

        x1 = Config._safe_int(
            roi.get(
                "x1",
                0,
            )
        )

        y1 = Config._safe_int(
            roi.get(
                "y1",
                0,
            )
        )

        x2 = Config._safe_int(
            roi.get(
                "x2",
                0,
            )
        )

        y2 = Config._safe_int(
            roi.get(
                "y2",
                0,
            )
        )

        if x1 == x2:

            raise ValueError(
                f"{camera_name}: "
                "jam ROI width cannot be zero."
            )

        if y1 == y2:

            raise ValueError(
                f"{camera_name}: "
                "jam ROI height cannot be zero."
            )

        # --------------------------------------------------
        # TRACK AGE
        # --------------------------------------------------

        try:

            min_track_age = int(
                jam.get(
                    "min_track_age",
                    4,
                )
            )

        except (
            TypeError,
            ValueError,
        ) as error:

            raise ValueError(
                f"{camera_name}: invalid "
                "jam min_track_age."
            ) from error

        if min_track_age < 1:

            raise ValueError(
                f"{camera_name}: "
                "jam min_track_age must "
                "be >= 1."
            )

        # --------------------------------------------------
        # TRACK TTL
        # --------------------------------------------------

        try:

            ttl = float(
                jam.get(
                    "track_ttl_seconds",
                    2.0,
                )
            )

        except (
            TypeError,
            ValueError,
        ) as error:

            raise ValueError(
                f"{camera_name}: invalid "
                "track_ttl_seconds."
            ) from error

        if ttl <= 0:

            raise ValueError(
                f"{camera_name}: "
                "track_ttl_seconds must "
                "be > 0."
            )