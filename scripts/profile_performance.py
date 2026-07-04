#!/usr/bin/env python3
"""Profile key app paths and print actionable performance metrics."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from eventcalendar.core.ics_builder import build_ics_from_events
from eventcalendar.core.image_preprocessing import preprocess_image_for_upload
from eventcalendar.ui.preview import format_date_display, parse_event_text


def _mean(values: List[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, int(len(ordered) * 0.95) - 1)
    return ordered[idx]


def _measure_import_ms(module: str, repeats: int = 5) -> Dict[str, float]:
    timings: List[float] = []
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_ROOT)
    snippet = (
        "import importlib,sys,time;"
        "mod=sys.argv[1];"
        "t=time.perf_counter();"
        "importlib.import_module(mod);"
        "print((time.perf_counter()-t)*1000)"
    )
    for _ in range(repeats):
        out = subprocess.check_output(
            [sys.executable, "-c", snippet, module],
            text=True,
            env=env,
        ).strip()
        timings.append(float(out))
    return {
        "mean_ms": round(_mean(timings), 3),
        "p95_ms": round(_p95(timings), 3),
    }


def benchmark_preview_parsing(iterations: int) -> Dict[str, float]:
    samples = [
        "Coffee with Sarah tomorrow at 2pm",
        "Team sync next Tuesday at 10:30am",
        "Project kickoff on March 30 at 9am at HQ",
        "Daily standup meetings Monday through Friday at 9:30am for 30 minutes",
        "Doctor appointment on March 15th at 2pm and follow-up visit on March 29th same time",
        "Dinner with Mia next Tuesday at 7pm",
    ]
    ref = datetime(2025, 1, 1, 12, 0, 0)
    start = time.perf_counter()
    for i in range(iterations):
        parse_event_text(samples[i % len(samples)], reference_date=ref)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return {
        "iterations": iterations,
        "total_ms": round(elapsed_ms, 3),
        "us_per_call": round((elapsed_ms * 1000) / iterations, 3),
    }


def benchmark_date_formatting(iterations: int) -> Dict[str, float]:
    samples = ["today", "tomorrow", "next friday", "March 30", "2025-12-01"]
    ref = datetime(2025, 1, 1, 12, 0, 0)
    start = time.perf_counter()
    for i in range(iterations):
        format_date_display(samples[i % len(samples)], reference_date=ref)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return {
        "iterations": iterations,
        "total_ms": round(elapsed_ms, 3),
        "us_per_call": round((elapsed_ms * 1000) / iterations, 3),
    }


def benchmark_ics_build(iterations: int) -> Dict[str, float]:
    example = {
        "uid": "event-1",
        "title": "Meeting",
        "start_time": "10:00 AM",
        "end_time": "11:00 AM",
        "date": "2025-03-30",
        "timezone": "America/New_York",
        "description": "Discuss roadmap",
        "location": "Room 1",
    }
    start = time.perf_counter()
    for i in range(iterations):
        data = dict(example)
        data["uid"] = f"event-{i}"
        build_ics_from_events([data])
    elapsed_ms = (time.perf_counter() - start) * 1000
    return {
        "iterations": iterations,
        "total_ms": round(elapsed_ms, 3),
        "ms_per_call": round(elapsed_ms / iterations, 4),
    }


def benchmark_image_preprocessing(iterations: int) -> Dict[str, float]:
    try:
        from PIL import Image
    except ImportError:
        return {"skipped": 1, "reason": "Pillow not installed"}

    fd, raw_path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    src_path = Path(raw_path)
    Image.new("RGB", (4032, 3024), color=(180, 120, 90)).save(src_path, format="JPEG", quality=95)

    timings: List[float] = []
    outputs: List[int] = []
    for _ in range(iterations):
        start = time.perf_counter()
        out = preprocess_image_for_upload(str(src_path), "image/jpeg")
        timings.append((time.perf_counter() - start) * 1000)
        try:
            outputs.append(Path(out.path).stat().st_size)
        except Exception:
            pass
        out.cleanup()

    result = {
        "iterations": iterations,
        "mean_ms": round(_mean(timings), 3),
        "p95_ms": round(_p95(timings), 3),
        "source_kb": round(src_path.stat().st_size / 1024, 2),
    }
    if outputs:
        result["output_kb_mean"] = round((_mean(outputs) / 1024), 2)

    src_path.unlink(missing_ok=True)
    return result


def profile_parse_hotpath(iterations: int, top_n: int = 20) -> str:
    samples = [
        "Coffee with Sarah tomorrow at 2pm",
        "Team sync next Tuesday at 10:30am",
        "Project kickoff on March 30 at 9am at HQ",
        "Daily standup meetings Monday through Friday at 9:30am for 30 minutes",
        "Doctor appointment on March 15th at 2pm and follow-up visit on March 29th same time",
    ]
    ref = datetime(2025, 1, 1, 12, 0, 0)
    profiler = cProfile.Profile()
    profiler.enable()
    for i in range(iterations):
        parse_event_text(samples[i % len(samples)], reference_date=ref)
    profiler.disable()
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumtime")
    stats.print_stats(top_n)
    return stream.getvalue()


def benchmark_ui_startup() -> Dict[str, object]:
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONPATH"] = str(SRC_ROOT)

    script = """
