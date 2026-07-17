"""
==========================================================
FillPac AI
Logger Module
==========================================================

Author  : Mandeep Rana
Project : Bag Counting & Print Detection Model

Description
-----------
Centralized logging for the application.
"""

import logging
import os


class Logger:

    def __init__(
        self,
        log_file="logs/application.log",
        level=logging.INFO
    ):

        os.makedirs("logs", exist_ok=True)

        self.logger = logging.getLogger("FillPacAI")
        self.logger.setLevel(level)

        # Avoid duplicate handlers
        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            "%Y-%m-%d %H:%M:%S"
        )

        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        # File Handler
        file_handler = logging.FileHandler(
            log_file,
            mode="a",
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)

        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    # ======================================================

    def info(self, message):
        self.logger.info(message)

    # ======================================================

    def warning(self, message):
        self.logger.warning(message)

    # ======================================================

    def error(self, message):
        self.logger.error(message)

    # ======================================================

    def critical(self, message):
        self.logger.critical(message)

    # ======================================================

    def debug(self, message):
        self.logger.debug(message)