import cv2

from src.camera import Camera


def test_camera_info_includes_runtime_fields():
    camera = Camera(name="Camera X", source="demo.mp4", mode="video")

    info = camera.info()

    assert info["name"] == "Camera X"
    assert info["source"] == "demo.mp4"
    assert info["mode"] == "video"


def test_rtsp_camera_uses_ffmpeg_backend():
    camera = Camera(name="RTSP Camera", source="rtsp://example.com/stream", mode="rtsp")

    assert camera._is_rtsp_source()
    assert camera._get_capture_backend() == cv2.CAP_FFMPEG
