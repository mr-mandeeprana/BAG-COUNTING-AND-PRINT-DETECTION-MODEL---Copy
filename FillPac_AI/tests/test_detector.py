import torch

from src.detector import Detector
from src.print_detector import PrintDetector


class FakeBox:
    def __init__(self, bbox, class_id, confidence):
        self.xyxy = torch.tensor([bbox], dtype=torch.float32)
        self.cls = torch.tensor([class_id], dtype=torch.float32)
        self.conf = torch.tensor([confidence], dtype=torch.float32)


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class FakeModel:
    names = {0: "bag", 1: "print"}

    def __init__(self, boxes):
        self.boxes = boxes

    def predict(self, **kwargs):
        return [FakeResult(self.boxes)]


def make_detector(boxes, **overrides):
    detector = Detector.__new__(Detector)
    detector.model = FakeModel(boxes)
    detector.confidence = overrides.get("confidence", 0.35)
    detector.iou = 0.45
    detector.image_size = 640
    detector.max_detections = 100
    allowed_classes = overrides.get("allowed_classes")
    detector.allowed_classes = (
        {int(class_id) for class_id in allowed_classes}
        if allowed_classes is not None
        else None
    )
    detector.min_bbox_area = overrides.get("min_bbox_area", 0.0)
    detector.class_confidence_thresholds = overrides.get(
        "class_confidence_thresholds",
        {},
    )
    detector.detection_roi = overrides.get("detection_roi")
    detector.frame_index = 0
    detector.device = "cpu"
    detector.half = False
    return detector


def test_detector_returns_geometry_metadata_and_safe_class_name():
    detector = make_detector(
        [FakeBox((10, 20, 50, 80), 9, 0.9)],
        allowed_classes=None,
    )
    detector.model.names = {0: "bag"}

    detections = detector.detect(frame=object())

    assert detections[0]["bbox"] == (10, 20, 50, 80)
    assert detections[0]["center"] == (30, 50)
    assert detections[0]["width"] == 40
    assert detections[0]["height"] == 60
    assert detections[0]["area"] == 2400
    assert detections[0]["class_name"] == "9"
    assert detections[0]["frame_index"] == 1
    assert "timestamp" in detections[0]


def test_detector_filters_classes_area_and_per_class_confidence():
    detector = make_detector(
        [
            FakeBox((0, 0, 40, 40), 0, 0.4),
            FakeBox((0, 0, 40, 40), 1, 0.5),
            FakeBox((0, 0, 40, 40), 2, 0.9),
            FakeBox((0, 0, 10, 10), 0, 0.9),
        ],
        allowed_classes={0, 1},
        min_bbox_area=800,
        class_confidence_thresholds={0: 0.35, 1: 0.55},
    )

    detections = detector.detect(frame=object())

    assert [detection["class_id"] for detection in detections] == [0]


def test_detector_filters_by_optional_detection_roi():
    detector = make_detector(
        [
            FakeBox((10, 10, 50, 50), 0, 0.9),
            FakeBox((10, 100, 50, 140), 0, 0.9),
        ],
        allowed_classes={0},
        detection_roi={"y1": 80},
    )

    detections = detector.detect(frame=object())

    assert len(detections) == 1
    assert detections[0]["center"] == (30, 120)


def test_print_detector_requires_confidence_threshold():
    detector = PrintDetector(confidence_threshold=0.5)

    bags = [
        {"bbox": (0, 0, 100, 100), "class_id": 0, "confidence": 0.9, "track_id": 1},
    ]
    detections = [
        {"bbox": (0, 0, 100, 100), "class_id": 0, "confidence": 0.9},
        {"bbox": (10, 10, 30, 30), "class_id": 1, "confidence": 0.4},
        {"bbox": (40, 40, 70, 70), "class_id": 1, "confidence": 0.8},
    ]

    results = detector.update(bags, detections)

    assert len(results) == 1
    assert results[0]["track_id"] == 1
    assert results[0]["bag_bbox"] == (0, 0, 100, 100)
    assert results[0]["print_present"] is True
    assert results[0]["print_bbox"] == (40, 40, 70, 70)
    assert results[0]["print_confidence"] == 0.8