import os
import time
from PyQt6.QtWidgets import QApplication
from eventcalendar.ui.main_window import NLCalendarCreator

app = QApplication.instance() or QApplication([])
runs = []
for _ in range(8):
    t0 = time.perf_counter()
    w = NLCalendarCreator()
    runs.append((time.perf_counter() - t0) * 1000.0)
    w.close()

print(",".join(f"{v:.6f}" for v in runs))
"""
    try:
        out = subprocess.check_output(
            [sys.executable, "-c", script],
            env=env,
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except Exception as exc:
        return {"skipped": 1, "reason": str(exc)}

    values = [float(item) for item in out.split(",") if item]
    warm = values[1:] if len(values) > 1 else values
    return {
        "runs": len(values),
        "cold_first_ms": round(values[0], 3) if values else 0.0,
        "overall_mean_ms": round(_mean(values), 3),
        "overall_p95_ms": round(_p95(values), 3),
        "warm_mean_ms": round(_mean(warm), 3),
        "warm_p95_ms": round(_p95(warm), 3),
        "warm_max_ms": round(max(warm), 3) if warm else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--iterations", type=int, default=30000, help="Iterations for fast-path micro-benchmarks")
    args = parser.parse_args()

    report = {
        "imports": {
            "eventcalendar.ui.preview": _measure_import_ms("eventcalendar.ui.preview"),
            "eventcalendar.core.api_client": _measure_import_ms("eventcalendar.core.api_client"),
            "eventcalendar.core.ics_builder": _measure_import_ms("eventcalendar.core.ics_builder"),
        },
        "preview_parse": benchmark_preview_parsing(args.iterations),
        "preview_date_format": benchmark_date_formatting(args.iterations),
        "ics_build": benchmark_ics_build(max(1, args.iterations // 20)),
        "image_preprocess": benchmark_image_preprocessing(8),
        "ui_startup": benchmark_ui_startup(),
        "parse_cprofile_top": profile_parse_hotpath(max(5000, args.iterations // 2)),
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print("=== Import Timings ===")
    for module, values in report["imports"].items():
        print(f"{module}: mean={values['mean_ms']}ms p95={values['p95_ms']}ms")

    print("\n=== Runtime Benchmarks ===")
    print(
        "parse_event_text: "
        f"{report['preview_parse']['us_per_call']}us/call "
        f"({report['preview_parse']['total_ms']}ms total)"
    )
    print(
        "format_date_display: "
        f"{report['preview_date_format']['us_per_call']}us/call "
        f"({report['preview_date_format']['total_ms']}ms total)"
    )
    print(
        "build_ics_from_events: "
        f"{report['ics_build']['ms_per_call']}ms/call "
        f"({report['ics_build']['total_ms']}ms total)"
    )
    if "skipped" in report["image_preprocess"]:
        print(f"image_preprocess: skipped ({report['image_preprocess']['reason']})")
    else:
        print(
            "image_preprocess: "
            f"mean={report['image_preprocess']['mean_ms']}ms p95={report['image_preprocess']['p95_ms']}ms"
        )
    if "skipped" in report["ui_startup"]:
        print(f"ui_startup: skipped ({report['ui_startup']['reason']})")
    else:
        print(
            "ui_startup: "
            f"cold_first={report['ui_startup']['cold_first_ms']}ms "
            f"warm_mean={report['ui_startup']['warm_mean_ms']}ms "
            f"warm_p95={report['ui_startup']['warm_p95_ms']}ms"
        )

    print("\n=== parse_event_text cProfile (top) ===")
    print(report["parse_cprofile_top"])


if __name__ == "__main__":
    main()
