#!/usr/bin/env python3
"""Deterministically profile submission call shape without spending API quota."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from google.genai import types

import eventcalendar.core.api_client as api_client_module
from eventcalendar.core.api_client import CalendarAPIClient
from eventcalendar.core.submission_runtime import (
    CancellableNetworkRuntime,
    SynchronousNetworkRuntime,
)

_EVENT_JSON = json.dumps(
    [
        {
            "title": "Profile event",
            "start_time": "10:00",
            "end_time": "11:00",
            "date": "2026-08-27",
            "timezone": "UTC",
        }
    ]
)


class _Processed:
    def __init__(self, path: str, mime_type: str) -> None:
        self.path = path
        self.mime_type = mime_type

    def cleanup(self) -> None:
        pass


def _client(sdk) -> CalendarAPIClient:
    client = object.__new__(CalendarAPIClient)
    client.api_key_masked = "profile"
    client.max_retries = 2
    client.base_delay = 0.001
    client._closed = False
    client._close_lock = threading.Lock()
    client._active_operations = 0
    client._transport_close_started = False
    client._types = types
    client.client = sdk
    client._network_runtime = SynchronousNetworkRuntime(sdk)
    client.generation_config = types.GenerateContentConfig()
    return client


def _profile_case(image_sizes: list[int], rtt_ms: float) -> dict[str, float | int]:
    calls = {"upload": 0, "delete": 0, "generate": 0, "wire": 0}

    class Files:
        def upload(self, *, file: str, config):
            del config
            calls["upload"] += 1
            chunks = math.ceil(Path(file).stat().st_size / (8 * 1024 * 1024))
            wire_calls = 1 + chunks
            calls["wire"] += wire_calls
            time.sleep(wire_calls * rtt_ms / 1000)
            return SimpleNamespace(name=f"files/profile-{calls['upload']}")

        def delete(self, *, name: str, config):
            del name, config
            calls["delete"] += 1
            calls["wire"] += 1
            time.sleep(rtt_ms / 1000)

    class Models:
        def generate_content(self, **_kwargs):
            calls["generate"] += 1
            calls["wire"] += 1
            time.sleep(rtt_ms / 1000)
            return SimpleNamespace(text=_EVENT_JSON)

    sdk = SimpleNamespace(files=Files(), models=Models(), close=lambda: None)
    client = _client(sdk)
    original_preprocessor = api_client_module.preprocess_image_for_upload
    api_client_module.preprocess_image_for_upload = (
        lambda path, mime: _Processed(path, mime or "image/png")
    )
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            images = []
            for index, size in enumerate(image_sizes):
                path = Path(temp_dir) / f"image-{index}.png"
                with path.open("wb") as output:
                    output.truncate(size)
                images.append((str(path), "image/png", None))
            started = time.perf_counter()
            result = client.extract_events("Profile", images)
            elapsed_ms = (time.perf_counter() - started) * 1000
    finally:
        api_client_module.preprocess_image_for_upload = original_preprocessor

    legacy_wire_calls = sum(
        1 + math.ceil(size / (8 * 1024 * 1024)) + 1 for size in image_sizes
    ) + 1
    return {
        "images": len(image_sizes),
        "payload_bytes": sum(image_sizes),
        "elapsed_ms": round(elapsed_ms, 3),
        "wire_calls": calls["wire"],
        "legacy_wire_calls": legacy_wire_calls,
        "modeled_legacy_rtt_ms": round(legacy_wire_calls * rtt_ms, 3),
        "inline_images": result.metrics.inline_images,
        "uploaded_images": result.metrics.uploaded_images,
        "sdk_calls": result.metrics.sdk_calls,
    }


def _profile_cancellation() -> dict[str, float | bool]:
    started = threading.Event()
    cancelled_inside_transport = threading.Event()

    class AsyncModels:
        async def generate_content(self, **_kwargs):
            started.set()
            try:
                await asyncio.sleep(30)
            finally:
                cancelled_inside_transport.set()

    class AsyncSDK:
        models = AsyncModels()

        async def aclose(self) -> None:
            pass

    class SDK:
        aio = AsyncSDK()

        class Models:
            def generate_content(self, **_kwargs):
                raise AssertionError("sync network path used")

        models = Models()

        def close(self) -> None:
            pass

    client = _client(SDK())
    client._network_runtime = CancellableNetworkRuntime(client.client)
    cancel_event = threading.Event()
    finished = threading.Event()

    def run() -> None:
        try:
            client.extract_events("Profile", [], cancel_event=cancel_event)
        except BaseException:
            pass
        finally:
            finished.set()

    worker = threading.Thread(target=run)
    worker.start()
    if not started.wait(2):
        raise RuntimeError("cancellation profile never entered transport")
    before_cancel = time.perf_counter()
    cancel_event.set()
    if not finished.wait(2):
        raise RuntimeError("cancellation profile did not finish")
    cancellation_ms = (time.perf_counter() - before_cancel) * 1000
    worker.join(1)
    transport_cancelled = cancelled_inside_transport.wait(1)
    client.close()
    return {
        "cancellation_ms": round(cancellation_ms, 3),
        "transport_cancelled": transport_cancelled,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rtt-ms", type=float, default=20.0)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    small = 64 * 1024
    report = {
        "assumptions": {
            "rtt_ms": args.rtt_ms,
            "file_api_chunk_bytes": 8 * 1024 * 1024,
            "legacy_small_image_wire_calls": "3N+1",
        },
        "small_transient_matrix": [
            _profile_case([small] * count, args.rtt_ms) for count in (0, 1, 4, 8)
        ],
        "over_inline_budget": _profile_case([12 * 1024 * 1024 + 1], args.rtt_ms),
        "cancellation": _profile_cancellation(),
    }
    failures = []
    for case in report["small_transient_matrix"]:
        if case["wire_calls"] != 1 or case["uploaded_images"] != 0:
            failures.append(f"{case['images']} small images did not stay one-request")
    if report["cancellation"]["cancellation_ms"] > 250:
        failures.append("active transport cancellation exceeded 250ms")
    if not report["cancellation"]["transport_cancelled"]:
        failures.append("active transport coroutine did not receive cancellation")
    report["check"] = {"passed": not failures, "failures": failures}
    print(json.dumps(report, indent=2))
    return 1 if args.check and failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
