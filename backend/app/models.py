from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

import numpy as np


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


class MachineStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    PLC_STOP = "PLC_STOP"


class AlarmLevel(StrEnum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    ALARM = "ALARM"


@dataclass(frozen=True)
class BBox:
    x: int
    y: int
    w: int
    h: int

    def as_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class DefectTemplate:
    annotation_id: str
    defect_type: str
    defect_name: str
    lane_id: int
    position_m: float
    end_position_m: float
    confidence: float
    severity: str
    bbox: BBox


@dataclass
class FramePacket:
    frame_id: int
    captured_at: datetime
    roll_id: str
    image: np.ndarray
    position_m: float
    viewport_start_m: float
    viewport_end_m: float
    loop_no: int
    viewport_top_px: int


@dataclass(frozen=True)
class Detection:
    annotation_id: str
    lane_id: int
    defect_type: str
    defect_name: str
    confidence: float
    severity: str
    absolute_position_m: float
    physical_interval: tuple[float, float]
    frame_bbox: BBox
    source_bbox: BBox

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "lane_id": self.lane_id,
            "defect_type": self.defect_type,
            "defect_name": self.defect_name,
            "confidence": self.confidence,
            "severity": self.severity,
            "position_m": round(self.absolute_position_m, 3),
            "bbox": self.frame_bbox.as_dict(),
        }

