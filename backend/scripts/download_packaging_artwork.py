#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path


ARTWORK_URL = (
    "https://images.openfoodfacts.org/images/products/301/776/003/8676/"
    "front_fr.39.full.jpg"
)
ARTWORK_SHA256 = "1025891e8f078a9401172e1a05ff9d224494981345fb5be69d22ff1497a96523"
ARTWORK_SIZE = 1_732_643


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(output: Path) -> None:
    if (
        output.exists()
        and output.stat().st_size == ARTWORK_SIZE
        and _sha256(output) == ARTWORK_SHA256
    ):
        print(f"Packaging artwork already exists and checksum is valid: {output}")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    request = urllib.request.Request(
        ARTWORK_URL,
        headers={"User-Agent": "PrintingInspectionDemo/1.0 (Open Food Facts reuse)"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    temporary.write_bytes(payload)
    if temporary.stat().st_size != ARTWORK_SIZE:
        raise RuntimeError(
            f"size mismatch: {temporary.stat().st_size} != {ARTWORK_SIZE}"
        )
    checksum = _sha256(temporary)
    if checksum != ARTWORK_SHA256:
        raise RuntimeError(f"checksum mismatch: {checksum} != {ARTWORK_SHA256}")
    temporary.replace(output)
    print(f"Packaging artwork ready: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download the openly licensed food-packaging artwork"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "assets"
        / "packaging"
        / "openfoodfacts_lulu.jpg",
    )
    arguments = parser.parse_args()
    download(arguments.output)


if __name__ == "__main__":
    main()
