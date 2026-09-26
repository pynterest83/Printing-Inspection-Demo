import pytest
import numpy as np
import cv2
from datetime import datetime, timezone

from app.config import AppConfig
from app.detector import MockDetector, ReferenceDiffDetector
from app.engine import distance_for, merge_intervals, overlap_length, speed_for_elapsed
from app.models import BBox, DefectTemplate, FramePacket


def test_240_m_per_minute_for_ten_seconds_is_40_metres():
    assert distance_for(240.0, 10.0) == pytest.approx(40.0)


def test_300_m_per_minute_for_ten_seconds_is_50_metres():
    assert distance_for(300.0, 10.0) == pytest.approx(50.0)


def test_speed_schedule_is_bounded_and_deterministic():
    values = [speed_for_elapsed(second) for second in range(0, 240)]
    assert min(values) >= 199.0
    assert max(values) <= 291.0
    assert speed_for_elapsed(80.0) == speed_for_elapsed(80.0)


def test_merge_intervals_prevents_double_counting():
    merged = merge_intervals([(10.0, 14.0), (12.0, 15.0), (20.0, 21.0)])
    assert merged == [(10.0, 15.0), (20.0, 21.0)]
    assert overlap_length(9.0, 22.0, merged) == pytest.approx(6.0)


def test_overlap_clips_to_travelled_segment():
    assert overlap_length(11.0, 13.0, [(10.0, 15.0)]) == pytest.approx(2.0)
    assert overlap_length(0.0, 9.0, [(10.0, 15.0)]) == 0.0


def test_detector_converts_global_bbox_to_frame_coordinates():
    annotation = DefectTemplate(
        annotation_id="D1",
        defect_type="dark_spot",
        defect_name="Dark Spot",
        lane_id=2,
        position_m=40.0,
        end_position_m=40.8,
        confidence=0.96,
        severity="medium",
        bbox=BBox(x=500, y=1600, w=40, h=32),
    )
    packet = FramePacket(
        frame_id=1,
        captured_at=datetime.now(timezone.utc),
        roll_id="ROLL-1",
        image=np.zeros((600, 1920, 3), dtype=np.uint8),
        position_m=45.0,
        viewport_start_m=30.0,
        viewport_end_m=45.0,
        loop_no=0,
        viewport_top_px=1200,
    )
    detections = MockDetector([annotation]).detect(packet)
    assert len(detections) == 1
    assert detections[0].frame_bbox == BBox(x=500, y=400, w=40, h=32)


def test_reference_detector_reads_pixels_and_tracks_without_annotations(tmp_path):
    config = AppConfig.model_validate(
        {
            "frame": {"width": 290, "height": 100},
            "master_roll": {
                "width": 290,
                "height": 400,
                "length_m": 10.0,
                "pixels_per_meter": 40.0,
            },
            "lanes": {"count": 5, "width": 50, "gap": 10},
            "detector": {
                "registration_enabled": False,
                "difference_threshold": 10,
                "min_component_area_px": 8,
            },
        }
    )
    reference = np.full((400, 290, 3), 210, dtype=np.uint8)
    inspected = reference.copy()
    cv2.ellipse(inspected, (84, 130), (18, 10), 0, 0, 360, (20, 20, 20), -1)
    reference_path = tmp_path / "reference.png"
    assert cv2.imwrite(str(reference_path), reference)

    detector = ReferenceDiffDetector(config, reference_path)
    detector.start()
    try:
        first = FramePacket(
            frame_id=1,
            captured_at=datetime.now(timezone.utc),
            roll_id="ROLL-PIXELS",
            image=inspected[100:200].copy(),
            position_m=5.0,
            viewport_start_m=2.5,
            viewport_end_m=5.0,
            loop_no=0,
            viewport_top_px=100,
        )
        second = FramePacket(
            frame_id=2,
            captured_at=datetime.now(timezone.utc),
            roll_id="ROLL-PIXELS",
            image=inspected[104:204].copy(),
            position_m=5.1,
            viewport_start_m=2.6,
            viewport_end_m=5.1,
            loop_no=0,
            viewport_top_px=104,
        )
        first_result = detector.detect(first)
        second_result = detector.detect(second)
    finally:
        detector.stop()

    assert len(first_result) == 1
    assert first_result[0].defect_type == "dark_spot"
    assert first_result[0].lane_id == 2
    assert second_result[0].annotation_id == first_result[0].annotation_id
    assert first_result[0].absolute_position_m == pytest.approx(2.975, abs=0.05)
