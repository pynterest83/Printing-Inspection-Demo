from __future__ import annotations

import math
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from typing import Any

import cv2

from .config import AppConfig
from .database import Database
from .detector import MockDetector, ReferenceDiffDetector
from .models import AlarmLevel, Detection, MachineStatus, iso_utc, utc_now
from .scenario import ensure_synthetic_assets
from .source import MockImageSource


class InvalidTransition(RuntimeError):
    pass


def distance_for(speed_m_min: float, delta_seconds: float) -> float:
    return speed_m_min / 60.0 * delta_seconds


def speed_for_elapsed(elapsed: float) -> float:
    if elapsed < 20.0:
        base = 200.0 + elapsed / 20.0 * 30.0
    elif elapsed < 60.0:
        base = 230.0 + (elapsed - 20.0) / 40.0 * 10.0
    elif elapsed < 100.0:
        base = 240.0 + (elapsed - 60.0) / 40.0 * 20.0
    elif elapsed < 140.0:
        base = 260.0 + (elapsed - 100.0) / 40.0 * 30.0
    elif elapsed < 170.0:
        base = 290.0 - (elapsed - 140.0) / 30.0 * 40.0
    else:
        base = 250.0
    noise = math.sin(elapsed * 0.73) * 0.65 + math.sin(elapsed * 0.11) * 0.25
    return base + noise


def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def overlap_length(start: float, end: float, intervals: list[tuple[float, float]]) -> float:
    if end <= start:
        return 0.0
    return sum(max(0.0, min(end, interval_end) - max(start, interval_start)) for interval_start, interval_end in intervals)