def test_print_detector_assigns_one_print_to_one_best_bag():
    detector = PrintDetector(confidence_threshold=0.5, min_overlap_ratio=0.3)
    bags = [
        {"bbox": (0, 0, 100, 100), "class_id": 0, "track_id": 1},
        {"bbox": (90, 0, 190, 100), "class_id": 0, "track_id": 2},
    ]
    detections = [
        {"bbox": (80, 20, 120, 80), "class_id": 1, "confidence": 0.9},
    ]

    results = detector.update(bags, detections)

    assert [result["print_present"] for result in results] == [False, True]
    assert results[1]["print_bbox"] == (80, 20, 120, 80)


def test_print_detector_rejects_tiny_sliver_overlap():
    detector = PrintDetector(confidence_threshold=0.5, min_overlap_ratio=0.3)
    bags = [
        {"bbox": (0, 0, 100, 100), "class_id": 0, "track_id": 1},
    ]
    detections = [
        {"bbox": (95, 20, 155, 80), "class_id": 1, "confidence": 0.9},
    ]

    assert detector.update(bags, detections)[0]["print_present"] is False


def test_print_detector_adapts_iou_threshold_for_small_contained_prints():
    detector = PrintDetector(
        confidence_threshold=0.5,
        iou_threshold=0.1,
        min_overlap_ratio=0.3,
    )
    bags = [
        {"bbox": (0, 0, 100, 100), "class_id": 0, "track_id": 1},
    ]
    detections = [
        {"bbox": (10, 10, 30, 30), "class_id": 1, "confidence": 0.9},
    ]

    assert detector.update(bags, detections)[0]["print_present"] is True


def test_print_detector_rejects_matches_below_effective_iou_threshold():
    detector = PrintDetector(
        confidence_threshold=0.5,
        iou_threshold=0.2,
        min_overlap_ratio=0.0,
    )
    bags = [
        {"bbox": (0, 0, 100, 100), "class_id": 0, "track_id": 1},
    ]
    detections = [
        {"bbox": (50, 50, 150, 150), "class_id": 1, "confidence": 0.9},
    ]

    assert detector.update(bags, detections)[0]["print_present"] is False


def test_print_detector_rejects_bad_print_quality():
    detector = PrintDetector(
        confidence_threshold=0.5,
        min_print_area=100,
        min_aspect_ratio=0.5,
        max_aspect_ratio=2.0,
    )
    bags = [
        {"bbox": (0, 0, 100, 100), "class_id": 0, "track_id": 1},
    ]
    detections = [
        {"bbox": (10, 10, 15, 15), "class_id": 1, "confidence": 0.9},
        {"bbox": (20, 20, 80, 25), "class_id": 1, "confidence": 0.9},
    ]

    assert detector.update(bags, detections)[0]["print_present"] is False


def test_print_detector_prefers_higher_confidence_when_match_quality_ties():
    detector = PrintDetector(confidence_threshold=0.5)
    bags = [
        {"bbox": (0, 0, 100, 100), "class_id": 0, "track_id": 1},
    ]
    detections = [
        {"bbox": (20, 20, 60, 60), "class_id": 1, "confidence": 0.6},
        {"bbox": (20, 20, 60, 60), "class_id": 1, "confidence": 0.9},
    ]

    result = detector.update(bags, detections)[0]

    assert result["print_present"] is True
    assert result["print_confidence"] == 0.9


def test_print_detector_prefers_contained_print_over_partial_higher_iou_match():
    detector = PrintDetector(
        confidence_threshold=0.5,
        iou_threshold=0.1,
        min_overlap_ratio=0.2,
    )
    bags = [
        {"bbox": (0, 0, 200, 200), "class_id": 0, "track_id": 1},
        {"bbox": (110, 80, 150, 120), "class_id": 0, "track_id": 2},
    ]
    detections = [
        {"bbox": (80, 80, 120, 120), "class_id": 1, "confidence": 0.9},
    ]

    results = detector.update(bags, detections)

    assert [result["print_present"] for result in results] == [True, False]
