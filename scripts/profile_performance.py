#!/usr/bin/env python3
"""Profile key app paths and print actionable performance metrics."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import cProfile
import io
import json
import math
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

from eventcalendar.core.ics_builder import (
    build_ics_from_events,
    build_merged_ics,
    combine_ics_strings,
)
from eventcalendar.core.image_preprocessing import preprocess_image_for_upload
from eventcalendar.ui.preview import format_date_display, parse_event_text


# Environment-sensitive measurements use generous catastrophic ceilings; the
# relative and UI-responsiveness checks below are the tighter regression gates.
PERFORMANCE_CEILINGS = {
    "preview_parse_us_per_call": 50.0,
    "preview_import_p95_ms": 300.0,
    "merged_ics_128_max_ms": 150.0,
    "image_preprocess_p95_ms": 500.0,
    "in_memory_encode_max_ms": 1_000.0,
    "cold_import_to_first_paint_max_ms": 1_000.0,
    "attachment_queue_max_ms": 25.0,
    "attachment_heartbeat_gap_max_ms": 50.0,
}
PERFORMANCE_FLOORS = {"merged_ics_128_speedup": 1.5}


def _mean(values: List[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[idx]


def _measure_import_ms(module: str, repeats: int = 20) -> Dict[str, float]:
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


def benchmark_ics_scaling() -> Dict[str, Dict[str, float]]:
    """Measure production's direct merge path against the compatibility path."""
    results: Dict[str, Dict[str, float]] = {}
    for count in (1, 8, 32, 128):
        events = [
            {
                "uid": f"event-{index}",
                "title": f"Meeting {index}",
                "start_time": "10:00 AM",
                "end_time": "11:00 AM",
                "date": "2025-03-30",
                "timezone": "America/New_York",
                "description": "Discuss roadmap",
                "location": "Room 1",
            }
            for index in range(count)
        ]
        repeats = 7 if count <= 8 else 3
        direct: List[float] = []
        compatibility: List[float] = []
        for _ in range(repeats):
            start = time.perf_counter()
            result = build_merged_ics(events)
            if result.ics_content is None or len(result.created_events) != count:
                raise RuntimeError("Direct ICS benchmark failed to build its event batch")
            direct.append((time.perf_counter() - start) * 1000)

            start = time.perf_counter()
            documents, warnings = build_ics_from_events(events)
            if warnings or len(documents) != count:
                raise RuntimeError("Compatibility ICS benchmark failed to build its event batch")
            combine_ics_strings(documents)
            compatibility.append((time.perf_counter() - start) * 1000)

        results[str(count)] = {
            "repeats": repeats,
            "direct_mean_ms": round(_mean(direct), 3),
            "direct_max_ms": round(max(direct), 3),
            "compatibility_mean_ms": round(_mean(compatibility), 3),
            "speedup": round(_mean(compatibility) / _mean(direct), 2),
        }
    return results


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


