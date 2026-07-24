"""
==========================================================
FillPac AI
Visualization Module
==========================================================

Visualizes:

- Bag bounding boxes
- Print bounding boxes
- Physical bag centers
- Physical-center counting line
- Count flash
- Print status
- FPS
- Bag totals

Jam Detection V1:
- Jam monitoring ROI
- Track ID
- Motion speed in pixels/second
- Stationary duration
- Per-track jam state
- Camera-level jam status

Jam States:
    NORMAL
    SLOW
    WARNING
    JAM
    RECOVERING
==========================================================
"""

import cv2
import time


class Visualizer:

    def __init__(self):

        self.count_flash_until = {}
        self.count_flash_seconds = 0.7
        self.line_flash_until = 0

    # ======================================================
    # BASIC BOX
    # ======================================================

    @staticmethod
    def draw_box(
        frame,
        bbox,
        color,
        label="",
    ):

        x1, y1, x2, y2 = [
            int(v)
            for v in bbox
        ]

        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            color,
            2,
        )

        if label:

            cv2.putText(
                frame,
                label,
                (
                    x1,
                    max(
                        y1 - 10,
                        20,
                    ),
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )

    # ======================================================
    # COUNT FLASH
    # ======================================================

    @staticmethod
    def draw_count_flash(
        frame,
        bbox,
    ):

        x1, y1, x2, y2 = [
            int(v)
            for v in bbox
        ]

        overlay = frame.copy()

        cv2.rectangle(
            overlay,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            -1,
        )

        cv2.addWeighted(
            overlay,
            0.28,
            frame,
            0.72,
            0,
            frame,
        )

        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            5,
        )

        cv2.putText(
            frame,
            "COUNTED",
            (
                x1,
                max(
                    y1 - 10,
                    25,
                ),
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            3,
        )

    # ======================================================
    # CENTER
    # ======================================================

    @staticmethod
    def draw_center(
        frame,
        center,
    ):

        center = (
            int(center[0]),
            int(center[1]),
        )

        cv2.circle(
            frame,
            center,
            5,
            (0, 0, 255),
            -1,
        )

    # ======================================================
    # COUNTING ROI / LINE
    # ======================================================

    @staticmethod
    def draw_roi_segment(
        frame,
        roi,
        color=(0, 255, 255),
        thickness=2,
    ):

        if not roi:
            return

        height, width = frame.shape[:2]

        x1 = min(
            max(
                int(
                    roi.get(
                        "x1",
                        0,
                    )
                ),
                0,
            ),
            width - 1,
        )

        x2 = min(
            max(
                int(
                    roi.get(
                        "x2",
                        0,
                    )
                ),
                0,
            ),
            width - 1,
        )

        y1 = min(
            max(
                int(
                    roi.get(
                        "y1",
                        0,
                    )
                ),
                0,
            ),
            height - 1,
        )

        y2 = min(
            max(
                int(
                    roi.get(
                        "y2",
                        0,
                    )
                ),
                0,
            ),
            height - 1,
        )

        cv2.line(
            frame,
            (x1, y1),
            (x2, y2),
            color,
            thickness,
        )

    # ======================================================
    # JAM ROI
    # ======================================================

    @staticmethod
    def draw_jam_roi(
        frame,
        roi,
        status="normal",
    ):

        if not roi:
            return

        try:

            x1 = int(
                roi.get(
                    "x1",
                    0,
                )
            )

            y1 = int(
                roi.get(
                    "y1",
                    0,
                )
            )

            x2 = int(
                roi.get(
                    "x2",
                    0,
                )
            )

            y2 = int(
                roi.get(
                    "y2",
                    0,
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            return

        # Invalid ROI
        if (
            x1 == x2
            or
            y1 == y2
        ):

            return

        height, width = frame.shape[:2]

        x1 = min(
            max(
                x1,
                0,
            ),
            width - 1,
        )

        x2 = min(
            max(
                x2,
                0,
            ),
            width - 1,
        )

        y1 = min(
            max(
                y1,
                0,
            ),
            height - 1,
        )

        y2 = min(
            max(
                y2,
                0,
            ),
            height - 1,
        )

        x_min = min(
            x1,
            x2,
        )

        x_max = max(
            x1,
            x2,
        )

        y_min = min(
            y1,
            y2,
        )

        y_max = max(
            y1,
            y2,
        )

        color = Visualizer.get_jam_color(
            status
        )

        # ----------------------------------------------
        # Transparent ROI overlay
        # ----------------------------------------------

        overlay = frame.copy()

        cv2.rectangle(
            overlay,
            (
                x_min,
                y_min,
            ),
            (
                x_max,
                y_max,
            ),
            color,
            -1,
        )

        cv2.addWeighted(
            overlay,
            0.08,
            frame,
            0.92,
            0,
            frame,
        )

        # ----------------------------------------------
        # ROI border
        # ----------------------------------------------

        thickness = (
            4
            if status == "jam"
            else 2
        )

        cv2.rectangle(
            frame,
            (
                x_min,
                y_min,
            ),
            (
                x_max,
                y_max,
            ),
            color,
            thickness,
        )

        # ----------------------------------------------
        # ROI title
        # ----------------------------------------------

        cv2.putText(
            frame,
            "JAM MONITORING ZONE",
            (
                x_min + 5,
                max(
                    y_min + 25,
                    25,
                ),
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

    # ======================================================
    # JAM COLOR
    # ======================================================

    @staticmethod
    def get_jam_color(
        status,
    ):

        status = str(
            status
            or "normal"
        ).lower()

        if status == "jam":

            return (
                0,
                0,
                255,
            )

        if status == "warning":

            return (
                0,
                165,
                255,
            )

        if status == "slow":

            return (
                0,
                255,
                255,
            )

        if status == "recovering":

            return (
                255,
                255,
                0,
            )

        if status == "error":

            return (
                255,
                0,
                255,
            )

        return (
            0,
            255,
            0,
        )

    # ======================================================
    # COUNT SUMMARY
    # ======================================================

    @staticmethod
    def draw_count_summary(
        frame,
        count,
        printed_count,
        missing_count,
    ):

        cv2.putText(
            frame,
            f"Count : {count}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2,
        )

        cv2.putText(
            frame,
            f"Printed : {printed_count}",
            (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 200, 0),
            2,
        )

        cv2.putText(
            frame,
            f"Not Printed : {missing_count}",
            (20, 115),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )

    # ======================================================
    # CAMERA NAME
    # ======================================================

    @staticmethod
    def draw_camera(
        frame,
        name,
    ):

        cv2.putText(
            frame,
            name,
            (20, 150),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )

    # ======================================================
    # FPS
    # ======================================================

    @staticmethod
    def draw_fps(
        frame,
        fps,
    ):

        cv2.putText(
            frame,
            f"FPS : {fps:.2f}",
            (20, 185),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 0),
            2,
        )

    # ======================================================
    # PRINT STATUS
    # ======================================================

    @staticmethod
    def draw_print_status(
        frame,
        bag_bbox,
        status,
    ):

        if status is None:
            return

        x1, y1, _, _ = [
            int(v)
            for v in bag_bbox
        ]

        color = (
            (0, 255, 0)
            if status
            else (0, 0, 255)
        )

        text = (
            "PRINT OK"
            if status
            else "PRINT MISSING"
        )

        cv2.putText(
            frame,
            text,
            (
                x1,
                max(
                    y1 - 35,
                    20,
                ),
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

    # ======================================================
    # CAMERA JAM STATUS
    # ======================================================

    @staticmethod
    def draw_camera_jam_status(
        frame,
        jam_result,
    ):

        if not jam_result:
            return

        if not jam_result.get(
            "enabled",
            False,
        ):

            return

        status = str(
            jam_result.get(
                "status",
                "normal",
            )
        ).lower()

        color = Visualizer.get_jam_color(
            status
        )

        text = (
            "JAM STATUS : "
            f"{status.upper()}"
        )

        cv2.putText(
            frame,
            text,
            (20, 225),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            color,
            2,
        )

        active_count = int(
            jam_result.get(
                "active_jam_count",
                0,
            )
            or 0
        )

        if active_count > 0:

            cv2.putText(
                frame,
                (
                    "JAMMED BAGS : "
                    f"{active_count}"
                ),
                (20, 260),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                color,
                2,
            )

    # ======================================================
    # PER TRACK JAM INFORMATION
    # ======================================================

    @staticmethod
    def draw_track_jam_info(
        frame,
        bag,
        jam_metrics,
        show_speed=True,
        show_stationary_time=True,
    ):

        if not jam_metrics:
            return

        bbox = bag.get(
            "bbox"
        )

        if not bbox:
            return

        x1, y1, _, y2 = [
            int(v)
            for v in bbox
        ]

        track_id = jam_metrics.get(
            "track_id"
        )

        state = str(
            jam_metrics.get(
                "state",
                "normal",
            )
        ).lower()

        history_ready = bool(
            jam_metrics.get(
                "history_ready",
                False,
            )
        )

        speed = float(
            jam_metrics.get(
                "speed_px_s",
                0.0,
            )
            or 0.0
        )

        stationary_seconds = float(
            jam_metrics.get(
                "stationary_seconds",
                0.0,
            )
            or 0.0
        )

        color = Visualizer.get_jam_color(
            state
        )

        # ----------------------------------------------
        # State
        # ----------------------------------------------

        cv2.putText(
            frame,
            (
                f"ID {track_id} | "
                f"{state.upper()}"
            ),
            (
                x1,
                min(
                    y2 + 25,
                    frame.shape[0] - 10,
                ),
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )

        line_y = (
            y2 + 48
        )

        # ----------------------------------------------
        # Waiting for sufficient history
        # ----------------------------------------------

        if not history_ready:

            cv2.putText(
                frame,
                "Motion: calibrating...",
                (
                    x1,
                    min(
                        line_y,
                        frame.shape[0] - 10,
                    ),
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                color,
                1,
            )

            return

        # ----------------------------------------------
        # Speed
        # ----------------------------------------------

        if show_speed:

            cv2.putText(
                frame,
                f"Speed: {speed:.1f} px/s",
                (
                    x1,
                    min(
                        line_y,
                        frame.shape[0] - 10,
                    ),
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                color,
                1,
            )

            line_y += 22

        # ----------------------------------------------
        # Stationary duration
        # ----------------------------------------------

        if show_stationary_time:

            cv2.putText(
                frame,
                (
                    "Stationary: "
                    f"{stationary_seconds:.1f}s"
                ),
                (
                    x1,
                    min(
                        line_y,
                        frame.shape[0] - 10,
                    ),
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                color,
                1,
            )

    # ======================================================
    # VISUALIZE
    # ======================================================

    def visualize(
        self,
        frame,
        camera_name,
        count,
        printed_count,
        missing_count,
        fps,
        roi,
        bag_tracks,
        all_detections,
        print_results,
        display_config,
        counted_bags=None,

        # --------------------------------------------------
        # JAM V1
        # --------------------------------------------------

        jam_result=None,
        jam_roi=None,
    ):

        # ==================================================
        # DISPLAY SETTINGS
        # ==================================================

        show_boxes = display_config.get(
            "show_boxes",
            True,
        )

        show_labels = display_config.get(
            "show_labels",
            True,
        )

        show_center = display_config.get(
            "show_center",
            True,
        )

        show_roi = display_config.get(
            "show_roi",
            True,
        )

        show_fps = display_config.get(
            "show_fps",
            True,
        )

        show_count = display_config.get(
            "show_count",
            True,
        )

        # ==================================================
        # JAM DISPLAY SETTINGS
        # ==================================================

        show_jam_roi = display_config.get(
            "show_jam_roi",
            True,
        )

        show_jam_status = display_config.get(
            "show_jam_status",
            True,
        )

        show_jam_speed = display_config.get(
            "show_jam_speed",
            True,
        )

        show_stationary_time = (
            display_config.get(
                "show_stationary_time",
                True,
            )
        )

        counted_bags = (
            counted_bags
            or []
        )

        jam_result = (
            jam_result
            or {}
        )

        current_time = (
            time.time()
        )

        # ==================================================
        # COUNT FLASH MEMORY
        # ==================================================

        for bag in counted_bags:

            track_id = bag.get(
                "track_id"
            )

            if track_id is not None:

                self.count_flash_until[
                    track_id
                ] = (
                    current_time
                    +
                    self.count_flash_seconds
                )

                self.line_flash_until = (
                    current_time
                    +
                    self.count_flash_seconds
                )

        self.count_flash_until = {

            track_id:
                flash_until

            for (
                track_id,
                flash_until,
            )
            in self.count_flash_until.items()

            if flash_until
            >
            current_time
        }

        # ==================================================
        # COUNTING LINE
        # ==================================================

        if show_roi:

            line_is_flashing = (
                self.line_flash_until
                >
                current_time
            )

            line_blink_on = (
                int(
                    current_time
                    * 10
                )
                % 2
                == 0
            )

            if (
                line_is_flashing
                and
                line_blink_on
            ):

                self.draw_roi_segment(
                    frame,
                    roi,
                    color=(
                        0,
                        255,
                        0,
                    ),
                    thickness=6,
                )

            else:

                self.draw_roi_segment(
                    frame,
                    roi,
                )

        # ==================================================
        # JAM ROI
        # ==================================================

        if (
            show_jam_roi
            and
            jam_result.get(
                "enabled",
                False,
            )
        ):

            self.draw_jam_roi(
                frame=frame,
                roi=jam_roi,
                status=jam_result.get(
                    "status",
                    "normal",
                ),
            )

        # ==================================================
        # JAM RESULT LOOKUP
        # ==================================================

        jam_lookup = {}

        for metrics in jam_result.get(
            "tracks",
            [],
        ):

            track_id = metrics.get(
                "track_id"
            )

            if track_id is not None:

                jam_lookup[
                    track_id
                ] = metrics

        # ==================================================
        # BAG TRACKS
        # ==================================================

        if show_boxes:

            for bag in bag_tracks:

                bbox = bag[
                    "bbox"
                ]

                track_id = bag.get(
                    "track_id"
                )

                jam_metrics = (
                    jam_lookup.get(
                        track_id
                    )
                )

                # ------------------------------------------
                # Bag box color
                #
                # If jam information exists, use the jam
                # state color.
                # ------------------------------------------

                if jam_metrics:

                    bag_color = (
                        self.get_jam_color(
                            jam_metrics.get(
                                "state",
                                "normal",
                            )
                        )
                    )

                else:

                    bag_color = (
                        0,
                        255,
                        0,
                    )

                if show_labels:

                    if track_id is not None:

                        label = (
                            f"Bag ID:{track_id}"
                        )

                    else:

                        label = "Bag"

                else:

                    label = ""

                self.draw_box(
                    frame,
                    bbox,
                    bag_color,
                    label,
                )

                # ------------------------------------------
                # Count flash
                # ------------------------------------------

                flash_until = (
                    self.count_flash_until.get(
                        track_id
                    )
                )

                if (
                    flash_until
                    and
                    int(
                        current_time
                        * 10
                    )
                    % 2
                    == 0
                ):

                    self.draw_count_flash(
                        frame,
                        bbox,
                    )

                # ------------------------------------------
                # Physical center
                # ------------------------------------------

                if show_center:

                    center = bag.get(
                        "center"
                    )

                    if center is None:

                        x1, y1, x2, y2 = bbox

                        center = (
                            int(
                                (
                                    x1
                                    +
                                    x2
                                )
                                / 2
                            ),
                            int(
                                (
                                    y1
                                    +
                                    y2
                                )
                                / 2
                            ),
                        )

                    self.draw_center(
                        frame,
                        center,
                    )

                # ------------------------------------------
                # JAM TRACK INFORMATION
                # ------------------------------------------

                if (
                    show_jam_status
                    and
                    jam_metrics
                ):

                    self.draw_track_jam_info(
                        frame=frame,
                        bag=bag,
                        jam_metrics=jam_metrics,
                        show_speed=show_jam_speed,
                        show_stationary_time=(
                            show_stationary_time
                        ),
                    )

            # ==================================================
            # PRINT DETECTIONS
            # ==================================================

            for det in all_detections:

                if det.get(
                    "class_id"
                ) != 1:

                    continue

                label = (
                    "Print"
                    if show_labels
                    else ""
                )

                self.draw_box(
                    frame,
                    det[
                        "bbox"
                    ],
                    (
                        255,
                        0,
                        0,
                    ),
                    label,
                )

        # ==================================================
        # PRINT STATUS
        # ==================================================

        for result in print_results:

            self.draw_print_status(
                frame,
                result[
                    "bag_bbox"
                ],
                result.get(
                    "print_present"
                ),
            )

        # ==================================================
        # COUNT SUMMARY
        # ==================================================

        if show_count:

            self.draw_count_summary(
                frame,
                count,
                printed_count,
                missing_count,
            )

        # ==================================================
        # CAMERA
        # ==================================================

        self.draw_camera(
            frame,
            camera_name,
        )

        # ==================================================
        # FPS
        # ==================================================

        if show_fps:

            self.draw_fps(
                frame,
                fps,
            )

        # ==================================================
        # CAMERA JAM STATUS
        # ==================================================

        if show_jam_status:

            self.draw_camera_jam_status(
                frame,
                jam_result,
            )