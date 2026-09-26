#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.request


def request_json(url: str, method: str = "GET") -> dict:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Wall-clock acceptance test at fixed 300 m/min")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--distance-tolerance", type=float, default=0.5)
    arguments = parser.parse_args()
    base = arguments.base_url.rstrip("/")

    status = request_json(f"{base}/api/status")
    if status["machine_status"] == "RUNNING":
        request_json(f"{base}/api/demo/stop", "POST")
    if status["machine_status"] != "IDLE" or status["position_m"] > 0:
        request_json(f"{base}/api/demo/reset", "POST")

    before = request_json(f"{base}/api/status")
    wall_start = time.monotonic()
    request_json(f"{base}/api/demo/start", "POST")
    try:
        deadline = wall_start + arguments.duration
        while time.monotonic() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        after = request_json(f"{base}/api/status")
    finally:
        request_json(f"{base}/api/demo/stop", "POST")

    elapsed = time.monotonic() - wall_start
    distance = after["position_m"] - before["position_m"]
    expected = 300.0 / 60.0 * elapsed
    error = abs(distance - expected)
    performance = after["performance"]
    result = {
        "elapsed_seconds": round(elapsed, 3),
        "expected_distance_m": round(expected, 3),
        "actual_distance_m": round(distance, 3),
        "distance_error_m": round(error, 3),
        **performance,
    }
    print(json.dumps(result, indent=2))

    failures = []
    if error > arguments.distance_tolerance:
        failures.append(f"distance error {error:.3f} m exceeds {arguments.distance_tolerance:.3f} m")
    if abs(performance["measured_speed_m_min"] - 300.0) > 1.0:
        failures.append("measured speed is not within 300 ± 1 m/min")
    if performance["input_fps"] < performance["target_input_fps"] * 0.95:
        failures.append("input FPS is below 95% of target")
    if performance["dropped_frames"] != 0:
        failures.append("frames were dropped")
    if performance["processing_p95_ms"] >= 1000.0 / performance["target_input_fps"]:
        failures.append("p95 processing latency exceeds the frame deadline")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        raise SystemExit(1)
    print("PASS: backend sustained the declared 300 m/min demo contract")


if __name__ == "__main__":
    main()
