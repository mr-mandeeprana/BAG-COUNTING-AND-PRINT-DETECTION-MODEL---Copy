"""
==========================================================
FillPac AI
Print Detection Module
==========================================================
"""

import math


class PrintDetector:
    def __init__(
        self,
        confidence_threshold=0.4,
        iou_threshold=0.0,
        min_overlap_ratio=0.3,
        min_print_area=0.0,
        max_print_area=0.0,
        min_aspect_ratio=0.0,
        max_aspect_ratio=0.0,
        max_center_distance=0.0,
    ):
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = max(float(iou_threshold), 0.0)
        self.min_overlap_ratio = max(float(min_overlap_ratio), 0.0)
        self.min_print_area = max(float(min_print_area), 0.0)
        self.max_print_area = max(float(max_print_area), 0.0)
        self.min_aspect_ratio = max(float(min_aspect_ratio), 0.0)
        self.max_aspect_ratio = max(float(max_aspect_ratio), 0.0)
        self.max_center_distance = max(float(max_center_distance), 0.0)

    @staticmethod
    def is_inside(bag_box, print_box):
        bx1, by1, bx2, by2 = bag_box
        px1, py1, px2, py2 = print_box

        return px1 >= bx1 and py1 >= by1 and px2 <= bx2 and py2 <= by2

    @staticmethod
    def is_overlap(bag_box, candidate_box):
        bx1, by1, bx2, by2 = bag_box
        cx1, cy1, cx2, cy2 = candidate_box

        return not (cx2 < bx1 or cx1 > bx2 or cy2 < by1 or cy1 > by2)

    @staticmethod
    def bbox_center(bbox):
        x1, y1, x2, y2 = bbox
        return (x1 + x2) / 2, (y1 + y2) / 2

    @staticmethod
    def center_distance(box_a, box_b):
        ax, ay = PrintDetector.bbox_center(box_a)
        bx, by = PrintDetector.bbox_center(box_b)
        return math.hypot(ax - bx, ay - by)

    @staticmethod
    def bbox_area(bbox):
        x1, y1, x2, y2 = bbox
        return max(x2 - x1, 0) * max(y2 - y1, 0)

    @staticmethod
    def intersection_area(box_a, box_b):
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        return max(inter_x2 - inter_x1, 0) * max(inter_y2 - inter_y1, 0)

    @staticmethod
    def bbox_iou(box_a, box_b):
        intersection = PrintDetector.intersection_area(box_a, box_b)
        union = (
            PrintDetector.bbox_area(box_a)
            + PrintDetector.bbox_area(box_b)
            - intersection
        )

        if union <= 0:
            return 0.0

        return intersection / union

    @staticmethod
    def overlap_ratio(reference_box, candidate_box):
        candidate_area = PrintDetector.bbox_area(candidate_box)
        if candidate_area <= 0:
            return 0.0

        return PrintDetector.intersection_area(reference_box, candidate_box) / candidate_area

    def _passes_print_quality(self, detection):
        if detection["class_id"] != 1:
            return False

        if detection.get("confidence", 0.0) < self.confidence_threshold:
            return False

        bbox = detection["bbox"]
        area = self.bbox_area(bbox)
        if area < self.min_print_area:
            return False

        if self.max_print_area > 0 and area > self.max_print_area:
            return False

        x1, y1, x2, y2 = bbox
        width = max(x2 - x1, 0)
        height = max(y2 - y1, 0)
        if width <= 0 or height <= 0:
            return False

        aspect_ratio = width / height
        if self.min_aspect_ratio > 0 and aspect_ratio < self.min_aspect_ratio:
            return False

        if self.max_aspect_ratio > 0 and aspect_ratio > self.max_aspect_ratio:
            return False

        return True

    def _candidate_match(self, bag_index, print_index, bag, print_det):
        bag_box = bag["bbox"]
        print_box = print_det["bbox"]
        inside = self.is_inside(bag_box, print_box)
        iou = self.bbox_iou(bag_box, print_box)
        overlap_ratio = self.overlap_ratio(bag_box, print_box)
        distance = self.center_distance(bag_box, print_box)
        iou_threshold = self._effective_iou_threshold(bag_box, print_box)

        if not inside and iou < iou_threshold:
            return None

        if overlap_ratio < self.min_overlap_ratio:
            return None

        if self.max_center_distance > 0 and distance > self.max_center_distance:
            return None

        return {
            "bag_index": bag_index,
            "print_index": print_index,
            "inside": inside,
            "iou": iou,
            "overlap_ratio": overlap_ratio,
            "distance": distance,
            "confidence": print_det.get("confidence", 0.0),
            "print_bbox": print_box,
        }

    def _effective_iou_threshold(self, bag_box, print_box):
        if self.iou_threshold <= 0:
            return 0.0

        bag_area = self.bbox_area(bag_box)
        print_area = self.bbox_area(print_box)
        larger_area = max(bag_area, print_area)
        if larger_area <= 0:
            return self.iou_threshold

        max_possible_iou = min(bag_area, print_area) / larger_area
        return min(self.iou_threshold, max_possible_iou)

    def best_matches(self, bags, prints):
        candidates = []

        for bag_index, bag in enumerate(bags):
            for print_index, print_det in enumerate(prints):
                match = self._candidate_match(bag_index, print_index, bag, print_det)
                if match is not None:
                    candidates.append(match)

        candidates.sort(
            key=lambda match: (
                match["inside"],
                match["iou"],
                match["confidence"],
                match["overlap_ratio"],
                -match["distance"],
            ),
            reverse=True,
        )

        matches = {}
        used_bags = set()
        used_prints = set()

        for match in candidates:
            bag_index = match["bag_index"]
            print_index = match["print_index"]
            if bag_index in used_bags or print_index in used_prints:
                continue

            matches[bag_index] = match
            used_bags.add(bag_index)
            used_prints.add(print_index)

        return matches

    def update(self, bags, detections):
        prints = [det for det in detections if self._passes_print_quality(det)]
        matches = self.best_matches(bags, prints)
        results = []

        for bag_index, bag in enumerate(bags):
            bag_box = bag["bbox"]
            match = matches.get(bag_index)
            results.append(
                {
                    "track_id": bag.get("track_id"),
                    "bag_bbox": bag_box,
                    "print_present": match is not None,
                    "print_bbox": match["print_bbox"] if match else None,
                    "print_confidence": match["confidence"] if match else 0.0,
                    "iou": match["iou"] if match else 0.0,
                    "overlap_ratio": match["overlap_ratio"] if match else 0.0,
                    "center_distance": match["distance"] if match else None,
                }
            )

        return results