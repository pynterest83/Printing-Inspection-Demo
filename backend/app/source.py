from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .config import AppConfig
from .models import BBox, FramePacket


class ImageSource(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def read(
        self,
        *,
        frame_id: int,
        captured_at: datetime,
        roll_id: str,
        position_m: float,
        loop_no: int,
        frame_height: int | None = None,
    ) -> FramePacket: ...


class MockImageSource:
    def __init__(self, config: AppConfig, image_path: Path):
        self.config = config
        self.image_path = image_path
        self.image: np.ndarray | None = None

    def start(self) -> None:
        self.image = cv2.imread(str(self.image_path), cv2.IMREAD_COLOR)
        if self.image is None:
            raise RuntimeError(f"Unable to load master roll: {self.image_path}")
        expected = (self.config.master_roll.height, self.config.master_roll.width)
        if self.image.shape[:2] != expected:
            raise RuntimeError(f"Unexpected master roll dimensions: {self.image.shape[:2]} != {expected}")

    def stop(self) -> None:
        self.image = None

    def read(
        self,
        *,
        frame_id: int,
        captured_at: datetime,
        roll_id: str,
        position_m: float,
        loop_no: int,
        frame_height: int | None = None,
    ) -> FramePacket:
        if self.image is None:
            raise RuntimeError("Image source has not been started")
        ppm = self.config.master_roll.pixels_per_meter
        requested_height = frame_height or self.config.frame.height
        bottom_px = min(round(position_m * ppm), self.config.master_roll.height)
        top_px = bottom_px - requested_height
        if top_px >= 0:
            frame = self.image[top_px:bottom_px].copy()
        else:
            frame = np.full((requested_height, self.config.frame.width, 3), (18, 23, 29), dtype=np.uint8)
            if bottom_px > 0:
                frame[-bottom_px:] = self.image[:bottom_px]
        if frame.shape[0] != requested_height:
            padded = np.full((requested_height, self.config.frame.width, 3), (18, 23, 29), dtype=np.uint8)
            padded[-frame.shape[0] :] = frame
            frame = padded
        return FramePacket(
            frame_id=frame_id,
            captured_at=captured_at,
            roll_id=roll_id,
            image=frame,
            position_m=position_m,
            viewport_start_m=max(0.0, position_m - requested_height / ppm),
            viewport_end_m=position_m,
            loop_no=loop_no,
            viewport_top_px=top_px,
        )

    def crop_global(self, bbox: BBox, margin: int = 36) -> np.ndarray:
        if self.image is None:
            raise RuntimeError("Image source has not been started")
        x0 = max(0, bbox.x - margin)
        y0 = max(0, bbox.y - margin)
        x1 = min(self.image.shape[1], bbox.x + bbox.w + margin)
        y1 = min(self.image.shape[0], bbox.y + bbox.h + margin)
        return self.image[y0:y1, x0:x1].copy()