def benchmark_in_memory_encoding(iterations: int) -> Dict[str, float]:
    """Measure the expensive in-memory drop operation now run by its worker."""
    try:
        from PyQt6.QtGui import QColor, QImage
        from eventcalendar.ui.widgets.image_area import ImageAttachmentArea
    except ImportError as exc:
        return {"skipped": 1, "reason": str(exc)}

    image = QImage(4032, 3024, QImage.Format.Format_RGB32)
    image.fill(QColor(180, 120, 90))
    timings: List[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        payload = ImageAttachmentArea._encode_in_memory_image(QImage(image))
        timings.append((time.perf_counter() - start) * 1000)
        Path(payload.temp_path).unlink(missing_ok=True)
    return {
        "iterations": iterations,
        "mean_ms": round(_mean(timings), 3),
        "max_ms": round(max(timings), 3),
    }


def benchmark_attachment_responsiveness(iterations: int = 3) -> Dict[str, float]:
    """Exercise the real executor handoff while pumping the Qt event loop."""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtGui import QColor, QImage
        from PyQt6.QtWidgets import QApplication
        from eventcalendar.ui.widgets.image_area import ImageAttachmentArea
    except ImportError as exc:
        return {"skipped": 1, "reason": str(exc)}

    app = QApplication.instance() or QApplication([])
    image = QImage(4032, 3024, QImage.Format.Format_RGB32)
    image.fill(QColor(180, 120, 90))
    queue_timings: List[float] = []
    heartbeat_gaps: List[float] = []
    completion_timings: List[float] = []

    for _ in range(iterations):
        area = ImageAttachmentArea()
        started = time.perf_counter()
        if not area._queue_in_memory_image(image):
            area.shutdown()
            raise RuntimeError("Attachment responsiveness benchmark could not queue its image")
        queue_timings.append((time.perf_counter() - started) * 1000)

        previous_pump = time.perf_counter()
        deadline = previous_pump + 5.0
        while area.has_pending_images and time.perf_counter() < deadline:
            app.processEvents()
            now = time.perf_counter()
            heartbeat_gaps.append((now - previous_pump) * 1000)
            previous_pump = now
            time.sleep(0.001)
        app.processEvents()
        completion_timings.append((time.perf_counter() - started) * 1000)
        if area.has_pending_images or not area.image_data:
            area.shutdown()
            raise RuntimeError("Attachment responsiveness benchmark timed out")
        managed_path = Path(area.image_data[0].temp_path)
        area.shutdown()
        if managed_path.exists():
            raise RuntimeError("Attachment responsiveness benchmark leaked its temp file")

    return {
        "iterations": iterations,
        "queue_mean_ms": round(_mean(queue_timings), 3),
        "queue_max_ms": round(max(queue_timings), 3),
        "heartbeat_gap_max_ms": round(max(heartbeat_gaps), 3),
        "completion_mean_ms": round(_mean(completion_timings), 3),
    }


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


def benchmark_ui_startup(repeats: int = 5) -> Dict[str, object]:
    """Measure cold imports through first paint plus warm window construction."""
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONPATH"] = str(SRC_ROOT)

    script = """import time
started = time.perf_counter()
import json
import os
from PyQt6.QtWidgets import QApplication
from eventcalendar.ui.main_window import NLCalendarCreator

app = QApplication.instance() or QApplication([])
first_started = time.perf_counter()
first = NLCalendarCreator()
first.show()
app.processEvents()
first_window_ms = (time.perf_counter() - first_started) * 1000.0
cold_to_paint_ms = (time.perf_counter() - started) * 1000.0
first.close()

warm = []
for _ in range(4):
    t0 = time.perf_counter()
    w = NLCalendarCreator()
    w.show()
    app.processEvents()
    warm.append((time.perf_counter() - t0) * 1000.0)
    w.close()

print(json.dumps({
    "cold_to_paint_ms": cold_to_paint_ms,
    "first_window_ms": first_window_ms,
    "warm_ms": warm,
}))
"""
    cold_values: List[float] = []
    first_window_values: List[float] = []
    warm_values: List[float] = []
    try:
        for _ in range(repeats):
            out = subprocess.check_output(
                [sys.executable, "-c", script],
                env=env,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            sample = json.loads(out.splitlines()[-1])
            cold_values.append(float(sample["cold_to_paint_ms"]))
            first_window_values.append(float(sample["first_window_ms"]))
            warm_values.extend(float(value) for value in sample["warm_ms"])
    except Exception as exc:
        return {"skipped": 1, "reason": str(exc)}

    return {
        "cold_runs": len(cold_values),
        "cold_import_to_first_paint_mean_ms": round(_mean(cold_values), 3),
        "cold_import_to_first_paint_median_ms": round(statistics.median(cold_values), 3),
        "cold_import_to_first_paint_max_ms": round(max(cold_values), 3),
        "first_window_mean_ms": round(_mean(first_window_values), 3),
        "warm_mean_ms": round(_mean(warm_values), 3),
        "warm_p95_ms": round(_p95(warm_values), 3),
        "warm_max_ms": round(max(warm_values), 3) if warm_values else 0.0,
    }


def evaluate_budgets(report: Dict[str, object]) -> List[str]:
    """Return human-readable ceiling and relative-shape violations."""
    checks = {
        "preview_parse_us_per_call": report["preview_parse"]["us_per_call"],
        "preview_import_p95_ms": report["imports"]["eventcalendar.ui.preview"]["p95_ms"],
        "merged_ics_128_max_ms": report["ics_scaling"]["128"]["direct_max_ms"],
        "image_preprocess_p95_ms": report["image_preprocess"].get("p95_ms"),
        "in_memory_encode_max_ms": report["in_memory_encode"].get("max_ms"),
        "cold_import_to_first_paint_max_ms": report["ui_startup"].get(
            "cold_import_to_first_paint_max_ms"
        ),
        "attachment_queue_max_ms": report["attachment_responsiveness"].get("queue_max_ms"),
        "attachment_heartbeat_gap_max_ms": report["attachment_responsiveness"].get(
            "heartbeat_gap_max_ms"
        ),
    }
    failures = []
    for name, limit in PERFORMANCE_CEILINGS.items():
        actual = checks.get(name)
        if actual is None:
            failures.append(f"{name}: measurement unavailable")
        elif actual > limit:
            failures.append(f"{name}: {actual:.3f} exceeded ceiling {limit:.3f}")
    floors = {"merged_ics_128_speedup": report["ics_scaling"]["128"]["speedup"]}
    for name, minimum in PERFORMANCE_FLOORS.items():
        actual = floors[name]
        if actual < minimum:
            failures.append(f"{name}: {actual:.3f} fell below floor {minimum:.3f}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--check", action="store_true", help="Fail if a regression budget is exceeded")
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
        "ics_scaling": benchmark_ics_scaling(),
        "image_preprocess": benchmark_image_preprocessing(20),
        "in_memory_encode": benchmark_in_memory_encoding(5),
        "attachment_responsiveness": benchmark_attachment_responsiveness(),
        "ui_startup": benchmark_ui_startup(),
        "parse_cprofile_top": profile_parse_hotpath(max(5000, args.iterations // 2)),
    }
    failures = evaluate_budgets(report) if args.check else []
    report["performance_check"] = {
        "passed": not failures,
        "ceilings": PERFORMANCE_CEILINGS,
        "floors": PERFORMANCE_FLOORS,
        "failures": failures,
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 1 if failures else 0

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
    merged = report["ics_scaling"]["128"]
    print(
        "build_merged_ics (128 events): "
        f"max={merged['direct_max_ms']}ms speedup={merged['speedup']}x"
    )
    if "skipped" in report["image_preprocess"]:
        print(f"image_preprocess: skipped ({report['image_preprocess']['reason']})")
    else:
        print(
            "image_preprocess: "
            f"mean={report['image_preprocess']['mean_ms']}ms p95={report['image_preprocess']['p95_ms']}ms"
        )
    if "skipped" in report["in_memory_encode"]:
        print(f"in_memory_encode: skipped ({report['in_memory_encode']['reason']})")
    else:
        print(
            "in_memory_encode (worker operation): "
            f"mean={report['in_memory_encode']['mean_ms']}ms "
            f"max={report['in_memory_encode']['max_ms']}ms"
        )
    if "skipped" in report["attachment_responsiveness"]:
        print(
            "attachment_responsiveness: skipped "
            f"({report['attachment_responsiveness']['reason']})"
        )
    else:
        responsive = report["attachment_responsiveness"]
        print(
            "attachment_responsiveness: "
            f"queue_max={responsive['queue_max_ms']}ms "
            f"heartbeat_gap_max={responsive['heartbeat_gap_max_ms']}ms"
        )
    if "skipped" in report["ui_startup"]:
        print(f"ui_startup: skipped ({report['ui_startup']['reason']})")
    else:
        print(
            "ui_startup: "
            "cold_import_to_first_paint_median="
            f"{report['ui_startup']['cold_import_to_first_paint_median_ms']}ms "
            "cold_import_to_first_paint_max="
            f"{report['ui_startup']['cold_import_to_first_paint_max_ms']}ms "
            f"warm_mean={report['ui_startup']['warm_mean_ms']}ms "
            f"warm_p95={report['ui_startup']['warm_p95_ms']}ms"
        )

    if args.check:
        print("\n=== Performance Budgets ===")
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}")
        else:
            print("PASS")

    print("\n=== parse_event_text cProfile (top) ===")
    print(report["parse_cprofile_top"])
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
