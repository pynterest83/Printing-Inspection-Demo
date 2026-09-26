from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

from .config import AppConfig
from .models import BBox, DefectTemplate


COLORS = {
    "dark_spot": (20, 20, 25),
    "color_shift": (60, 50, 220),
    "missing_ink": (225, 225, 225),
    "contamination": (35, 30, 30),
    "streak": (25, 35, 45),
    "pinhole": (245, 245, 245),
}


def lane_x(config: AppConfig, lane_id: int) -> int:
    return (lane_id - 1) * (config.lanes.width + config.lanes.gap)


def default_scenario(config: AppConfig) -> list[DefectTemplate]:
    ppm = config.master_roll.pixels_per_meter
    specs = [
        ("DARK-001", "dark_spot", "Dark Spot", 2, 40.0, 0.8, 44, 0.96, "medium"),
        ("PIN-001", "pinhole", "Pinhole", 5, 100.0, 0.5, 28, 0.94, "low"),
        ("INK-001", "missing_ink", "Missing Ink", 1, 180.0, 0.9, 150, 0.93, "high"),
        ("COLOR-001", "color_shift", "Color Shift", 3, 270.0, 12.0, 230, 0.91, "high"),
        ("HAIR-001", "contamination", "Contamination", 4, 360.0, 1.2, 110, 0.95, "medium"),
        ("LINE-001", "streak", "Streak", 4, 450.0, 1.5, 20, 0.97, "high"),
    ]
    for index, position in enumerate((520.0, 522.0, 524.0, 526.0, 528.0), start=1):
        specs.append((f"MULTI-{index:03d}", "dark_spot", "Dark Spot", 2, position, 0.7, 38, 0.92 + index * 0.01, "medium"))
    specs.append(("LINE-STOP", "streak", "Continuous Streak", 4, 600.0, 4.0, 24, 0.99, "critical"))

    templates: list[DefectTemplate] = []
    for annotation_id, kind, name, lane, position, length, width, confidence, severity in specs:
        x0 = lane_x(config, lane)
        x = x0 + (config.lanes.width - width) // 2
        height = max(12, round(length * ppm))
        y = round(position * ppm)
        templates.append(
            DefectTemplate(
                annotation_id=annotation_id,
                defect_type=kind,
                defect_name=name,
                lane_id=lane,
                position_m=position,
                end_position_m=position + height / ppm,
                confidence=min(confidence, 0.99),
                severity=severity,
                bbox=BBox(x=x, y=y, w=width, h=height),
            )
        )
    return templates


