#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import os
import time
import urllib.request
from pathlib import Path


DATASET_URL = "https://zenodo.org/api/records/15318946/files/Taktpixel2025PD-CD.zip/content"
DATASET_SIZE = 640_266_819
DATASET_MD5 = "157ee2371e1fad27b77442a78d7ee63c"


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_range(url: str, start: int, end: int, retries: int = 6) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = response.read()
            expected = end - start + 1
            if len(payload) != expected:
                raise RuntimeError(f"range {start}-{end}: expected {expected} bytes, got {len(payload)}")
            return start, payload
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(min(30, 2**attempt))
    raise RuntimeError("unreachable")


def download(output: Path, workers: int, chunk_size: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    ranges = [
        (start, min(DATASET_SIZE - 1, start + chunk_size - 1))
        for start in range(0, DATASET_SIZE, chunk_size)
    ]
    descriptor = os.open(temporary, os.O_CREAT | os.O_RDWR, 0o644)
    os.ftruncate(descriptor, DATASET_SIZE)
    completed = 0
    started = time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_download_range, DATASET_URL, start, end): (start, end)
                for start, end in ranges
            }
            for future in concurrent.futures.as_completed(futures):
                start, payload = future.result()
                os.pwrite(descriptor, payload, start)
                completed += len(payload)
                elapsed = max(0.001, time.monotonic() - started)
                print(
                    f"Downloaded {completed / 1024 / 1024:.1f}/{DATASET_SIZE / 1024 / 1024:.1f} MiB "
                    f"({completed / DATASET_SIZE * 100:.1f}%) at {completed / elapsed / 1024 / 1024:.1f} MiB/s",
                    flush=True,
                )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

    checksum = _md5(temporary)
    if checksum != DATASET_MD5:
        raise RuntimeError(f"checksum mismatch: {checksum} != {DATASET_MD5}")
    temporary.replace(output)
    print(f"Dataset ready: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Taktpixel2025PD-CD with parallel ranges")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--chunk-mib", type=int, default=8)
    arguments = parser.parse_args()
    if arguments.output.exists():
        if arguments.output.stat().st_size == DATASET_SIZE and _md5(arguments.output) == DATASET_MD5:
            print(f"Dataset already exists and checksum is valid: {arguments.output}")
            return
        print(f"Removing invalid existing download: {arguments.output}")
        arguments.output.unlink()
    download(arguments.output, max(1, arguments.workers), max(1, arguments.chunk_mib) * 1024 * 1024)


if __name__ == "__main__":
    main()