class InspectionEngine:
    def __init__(self, config: AppConfig):
        self.config = config
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.ready = False
        self.database = Database(config.storage_path)
        now = utc_now()
        self.database.interrupt_open_rolls(now)
        inspection_path, reference_path, ground_truth = ensure_synthetic_assets(config)
        self.source = MockImageSource(config, inspection_path)
        if config.detector.mode == "mock":
            self.detector = MockDetector(ground_truth)
        else:
            self.detector = ReferenceDiffDetector(config, reference_path)

        self.machine_status = MachineStatus.IDLE
        self.alarm = self._normal_alarm()
        self.alarm_latched = False
        self.position_m = 0.0
        self.bad_m = 0.0
        self.speed_m_min = config.machine.initial_speed_m_min
        self.running_elapsed = 0.0
        self.frame_id = 0
        self.roll_no = 0
        self.roll_id = self._make_roll_id()
        self.database.create_roll(self.roll_id, self.machine_status.value, now)
        self.emitted: set[str] = set()
        self.detected_intervals: dict[str, tuple[float, float]] = {}
        self.detected_tracks: dict[str, Detection] = {}
        self.current_detections: list[Detection] = []
        self.defect_positions: dict[int, deque[float]] = defaultdict(deque)
        self.lane_hold_until: dict[int, float] = defaultdict(float)
        self.consecutive_triggered = False
        self.latest_jpeg: bytes | None = None
        self.sequence = 0
        self.events: deque[dict[str, Any]] = deque(maxlen=1000)
        self.last_checkpoint = 0.0
        self.last_jpeg_at = 0.0

    def start_background(self) -> None:
        self.source.start()
        self.detector.start()
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="inspection-engine", daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.ready and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.ready:
            raise RuntimeError("Inspection engine failed to become ready")

    def shutdown(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        with self.lock:
            self._checkpoint(utc_now())
        self.source.stop()
        self.detector.stop()
        self.ready = False

    def command_start(self) -> dict[str, Any]:
        with self.lock:
            if self.machine_status == MachineStatus.PLC_STOP:
                raise InvalidTransition("Reset is required before starting after PLC stop")
            if self.machine_status != MachineStatus.RUNNING:
                self.machine_status = MachineStatus.RUNNING
                now = utc_now()
                self.database.update_roll(
                    self.roll_id,
                    status=self.machine_status.value,
                    total_m=self.position_m,
                    good_m=self.good_m,
                    bad_m=self.bad_m,
                    now=now,
                )
                self._append_event("machine.changed", {"machine_status": self.machine_status.value}, now)
            return self.status_snapshot()

    def command_stop(self) -> dict[str, Any]:
        with self.lock:
            if self.machine_status == MachineStatus.RUNNING:
                self.machine_status = MachineStatus.STOPPED
                now = utc_now()
                self._checkpoint(now)
                self._append_event("machine.changed", {"machine_status": self.machine_status.value}, now)
            return self.status_snapshot()

    def command_reset(self) -> dict[str, Any]:
        with self.lock:
            if self.machine_status == MachineStatus.RUNNING:
                raise InvalidTransition("Stop the machine before resetting")
            now = utc_now()
            self.database.update_roll(
                self.roll_id,
                status="RESET",
                total_m=self.position_m,
                good_m=self.good_m,
                bad_m=self.bad_m,
                now=now,
                final=True,
                stop_reason="Operator reset",
            )
            self._reset_roll(MachineStatus.IDLE, now)
            self._append_event("machine.changed", {"machine_status": self.machine_status.value}, now)
            return self.status_snapshot()

    @property
    def good_m(self) -> float:
        return max(0.0, self.position_m - self.bad_m)

    def status_snapshot(self) -> dict[str, Any]:
        with self.lock:
            total = self.position_m
            bad_ratio = self.bad_m / total * 100 if total else 0.0
            now_monotonic = time.monotonic()
            lanes = [
                {
                    "lane_id": lane,
                    "status": "NG" if self._lane_is_bad(lane, now_monotonic) else "OK",
                }
                for lane in range(1, self.config.lanes.count + 1)
            ]
            return {
                "machine_status": self.machine_status.value,
                "detector_mode": self.config.detector.mode,
                "speed_m_min": round(self.speed_m_min if self.machine_status == MachineStatus.RUNNING else 0.0, 1),
                "position_m": round(self.position_m, 3),
                "frame_id": self.frame_id,
                "roll": {
                    "roll_id": self.roll_id,
                    "status": self.machine_status.value,
                    "total_m": round(total, 3),
                    "good_m": round(self.good_m, 3),
                    "bad_m": round(self.bad_m, 3),
                    "bad_ratio": round(bad_ratio, 3),
                },
                "lanes": lanes,
                "alarm": dict(self.alarm),
            }

    def snapshot_envelope(self) -> dict[str, Any]:
        with self.lock:
            defects = self.database.list_defects(self.roll_id, 50, 0)["items"]
            return {
                "type": "snapshot",
                "sequence": self.sequence,
                "timestamp": iso_utc(),
                "data": {"status": self.status_snapshot(), "defects": defects},
            }

    def telemetry_envelope(self) -> dict[str, Any]:
        with self.lock:
            return {
                "type": "telemetry",
                "sequence": self.sequence,
                "timestamp": iso_utc(),
                "data": self.status_snapshot(),
            }

    def events_after(self, sequence: int) -> list[dict[str, Any]]:
        with self.lock:
            return [event for event in self.events if event["sequence"] > sequence]

    def frame_bytes(self) -> bytes | None:
        with self.lock:
            return self.latest_jpeg

    def _run(self) -> None:
        previous_tick = time.monotonic()
        frame_period = 1.0 / self.config.frame.engine_fps
        next_tick = previous_tick
        try:
            self._render_frame(previous_tick)
            self.ready = True
            while not self.stop_event.is_set():
                now_tick = time.monotonic()
                if now_tick < next_tick:
                    self.stop_event.wait(min(next_tick - now_tick, 0.02))
                    continue
                dt = min(max(now_tick - previous_tick, 0.0), 0.25)
                previous_tick = now_tick
                next_tick = now_tick + frame_period
                with self.lock:
                    if self.machine_status == MachineStatus.RUNNING:
                        self._advance(dt, now_tick)
                    if now_tick - self.last_jpeg_at >= 1.0 / self.config.frame.jpeg_fps:
                        self._render_frame(now_tick)
                    if now_tick - self.last_checkpoint >= 1.0:
                        self._checkpoint(utc_now())
                        self.last_checkpoint = now_tick
        finally:
            self.ready = False

    def _advance(self, dt: float, monotonic_now: float) -> None:
        previous_position = self.position_m
        self.running_elapsed += dt
        self.speed_m_min = max(
            self.config.machine.min_speed_m_min,
            min(self.config.machine.max_speed_m_min, speed_for_elapsed(self.running_elapsed)),
        )
        movement = distance_for(self.speed_m_min, dt)
        self.position_m = min(self.config.master_roll.length_m, previous_position + movement)
        self.frame_id += 1

        packet = self.source.read(
            frame_id=self.frame_id,
            captured_at=utc_now(),
            roll_id=self.roll_id,
            position_m=self.position_m,
            loop_no=self.roll_no,
        )
        detections = self.detector.detect(packet)
        self.current_detections = detections
        for detection in detections:
            known = self.detected_intervals.get(detection.annotation_id)
            start, end = detection.physical_interval
            if known:
                start, end = min(start, known[0]), max(end, known[1])
            self.detected_intervals[detection.annotation_id] = (start, end)
            self.detected_tracks[detection.annotation_id] = detection
            if detection.annotation_id not in self.emitted and detection.absolute_position_m <= self.position_m:
                self._emit_defect(detection, monotonic_now)

        discovered_bad = merge_intervals(list(self.detected_intervals.values()))
        self.bad_m = overlap_length(0.0, self.position_m, discovered_bad)

        self._evaluate_alarm(detections)
        if self.position_m >= self.config.master_roll.length_m and self.machine_status == MachineStatus.RUNNING:
            now = utc_now()
            self.database.update_roll(
                self.roll_id,
                status="COMPLETED",
                total_m=self.position_m,
                good_m=self.good_m,
                bad_m=self.bad_m,
                now=now,
                final=True,
            )
            self._reset_roll(MachineStatus.RUNNING, now)
            self._append_event("machine.changed", {"machine_status": self.machine_status.value, "new_roll": True}, now)

    def _render_frame(self, monotonic_now: float) -> None:
        packet = self.source.read(
            frame_id=self.frame_id,
            captured_at=utc_now(),
            roll_id=self.roll_id,
            position_m=self.position_m,
            loop_no=self.roll_no,
        )
        detections = self.detector.detect(packet)
        self.current_detections = detections
        frame = packet.image
        for lane in range(1, self.config.lanes.count):
            x = lane * self.config.lanes.width + (lane - 1) * self.config.lanes.gap + self.config.lanes.gap // 2
            cv2.line(frame, (x, 0), (x, frame.shape[0]), (18, 25, 32), 3)
        for detection in detections:
            self._draw_detection(frame, detection)
        if self.position_m <= 0.001:
            cv2.putText(frame, "ROLL READY - PRESS START", (570, 320), cv2.FONT_HERSHEY_DUPLEX, 1.2, (80, 220, 255), 3, cv2.LINE_AA)
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, self.config.frame.jpeg_quality],
        )
        if ok:
            self.latest_jpeg = encoded.tobytes()
            self.last_jpeg_at = monotonic_now

    @staticmethod
    def _draw_detection(frame: Any, detection: Detection) -> None:
        box = detection.frame_bbox
        x0 = max(0, box.x)
        y0 = max(0, box.y)
        x1 = min(frame.shape[1] - 1, box.x + box.w)
        y1 = min(frame.shape[0] - 1, box.y + box.h)
        if x1 <= x0 or y1 <= y0:
            return
        color = (0, 70, 255) if detection.severity in {"high", "critical"} else (0, 190, 255)
        cv2.rectangle(frame, (x0, y0), (x1, y1), color, 3)
        label = f"L{detection.lane_id} {detection.defect_name} {detection.confidence:.0%}"
        text_y = max(24, y0 - 8)
        cv2.rectangle(frame, (x0, text_y - 22), (min(frame.shape[1] - 1, x0 + 300), text_y + 4), (14, 20, 28), -1)
        cv2.putText(frame, label, (x0 + 5, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, color, 2, cv2.LINE_AA)

    def _emit_defect(self, detection: Detection, monotonic_now: float) -> None:
        self.emitted.add(detection.annotation_id)
        self.defect_positions[detection.lane_id].append(detection.absolute_position_m)
        self.lane_hold_until[detection.lane_id] = max(
            self.lane_hold_until[detection.lane_id],
            monotonic_now + self.config.demo.lane_status_hold_seconds,
        )
        event_id = f"DEF-{uuid.uuid4().hex[:12].upper()}"
        now = utc_now()
        thumbnail_dir = self.config.storage_path / "thumbnails" / self.roll_id
        thumbnail_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_path = thumbnail_dir / f"{event_id}.jpg"
        crop = self.source.crop_global(detection.source_bbox)
        cv2.imwrite(str(thumbnail_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        data = {
            "id": event_id,
            "annotation_id": detection.annotation_id,
            "timestamp": iso_utc(now),
            "roll_id": self.roll_id,
            "lane_id": detection.lane_id,
            "position_m": round(detection.absolute_position_m, 3),
            "end_position_m": round(detection.physical_interval[1], 3),
            "defect_type": detection.defect_type,
            "defect_name": detection.defect_name,
            "confidence": detection.confidence,
            "severity": detection.severity,
            "area_mm2": round(detection.source_bbox.w * detection.source_bbox.h / 950.0, 2),
            "length_mm": round((detection.physical_interval[1] - detection.physical_interval[0]) * 1000, 1),
            "bbox": detection.frame_bbox.as_dict(),
            "image_url": f"/api/defects/{event_id}/thumbnail.jpg",
        }
        relative_path = str(thumbnail_path.relative_to(self.config.storage_path))
        self.database.add_defect(data, relative_path)
        self._append_event("defect.created", data, now)

    def _evaluate_alarm(self, detections: list[Detection]) -> None:
        if self.alarm_latched:
            return
        self.consecutive_triggered = False
        for lane, positions in self.defect_positions.items():
            while positions and positions[0] < self.position_m - self.config.alarm.consecutive_window_m:
                positions.popleft()
            if len(positions) < self.config.alarm.consecutive_defects:
                continue
            self.consecutive_triggered = True

        continuous = None
        line_tolerance_m = max(0.1, self.speed_m_min / 60.0 / self.config.frame.engine_fps * 2.0)
        for item in detections:
            if item.defect_type != "streak":
                continue
            start, detected_end = self.detected_intervals.get(item.annotation_id, item.physical_interval)
            if self.position_m < start or detected_end < self.position_m - line_tolerance_m:
                continue
            progress = min(self.position_m, detected_end) - start
            if progress >= self.config.alarm.continuous_stop_m:
                continuous = (AlarmLevel.ALARM, "CONTINUOUS_STREAK_STOP", "Continuous streak exceeded stop threshold", item.lane_id)
                break
            if progress >= self.config.alarm.continuous_warning_m:
                continuous = (AlarmLevel.WARNING, "CONTINUOUS_STREAK", "Continuous streak detected", item.lane_id)

        ratio = self.bad_m / self.position_m * 100 if self.position_m else 0.0
        candidate: tuple[AlarmLevel, str, str, int | None]
        if continuous:
            candidate = continuous
        elif self.consecutive_triggered:
            candidate = (AlarmLevel.WARNING, "CONSECUTIVE_DEFECTS", "Five defects detected within 10 m", self._consecutive_lane())
        elif self.position_m >= self.config.alarm.bad_ratio_min_length_m and ratio > self.config.alarm.bad_ratio_warning_percent:
            candidate = (AlarmLevel.WARNING, "BAD_RATIO", f"Bad ratio is {ratio:.2f}%", None)
        else:
            candidate = (AlarmLevel.NORMAL, "CLEAR", "No active alarm", None)

        level, code, message, lane_id = candidate
        if code == self.alarm["code"] and level.value == self.alarm["level"]:
            return
        now = utc_now()
        self.alarm = {
            "level": level.value,
            "code": code,
            "message": message,
            "lane_id": lane_id,
            "position_m": round(self.position_m, 3),
            "timestamp": iso_utc(now),
        }
        self.database.add_alarm({"roll_id": self.roll_id, **self.alarm})
        self._append_event("alarm.changed", dict(self.alarm), now)
        if level == AlarmLevel.ALARM:
            self.alarm_latched = True
            self.machine_status = MachineStatus.PLC_STOP
            self.database.update_roll(
                self.roll_id,
                status=self.machine_status.value,
                total_m=self.position_m,
                good_m=self.good_m,
                bad_m=self.bad_m,
                now=now,
                stop_reason=message,
            )
            self._append_event("machine.changed", {"machine_status": self.machine_status.value}, now)

    def _consecutive_lane(self) -> int | None:
        for lane, positions in self.defect_positions.items():
            if len(positions) >= self.config.alarm.consecutive_defects:
                return lane
        return None

    def _lane_is_bad(self, lane: int, monotonic_now: float) -> bool:
        if monotonic_now < self.lane_hold_until[lane]:
            return True
        tolerance = 0.1
        return any(
            item.lane_id == lane
            and item.physical_interval[0] <= self.position_m
            and item.physical_interval[1] >= self.position_m - tolerance
            for item in self.current_detections
        )

    def _checkpoint(self, now: datetime) -> None:
        self.database.update_roll(
            self.roll_id,
            status=self.machine_status.value,
            total_m=self.position_m,
            good_m=self.good_m,
            bad_m=self.bad_m,
            now=now,
            stop_reason=self.alarm["message"] if self.machine_status == MachineStatus.PLC_STOP else None,
        )

    def _reset_roll(self, status: MachineStatus, now: datetime) -> None:
        self.roll_no += 1
        self.roll_id = self._make_roll_id()
        self.machine_status = status
        self.position_m = 0.0
        self.bad_m = 0.0
        self.speed_m_min = self.config.machine.initial_speed_m_min
        self.running_elapsed = 0.0
        self.frame_id = 0
        self.emitted.clear()
        self.detected_intervals.clear()
        self.detected_tracks.clear()
        self.current_detections.clear()
        self.defect_positions.clear()
        self.lane_hold_until.clear()
        self.consecutive_triggered = False
        self.alarm_latched = False
        self.alarm = self._normal_alarm()
        self.database.create_roll(self.roll_id, status.value, now)
        self._render_frame(time.monotonic())

    def _append_event(self, event_type: str, data: dict[str, Any], now: datetime) -> None:
        self.sequence += 1
        self.events.append(
            {
                "type": event_type,
                "sequence": self.sequence,
                "timestamp": iso_utc(now),
                "data": data,
            }
        )

    def _make_roll_id(self) -> str:
        stamp = utc_now().strftime("%Y%m%d-%H%M%S")
        return f"ROLL-{stamp}-{uuid.uuid4().hex[:4].upper()}"

    @staticmethod
    def _normal_alarm() -> dict[str, Any]:
        return {
            "level": AlarmLevel.NORMAL.value,
            "code": "CLEAR",
            "message": "No active alarm",
            "lane_id": None,
            "position_m": 0.0,
            "timestamp": iso_utc(),
        }
