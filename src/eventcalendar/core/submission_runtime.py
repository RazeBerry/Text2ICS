"""Request-local profiling, deadlines, media ownership, and cancellable I/O."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterator, List, Protocol, TypeVar

from eventcalendar.exceptions.errors import RequestDeadlineExceeded

_T = TypeVar("_T")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubmissionMetrics:
    """Low-cardinality timing and call counts for one extraction request."""

    total_seconds: float = 0.0
    preprocessing_seconds: float = 0.0
    upload_seconds: float = 0.0
    generation_seconds: float = 0.0
    cleanup_seconds: float = 0.0
    image_count: int = 0
    input_bytes: int = 0
    inline_images: int = 0
    uploaded_images: int = 0
    generation_attempts: int = 0
    upload_attempts: int = 0
    reconciliation_attempts: int = 0
    cleanup_attempts: int = 0
    retries: int = 0

    @property
    def sdk_calls(self) -> int:
        """Count visible SDK calls (an SDK upload may use multiple HTTP calls)."""
        return (
            self.generation_attempts
            + self.upload_attempts
            + self.reconciliation_attempts
            + self.cleanup_attempts
        )


class SubmissionProfiler:
    """Mutable request-local accumulator; never shared across submissions."""

    def __init__(self, image_count: int) -> None:
        self.started = time.perf_counter()
        self.image_count = image_count
        self.preprocessing_seconds = 0.0
        self.upload_seconds = 0.0
        self.generation_seconds = 0.0
        self.cleanup_seconds = 0.0
        self.input_bytes = 0
        self.inline_images = 0
        self.uploaded_images = 0
        self.generation_attempts = 0
        self.upload_attempts = 0
        self.reconciliation_attempts = 0
        self.cleanup_attempts = 0
        self.retries = 0

    @contextmanager
    def phase(self, attribute: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            setattr(
                self,
                attribute,
                getattr(self, attribute) + (time.perf_counter() - started),
            )

    def snapshot(self) -> SubmissionMetrics:
        return SubmissionMetrics(
            total_seconds=time.perf_counter() - self.started,
            preprocessing_seconds=self.preprocessing_seconds,
            upload_seconds=self.upload_seconds,
            generation_seconds=self.generation_seconds,
            cleanup_seconds=self.cleanup_seconds,
            image_count=self.image_count,
            input_bytes=self.input_bytes,
            inline_images=self.inline_images,
            uploaded_images=self.uploaded_images,
            generation_attempts=self.generation_attempts,
            upload_attempts=self.upload_attempts,
            reconciliation_attempts=self.reconciliation_attempts,
            cleanup_attempts=self.cleanup_attempts,
            retries=self.retries,
        )


@dataclass(frozen=True)
class RequestBudget:
    """Monotonic end-to-end deadline shared by every request phase."""

    seconds: float
    started: float = field(default_factory=time.monotonic)

    @property
    def remaining(self) -> float:
        return max(0.0, self.seconds - (time.monotonic() - self.started))

    def timeout_for(self, phase_cap: float) -> float:
        remaining = self.remaining
        if remaining <= 0:
            raise RequestDeadlineExceeded(self.seconds)
        return min(phase_cap, remaining)


@dataclass
class PreparedMediaBatch:
    """Request contents plus the exact remote resources this operation owns."""

    contents: List[object] = field(default_factory=list)
    remote_files: List[object] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RemoteFileRef:
    """Cleanup handle retained even when an upload response is lost."""

    name: str


class NetworkRuntime(Protocol):
    """Injected execution policy for SDK calls."""

    def run(
        self,
        async_factory: Callable[[], Awaitable[_T]],
        sync_factory: Callable[[], _T],
        cancel_check: Callable[[], None],
        budget: RequestBudget,
    ) -> _T: ...

    def close(self, timeout_seconds: float) -> None: ...


class SynchronousNetworkRuntime:
    """Deterministic runtime used by SDK fakes and offline profiling."""

    def __init__(self, client) -> None:
        self._client = client

    def run(
        self,
        async_factory: Callable[[], Awaitable[_T]],
        sync_factory: Callable[[], _T],
        cancel_check: Callable[[], None],
        budget: RequestBudget,
    ) -> _T:
        del async_factory
        cancel_check()
        budget.timeout_for(budget.seconds)
        return sync_factory()

    def close(self, timeout_seconds: float) -> None:
        del timeout_seconds
        self._client.close()


class CancellableNetworkRuntime:
    """Own one async SDK loop and expose a blocking, cancellable boundary."""

    def __init__(self, client) -> None:
        self._client = client
        self._loop_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()
            ready = threading.Event()

            def run_loop() -> None:
                asyncio.set_event_loop(loop)
                ready.set()
                loop.run_forever()

            thread = threading.Thread(
                target=run_loop,
                name="calendar_network",
                daemon=True,
            )
            self._loop = loop
            self._thread = thread
            thread.start()
        ready.wait()
        return loop

    def run(
        self,
        async_factory: Callable[[], Awaitable[_T]],
        sync_factory: Callable[[], _T],
        cancel_check: Callable[[], None],
        budget: RequestBudget,
    ) -> _T:
        """Wait synchronously while cancellation remains able to stop HTTP."""
        del sync_factory
        cancel_check()
        budget.timeout_for(budget.seconds)
        future = asyncio.run_coroutine_threadsafe(async_factory(), self._ensure_loop())
        try:
            while True:
                cancel_check()
                remaining = budget.remaining
                if remaining <= 0:
                    raise RequestDeadlineExceeded(budget.seconds)
                try:
                    return future.result(timeout=min(0.05, remaining))
                except FutureTimeoutError:
                    continue
        except BaseException:
            if not future.done():
                future.cancel()
                try:
                    future.result(timeout=0.5)
                except BaseException:
                    pass
            raise

    def close(self, timeout_seconds: float) -> None:
        """Bound async transport shutdown, then close the sync transport."""
        if self._loop is not None and self._loop.is_running():
            close_future = asyncio.run_coroutine_threadsafe(
                self._client.aio.aclose(),
                self._loop,
            )
            try:
                close_future.result(timeout=timeout_seconds)
            except FutureTimeoutError:
                close_future.cancel()
                logger.warning("Timed out closing asynchronous Gemini transport")
            except Exception:
                logger.warning("Asynchronous Gemini transport close failed", exc_info=True)
            finally:
                self._loop.call_soon_threadsafe(self._loop.stop)
                if self._thread is not None and self._thread is not threading.current_thread():
                    self._thread.join(timeout=1.0)
                if self._thread is None or not self._thread.is_alive():
                    self._loop.close()
        self._client.close()
