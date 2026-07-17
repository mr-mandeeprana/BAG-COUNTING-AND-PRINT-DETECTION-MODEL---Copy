from src.config import Config
from pathlib import Path


def test_config_uses_camera_list_format():
    config = Config("config.yaml")

    cameras = config.get("cameras")

    assert isinstance(cameras, list)
    assert len(cameras) == 4
    assert cameras[0]["name"] == "Camera 1"


def test_config_applies_global_display_settings():
    config = Config("config.yaml")

    camera = config.get("cameras")[0]

    assert camera["display"]["show_center"] is True
    assert camera["display"]["show_count"] is True


def test_config_exposes_tracking_and_counting_stability_settings():
    config = Config("config.yaml")

    assert config.get("counting", "minimum_cross_distance") == 15
    assert config.get("tracker", "unstable_frame_threshold") == 3
    assert config.get("print_detection", "vote_threshold") == 0.60
    assert config.get("print_detection", "min_votes") == 4


def test_config_uses_trained_model_and_dataset_yaml():
    config = Config("config.yaml")

    camera = config.get("cameras")[0]

    assert camera["model"]["path"] == "models/fillpac_yolo26n_best.pt"
    assert camera["model"]["image_size"] == 640
    assert camera["model"]["detection_roi"] == {
        "x1": 0,
        "y1": 120,
        "x2": 1920,
        "y2": 1080,
    }
    assert camera["model"]["half"] is True
    assert camera["model"]["max_detections"] == 50
    assert camera["buffer_size"] == 1
    assert Path("models/data.yaml").exists()
