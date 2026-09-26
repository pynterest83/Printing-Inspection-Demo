#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import load_config  # noqa: E402
from app.scenario import default_scenario  # noqa: E402


CATEGORY_FOR_TYPE = {
    "dark_spot": "blackspot",
    "color_shift": "colorshift",
    "missing_ink": "friction",
    "contamination": "hair",
    "streak": "line",
    "pinhole": "pinhole",
}


def _decode(archive: zipfile.ZipFile, member: str, grayscale: bool = False) -> np.ndarray:
    raw = np.frombuffer(archive.read(member), dtype=np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Unable to decode dataset member: {member}")
    return image


def _cover(image: np.ndarray, width: int, height: int, interpolation: int) -> np.ndarray:
    source_height, source_width = image.shape[:2]
    scale = max(width / source_width, height / source_height)
    resized = cv2.resize(
        image,
        (max(width, round(source_width * scale)), max(height, round(source_height * scale))),
        interpolation=interpolation,
    )
    x = max(0, (resized.shape[1] - width) // 2)
    y = max(0, (resized.shape[0] - height) // 2)
    return resized[y : y + height, x : x + width].copy()


def _members(archive: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    groups: dict[str, dict[str, str]] = {"A": {}, "B": {}, "OUT": {}}
    for member in archive.namelist():
        normalized = "/" + member.replace("\\", "/").strip("/")
        if "/test/" not in normalized.lower() or normalized.endswith("/"):
            continue
        parts = normalized.split("/")
        for group in groups:
            if group in parts:
                groups[group][Path(member).name] = member
                break
    common = set(groups["A"]) & set(groups["B"]) & set(groups["OUT"])
    if not common:
        raise RuntimeError("No matching test/A, test/B and test/OUT image triplets found")
    return tuple({name: groups[group][name] for name in common} for group in ("A", "B", "OUT"))  # type: ignore[return-value]


def _mask_crop(mask: np.ndarray) -> tuple[int, int, int, int]:
    _, binary = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
    if cv2.countNonZero(binary) > binary.size // 2:
        binary = cv2.bitwise_not(binary)
    points = cv2.findNonZero(binary)
    if points is None:
        raise RuntimeError("Dataset mask contains no defect pixels")
    x, y, w, h = cv2.boundingRect(points)
    margin_x = max(2, round(w * 0.05))
    margin_y = max(2, round(h * 0.05))
    return (
        max(0, x - margin_x),
        max(0, y - margin_y),
        min(mask.shape[1], x + w + margin_x),
        min(mask.shape[0], y + h + margin_y),
    )


def _apply_camera_noise(image: np.ndarray, rng: np.random.Generator, sigma: float, amplitude: float) -> None:
    height = image.shape[0]
    for y0 in range(0, height, 600):
        y1 = min(height, y0 + 600)
        rows = np.arange(y0, y1, dtype=np.float32)[:, None, None]
        banding = np.sin(rows * 0.071) * amplitude
        noise = rng.normal(0.0, sigma, (y1 - y0, image.shape[1], 1))
        block = image[y0:y1].astype(np.float32)
        np.clip(block + banding + noise, 0, 255, out=block)
        image[y0:y1] = block.astype(np.uint8)


def _packaging_repeat(path: Path, lane_width: int) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(
            f"Unable to load packaging artwork: {path}. "
            "Run backend/scripts/download_packaging_artwork.py first."
        )
    # The selected source photograph contains two vertically stacked copies
    # of the same carton artwork. Use the upper repeat as the web master.
    repeat = image[: image.shape[0] // 2]
    repeat_height = max(80, round(repeat.shape[0] * lane_width / repeat.shape[1]))
    return cv2.resize(repeat, (lane_width, repeat_height), interpolation=cv2.INTER_AREA)


def prepare(archive_path: Path, output: Path, packaging_artwork: Path) -> None:
    config = load_config({"dataset": {"mode": "taktpixel"}})
    templates = default_scenario(config)
    rng = np.random.default_rng(config.dataset.noise_seed)
    height, width = config.master_roll.height, config.master_roll.width
    reference = np.full((height, width, 3), (24, 28, 34), dtype=np.uint8)

    with zipfile.ZipFile(archive_path) as archive:
        masters, targets, masks = _members(archive)
        by_category: dict[str, list[str]] = defaultdict(list)
        for name in sorted(masters):
            lowered = name.lower()
            for category in set(CATEGORY_FOR_TYPE.values()):
                if category in lowered:
                    by_category[category].append(name)
                    break
        missing_categories = [name for name in set(CATEGORY_FOR_TYPE.values()) if not by_category[name]]
        if missing_categories:
            raise RuntimeError(f"Dataset categories missing from test split: {missing_categories}")

        # Prefer clear, high-signal examples while keeping all pixels sourced
        # from the real A/B pairs. This prevents JPEG/noise augmentation from
        # hiding very faint benchmark samples in the live demonstration.
        for category, names in by_category.items():
            scored: list[tuple[float, str]] = []
            for name in names:
                master = _decode(archive, masters[name])
                target = _decode(archive, targets[name])
                mask = _decode(archive, masks[name], grayscale=True)
                foreground = mask > 127
                if float(np.mean(foreground)) > 0.5:
                    foreground = ~foreground
                difference = np.max(cv2.absdiff(master, target), axis=2)
                score = float(np.mean(difference[foreground])) if np.any(foreground) else 0.0
                scored.append((score, name))
            by_category[category] = [name for _, name in sorted(scored, reverse=True)]

        packaging_repeat = _packaging_repeat(packaging_artwork, config.lanes.width)
        tile_height = packaging_repeat.shape[0]
        stride = config.lanes.width + config.lanes.gap
        for lane in range(config.lanes.count):
            x0 = lane * stride
            for y0 in range(0, height, tile_height):
                repeat_height = min(tile_height, height - y0)
                reference[y0 : y0 + repeat_height, x0 : x0 + config.lanes.width] = (
                    packaging_repeat[:repeat_height]
                )

        inspection = reference.copy()
        category_offsets: dict[str, int] = defaultdict(int)
        sources: list[dict[str, object]] = []
        for template in templates:
            category = CATEGORY_FOR_TYPE[template.defect_type]
            candidates = by_category[category]
            name = candidates[category_offsets[category] % len(candidates)]
            if category != "line":
                category_offsets[category] += 1
            master = _decode(archive, masters[name])
            target = _decode(archive, targets[name])
            mask = _decode(archive, masks[name], grayscale=True)
            x0, y0, x1, y1 = _mask_crop(mask)
            master_crop = master[y0:y1, x0:x1]
            target_crop = target[y0:y1, x0:x1]
            mask_crop = mask[y0:y1, x0:x1]
            if cv2.countNonZero(mask_crop) > mask_crop.size // 2:
                mask_crop = cv2.bitwise_not(mask_crop)
            box = template.bbox
            master_patch = cv2.resize(master_crop, (box.w, box.h), interpolation=cv2.INTER_AREA)
            target_patch = cv2.resize(target_crop, (box.w, box.h), interpolation=cv2.INTER_AREA)
            resized_mask = cv2.resize(mask_crop, (box.w, box.h), interpolation=cv2.INTER_NEAREST)
            _, resized_mask = cv2.threshold(resized_mask, 127, 255, cv2.THRESH_BINARY)
            if template.defect_type == "color_shift":
                # A color shift is a region-level defect. The source mask can
                # contain separated islands, so apply its real A/B change to
                # the full prepared region to preserve a continuous 12 m run.
                resized_mask.fill(255)
            alpha = (resized_mask.astype(np.float32) / 255.0)[..., None]
            # Transfer only the real defect residual (B - A) onto the package
            # master. This keeps the packaging artwork continuous instead of
            # exposing rectangular crops from the source benchmark.
            package_region = inspection[
                box.y : box.y + box.h, box.x : box.x + box.w
            ].astype(np.float32)
            residual = target_patch.astype(np.float32) - master_patch.astype(np.float32)
            composite = package_region + residual * alpha
            inspection[box.y : box.y + box.h, box.x : box.x + box.w] = np.clip(
                composite, 0, 255
            ).astype(np.uint8)
            sources.append(
                {
                    "annotation_id": template.annotation_id,
                    "type": template.defect_type,
                    "dataset_category": category,
                    "dataset_file": name,
                    "bbox": template.bbox.as_dict(),
                }
            )

    blur = config.dataset.motion_blur_px
    if blur > 1:
        cv2.blur(reference, (1, blur), dst=reference)
        cv2.blur(inspection, (1, blur), dst=inspection)
    _apply_camera_noise(
        reference,
        np.random.default_rng(config.dataset.noise_seed + 1),
        config.dataset.gaussian_noise_sigma,
        config.dataset.scanline_amplitude,
    )
    _apply_camera_noise(
        inspection,
        np.random.default_rng(config.dataset.noise_seed + 2),
        config.dataset.gaussian_noise_sigma,
        config.dataset.scanline_amplitude,
    )

    output.mkdir(parents=True, exist_ok=True)
    reference_path = output / "reference_roll.jpg"
    inspection_path = output / "inspection_roll.jpg"
    if not cv2.imwrite(str(reference_path), reference, [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise RuntimeError(f"Unable to write {reference_path}")
    if not cv2.imwrite(str(inspection_path), inspection, [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise RuntimeError(f"Unable to write {inspection_path}")
    manifest = {
        "dataset": "Open Food Facts packaging artwork + Taktpixel2025PD-CD defects",
        "background": {
            "source": "Open Food Facts",
            "product_code": "3017760038676",
            "image": "front_fr.39.full.jpg",
            "license": "CC-BY-SA-3.0",
            "path": str(packaging_artwork),
        },
        "defects": {
            "source": "Taktpixel2025PD-CD",
            "doi": "10.5281/zenodo.15318946",
            "license": "CC-BY-SA-4.0",
        },
        "width": width,
        "height": height,
        "pixels_per_meter": config.master_roll.pixels_per_meter,
        "noise": config.dataset.model_dump(exclude={"assets_directory"}),
        "sources": sources,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Prepared Taktpixel roll: {output}")
    print(f"Defect samples: {len(sources)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a noisy five-lane roll from Taktpixel pairs")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=BACKEND_ROOT / "assets" / "taktpixel_roll")
    parser.add_argument(
        "--packaging-artwork",
        type=Path,
        default=BACKEND_ROOT / "assets" / "packaging" / "openfoodfacts_lulu.jpg",
    )
    arguments = parser.parse_args()
    prepare(arguments.archive, arguments.output, arguments.packaging_artwork)


if __name__ == "__main__":
    main()
