"""Background event-creation lifecycle owned outside the main window."""

from __future__ import annotations

import logging
import hashlib
import threading
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from enum import Enum
from typing import Callable, Iterable, Optional, Protocol

from PyQt6.QtCore import QObject, pyqtSignal

from eventcalendar.config.settings import UI_CONFIG
from eventcalendar.core.attachments import ImageAttachmentPayload

logger = logging.getLogger(__name__)


class EventExtractionClient(Protocol):
    """Structural client contract owned by the orchestration boundary."""

    def extract_events(
        self,
        event_description: str,
        image_data: list[tuple[str, str, Optional[str]]],
        status_callback: Callable[[str], None],
        cancel_event: threading.Event,
    ): ...

    def close(self) -> None: ...


class JobState(str, Enum):
    """Externally observable lifecycle for one-at-a-time event creation."""

    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CLOSING = "closing"
    CLOSED = "closed"


class EventCreationController(QObject):
    """Own the executor, API client, cancellation, and completion boundary."""

    status_changed = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(object)
    cancelled = pyqtSignal()
    state_changed = pyqtSignal(object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._executor = ThreadPoolExecutor(
            # The controller admits one job at a time; a larger pool would only
            # weaken the shared-client invariant without increasing throughput.
            max_workers=UI_CONFIG.executor_max_workers,
            thread_name_prefix="calendar_worker",
        )
        self._lock = threading.Lock()
        self._client_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._futures: set[Future] = set()
        self._client: Optional[EventExtractionClient] = None
        self._client_key_fingerprint: Optional[bytes] = None
        self._state = JobState.IDLE

    @property
    def state(self) -> JobState:
        with self._lock:
            return self._state

    @property
    def client(self):
        with self._client_lock:
            return self._client

    def submit(
        self,
        event_description: str,
        image_payloads: Iterable[ImageAttachmentPayload],
        api_key: str,
    ) -> None:
        """Start exactly one job or fail before mutating UI-visible state."""
        with self._lock:
            if self._state is not JobState.IDLE:
                raise RuntimeError(f"Cannot start event creation while controller is {self._state.value}")
            self._state = JobState.RUNNING
            self._cancel_event.clear()
            try:
                future = self._executor.submit(
                    self._run,
                    event_description,
                    tuple(image_payloads),
                    api_key,
                )
            except Exception:
                self._state = JobState.IDLE
                raise
            self._futures.add(future)

        self.state_changed.emit(JobState.RUNNING)
        future.add_done_callback(self._finish)

    def _run(
        self,
        event_description: str,
        image_payloads: tuple[ImageAttachmentPayload, ...],
        api_key: str,
    ):
        if self._cancel_event.is_set():
            raise CancelledError("Event creation was cancelled")

        with self._client_lock:
            # close() may win the race after the first cancellation check but
            # before client construction. Recheck while holding the same lock
            # close() uses to claim and close the client.
            self._check_cancelled()
            key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).digest()
            should_rotate = (
                self._client is not None
                and self._client_key_fingerprint is not None
                and self._client_key_fingerprint != key_fingerprint
            )
            if should_rotate:
                self.status_changed.emit("Applying updated API credentials...")
                self._client.close()
                self._client = None
            if self._client is None:
                self.status_changed.emit("Initializing AI client...")
                from eventcalendar.core.api_client import CalendarAPIClient

                self._client = CalendarAPIClient(api_key)
                self._client_key_fingerprint = key_fingerprint
            client = self._client

        image_data = [payload.materialize(include_base64=False) for payload in image_payloads]

        def notify(message: str) -> None:
            if not self._cancel_event.is_set():
                self.status_changed.emit(message)

        return client.extract_events(
            event_description,
            image_data,
            notify,
            cancel_event=self._cancel_event,
        )

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise CancelledError("Event creation was cancelled")

    def _finish(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)
            closing = self._state in {JobState.CLOSING, JobState.CLOSED}

        if not closing:
            try:
                result = future.result()
            except CancelledError:
                self.cancelled.emit()
                result = None
            except Exception as exc:
                self.failed.emit(exc)
                result = None
            else:
                self.completed.emit(result)

        with self._lock:
            if self._state in {JobState.RUNNING, JobState.CANCELLING}:
                self._state = JobState.IDLE
                next_state = JobState.IDLE
            elif self._state is JobState.CLOSING and not self._futures:
                self._state = JobState.CLOSED
                next_state = JobState.CLOSED
            else:
                next_state = None
        if next_state is not None:
            self.state_changed.emit(next_state)

    def reset_client(self) -> None:
        """Discard credentials only while no job can be using the client."""
        with self._lock:
            if self._state is not JobState.IDLE:
                raise RuntimeError("Cannot reset the API client during event creation")
        with self._client_lock:
            client, self._client = self._client, None
            self._client_key_fingerprint = None
        if client is not None:
            client.close()

    def cancel(self) -> bool:
        """Cancel the current queued or in-flight extraction."""
        with self._lock:
            if self._state is not JobState.RUNNING:
                return False
            self._state = JobState.CANCELLING
            futures = tuple(self._futures)
        self.state_changed.emit(JobState.CANCELLING)
        self.status_changed.emit("Cancelling current network request...")
        self._cancel_event.set()
        for future in futures:
            future.cancel()
        return True

    def close(self) -> None:
        """Reject new work, cancel queued work, and begin bounded cleanup."""
        with self._lock:
            if self._state in {JobState.CLOSING, JobState.CLOSED}:
                return
            self._state = JobState.CLOSING
            futures = tuple(self._futures)
        self.state_changed.emit(JobState.CLOSING)
        self._cancel_event.set()
        for future in futures:
            future.cancel()

        with self._client_lock:
            client = self._client
        try:
            if client is not None:
                # CalendarAPIClient defers transport close until active extraction
                # and remote-file cleanup finish.
                client.close()
        except Exception:
            logger.warning("Event-creation client close failed", exc_info=True)
        finally:
            self._executor.shutdown(wait=False, cancel_futures=True)

            with self._lock:
                if not self._futures and self._state is JobState.CLOSING:
                    self._state = JobState.CLOSED
                    closed_now = True
                else:
                    closed_now = False
        if closed_now:
            self.state_changed.emit(JobState.CLOSED)

    def set_client_for_testing(self, client: EventExtractionClient) -> None:
        """Install a deterministic fake without exposing mutable production state."""
        with self._client_lock:
            self._client = client
            # Test-injected clients are intentionally not tied to a credential.
            self._client_key_fingerprint = None