def ensure_synthetic_assets(config: AppConfig) -> tuple[Path, Path, list[DefectTemplate]]:
    data_dir = config.storage_path
    roll_dir = data_dir / "master_roll"
    annotations_dir = data_dir / "annotations"
    thumbnails_dir = data_dir / "thumbnails"
    roll_dir.mkdir(parents=True, exist_ok=True)
    annotations_dir.mkdir(parents=True, exist_ok=True)
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    annotation_path = annotations_dir / "annotations.json"
    templates = default_scenario(config)
    if config.dataset.mode == "taktpixel":
        reference_path = config.dataset.assets_path / "reference_roll.jpg"
        inspection_path = config.dataset.assets_path / "inspection_roll.jpg"
        missing = [str(path) for path in (reference_path, inspection_path) if not path.exists()]
        if missing:
            raise RuntimeError(
                "Prepared Taktpixel assets are missing: "
                + ", ".join(missing)
                + ". Run backend/scripts/prepare_taktpixel.py first."
            )
    else:
        reference_path = roll_dir / "reference_roll.jpg"
        inspection_path = roll_dir / "inspection_roll.jpg"
        signature_path = roll_dir / "signature.json"
        signature = {
            "width": config.master_roll.width,
            "height": config.master_roll.height,
            "ppm": config.master_roll.pixels_per_meter,
            "seed": config.demo.seed,
            "generator_version": 3,
        }
        existing_signature = None
        if signature_path.exists():
            try:
                existing_signature = json.loads(signature_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        if not reference_path.exists() or not inspection_path.exists() or existing_signature != signature:
            reference = _build_clean_roll(config)
            if not cv2.imwrite(str(reference_path), reference, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                raise RuntimeError(f"Unable to write clean reference roll to {reference_path}")
            inspection = reference.copy()
            for defect in templates:
                _draw_defect(inspection, defect)
            if not cv2.imwrite(str(inspection_path), inspection, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                raise RuntimeError(f"Unable to write synthetic inspection roll to {inspection_path}")
            signature_path.write_text(json.dumps(signature, indent=2), encoding="utf-8")
    annotation_path.write_text(
        json.dumps(
            {
                "roll_length_m": config.master_roll.length_m,
                "pixels_per_meter": config.master_roll.pixels_per_meter,
                "defects": [
                    {
                        "id": item.annotation_id,
                        "type": item.defect_type,
                        "name": item.defect_name,
                        "lane": item.lane_id,
                        "position_m": item.position_m,
                        "end_position_m": item.end_position_m,
                        "confidence": item.confidence,
                        "severity": item.severity,
                        "bbox": item.bbox.as_dict(),
                    }
                    for item in templates
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return inspection_path, reference_path, templates


def _build_clean_roll(config: AppConfig) -> np.ndarray:
    rng = np.random.default_rng(config.demo.seed)
    height, width = config.master_roll.height, config.master_roll.width
    image = np.full((height, width, 3), (27, 32, 38), dtype=np.uint8)
    tile_height = 300

    for lane in range(1, config.lanes.count + 1):
        x0 = lane_x(config, lane)
        x1 = x0 + config.lanes.width
        lane_color = (215 + lane * 3, 205 + lane * 2, 185 + lane * 2)
        image[:, x0:x1] = lane_color
        for y in range(0, height, tile_height):
            cv2.rectangle(image, (x0 + 16, y + 14), (x1 - 16, min(y + 284, height - 1)), (72, 82, 98), 3)
            cv2.rectangle(image, (x0 + 28, y + 28), (x1 - 28, min(y + 270, height - 1)), (235, 230, 215), -1)
            cv2.putText(image, "NOVA", (x0 + 82, y + 116), cv2.FONT_HERSHEY_DUPLEX, 1.45, (37, 72, 128), 3, cv2.LINE_AA)
            cv2.putText(image, f"PREMIUM  L{lane}", (x0 + 72, y + 165), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (65, 70, 75), 2, cv2.LINE_AA)
            cv2.putText(image, "PRINT CONTROL", (x0 + 76, y + 210), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (90, 96, 104), 1, cv2.LINE_AA)
            for dot in range(8):
                cx = x0 + 45 + dot * 38
                cv2.circle(image, (cx, min(y + 246, height - 1)), 7, (40 + dot * 15, 110, 165 - dot * 9), -1)

    # Add sparse deterministic texture without allocating another full-size float image.
    for _ in range(1800):
        y = int(rng.integers(0, height))
        x = int(rng.integers(0, width))
        shade = int(rng.integers(175, 235))
        cv2.circle(image, (x, y), 1, (shade, shade, shade), -1)

    return image


def _draw_defect(image: np.ndarray, defect: DefectTemplate) -> None:
    box = defect.bbox
    center = (box.x + box.w // 2, box.y + box.h // 2)
    if defect.defect_type == "dark_spot":
        cv2.ellipse(image, center, (box.w // 2, max(6, box.h // 2)), 18, 0, 360, COLORS[defect.defect_type], -1, cv2.LINE_AA)
        cv2.circle(image, (center[0] - 8, center[1] - 3), max(3, box.w // 8), (5, 5, 7), -1)
    elif defect.defect_type == "pinhole":
        cv2.circle(image, center, min(box.w, box.h) // 2, COLORS[defect.defect_type], -1, cv2.LINE_AA)
        cv2.circle(image, center, max(2, min(box.w, box.h) // 3), (255, 255, 255), -1, cv2.LINE_AA)
    elif defect.defect_type == "missing_ink":
        cv2.rectangle(image, (box.x, box.y), (box.x + box.w, box.y + box.h), COLORS[defect.defect_type], -1)
        for offset in range(0, box.w, 18):
            cv2.line(image, (box.x + offset, box.y), (box.x + offset + 8, box.y + box.h), (190, 190, 190), 2)
    elif defect.defect_type == "color_shift":
        roi = image[box.y : box.y + box.h, box.x : box.x + box.w]
        tint = np.full_like(roi, COLORS[defect.defect_type])
        cv2.addWeighted(tint, 0.33, roi, 0.67, 0, roi)
    elif defect.defect_type == "contamination":
        points = []
        for step in range(20):
            ratio = step / 19
            px = box.x + round(ratio * box.w)
            py = box.y + round(ratio * box.h + math.sin(ratio * math.pi * 4) * 12)
            points.append((px, py))
        cv2.polylines(image, [np.asarray(points, dtype=np.int32)], False, COLORS[defect.defect_type], 5, cv2.LINE_AA)
    elif defect.defect_type == "streak":
        cv2.rectangle(image, (box.x, box.y), (box.x + box.w, box.y + box.h), COLORS[defect.defect_type], -1)
        cv2.line(image, (center[0] - 3, box.y), (center[0] + 3, box.y + box.h), (0, 0, 0), max(2, box.w // 4), cv2.LINE_AA)
