#!/usr/bin/env python3
"""Simple compile endpoint benchmark for local/prod profiling."""

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request


def run_once(base_url: str, project_id: str, tex: str) -> float:
    payload = json.dumps({"project_id": project_id, "tex": tex}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/compile",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as response:
        response.read()
    return time.perf_counter() - start


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000", help="Compiler base URL")
    parser.add_argument("--runs", type=int, default=5, help="Number of benchmark runs")
    parser.add_argument("--project-id", default="bench-project", help="Project ID to use")
    args = parser.parse_args()

    tex = r"\documentclass{article}\begin{document}benchmark\end{document}"
    timings: list[float] = []

    for i in range(args.runs):
        try:
            duration = run_once(args.url, f"{args.project_id}-{i}", tex)
            timings.append(duration)
            print(f"run={i + 1} duration={duration:.3f}s")
        except urllib.error.HTTPError as exc:
            print(f"run={i + 1} failed with HTTP {exc.code}")
            return 1
        except Exception as exc:
            print(f"run={i + 1} failed: {exc}")
            return 1

    print(
        "summary "
        f"avg={statistics.mean(timings):.3f}s "
        f"median={statistics.median(timings):.3f}s "
        f"min={min(timings):.3f}s "
        f"max={max(timings):.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
