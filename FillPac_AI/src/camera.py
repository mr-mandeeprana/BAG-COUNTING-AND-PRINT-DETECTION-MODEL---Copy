"""
============================================================
FillPac AI
Camera Module
============================================================
"""

import time
from typing import Optional, Union

import cv2


class Camera:
    def __init__(
        self,
        name: str,
        source: Union[str, int],
        mode: str = "video",
        buffer_size: int = 1,
        logger=None,
    ):
        self.name = name
        self.source = source
        self.mode = mode.lower()
        self.buffer_size = buffer_size
        self.logger = logger
        self.cap = None
        self.connected = False
        self.width = 0
        self.height = 0
        self.fps = 0

    def connect(self) -> bool:
        self.cap = cv2.VideoCapture(self.source)

        if not self.cap.isOpened():
            self._log("error", f"{self.name} connection failed")
            return False

        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, self.buffer_size)

        self.connected = True
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self._log("info", f"{self.name} connected")
        return True

    def read(self):
        if not self.connected:
            return False, None

        success, frame = self.cap.read()

        if not success:
            if self.mode == "video":
                return False, None

            self._log("warning", f"{self.name} disconnected")
            return False, None

        return True, frame

    def release(self):
        if self.cap is not None:
            self.cap.release()

        self.connected = False

    def reset(self):
        self.release()
        return self.connect()

    def disconnect(self):
        self.release()

    def is_open(self):
        return self.connected

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_fps(self):
        return self.fps

    def info(self):
        return {
            "name": self.name,
            "source": self.source,
            "mode": self.mode,
            "buffer_size": self.buffer_size,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
        }

    def _log(self, level, message):
        if self.logger is not None:
            getattr(self.logger, level)(message)
            return

        print(f"[{level.upper()}] {message}")