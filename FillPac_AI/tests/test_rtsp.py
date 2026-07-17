from src.camera import Camera


def test_camera_info_includes_runtime_fields():
    camera = Camera(name="Camera X", source="demo.mp4", mode="video")

    info = camera.info()

    assert info["name"] == "Camera X"
    assert info["source"] == "demo.mp4"
    assert info["mode"] == "video"
