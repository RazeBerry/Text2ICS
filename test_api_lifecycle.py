"""Deterministic retry, upload, and shutdown lifecycle regressions."""

from __future__ import annotations

import json
import asyncio
import threading
import time
from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional

import pytest
from google.genai.errors import APIError, ServerError

import eventcalendar.core.api_client as api_client_module
from eventcalendar.core.api_client import CalendarAPIClient
from eventcalendar.core.retry import RetryCategory, classify_retry
from eventcalendar.core.submission_runtime import (
    CancellableNetworkRuntime,
    SynchronousNetworkRuntime,
)
from eventcalendar.exceptions.errors import CalendarAPIError, ImageProcessingError


def _valid_event() -> dict:
    return {
        "title": "Review",
        "start_time": "10:00",
        "end_time": "11:00",
        "date": "2026-07-30",
        "timezone": "UTC",
    }


def _bare_client(sdk, *, max_retries: int = 3, base_delay: float = 0) -> CalendarAPIClient:
    client = object.__new__(CalendarAPIClient)
    client.api_key_masked = "AIza...test"
    client.max_retries = max_retries
    client.base_delay = base_delay
    client._closed = False
    client._close_lock = threading.Lock()
    client._active_operations = 0
    client._transport_close_started = False
    client._types = SimpleNamespace(
        UploadFileConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        DeleteFileConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    client.client = sdk
    client._network_runtime = SynchronousNetworkRuntime(sdk)
    client.generation_config = object()
    return client


@dataclass
class _ProcessedImage:
    path: str
    mime_type: str
    on_cleanup: Callable[[], None]

    def cleanup(self) -> None:
        self.on_cleanup()


@pytest.mark.parametrize(
    ("error", "retryable", "category"),
    [
        (APIError(401, {"status": "UNAUTHENTICATED"}), False, RetryCategory.CREDENTIALS),
        (APIError(403, {"status": "PERMISSION_DENIED"}), False, RetryCategory.PERMISSION),
        (APIError(429, {"status": "RESOURCE_EXHAUSTED"}), True, RetryCategory.RATE_LIMIT),
        (ServerError(503, {"status": "UNAVAILABLE"}), True, RetryCategory.SERVER),
        (TimeoutError("socket timed out"), True, RetryCategory.TIMEOUT),
        (Exception("Quota exceeded for the day"), False, RetryCategory.QUOTA),
        (Exception("unknown vendor wording"), False, RetryCategory.UNKNOWN),
        (TypeError("bad call site"), False, RetryCategory.UNKNOWN),
        (APIError(429, {"status": "RESOURCE_EXHAUSTED", "message": "requests per day"}), False, RetryCategory.QUOTA),
    ],
)
def test_retry_decisions_prefer_typed_status_and_keep_legacy_fallback(
    error: Exception,
    retryable: bool,
    category: RetryCategory,
) -> None:
    decision = classify_retry(error)
    assert decision.retryable is retryable
    assert decision.category == category
    assert decision.reason


def test_upload_retries_are_per_file_and_preprocessing_is_not_repeated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("one.png", "two.png", "invalid.png", "exhausted.png"):
        (tmp_path / name).write_bytes(b"test image fixture")

    attempts: dict[str, int] = {}
    cleanup_counts: dict[str, int] = {}

    class Files:
        def upload(self, *, file: str, config):
            del config
            name = Path(file).name
            attempts[name] = attempts.get(name, 0) + 1
            if name == "two.png" and attempts[name] == 1:
                raise ServerError(503, {"status": "UNAVAILABLE"})
            if name == "exhausted.png":
                raise ServerError(503, {"status": "UNAVAILABLE"})
            return SimpleNamespace(name=f"files/{name}")

        def delete(self, *, name: str, config) -> None:
            del name, config

    sdk = SimpleNamespace(files=Files(), close=lambda: None)
    client = _bare_client(sdk)

    def preprocess(path: str, mime_type: Optional[str]):
        name = Path(path).name
        if name == "invalid.png":
            raise ImageProcessingError(path, "invalid image contents")
        cleanup_counts.setdefault(name, 0)
        return _ProcessedImage(
            path,
            mime_type or "image/png",
            lambda name=name: cleanup_counts.__setitem__(name, cleanup_counts[name] + 1),
        )

    monkeypatch.setattr(api_client_module, "preprocess_image_for_upload", preprocess)
    image_data = [
        (str(tmp_path / name), "image/png", None)
        for name in ("one.png", "two.png", "invalid.png", "exhausted.png")
    ]

    batch = client._prepare_images(image_data, None)

    assert [uploaded.name for uploaded in batch.contents] == ["files/one.png", "files/two.png"]
    assert attempts == {"one.png": 1, "two.png": 2, "exhausted.png": 3}
    assert cleanup_counts == {"one.png": 1, "two.png": 1, "exhausted.png": 1}
    assert len(batch.failures) == 2
    assert any("invalid image contents" in failure for failure in batch.failures)
    assert any("Failed after 3 attempts" in failure for failure in batch.failures)


def test_cancellation_during_upload_backoff_cleans_processed_and_remote_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("uploaded.png", "retrying.png"):
        (tmp_path / name).write_bytes(b"test image fixture")

    upload_attempts: list[str] = []
    deleted: list[str] = []
    cleaned: list[str] = []

    class Files:
        def upload(self, *, file: str, config):
            del config
            name = Path(file).name
            upload_attempts.append(name)
            if name == "retrying.png":
                raise ServerError(503, {"status": "UNAVAILABLE"})
            return SimpleNamespace(name=f"files/{name}")

        def delete(self, *, name: str, config) -> None:
            del config
            deleted.append(name)

    class CancelDuringWait:
        waits: list[float]

        def __init__(self) -> None:
            self.waits = []

        def is_set(self) -> bool:
            return False

        def wait(self, delay: float) -> bool:
            self.waits.append(delay)
            return True

    sdk = SimpleNamespace(files=Files(), close=lambda: None)
    client = _bare_client(sdk, base_delay=2)
    cancel = CancelDuringWait()

    monkeypatch.setattr(
        api_client_module,
        "preprocess_image_for_upload",
        lambda path, mime: _ProcessedImage(
            path,
            mime or "image/png",
            lambda path=path: cleaned.append(Path(path).name),
        ),
    )

    with pytest.raises(CancelledError):
        client._prepare_images(
            [
                (str(tmp_path / "uploaded.png"), "image/png", None),
                (str(tmp_path / "retrying.png"), "image/png", None),
            ],
            cancel,  # type: ignore[arg-type]
        )

    assert upload_attempts == ["uploaded.png", "retrying.png"]
    assert cancel.waits == [2]
    assert cleaned == ["uploaded.png", "retrying.png"]
    assert len(deleted) == 2
    assert all(name.startswith("files/eventcalendar-") for name in deleted)


def test_close_during_generation_waits_for_remote_cleanup_and_closes_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "event.png"
    image_path.write_bytes(b"test image fixture")
    generation_started = threading.Event()
    release_generation = threading.Event()
    order: list[str] = []

    class Files:
        def upload(self, *, file: str, config):
            del file, config
            order.append("upload")
            return SimpleNamespace(name="files/event.png")

        def delete(self, *, name: str, config) -> None:
            del config
            assert name.startswith("files/eventcalendar-")
            order.append("delete")

    class Models:
        def generate_content(self, **kwargs):
            del kwargs
            order.append("generation-start")
            generation_started.set()
            assert release_generation.wait(5), "test did not release blocked generation"
            order.append("generation-finish")
            return SimpleNamespace(text=json.dumps([_valid_event()]))

    class SDK:
        files = Files()
        models = Models()

        def close(self) -> None:
            order.append("close")

    client = _bare_client(SDK())
    monkeypatch.setattr(
        api_client_module,
        "preprocess_image_for_upload",
        lambda path, mime: _ProcessedImage(path, mime or "image/png", lambda: None),
    )

    results = []
    failures: list[BaseException] = []

    def run_extract() -> None:
        try:
            results.append(client.extract_events("Review", [(str(image_path), "image/png", None)]))
        except BaseException as exc:  # Captured for assertion in the test thread.
            failures.append(exc)

    worker = threading.Thread(target=run_extract, name="blocked_generation_test")
    worker.start()
    assert generation_started.wait(5)

    try:
        client.close()
        assert "close" not in order
        with pytest.raises(CalendarAPIError, match="closed"):
            client.extract_events("New work", [])
        with pytest.raises(CalendarAPIError, match="closed"):
            client.upload_to_gemini(str(image_path), "image/png")
    finally:
        release_generation.set()
        worker.join(5)

    assert not worker.is_alive()
    assert failures == []
    assert len(results) == 1
    assert order == ["upload", "generation-start", "generation-finish", "delete", "close"]

    client.close()
    assert order.count("close") == 1


def test_transport_close_failure_is_terminal_and_idempotent() -> None:
    calls = []

    class SDK:
        def close(self) -> None:
            calls.append("close")
            raise RuntimeError("close failed")

    client = _bare_client(SDK())

    client.close()
    client.close()

    assert calls == ["close"]
    with pytest.raises(CalendarAPIError, match="closed"):
        client.extract_events("new work", [])


def test_inline_images_collapse_submission_to_one_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from google.genai import types

    paths = []
    for index in range(8):
        path = tmp_path / f"image-{index}.png"
        path.write_bytes(b"small-image")
        paths.append((str(path), "image/png", None))

    calls = {"generate": 0}

    class Files:
        def upload(self, **_kwargs):
            raise AssertionError("small transient images must not use the File API")

        def delete(self, **_kwargs):
            raise AssertionError("inline images own no remote cleanup")

    class Models:
        def generate_content(self, **kwargs):
            calls["generate"] += 1
            assert len(kwargs["contents"]) == 9
            return SimpleNamespace(text=json.dumps([_valid_event()]))

    sdk = SimpleNamespace(files=Files(), models=Models(), close=lambda: None)
    client = _bare_client(sdk)
    client._types = types
    monkeypatch.setattr(
        api_client_module,
        "preprocess_image_for_upload",
        lambda path, mime: _ProcessedImage(path, mime or "image/png", lambda: None),
    )

    result = client.extract_events("Review", paths)

    assert calls == {"generate": 1}
    assert result.metrics.inline_images == 8
    assert result.metrics.uploaded_images == 0
    assert result.metrics.sdk_calls == 1


def test_active_async_request_is_cancelled_promptly() -> None:
    from google.genai import types

    started = threading.Event()
    coroutine_cancelled = threading.Event()

    class AsyncModels:
        async def generate_content(self, **_kwargs):
            started.set()
            try:
                await asyncio.sleep(60)
            finally:
                coroutine_cancelled.set()

    class AsyncClient:
        models = AsyncModels()

        async def aclose(self) -> None:
            pass

    class SyncModels:
        def generate_content(self, **_kwargs):
            raise AssertionError("production-shaped clients must use cancellable async I/O")

    class SDK:
        aio = AsyncClient()
        models = SyncModels()

        def close(self) -> None:
            pass

    client = _bare_client(SDK())
    client._types = types
    client._network_runtime = CancellableNetworkRuntime(client.client)
    cancel = threading.Event()
    failures: list[BaseException] = []

    worker = threading.Thread(
        target=lambda: _capture_failure(
            failures,
            lambda: client.extract_events("Review", [], cancel_event=cancel),
        )
    )
    worker.start()
    assert started.wait(1)
    cancelled_at = time.perf_counter()
    cancel.set()
    worker.join(1)

    assert not worker.is_alive()
    assert time.perf_counter() - cancelled_at < 0.25
    assert len(failures) == 1 and isinstance(failures[0], CancelledError)
    assert coroutine_cancelled.wait(1)
    client.close()


def test_end_to_end_deadline_cancels_active_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from google.genai import types

    from eventcalendar.exceptions.errors import RequestDeadlineExceeded

    transport_cancelled = threading.Event()

    class AsyncModels:
        async def generate_content(self, **_kwargs):
            try:
                await asyncio.sleep(60)
            finally:
                transport_cancelled.set()

    class AsyncClient:
        models = AsyncModels()

        async def aclose(self) -> None:
            pass

    class SDK:
        aio = AsyncClient()
        models = SimpleNamespace(generate_content=lambda **_kwargs: None)

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        api_client_module,
        "API_CONFIG",
        replace(
            api_client_module.API_CONFIG,
            request_deadline_seconds=0.10,
            generation_timeout_seconds=30.0,
        ),
    )
    client = _bare_client(SDK())
    client._types = types
    client._network_runtime = CancellableNetworkRuntime(client.client)

    started = time.perf_counter()
    with pytest.raises(RequestDeadlineExceeded):
        client.extract_events("Review", [])
    elapsed = time.perf_counter() - started

    assert elapsed < 0.30
    assert transport_cancelled.wait(1)
    client.close()


