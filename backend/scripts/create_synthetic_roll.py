#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import load_config  # noqa: E402
from app.scenario import ensure_synthetic_assets  # noqa: E402


def main() -> None:
    config = load_config()
    inspection_path, reference_path, annotations = ensure_synthetic_assets(config)
    print(f"Clean reference: {reference_path}")
    print(f"Inspection roll: {inspection_path}")
    print(f"Dimensions: {config.master_roll.width}x{config.master_roll.height}")
    print(f"Logical length: {config.master_roll.length_m:.1f} m")
    print(f"Annotations: {len(annotations)}")


if __name__ == "__main__":
    main()
