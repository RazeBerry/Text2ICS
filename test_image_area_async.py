"""Regression tests for non-blocking attachment preparation."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

from eventcalendar.ui.widgets.image_area import ImageAttachmentArea, ImageAttachmentPayload


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def _wait_until(app: QApplication, predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def _image() -> QImage:
    image = QImage(320, 200, QImage.Format.Format_RGB32)
    image.fill(QColor(120, 80, 40))
    return image


def test_in_memory_encoding_runs_off_the_qt_thread(qt_app, tmp_path: Path, monkeypatch) -> None:
    area = ImageAttachmentArea()
    release = threading.Event()
    worker_threads: list[int] = []
    output = tmp_path / "worker.png"

    def encode(_image: QImage) -> ImageAttachmentPayload:
        worker_threads.append(threading.get_ident())
        assert release.wait(1)
        output.write_bytes(b"worker-owned")
        return ImageAttachmentPayload(str(output), "image/png", str(output))

    monkeypatch.setattr(area, "_encode_in_memory_image", encode)
    assert area._queue_in_memory_image(_image()) is True
    assert area.has_pending_images is True
    assert worker_threads or release.wait(0.05) is False

    release.set()
    _wait_until(qt_app, lambda: bool(area.image_data))
    assert worker_threads == [worker_threads[0]]
    assert worker_threads[0] != threading.get_ident()
    assert area.has_pending_images is False
    area.shutdown()


def test_reset_rejects_and_cleans_a_stale_worker_result(qt_app, tmp_path: Path, monkeypatch) -> None:
    area = ImageAttachmentArea()
    release = threading.Event()
    output = tmp_path / "stale.png"

    def encode(_image: QImage) -> ImageAttachmentPayload:
        assert release.wait(1)
        output.write_bytes(b"stale")
        return ImageAttachmentPayload(str(output), "image/png", str(output))

    monkeypatch.setattr(area, "_encode_in_memory_image", encode)
    assert area._queue_in_memory_image(_image()) is True
    area.reset_state()
    release.set()

    _wait_until(qt_app, lambda: not output.exists())
    assert area.image_data == []
    assert area.has_pending_images is False
    area.shutdown()


def test_real_in_memory_encode_produces_a_valid_managed_payload(qt_app) -> None:
    area = ImageAttachmentArea()
    assert area._queue_in_memory_image(_image()) is True

    _wait_until(qt_app, lambda: bool(area.image_data))
    payload = area.image_data[0]
    assert payload.mime_type == "image/png"
    assert Path(payload.temp_path).is_file()

    managed_path = Path(payload.temp_path)
    area.reset_state()
    assert not managed_path.exists()
    area.shutdown()


def test_file_validation_and_snapshot_run_off_the_qt_thread(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    from PIL import Image

    source = tmp_path / "source.png"
    Image.new("RGB", (64, 64), "white").save(source)
    area = ImageAttachmentArea()
    original = area._create_payload_from_url
    release = threading.Event()
    worker_threads: list[int] = []

    def prepare(path: str):
        worker_threads.append(threading.get_ident())
        assert release.wait(1)
        return original(path)

    monkeypatch.setattr(area, "_create_payload_from_url", prepare)
    assert area._queue_file_path(str(source)) is True
    assert area.has_pending_images is True
    assert worker_threads or release.wait(0.05) is False

    release.set()
    _wait_until(qt_app, lambda: bool(area.image_data))
    assert worker_threads[0] != threading.get_ident()
    payload = area.image_data[0]
    assert Path(payload.temp_path) != source
    assert Path(payload.temp_path).is_file()
    area.shutdown()
    assert not Path(payload.temp_path).exists()
