#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import load_config  # noqa: E402
from app.detector import ReferenceDiffDetector  # noqa: E402
from app.models import utc_now  # noqa: E402
from app.scenario import ensure_synthetic_assets  # noqa: E402
from app.source import MockImageSource  # noqa: E402


def main() -> None:
    config = load_config({"detector": {"mode": "reference_diff"}})
    inspection_path, reference_path, ground_truth = ensure_synthetic_assets(config)
    source = MockImageSource(config, inspection_path)
    detector = ReferenceDiffDetector(config, reference_path)
    source.start()
    detector.start()
    predictions = {}
    try:
        positions = sorted({item.end_position_m + 0.2 for item in ground_truth})
        for frame_id, position_m in enumerate(positions, start=1):
            packet = source.read(
                frame_id=frame_id,
                captured_at=utc_now(),
                roll_id="OFFLINE-EVALUATION",
                position_m=position_m,
                loop_no=0,
            )
            for detection in detector.detect(packet):
                predictions[detection.annotation_id] = detection
    finally:
        detector.stop()
        source.stop()

    unmatched = set(predictions)
    correct = 0
    type_errors: list[str] = []
    misses: list[str] = []
    for expected in ground_truth:
        candidates = [
            prediction
            for key, prediction in predictions.items()
            if key in unmatched
            and prediction.lane_id == expected.lane_id
            and abs(prediction.absolute_position_m - expected.position_m) <= 0.25
        ]
        if not candidates:
            misses.append(expected.annotation_id)
            continue
        prediction = min(
            candidates, key=lambda item: abs(item.absolute_position_m - expected.position_m)
        )
        unmatched.remove(prediction.annotation_id)
        if prediction.defect_type == expected.defect_type:
            correct += 1
        else:
            type_errors.append(
                f"{expected.annotation_id}: expected {expected.defect_type}, got {prediction.defect_type}"
            )

    matched = len(ground_truth) - len(misses)
    precision = matched / len(predictions) if predictions else 0.0
    recall = matched / len(ground_truth) if ground_truth else 0.0
    classification_accuracy = correct / matched if matched else 0.0
    print(f"Ground truth: {len(ground_truth)}")
    print(f"Predictions:  {len(predictions)}")
    print(f"Precision:    {precision:.3f}")
    print(f"Recall:       {recall:.3f}")
    print(f"Type accuracy:{classification_accuracy:>9.3f}")
    if misses:
        print(f"Misses: {', '.join(misses)}")
    if type_errors:
        print("Type errors:")
        for error in type_errors:
            print(f"  - {error}")
    if unmatched:
        print(f"False positives: {', '.join(sorted(unmatched))}")
    if misses or type_errors or unmatched:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
