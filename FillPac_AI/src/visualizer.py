"""
==========================================================
FillPac AI
Visualization Module
==========================================================
"""

import cv2
import time


class Visualizer:
    def __init__(self):
        self.count_flash_until = {}
        self.count_flash_seconds = 0.7
        self.line_flash_until = 0

    @staticmethod
    def draw_box(frame, bbox, color, label=""):
        x1, y1, x2, y2 = bbox
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        if label:
            cv2.putText(
                frame,
                label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )

    @staticmethod
    def draw_count_flash(frame, bbox):
        x1, y1, x2, y2 = bbox
        overlay = frame.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 0), -1)
        cv2.addWeighted(overlay, 0.28, frame, 0.72, 0, frame)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 5)
        cv2.putText(
            frame,
            "COUNTED",
            (x1, max(y1 - 10, 25)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            3,
        )

    @staticmethod
    def draw_center(frame, center):
        cv2.circle(frame, center, 5, (0, 0, 255), -1)

    @staticmethod
    def draw_roi_segment(frame, roi, color=(0, 255, 255), thickness=2):
        height, width = frame.shape[:2]
        x1 = min(max(int(roi["x1"]), 0), width - 1)
        x2 = min(max(int(roi["x2"]), 0), width - 1)
        y1 = min(max(int(roi["y1"]), 0), height - 1)
        y2 = min(max(int(roi["y2"]), 0), height - 1)

        cv2.line(
            frame,
            (x1, y1),
            (x2, y2),
            color,
            thickness,
        )

    @staticmethod
    def draw_count_summary(frame, count, printed_count, missing_count):
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

    @staticmethod
    def draw_camera(frame, name):
        cv2.putText(
            frame,
            name,
            (20, 150),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )

    @staticmethod
    def draw_fps(frame, fps):
        cv2.putText(
            frame,
            f"FPS : {fps:.2f}",
            (20, 185),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 0),
            2,
        )

    @staticmethod
    def draw_print_status(frame, bag_bbox, status):
        x1, y1, _, _ = bag_bbox
        color = (0, 255, 0) if status else (0, 0, 255)
        text = "PRINT OK" if status else "PRINT MISSING"

        cv2.putText(
            frame,
            text,
            (x1, y1 - 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

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
    ):
        show_boxes = display_config.get("show_boxes", True)
        show_labels = display_config.get("show_labels", True)
        show_center = display_config.get("show_center", True)
        show_roi = display_config.get("show_roi", True)
        show_fps = display_config.get("show_fps", True)
        show_count = display_config.get("show_count", True)
        counted_bags = counted_bags or []
        current_time = time.time()

        for bag in counted_bags:
            track_id = bag.get("track_id")
            if track_id is not None:
                self.count_flash_until[track_id] = current_time + self.count_flash_seconds
                self.line_flash_until = current_time + self.count_flash_seconds

        self.count_flash_until = {
            track_id: flash_until
            for track_id, flash_until in self.count_flash_until.items()
            if flash_until > current_time
        }

        if show_roi:
            line_is_flashing = self.line_flash_until > current_time
            line_blink_on = int(current_time * 10) % 2 == 0
            if line_is_flashing and line_blink_on:
                self.draw_roi_segment(frame, roi, color=(0, 255, 0), thickness=6)
            else:
                self.draw_roi_segment(frame, roi)

        if show_boxes:
            for bag in bag_tracks:
                bbox = bag["bbox"]
                label = "Bag" if show_labels else ""
                self.draw_box(frame, bbox, (0, 255, 0), label)

                track_id = bag.get("track_id")
                flash_until = self.count_flash_until.get(track_id)
                if flash_until and int(current_time * 10) % 2 == 0:
                    self.draw_count_flash(frame, bbox)

                if show_center:
                    x1, y1, x2, y2 = bbox
                    center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                    self.draw_center(frame, center)

            for det in all_detections:
                if det["class_id"] != 1:
                    continue

                label = "Print" if show_labels else ""
                self.draw_box(frame, det["bbox"], (255, 0, 0), label)

        for result in print_results:
            self.draw_print_status(frame, result["bag_bbox"], result["print_present"])

        if show_count:
            self.draw_count_summary(frame, count, printed_count, missing_count)

        self.draw_camera(frame, camera_name)

        if show_fps:
            self.draw_fps(frame, fps)