def _capture_failure(failures: list[BaseException], operation: Callable[[], object]) -> None:
    try:
        operation()
    except BaseException as exc:
        failures.append(exc)


def test_success_status_is_not_emitted_before_cleanup_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "large.png"
    image_path.write_bytes(b"image")
    cleanup_started = threading.Event()
    release_cleanup = threading.Event()
    statuses: list[str] = []

    class Files:
        def upload(self, **_kwargs):
            return SimpleNamespace(name="files/large")

        def delete(self, **_kwargs):
            cleanup_started.set()
            assert release_cleanup.wait(2)

    class Models:
        def generate_content(self, **_kwargs):
            return SimpleNamespace(text=json.dumps([_valid_event()]))

    client = _bare_client(SimpleNamespace(files=Files(), models=Models(), close=lambda: None))
    monkeypatch.setattr(
        api_client_module,
        "preprocess_image_for_upload",
        lambda path, mime: _ProcessedImage(path, mime or "image/png", lambda: None),
    )
    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            client.extract_events("Review", [(str(image_path), "image/png", None)], statuses.append)
        )
    )
    worker.start()
    assert cleanup_started.wait(1)
    assert statuses[-1] == "Cleaning up temporary uploads..."
    assert not any(status.startswith("Successfully") for status in statuses)
    release_cleanup.set()
    worker.join(2)

    assert len(results) == 1
    assert statuses[-1].startswith("Successfully")


