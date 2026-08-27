"""Concurrency-state tests for event creation orchestration."""

from __future__ import annotations

import os
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("EVENTCALENDAR_RUN_UI_TESTS") != "1",
    reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).",
)


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait_until(qt_app, predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def test_controller_admits_only_one_job_and_returns_to_idle(qt_app) -> None:
    from eventcalendar.core.api_client import ExtractionResult
    from eventcalendar.ui.event_creation_controller import EventCreationController, JobState

    started = threading.Event()
    release = threading.Event()

    class FakeClient:
        def extract_events(self, *_args, **_kwargs):
            started.set()
            assert release.wait(2)
            return ExtractionResult([])

        def close(self) -> None:
            pass

    controller = EventCreationController()
    controller.set_client_for_testing(FakeClient())
    controller.submit("first", (), "key")
    assert started.wait(1)

    with pytest.raises(RuntimeError, match="running"):
        controller.submit("second", (), "key")

    release.set()
    _wait_until(qt_app, lambda: controller.state is JobState.IDLE)
    controller.close()
    assert controller.state is JobState.CLOSED


def test_close_cannot_race_past_client_construction(qt_app, monkeypatch) -> None:
    """A close between cancellation checks must not create an unclosed client."""
    import eventcalendar.core.api_client as api_client_module
    from eventcalendar.ui.event_creation_controller import EventCreationController, JobState

    constructed = []

    class FakeClient:
        def __init__(self, _api_key: str):
            constructed.append(self)

        def extract_events(self, *_args, **_kwargs):
            raise AssertionError("cancelled work reached extraction")

        def close(self) -> None:
            pass

    monkeypatch.setattr(api_client_module, "CalendarAPIClient", FakeClient)
    controller = EventCreationController()
    controller._client_lock.acquire()
    try:
        controller.submit("event", (), "key")
        closer = threading.Thread(target=controller.close)
        closer.start()
        _wait_until(qt_app, lambda: controller.state is JobState.CLOSING)
    finally:
        controller._client_lock.release()

    closer.join(timeout=2)
    assert not closer.is_alive()
    _wait_until(qt_app, lambda: controller.state is JobState.CLOSED)
    assert constructed == []


def test_throwing_client_close_still_finalizes_controller() -> None:
    from eventcalendar.ui.event_creation_controller import EventCreationController, JobState

    class FakeClient:
        def extract_events(self, *_args, **_kwargs):
            raise AssertionError("no work expected")

        def close(self) -> None:
            raise RuntimeError("transport close failed")

    controller = EventCreationController()
    controller.set_client_for_testing(FakeClient())

    controller.close()

    assert controller.state is JobState.CLOSED
    assert controller._cancel_event.is_set()


def test_user_cancel_emits_terminal_signal_and_returns_idle(qt_app) -> None:
    from concurrent.futures import CancelledError

    from eventcalendar.ui.event_creation_controller import EventCreationController, JobState

    started = threading.Event()
    cancelled_signals = []

    class FakeClient:
        def extract_events(self, *_args, cancel_event, **_kwargs):
            started.set()
            assert cancel_event.wait(2)
            raise CancelledError("cancelled")

        def close(self) -> None:
            pass

    controller = EventCreationController()
    controller.set_client_for_testing(FakeClient())
    controller.cancelled.connect(lambda: cancelled_signals.append(True))
    controller.submit("event", (), "key")
    assert started.wait(1)

    assert controller.cancel() is True
    _wait_until(
        qt_app,
        lambda: controller.state is JobState.IDLE and cancelled_signals == [True],
    )

    assert cancelled_signals == [True]
    assert controller.cancel() is False
    controller.close()


def test_changed_api_key_rotates_idle_client(qt_app, monkeypatch) -> None:
    import eventcalendar.core.api_client as api_client_module
    from eventcalendar.core.api_client import ExtractionResult
    from eventcalendar.ui.event_creation_controller import EventCreationController, JobState

    clients = []

    class FakeClient:
        def __init__(self, api_key: str):
            self.api_key = api_key
            self.closed = False
            clients.append(self)

        def extract_events(self, *_args, **_kwargs):
            return ExtractionResult([])

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(api_client_module, "CalendarAPIClient", FakeClient)
    controller = EventCreationController()
    controller.submit("first", (), "old-key")
    _wait_until(qt_app, lambda: controller.state is JobState.IDLE)
    controller.submit("second", (), "new-key")
    _wait_until(qt_app, lambda: controller.state is JobState.IDLE)

    assert [client.api_key for client in clients] == ["old-key", "new-key"]
    assert clients[0].closed is True
    controller.close()


def test_close_emits_closed_once_when_queued_job_is_cancelled(qt_app) -> None:
    from eventcalendar.ui.event_creation_controller import EventCreationController, JobState

    blocker_started = threading.Event()
    release_blocker = threading.Event()
    states = []

    controller = EventCreationController()
    controller.state_changed.connect(states.append)
    blocker = controller._executor.submit(
        lambda: (blocker_started.set(), release_blocker.wait(2))
    )
    assert blocker_started.wait(1)
    controller.submit("queued", (), "key")

    controller.close()
    release_blocker.set()
    blocker.result(timeout=2)
    _wait_until(qt_app, lambda: controller.state is JobState.CLOSED)

    assert states.count(JobState.CLOSED) == 1
