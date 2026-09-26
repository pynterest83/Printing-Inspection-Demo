from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .config import AppConfig
from .models import BBox, DefectTemplate, Detection, FramePacket


class Detector(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def detect(self, packet: FramePacket) -> list[Detection]: ...


class MockDetector:
    """Annotation-backed detector retained as an explicit debug fallback."""

    def __init__(self, annotations: list[DefectTemplate]):
        self.annotations = annotations

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def detect(self, packet: FramePacket) -> list[Detection]:
        frame_top = packet.viewport_top_px
        frame_bottom = frame_top + packet.image.shape[0]
        detections: list[Detection] = []
        for item in self.annotations:
            defect_top = item.bbox.y
            defect_bottom = item.bbox.y + item.bbox.h
            if defect_top >= frame_bottom or defect_bottom <= frame_top:
                continue
            detections.append(
                Detection(
                    annotation_id=item.annotation_id,
                    lane_id=item.lane_id,
                    defect_type=item.defect_type,
                    defect_name=item.defect_name,
                    confidence=item.confidence,
                    severity=item.severity,
                    absolute_position_m=item.position_m,
                    physical_interval=(item.position_m, item.end_position_m),
                    frame_bbox=BBox(item.bbox.x, item.bbox.y - frame_top, item.bbox.w, item.bbox.h),
                    source_bbox=item.bbox,
                )
            )
        return detections


@dataclass(frozen=True)
class _Candidate:
    lane_id: int
    defect_type: str
    defect_name: str
    confidence: float
    severity: str
    frame_bbox: BBox
    source_bbox: BBox


@dataclass
class _Track:
    track_id: str
    roll_id: str
    lane_id: int
    defect_type: str
    defect_name: str
    confidence: float
    severity: str
    x0: int
    x1: int
    y0: int
    y1: int
    last_frame_id: int


class ReferenceDiffDetector:
    """Pixel-only reference inspection with translation registration and tracking.

    Ground-truth annotations are deliberately not accepted. They are used only by
    offline tests/evaluation and cannot influence runtime predictions.
    """

    _TYPE_DETAILS = {
        "dark_spot": ("Dark Spot", "medium"),
        "color_shift": ("Color Shift", "high"),
        "missing_ink": ("Missing Ink", "high"),
        "contamination": ("Contamination/Hair", "medium"),
        "streak": ("Streak", "high"),
        "pinhole": ("Pinhole", "low"),
    }

    def __init__(self, config: AppConfig, reference_path: Path):
        self.config = config
        self.reference_path = reference_path
        self.reference: np.ndarray | None = None
        self._tracks: dict[str, list[_Track]] = {}
        self._next_track = 1
        self._cache_key: tuple[str, int, int] | None = None
        self._cache_value: list[Detection] = []

    def start(self) -> None:
        self.reference = cv2.imread(str(self.reference_path), cv2.IMREAD_COLOR)
        if self.reference is None:
            raise RuntimeError(f"Unable to load clean reference roll: {self.reference_path}")
        expected = (self.config.master_roll.height, self.config.master_roll.width)
        if self.reference.shape[:2] != expected:
            raise RuntimeError(f"Unexpected reference dimensions: {self.reference.shape[:2]} != {expected}")

    def stop(self) -> None:
        self.reference = None
        self._tracks.clear()
        self._cache_key = None
        self._cache_value = []

    def detect(self, packet: FramePacket) -> list[Detection]:
        if self.reference is None:
            raise RuntimeError("Reference detector has not been started")
        cache_key = (packet.roll_id, packet.frame_id, packet.viewport_top_px)
        if cache_key == self._cache_key:
            return list(self._cache_value)

        reference_frame = self._reference_frame(packet)
        registered_reference = self._register(reference_frame, packet.image)
        raw_difference = cv2.absdiff(packet.image, registered_reference)
        blue_diff, green_diff, red_diff = cv2.split(raw_difference)
        difference_score = cv2.max(cv2.max(blue_diff, green_diff), red_diff)
        _, raw_mask = cv2.threshold(
            difference_score,
            self.config.detector.difference_threshold,
            255,
            cv2.THRESH_BINARY,
        )
        kernel_size = self.config.detector.morphology_kernel_px
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        mask = cv2.morphologyEx(raw_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.dilate(mask, kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[_Candidate] = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            changed_pixels = int(cv2.countNonZero(raw_mask[y : y + h, x : x + w]))
            if changed_pixels < self.config.detector.min_component_area_px:
                continue
            candidate = self._make_candidate(
                packet, registered_reference, raw_mask, x, y, w, h, changed_pixels
            )
            if candidate is not None:
                candidates.append(candidate)

        detections = [
            self._track(packet, item)
            for item in sorted(candidates, key=lambda item: (item.source_bbox.y, item.source_bbox.x))
        ]
        self._cache_key = cache_key
        self._cache_value = detections
        return list(detections)

    def _reference_frame(self, packet: FramePacket) -> np.ndarray:
        assert self.reference is not None
        frame_height, frame_width = packet.image.shape[:2]
        top = packet.viewport_top_px
        bottom = top + frame_height
        if top >= 0:
            return self.reference[top:bottom].copy()
        frame = np.full((frame_height, frame_width, 3), (18, 23, 29), dtype=np.uint8)
        valid_bottom = max(0, bottom)
        if valid_bottom:
            frame[-valid_bottom:] = self.reference[:valid_bottom]
        return frame

    def _register(self, reference: np.ndarray, observed: np.ndarray) -> np.ndarray:
        settings = self.config.detector
        if not settings.registration_enabled:
            return reference
        scale = settings.registration_scale
        reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        observed_gray = cv2.cvtColor(observed, cv2.COLOR_BGR2GRAY)
        if scale < 1.0:
            reference_gray = cv2.resize(
                reference_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            )
            observed_gray = cv2.resize(
                observed_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            )
        if float(np.std(reference_gray)) < 1.0 or float(np.std(observed_gray)) < 1.0:
            return reference
        (shift_x, shift_y), response = cv2.phaseCorrelate(
            reference_gray.astype(np.float32), observed_gray.astype(np.float32)
        )
        shift_x /= scale
        shift_y /= scale
        if response < 0.1 or max(abs(shift_x), abs(shift_y)) > settings.registration_max_shift_px:
            return reference
        # Phase correlation has sub-pixel jitter even for an already aligned
        # frame. Warping for that noise creates differences around every print
        # edge, so keep the original reference inside a small dead band.
        if max(abs(shift_x), abs(shift_y)) < 0.75:
            return reference
        transform = np.float32([[1.0, 0.0, shift_x], [0.0, 1.0, shift_y]])
        return cv2.warpAffine(
            reference,
            transform,
            (reference.shape[1], reference.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )

    def _make_candidate(
        self,
        packet: FramePacket,
        reference: np.ndarray,
        raw_mask: np.ndarray,
        x: int,
        y: int,
        w: int,
        h: int,
        changed_pixels: int,
    ) -> _Candidate | None:
        if h < 5 or w < 3:
            return None
        center_x = x + w // 2
        stride = self.config.lanes.width + self.config.lanes.gap
        lane_id = min(self.config.lanes.count, center_x // stride + 1)
        lane_start = (lane_id - 1) * stride
        if center_x >= lane_start + self.config.lanes.width:
            return None

        region_mask = raw_mask[y : y + h, x : x + w] > 0
        observed_region = packet.image[y : y + h, x : x + w].astype(np.int16)
        reference_region = reference[y : y + h, x : x + w].astype(np.int16)
        signed_gray = np.mean(observed_region, axis=2) - np.mean(reference_region, axis=2)
        mean_signed = float(np.mean(signed_gray[region_mask])) if np.any(region_mask) else 0.0
        fill_ratio = changed_pixels / max(1, w * h)
        defect_type = self._classify(w, h, fill_ratio, mean_signed)
        if defect_type is None:
            return None
        name, severity = self._TYPE_DETAILS[defect_type]
        signal_values = np.max(np.abs(observed_region - reference_region), axis=2)[region_mask]
        signal = min(1.0, float(np.mean(signal_values)) / 90.0)
        confidence = round(
            min(0.99, 0.72 + 0.18 * signal + 0.09 * min(1.0, fill_ratio * 2.0)), 3
        )
        frame_bbox = BBox(x=x, y=y, w=w, h=h)
        source_bbox = BBox(x=x, y=packet.viewport_top_px + y, w=w, h=h)
        return _Candidate(
            lane_id, defect_type, name, confidence, severity, frame_bbox, source_bbox
        )

    @staticmethod
    def _classify(w: int, h: int, fill_ratio: float, mean_signed: float) -> str | None:
        if 10 <= w <= 38 and 10 <= h <= 38 and mean_signed > 12.0:
            return "pinhole"
        if w <= 34 and h >= 22:
            return "streak"
        if w >= 180:
            if h < 16:
                return None
            return "color_shift"
        if w >= 85 and h <= 85:
            if h < 10:
                return None
            return "contamination" if fill_ratio < 0.42 else "missing_ink"
        if w >= 55 and fill_ratio < 0.5:
            return "contamination"
        if w >= 35 and h >= 18 and mean_signed < -8.0:
            return "dark_spot"
        return None

    def _track(self, packet: FramePacket, candidate: _Candidate) -> Detection:
        box = candidate.source_bbox
        tracks = self._tracks.setdefault(packet.roll_id, [])
        match: _Track | None = None
        best_score = float("inf")
        for track in tracks:
            if track.lane_id != candidate.lane_id:
                continue
            vertical_gap = max(0, max(track.y0, box.y) - min(track.y1, box.y + box.h))
            horizontal_gap = max(0, max(track.x0, box.x) - min(track.x1, box.x + box.w))
            if vertical_gap > 12 or horizontal_gap > 24:
                continue
            score = vertical_gap * 4 + horizontal_gap
            if score < best_score:
                match = track
                best_score = score

        if match is None:
            match = _Track(
                track_id=f"CV-{self._next_track:06d}",
                roll_id=packet.roll_id,
                lane_id=candidate.lane_id,
                defect_type=candidate.defect_type,
                defect_name=candidate.defect_name,
                confidence=candidate.confidence,
                severity=candidate.severity,
                x0=box.x,
                x1=box.x + box.w,
                y0=box.y,
                y1=box.y + box.h,
                last_frame_id=packet.frame_id,
            )
            self._next_track += 1
            tracks.append(match)
        else:
            match.x0 = min(match.x0, box.x)
            match.x1 = max(match.x1, box.x + box.w)
            match.y0 = min(match.y0, box.y)
            match.y1 = max(match.y1, box.y + box.h)
            match.last_frame_id = packet.frame_id
            if candidate.defect_type in {
                "streak",
                "color_shift",
                "missing_ink",
                "contamination",
            }:
                match.defect_type = candidate.defect_type
                match.defect_name = candidate.defect_name
                match.severity = candidate.severity
            match.confidence = max(match.confidence, candidate.confidence)

        ppm = self.config.master_roll.pixels_per_meter
        source_bbox = BBox(match.x0, match.y0, match.x1 - match.x0, match.y1 - match.y0)
        return Detection(
            annotation_id=match.track_id,
            lane_id=match.lane_id,
            defect_type=match.defect_type,
            defect_name=match.defect_name,
            confidence=match.confidence,
            severity=match.severity,
            absolute_position_m=max(0.0, match.y0 / ppm),
            physical_interval=(max(0.0, match.y0 / ppm), max(0.0, match.y1 / ppm)),
            frame_bbox=candidate.frame_bbox,
            source_bbox=source_bbox,
        )