def test_accepted_upload_with_lost_response_is_reconciled_and_deleted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from google.genai import types

    image_path = tmp_path / "overflow.png"
    with image_path.open("wb") as output:
        output.truncate(12 * 1024 * 1024 + 1)
    calls = {"upload": 0, "get": 0, "delete": []}

    class Files:
        def upload(self, *, file, config):
            del file, config
            calls["upload"] += 1
            raise TimeoutError("response lost after server acceptance")

        def get(self, *, name, config):
            del config
            calls["get"] += 1
            return types.File(name=name, mime_type="image/png")

        def delete(self, *, name, config):
            del config
            calls["delete"].append(name)

    class Models:
        def generate_content(self, **_kwargs):
            return SimpleNamespace(text=json.dumps([_valid_event()]))

    client = _bare_client(SimpleNamespace(files=Files(), models=Models(), close=lambda: None))
    client._types = types
    monkeypatch.setattr(
        api_client_module,
        "preprocess_image_for_upload",
        lambda path, mime: _ProcessedImage(path, mime or "image/png", lambda: None),
    )

    result = client.extract_events(
        "Review",
        [(str(image_path), "image/png", None)],
    )

    assert calls["upload"] == 1
    assert calls["get"] == 1
    assert len(calls["delete"]) == 1
    assert calls["delete"][0].startswith("files/eventcalendar-")
    assert result.metrics.reconciliation_attempts == 1


def test_transient_remote_delete_is_retried_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from google.genai import types

    image_path = tmp_path / "overflow.png"
    with image_path.open("wb") as output:
        output.truncate(12 * 1024 * 1024 + 1)
    delete_attempts = []

    class Files:
        def upload(self, *, file, config):
            del file
            return types.File(name=config.name, mime_type="image/png")

        def delete(self, *, name, config):
            del config
            delete_attempts.append(name)
            if len(delete_attempts) == 1:
                raise TimeoutError("transient cleanup timeout")

    class Models:
        def generate_content(self, **_kwargs):
            return SimpleNamespace(text=json.dumps([_valid_event()]))

    client = _bare_client(SimpleNamespace(files=Files(), models=Models(), close=lambda: None))
    client._types = types
    monkeypatch.setattr(
        api_client_module,
        "preprocess_image_for_upload",
        lambda path, mime: _ProcessedImage(path, mime or "image/png", lambda: None),
    )

    result = client.extract_events(
        "Review",
        [(str(image_path), "image/png", None)],
    )

    assert len(delete_attempts) == 2
    assert result.metrics.cleanup_attempts == 2
