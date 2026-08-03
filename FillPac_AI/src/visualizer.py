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

Jam Detection - Condition A
---------------------------
Movement-based jam detection:
- Jam monitoring ROI
- Track ID
- Motion speed in pixels/second
- Stationary duration
- Per-track movement jam state

Bag Spacing - Condition B
-------------------------
Calibrated physical bag-spacing detection:
- Spacing monitoring ROI
- Adjacent bag pair measurement
- Edge-to-edge physical gap in millimetres
- Minimum current gap
- Configured jam threshold
- Spacing jam pair highlighting

Final Jam
---------
Final camera jam state:

    Condition A OR Condition B

Therefore:

    movement jam = True  -> JAM
    spacing jam  = True  -> JAM
    neither              -> NORMAL

Spacing detection does NOT modify counting logic.
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
        thickness=2,
    ):

        if not bbox:
            return

        try:

            x1, y1, x2, y2 = [
                int(v)
                for v in bbox
            ]

        except (
            TypeError,
            ValueError,
        ):

            return

        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            color,
            thickness,
        )

        if label:

            cv2.putText(
                frame,
                str(label),
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

        if not bbox:
            return

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

        if center is None:
            return

        try:

            center = (
                int(center[0]),
                int(center[1]),
            )

        except (
            TypeError,
            ValueError,
            IndexError,
        ):

            return

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
    # GENERIC RECTANGULAR ROI
    # ======================================================

    @staticmethod
    def _draw_rectangular_roi(
        frame,
        roi,
        color,
        title,
        fill_alpha=0.05,
        thickness=2,
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

        if fill_alpha > 0:

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
                fill_alpha,
                frame,
                1.0 - fill_alpha,
                0,
                frame,
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

        if title:

            cv2.putText(
                frame,
                title,
                (
                    x_min + 5,
                    max(
                        y_min + 25,
                        25,
                    ),
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

    # ======================================================
    # JAM ROI - CONDITION A
    # ======================================================

    @staticmethod
    def draw_jam_roi(
        frame,
        roi,
        status="normal",
    ):

        color = Visualizer.get_jam_color(
            status
        )

        thickness = (
            4
            if str(
                status
            ).lower() == "jam"
            else 2
        )

        Visualizer._draw_rectangular_roi(
            frame=frame,
            roi=roi,
            color=color,
            title="MOVEMENT JAM ZONE",
            fill_alpha=0.08,
            thickness=thickness,
        )

    # ======================================================
    # SPACING ROI - CONDITION B
    # ======================================================

    @staticmethod
    def draw_spacing_roi(
        frame,
        roi,
        status="normal",
    ):

        status = str(
            status
            or "normal"
        ).lower()

        color = (
            (0, 0, 255)
            if status == "jam"
            else (255, 255, 0)
        )

        thickness = (
            4
            if status == "jam"
            else 2
        )

        Visualizer._draw_rectangular_roi(
            frame=frame,
            roi=roi,
            color=color,
            title="BAG SPACING ZONE",
            fill_alpha=0.04,
            thickness=thickness,
        )

    # ======================================================
    # ROI OCCUPANCY ROI - CONDITION C
    # ======================================================

    @staticmethod
    def draw_condition_c_roi(
        frame,
        roi,
        jam=False,
    ):

        color = (
            (0, 0, 255)
            if jam
            else (255, 0, 255)
        )

        thickness = 4 if jam else 2

        Visualizer._draw_rectangular_roi(
            frame=frame,
            roi=roi,
            color=color,
            title="ROI OCCUPANCY",
            fill_alpha=0.04,
            thickness=thickness,
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

        if status == "disabled":

            return (
                160,
                160,
                160,
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
            str(name),
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

        if (
            status is None
            or
            not bag_bbox
        ):

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
    # MOVEMENT JAM STATUS - CONDITION A
    # ======================================================

    @staticmethod
    def draw_movement_jam_status(
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

        cv2.putText(
            frame,
            (
                "Movement : "
                f"{status.upper()}"
            ),
            (20, 300),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            color,
            2,
        )

    # ======================================================
    # FINAL CAMERA JAM STATUS
    # ======================================================

    @staticmethod
    def draw_final_jam_status(
        frame,
        final_jam_result,
    ):

        if not final_jam_result:
            return

        status = str(
            final_jam_result.get(
                "status",
                "normal",
            )
        ).lower()

        color = Visualizer.get_jam_color(
            status
        )

        cv2.putText(
            frame,
            (
                "JAM STATUS : "
                f"{status.upper()}"
            ),
            (20, 225),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            color,
            2,
        )

        jam_types = (
            final_jam_result.get(
                "jam_types",
                [],
            )
            or []
        )

        if jam_types:

            readable = []

            for jam_type in jam_types:

                if jam_type == "movement":

                    readable.append(
                        "MOVEMENT"
                    )

                elif jam_type == "bag_spacing":

                    readable.append(
                        "BAG SPACING"
                    )

                elif jam_type == "roi_occupancy":

                    readable.append(
                        "ROI OCCUPANCY"
                    )

                else:

                    readable.append(
                        str(
                            jam_type
                        ).upper()
                    )

            reason = " + ".join(
                readable
            )

            cv2.putText(
                frame,
                f"Reason : {reason}",
                (20, 260),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                color,
                2,
            )

    # ======================================================
    # PER TRACK MOVEMENT JAM INFORMATION
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

        x1, _, _, y2 = [
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
    # SPACING RESULT HELPERS
    # ======================================================

    @staticmethod
    def _get_pair_track_ids(
        pair,
    ):

        if not isinstance(
            pair,
            dict,
        ):

            return (
                None,
                None,
            )

        id_a = pair.get(
            "track_id_a"
        )

        id_b = pair.get(
            "track_id_b"
        )

        # Compatibility with possible alternate names.
        if id_a is None:

            id_a = pair.get(
                "front_track_id"
            )

        if id_b is None:

            id_b = pair.get(
                "rear_track_id"
            )

        if id_a is None:

            id_a = pair.get(
                "bag_a_track_id"
            )

        if id_b is None:

            id_b = pair.get(
                "bag_b_track_id"
            )

        if (
            id_a is None
            or
            id_b is None
        ):

            track_ids = pair.get(
                "track_ids"
            )

            if (
                isinstance(
                    track_ids,
                    (list, tuple),
                )
                and
                len(track_ids) >= 2
            ):

                id_a = track_ids[0]
                id_b = track_ids[1]

        return (
            id_a,
            id_b,
        )

    @staticmethod
    def _get_pair_gap_mm(
        pair,
    ):

        if not isinstance(
            pair,
            dict,
        ):

            return None

        for key in (
            "gap_mm",
            "edge_gap_mm",
            "distance_mm",
            "spacing_mm",
        ):

            value = pair.get(
                key
            )

            if value is None:
                continue

            try:

                return float(
                    value
                )

            except (
                TypeError,
                ValueError,
            ):

                continue

        return None

    @staticmethod
    def _get_pair_jam_state(
        pair,
        threshold_mm=None,
    ):

        if not isinstance(
            pair,
            dict,
        ):

            return False

        for key in (
            "jam_detected",
            "is_jam",
            "jam",
        ):

            if key in pair:

                return bool(
                    pair.get(
                        key
                    )
                )

        gap_mm = (
            Visualizer._get_pair_gap_mm(
                pair
            )
        )

        if (
            gap_mm is not None
            and
            threshold_mm is not None
        ):

            try:

                return (
                    gap_mm
                    <=
                    float(
                        threshold_mm
                    )
                )

            except (
                TypeError,
                ValueError,
            ):

                return False

        return False

    # ======================================================
    # SPACING PAIR DRAWING
    # ======================================================

    @staticmethod
    def draw_spacing_pairs(
        frame,
        spacing_result,
        bag_tracks,
    ):

        if not spacing_result:
            return

        pairs = (
            spacing_result.get(
                "pairs",
                [],
            )
            or []
        )

        if not pairs:
            return

        threshold_mm = (
            spacing_result.get(
                "threshold_mm"
            )
        )

        track_lookup = {

            track.get(
                "track_id"
            ):
                track

            for track in bag_tracks

            if track.get(
                "track_id"
            ) is not None
        }

        for pair in pairs:

            (
                track_id_a,
                track_id_b,
            ) = (
                Visualizer._get_pair_track_ids(
                    pair
                )
            )

            if (
                track_id_a is None
                or
                track_id_b is None
            ):

                continue

            bag_a = track_lookup.get(
                track_id_a
            )

            bag_b = track_lookup.get(
                track_id_b
            )

            if (
                not bag_a
                or
                not bag_b
            ):

                continue

            bbox_a = bag_a.get(
                "bbox"
            )

            bbox_b = bag_b.get(
                "bbox"
            )

            if (
                not bbox_a
                or
                not bbox_b
            ):

                continue

            gap_mm = (
                Visualizer._get_pair_gap_mm(
                    pair
                )
            )

            is_jam = (
                Visualizer._get_pair_jam_state(
                    pair,
                    threshold_mm,
                )
            )

            color = (
                (0, 0, 255)
                if is_jam
                else (0, 255, 0)
            )

            # ----------------------------------------------
            # Prefer detector-provided image edge points.
            #
            # This is the most accurate visualization
            # because Condition B is EDGE-TO-EDGE.
            # ----------------------------------------------

            point_a = (
                pair.get(
                    "edge_point_a"
                )
                or
                pair.get(
                    "image_edge_a"
                )
            )

            point_b = (
                pair.get(
                    "edge_point_b"
                )
                or
                pair.get(
                    "image_edge_b"
                )
            )

            if (
                point_a is not None
                and
                point_b is not None
            ):

                try:

                    point_a = (
                        int(
                            point_a[0]
                        ),
                        int(
                            point_a[1]
                        ),
                    )

                    point_b = (
                        int(
                            point_b[0]
                        ),
                        int(
                            point_b[1]
                        ),
                    )

                except (
                    TypeError,
                    ValueError,
                    IndexError,
                ):

                    point_a = None
                    point_b = None

            # ----------------------------------------------
            # Fallback visualization
            #
            # If BagSpacingDetector has not returned edge
            # image points, approximate the closest bbox
            # edges only for drawing.
            #
            # This fallback DOES NOT calculate gap_mm.
            # The physical value still comes exclusively
            # from BagSpacingDetector.
            # ----------------------------------------------

            if (
                point_a is None
                or
                point_b is None
            ):

                ax1, ay1, ax2, ay2 = [
                    int(v)
                    for v in bbox_a
                ]

                bx1, by1, bx2, by2 = [
                    int(v)
                    for v in bbox_b
                ]

                center_a_y = int(
                    (
                        ay1
                        +
                        ay2
                    )
                    / 2
                )

                center_b_y = int(
                    (
                        by1
                        +
                        by2
                    )
                    / 2
                )

                center_a_x = int(
                    (
                        ax1
                        +
                        ax2
                    )
                    / 2
                )

                center_b_x = int(
                    (
                        bx1
                        +
                        bx2
                    )
                    / 2
                )

                # Conveyor direction is predominantly
                # vertical in the current FillPac setup.
                #
                # Choose facing Y edges.

                if center_a_y <= center_b_y:

                    point_a = (
                        center_a_x,
                        ay2,
                    )

                    point_b = (
                        center_b_x,
                        by1,
                    )

                else:

                    point_a = (
                        center_a_x,
                        ay1,
                    )

                    point_b = (
                        center_b_x,
                        by2,
                    )

            # ----------------------------------------------
            # Measurement line
            # ----------------------------------------------

            cv2.line(
                frame,
                point_a,
                point_b,
                color,
                3 if is_jam else 2,
            )

            cv2.circle(
                frame,
                point_a,
                5,
                color,
                -1,
            )

            cv2.circle(
                frame,
                point_b,
                5,
                color,
                -1,
            )

            # ----------------------------------------------
            # Measurement text
            # ----------------------------------------------

            text_x = int(
                (
                    point_a[0]
                    +
                    point_b[0]
                )
                / 2
            )

            text_y = int(
                (
                    point_a[1]
                    +
                    point_b[1]
                )
                / 2
            )

            if gap_mm is not None:

                if is_jam:

                    text = (
                        f"JAM | {gap_mm:.1f} mm"
                    )

                else:

                    text = (
                        f"{gap_mm:.1f} mm"
                    )

            else:

                text = (
                    "JAM"
                    if is_jam
                    else "Spacing"
                )

            # Background improves readability.
            (
                text_width,
                text_height,
            ), baseline = cv2.getTextSize(
                text,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                2,
            )

            label_x = max(
                text_x
                -
                text_width // 2,
                0,
            )

            label_y = max(
                text_y - 8,
                text_height + 4,
            )

            cv2.rectangle(
                frame,
                (
                    label_x - 4,
                    label_y
                    -
                    text_height
                    -
                    4,
                ),
                (
                    label_x
                    +
                    text_width
                    +
                    4,
                    label_y
                    +
                    baseline
                    +
                    4,
                ),
                (0, 0, 0),
                -1,
            )

            cv2.putText(
                frame,
                text,
                (
                    label_x,
                    label_y,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

    # ======================================================
    # HIGHLIGHT SPACING JAM BAGS
    # ======================================================

    @staticmethod
    def draw_spacing_jam_bags(
        frame,
        spacing_result,
        bag_tracks,
    ):

        if not spacing_result:
            return

        jam_ids = set(
            spacing_result.get(
                "active_jam_track_ids",
                [],
            )
            or []
        )

        # Also derive IDs from jam_pairs for compatibility.

        for pair in (
            spacing_result.get(
                "jam_pairs",
                [],
            )
            or []
        ):

            (
                id_a,
                id_b,
            ) = (
                Visualizer._get_pair_track_ids(
                    pair
                )
            )

            if id_a is not None:

                jam_ids.add(
                    id_a
                )

            if id_b is not None:

                jam_ids.add(
                    id_b
                )

        if not jam_ids:
            return

        for bag in bag_tracks:

            track_id = bag.get(
                "track_id"
            )

            if track_id not in jam_ids:
                continue

            bbox = bag.get(
                "bbox"
            )

            if not bbox:
                continue

            Visualizer.draw_box(
                frame=frame,
                bbox=bbox,
                color=(
                    0,
                    0,
                    255,
                ),
                label=(
                    f"SPACING JAM ID:{track_id}"
                ),
                thickness=5,
            )

    # ======================================================
    # SPACING STATUS PANEL
    # ======================================================

    @staticmethod
    def draw_spacing_status(
        frame,
        spacing_result,
    ):

        if not spacing_result:
            return

        enabled = spacing_result.get(
            "enabled",
            True,
        )

        if not enabled:
            return

        status = str(
            spacing_result.get(
                "status",
                "normal",
            )
        ).lower()

        color = Visualizer.get_jam_color(
            status
        )

        threshold_mm = (
            spacing_result.get(
                "threshold_mm"
            )
        )

        minimum_gap_mm = (
            spacing_result.get(
                "minimum_gap_mm"
            )
        )

        y = 325

        cv2.putText(
            frame,
            (
                "Spacing : "
                f"{status.upper()}"
            ),
            (
                20,
                y,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            color,
            2,
        )

        y += 28

        if threshold_mm is not None:

            try:

                threshold_text = (
                    f"Threshold : "
                    f"{float(threshold_mm):.1f} mm"
                )

            except (
                TypeError,
                ValueError,
            ):

                threshold_text = (
                    f"Threshold : {threshold_mm}"
                )

            cv2.putText(
                frame,
                threshold_text,
                (
                    20,
                    y,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

            y += 26

        if minimum_gap_mm is not None:

            try:

                gap_text = (
                    f"Minimum Gap : "
                    f"{float(minimum_gap_mm):.1f} mm"
                )

            except (
                TypeError,
                ValueError,
            ):

                gap_text = (
                    f"Minimum Gap : "
                    f"{minimum_gap_mm}"
                )

            cv2.putText(
                frame,
                gap_text,
                (
                    20,
                    y,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

    # ======================================================
    # CONDITION C STATUS
    # ======================================================

    @staticmethod
    def draw_condition_c_status(
        frame,
        result,
        max_bags=None,
    ):

        if not result:
            return

        jam = result.get(
            "jam",
            False,
        )

        bag_count = result.get(
            "bag_count",
            0,
        )

        minimum_gap_mm = result.get(
            "minimum_gap_mm"
        )

        color = (
            (0, 0, 255)
            if jam
            else (255, 0, 255)
        )

        status = (
            "JAM"
            if jam
            else "NORMAL"
        )

        if max_bags is not None:

            bags_text = (
                f"Bags : {bag_count} / {max_bags}"
            )

        else:

            bags_text = (
                f"Bags Inside ROI : {bag_count}"
            )

        # --------------------------------------------------
        # PANEL BACKGROUND
        # --------------------------------------------------

        panel_x1 = 10
        panel_y1 = 385
        panel_x2 = 320
        panel_y2 = (
            460
            if minimum_gap_mm is not None
            else 435
        )

        overlay = frame.copy()

        cv2.rectangle(
            overlay,
            (panel_x1, panel_y1),
            (panel_x2, panel_y2),
            (0, 0, 0),
            -1,
        )

        cv2.addWeighted(
            overlay,
            0.35,
            frame,
            0.65,
            0,
            frame,
        )

        cv2.rectangle(
            frame,
            (panel_x1, panel_y1),
            (panel_x2, panel_y2),
            color,
            1,
        )

        cv2.putText(
            frame,
            f"ROI OCCUPANCY : {status}",
            (20, 405),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

        cv2.putText(
            frame,
            bags_text,
            (20, 432),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )

        if minimum_gap_mm is not None:

            cv2.putText(
                frame,
                f"Minimum Gap : {minimum_gap_mm:.1f} mm",
                (20, 456),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

    # ======================================================
    # CONDITION C - ROI DISTANCE DRAWING
    # ======================================================

    @staticmethod
    def draw_condition_c_distances(
        frame,
        condition_c_result,
    ):

        if not condition_c_result:
            return

        distances = (
            condition_c_result.get(
                "distances",
                [],
            )
            or []
        )

        if not distances:
            return

        color = (255, 0, 255)

        for pair in distances:

            if not isinstance(
                pair,
                dict,
            ):
                continue

            point_a = (
                pair.get(
                    "edge_point_a"
                )
                or
                pair.get(
                    "image_edge_a"
                )
            )

            point_b = (
                pair.get(
                    "edge_point_b"
                )
                or
                pair.get(
                    "image_edge_b"
                )
            )

            if (
                point_a is None
                or
                point_b is None
            ):
                continue

            try:

                point_a = (
                    int(
                        point_a[0]
                    ),
                    int(
                        point_a[1]
                    ),
                )

                point_b = (
                    int(
                        point_b[0]
                    ),
                    int(
                        point_b[1]
                    ),
                )

            except (
                TypeError,
                ValueError,
                IndexError,
            ):
                continue

            cv2.line(
                frame,
                point_a,
                point_b,
                color,
                2,
            )

            cv2.circle(
                frame,
                point_a,
                5,
                color,
                -1,
            )

            cv2.circle(
                frame,
                point_b,
                5,
                color,
                -1,
            )

            gap_mm = (
                Visualizer._get_pair_gap_mm(
                    pair
                )
            )

            text = (
                f"ROI | {gap_mm:.1f} mm"
                if gap_mm is not None
                else "ROI"
            )

            text_x = int(
                (
                    point_a[0]
                    +
                    point_b[0]
                )
                / 2
            )

            text_y = int(
                (
                    point_a[1]
                    +
                    point_b[1]
                )
                / 2
            )

            (
                text_width,
                text_height,
            ), baseline = cv2.getTextSize(
                text,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                2,
            )

            label_x = max(
                text_x
                -
                text_width // 2,
                0,
            )

            label_y = max(
                text_y - 8,
                text_height + 4,
            )

            cv2.rectangle(
                frame,
                (
                    label_x - 4,
                    label_y
                    -
                    text_height
                    -
                    4,
                ),
                (
                    label_x
                    +
                    text_width
                    +
                    4,
                    label_y
                    +
                    baseline
                    +
                    4,
                ),
                (0, 0, 0),
                -1,
            )

            cv2.putText(
                frame,
                text,
                (
                    label_x,
                    label_y,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
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
        # CONDITION A
        # --------------------------------------------------

        jam_result=None,
        jam_roi=None,

        # --------------------------------------------------
        # CONDITION B
        # --------------------------------------------------

        spacing_result=None,
        spacing_roi=None,

        # --------------------------------------------------
        # FINAL CONDITION A OR B
        # --------------------------------------------------

        final_jam_result=None,

        # ------------------------------------
        # CONDITION C
        # ------------------------------------

        condition_c_result=None,
        condition_c_roi=None,
        condition_c_max_bags=None,
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
        # CONDITION A DISPLAY SETTINGS
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

        # ==================================================
        # CONDITION B DISPLAY SETTINGS
        # ==================================================

        show_spacing_roi = display_config.get(
            "show_spacing_roi",
            True,
        )

        show_spacing_lines = display_config.get(
            "show_spacing_lines",
            True,
        )

        show_spacing_status = display_config.get(
            "show_spacing_status",
            True,
        )

        show_spacing_jam_boxes = display_config.get(
            "show_spacing_jam_boxes",
            True,
        )

        # ==================================================
        # CONDITION C DISPLAY SETTINGS
        # ==================================================

        show_condition_c_status = display_config.get(
            "show_condition_c_status",
            True,
        )

        show_condition_c_lines = display_config.get(
            "show_condition_c_lines",
            True,
        )

        counted_bags = (
            counted_bags
            or []
        )

        bag_tracks = (
            bag_tracks
            or []
        )

        all_detections = (
            all_detections
            or []
        )

        print_results = (
            print_results
            or []
        )

        jam_result = (
            jam_result
            or {}
        )

        spacing_result = (
            spacing_result
            or {}
        )

        final_jam_result = (
            final_jam_result
            or {}
        )

        condition_c_result = (
            condition_c_result
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
        # CONDITION A ROI
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
        # CONDITION B ROI
        # ==================================================

        spacing_enabled = bool(
            spacing_result.get(
                "enabled",
                True,
            )
        )

        if (
            show_spacing_roi
            and
            spacing_enabled
            and
            spacing_roi
        ):

            self.draw_spacing_roi(
                frame=frame,
                roi=spacing_roi,
                status=spacing_result.get(
                    "status",
                    "normal",
                ),
            )

        # ==================================================
        # CONDITION C ROI
        # ==================================================

        if condition_c_roi:

            self.draw_condition_c_roi(

                frame=frame,

                roi=condition_c_roi,

                jam=condition_c_result.get(
                    "jam",
                    False,
                ),
            )

        # ==================================================
        # CONDITION A RESULT LOOKUP
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
        # CONDITION B JAM TRACK IDS
        # ==================================================

        spacing_jam_ids = set(
            spacing_result.get(
                "active_jam_track_ids",
                [],
            )
            or []
        )

        for pair in spacing_result.get(
            "jam_pairs",
            [],
        ) or []:

            (
                id_a,
                id_b,
            ) = self._get_pair_track_ids(
                pair
            )

            if id_a is not None:

                spacing_jam_ids.add(
                    id_a
                )

            if id_b is not None:

                spacing_jam_ids.add(
                    id_b
                )

        # ==================================================
        # BAG TRACKS
        # ==================================================

        if show_boxes:

            condition_c_ids = set(
                condition_c_result.get(
                    "track_ids",
                    [],
                )
            )

            for bag in bag_tracks:

                bbox = bag.get(
                    "bbox"
                )

                if not bbox:
                    continue

                track_id = bag.get(
                    "track_id"
                )

                if track_id in condition_c_ids:

                    cv2.rectangle(
                        frame,
                        (
                            int(bbox[0]),
                            int(bbox[1]),
                        ),
                        (
                            int(bbox[2]),
                            int(bbox[3]),
                        ),
                        (255, 0, 255),
                        5,
                    )

                jam_metrics = (
                    jam_lookup.get(
                        track_id
                    )
                )

                # ------------------------------------------
                # BOX COLOR PRIORITY
                #
                # Spacing JAM > Movement state > Normal
                # ------------------------------------------

                if track_id in spacing_jam_ids:

                    bag_color = (
                        0,
                        0,
                        255,
                    )

                elif jam_metrics:

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

                # ------------------------------------------
                # LABEL
                # ------------------------------------------

                if show_labels:

                    if (
                        track_id is not None
                        and
                        track_id in condition_c_ids
                    ):

                        label = (
                            f"ROI ID:{track_id}"
                        )

                    elif track_id is not None:

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
                # COUNT FLASH
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
                # PHYSICAL CENTER
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
                # CONDITION A TRACK INFO
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
                    det.get(
                        "bbox"
                    ),
                    (
                        255,
                        0,
                        0,
                    ),
                    label,
                )

        # ==================================================
        # CONDITION B PAIR MEASUREMENTS
        # ==================================================

        if (
            show_spacing_lines
            and
            spacing_enabled
        ):

            self.draw_spacing_pairs(
                frame=frame,
                spacing_result=spacing_result,
                bag_tracks=bag_tracks,
            )

        # ==================================================
        # CONDITION B JAM BAG HIGHLIGHT
        # ==================================================

        if (
            show_spacing_jam_boxes
            and
            spacing_enabled
            and
            spacing_result.get(
                "jam_detected",
                False,
            )
        ):

            self.draw_spacing_jam_bags(
                frame=frame,
                spacing_result=spacing_result,
                bag_tracks=bag_tracks,
            )

        # ==================================================
        # CONDITION C ROI DISTANCE MEASUREMENTS
        # ==================================================

        if (
            show_condition_c_lines
            and
            condition_c_roi
        ):

            self.draw_condition_c_distances(
                frame=frame,
                condition_c_result=condition_c_result,
            )

        # ==================================================
        # PRINT STATUS
        # ==================================================

        for result in print_results:

            bag_bbox = result.get(
                "bag_bbox"
            )

            if not bag_bbox:
                continue

            self.draw_print_status(
                frame,
                bag_bbox,
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
        # FINAL JAM STATUS
        # ==================================================

        if show_jam_status:

            self.draw_final_jam_status(
                frame,
                final_jam_result,
            )

            # Condition A status shown separately.
            self.draw_movement_jam_status(
                frame,
                jam_result,
            )

        # ==================================================
        # CONDITION B STATUS
        # ==================================================

        if (
            show_spacing_status
            and
            spacing_enabled
        ):

            self.draw_spacing_status(
                frame,
                spacing_result,
            )

        if show_condition_c_status:

            self.draw_condition_c_status(
                frame,
                condition_c_result,
                max_bags=condition_c_max_bags,
            )