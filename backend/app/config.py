from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class MachineConfig(BaseModel):
    min_speed_m_min: float = 200.0
    max_speed_m_min: float = 300.0
    initial_speed_m_min: float = 200.0


class FrameConfig(BaseModel):
    width: int = 1920
    height: int = 600
    engine_fps: int = 30
    jpeg_fps: int = 8
    jpeg_quality: int = 82


class MasterRollConfig(BaseModel):
    width: int = 1920
    height: int = 30000
    length_m: float = 750.0
    pixels_per_meter: float = 40.0

    @model_validator(mode="after")
    def dimensions_match_scale(self) -> "MasterRollConfig":
        expected = self.length_m * self.pixels_per_meter
        if abs(expected - self.height) > 1:
            raise ValueError("master_roll.height must equal length_m * pixels_per_meter")
        return self


class LaneConfig(BaseModel):
    count: int = 5
    width: int = 376
    gap: int = 10


class TelemetryConfig(BaseModel):
    hz: int = 10


class AlarmConfig(BaseModel):
    consecutive_defects: int = 5
    consecutive_window_m: float = 10.0
    continuous_warning_m: float = 1.0
    continuous_stop_m: float = 3.0
    bad_ratio_warning_percent: float = 3.0
    bad_ratio_min_length_m: float = 50.0


class DemoConfig(BaseModel):
    seed: int = 42
    lane_status_hold_seconds: float = 1.5


class DetectorConfig(BaseModel):
    mode: str = "reference_diff"
    difference_threshold: int = 24
    min_component_area_px: int = 24
    morphology_kernel_px: int = 3
    registration_enabled: bool = True
    registration_scale: float = 0.25
    registration_max_shift_px: float = 8.0

    @model_validator(mode="after")
    def validate_detector(self) -> "DetectorConfig":
        if self.mode not in {"reference_diff", "mock"}:
            raise ValueError("detector.mode must be 'reference_diff' or 'mock'")
        if self.difference_threshold < 1 or self.difference_threshold > 255:
            raise ValueError("detector.difference_threshold must be between 1 and 255")
        if self.morphology_kernel_px < 1 or self.morphology_kernel_px % 2 == 0:
            raise ValueError("detector.morphology_kernel_px must be a positive odd number")
        if not 0.05 <= self.registration_scale <= 1.0:
            raise ValueError("detector.registration_scale must be between 0.05 and 1.0")
        return self


class StorageConfig(BaseModel):
    directory: str = "data"


class AppConfig(BaseModel):
    machine: MachineConfig = Field(default_factory=MachineConfig)
    frame: FrameConfig = Field(default_factory=FrameConfig)
    master_roll: MasterRollConfig = Field(default_factory=MasterRollConfig)
    lanes: LaneConfig = Field(default_factory=LaneConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    alarm: AlarmConfig = Field(default_factory=AlarmConfig)
    demo: DemoConfig = Field(default_factory=DemoConfig)
    detector: DetectorConfig = Field(default_factory=DetectorConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    @model_validator(mode="after")
    def validate_layout(self) -> "AppConfig":
        used = self.lanes.count * self.lanes.width + (self.lanes.count - 1) * self.lanes.gap
        if used != self.frame.width or used != self.master_roll.width:
            raise ValueError("lane widths and gaps must exactly fill frame/master width")
        if self.frame.height >= self.master_roll.height:
            raise ValueError("frame height must be smaller than master roll height")
        return self

    @property
    def storage_path(self) -> Path:
        path = Path(os.getenv("PRINTING_DATA_DIR", self.storage.directory))
        if not path.is_absolute():
            path = backend_root() / path
        return path


def backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config(overrides: dict[str, Any] | None = None) -> AppConfig:
    config_path = Path(os.getenv("PRINTING_CONFIG", backend_root() / "config.yaml"))
    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if overrides:
        raw = _deep_merge(raw, overrides)
    return AppConfig.model_validate(raw)


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
