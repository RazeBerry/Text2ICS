"""Gemini API client for validated calendar-event extraction."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from string import Formatter
from typing import Awaitable, Callable, Dict, Iterator, List, Optional, Tuple, TypeVar

from eventcalendar.config.constants import (
    STATUS_ATTEMPTING,
    STATUS_MAX_RETRIES,
    STATUS_SUCCESS,
)
from eventcalendar.config.settings import API_CONFIG
from eventcalendar.core.event_model import CalendarEvent
from eventcalendar.core.ics_builder import build_ics_from_events, combine_ics_strings
from eventcalendar.core.image_preprocessing import preprocess_image_for_upload
from eventcalendar.core.retry import RetryCategory, classify_retry, wrap_api_key_error
from eventcalendar.core.submission_runtime import (
    CancellableNetworkRuntime,
    NetworkRuntime,
    PreparedMediaBatch,
    RemoteFileRef,
    RequestBudget,
    SubmissionMetrics,
    SubmissionProfiler,
)
from eventcalendar.exceptions.errors import (
    APIResponseError,
    CalendarAPIError,
    ImageProcessingError,
    RequestDeadlineExceeded,
    RetryExhaustedError,
)
from eventcalendar.utils.masking import mask_key

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


@dataclass(frozen=True)
class ExtractionResult:
    """Validated extraction output plus non-fatal attachment warnings."""

    events: List[Dict]
    warnings: List[str] = field(default_factory=list)
    event_models: Tuple[CalendarEvent, ...] = field(default_factory=tuple)
    metrics: SubmissionMetrics = field(default_factory=SubmissionMetrics)


class CalendarAPIClient:
    """Per-instance client for Google's supported ``google-genai`` SDK."""

    SYSTEM_PROMPT = """
Extract every distinct calendar event from the text and images.

Return a JSON array and nothing else. For each event:
- title, date, start_time, end_time, timezone, description, location, and all_day are required.
- date/end_date use YYYY-MM-DD.
- start_time/end_time each contain one clock time, never a range or date.
- always output start_time and end_time; for an all_day event set both to "00:00" (they are ignored).
- preserve stated wall-clock times; never convert them.
- use "local" when no timezone is stated.
- use an IANA timezone or numeric UTC offset when an abbreviation is ambiguous.
- start_timezone/end_timezone and end_date may describe travel across zones/dates.
- estimate a reasonable end time when only a start time is given.
- uid may be omitted; the application will create one.
"""

    USER_PROMPT_TEMPLATE = """
<event_description>
{event_description}
</event_description>

Today's date is {day_name}, {formatted_date}.
Current timezone: {user_timezone}
"""

    RESPONSE_JSON_SCHEMA = {
        # Do not add maxItems here: Gemini 3.7's generateContent endpoint
        # currently rejects it even though the general structured-output guide
        # lists that keyword.  _parse_response_models enforces the same bound.
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "uid": {"type": "string"},
                "title": {"type": "string"},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
                "date": {"type": "string"},
                "end_date": {"type": "string"},
                "timezone": {"type": "string"},
                "start_timezone": {"type": "string"},
                "end_timezone": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "all_day": {"type": "boolean"},
            },
            # Gemini 3.x constrained decoding emits properties in this order and skips
            # optional ones, so the time fields must be ordered early and required.
            # All-day events send a placeholder time that CalendarEvent.from_dict ignores.
            "propertyOrdering": [
                "title", "date", "start_time", "end_time", "end_date", "timezone",
                "start_timezone", "end_timezone", "description", "location", "all_day", "uid",
            ],
            "required": [
                "title", "date", "start_time", "end_time",
                "timezone", "description", "location", "all_day",
            ],
            "additionalProperties": False,
        },
    }

    def __init__(self, api_key: str):
        from google import genai
        from google.genai import types

        self.api_key_masked = mask_key(api_key)
        self.base_delay = API_CONFIG.base_delay
        self.max_retries = API_CONFIG.max_retries
        self._closed = False
        self._close_lock = threading.Lock()
        self._active_operations = 0
        self._transport_close_started = False
        self._types = types

        self._validate_prompt_template()
        http_options = types.HttpOptions(
            timeout=max(1, int(API_CONFIG.generation_timeout_seconds * 1000)),
            # The app owns retry policy and status reporting; avoid nested retries.
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        self.client = genai.Client(api_key=api_key, http_options=http_options)
        self._network_runtime: NetworkRuntime = CancellableNetworkRuntime(self.client)
        self.generation_config = types.GenerateContentConfig(
            system_instruction=self.SYSTEM_PROMPT,
            max_output_tokens=API_CONFIG.max_output_tokens,
            response_mime_type="application/json",
            response_json_schema=self.RESPONSE_JSON_SCHEMA,
            thinking_config=types.ThinkingConfig(
                thinking_level=API_CONFIG.thinking_level,
            ),
        )

    def _http_options(self, timeout_seconds: float):
        """Build per-call options so retries cannot silently multiply."""
        if not hasattr(self._types, "HttpOptions"):
            return None
        return self._types.HttpOptions(
            timeout=max(1, int(timeout_seconds * 1000)),
            retry_options=self._types.HttpRetryOptions(attempts=1),
        )

    def _run_network_call(
        self,
        async_factory: Callable[[], Awaitable[_T]],
        sync_factory: Callable[[], _T],
        cancel_event: Optional[threading.Event],
        budget: RequestBudget,
    ) -> _T:
        """Run cancellable SDK I/O, with a sync seam for lightweight test fakes."""
        return self._network_runtime.run(
            async_factory,
            sync_factory,
            lambda: self._check_cancelled(cancel_event),
            budget,
        )

    def _validate_prompt_template(self) -> None:
        template_keys = {fn for _, fn, _, _ in Formatter().parse(self.USER_PROMPT_TEMPLATE) if fn}
        required = {"event_description", "day_name", "formatted_date", "user_timezone"}
        if template_keys != required:
            raise ValueError(f"Template mismatch! Expected keys {required} but got {template_keys}")

    @staticmethod
    def _notify(callback: Optional[Callable[[str], None]], message: str) -> None:
        """Status observers are best-effort and never alter API control flow."""
        if callback is None:
            return
        try:
            callback(message)
        except Exception:
            logger.debug("Status callback failed", exc_info=True)

    @staticmethod
    def _check_cancelled(cancel_event: Optional[threading.Event]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("Event extraction was cancelled")

    @contextmanager
    def _operation(self) -> Iterator[None]:
        """Keep the transport alive for one public unit of SDK work."""
        with self._close_lock:
            if self._closed:
                raise CalendarAPIError("API client is closed")
            self._active_operations += 1
        try:
            yield
        finally:
            should_close = False
            with self._close_lock:
                self._active_operations -= 1
                if (
                    self._closed
                    and self._active_operations == 0
                    and not self._transport_close_started
                ):
                    self._transport_close_started = True
                    should_close = True
            if should_close:
                try:
                    self._close_transport()
                except Exception:
                    # A deferred close must not replace the active operation's result.
                    logger.warning("Deferred API client close failed", exc_info=True)

    def upload_to_gemini(self, path: str, mime_type: Optional[str] = None):
        """Upload one verified file through this client's credential boundary."""
        with self._operation():
            budget = RequestBudget(API_CONFIG.request_deadline_seconds)
            return self._upload_once(path, mime_type, None, None, budget)

    def _upload_once(
        self,
        path: str,
        mime_type: Optional[str],
        remote_name: Optional[str],
        cancel_event: Optional[threading.Event],
        budget: RequestBudget,
    ):
        """Perform one upload attempt inside an already-owned operation."""
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found: {path}")
        timeout = budget.timeout_for(API_CONFIG.upload_timeout_seconds)
        config_kwargs = {"mime_type": mime_type, "name": remote_name}
        http_options = self._http_options(timeout)
        if http_options is not None:
            config_kwargs["http_options"] = http_options
        config = self._types.UploadFileConfig(**config_kwargs)
        try:
            return self._run_network_call(
                lambda: self.client.aio.files.upload(file=path, config=config),
                lambda: self.client.files.upload(file=path, config=config),
                cancel_event,
                budget,
            )
        except Exception as exc:
            logger.warning("Image upload failed for %s: %s", Path(path).name, exc)
            if classify_retry(exc).category == RetryCategory.CREDENTIALS:
                raise wrap_api_key_error(exc, self.api_key_masked) from exc
            raise

    def extract_events(
        self,
        event_description: str,
        image_data: List[Tuple[str, str, Optional[str]]],
        status_callback: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> ExtractionResult:
        """Extract and validate events, cleaning every remote upload on exit."""
        with self._operation():
            return self._extract_events(
                event_description,
                image_data,
                status_callback,
                cancel_event,
            )

    def _extract_events(
        self,
        event_description: str,
        image_data: List[Tuple[str, str, Optional[str]]],
        status_callback: Optional[Callable[[str], None]],
        cancel_event: Optional[threading.Event],
    ) -> ExtractionResult:
        self._check_cancelled(cancel_event)
        budget = RequestBudget(API_CONFIG.request_deadline_seconds)
        profiler = SubmissionProfiler(len(image_data))
        prompt = self._build_prompt(event_description)
        try:
            batch = self._prepare_images(
                image_data,
                cancel_event,
                status_callback,
                budget,
                profiler,
            )
            warnings = list(batch.failures)
            try:
                if image_data and not batch.contents:
                    reason = "; ".join(batch.failures) or "no valid image could be attached"
                    raise ImageProcessingError("attachments", reason)
                if warnings:
                    self._notify(
                        status_callback,
                        f"Continuing with {len(batch.contents)} image(s); "
                        f"{len(warnings)} failed.",
                    )

                event_models: Optional[Tuple[CalendarEvent, ...]] = None
                for attempt in range(self.max_retries):
                    self._check_cancelled(cancel_event)
                    budget.timeout_for(API_CONFIG.generation_timeout_seconds)
                    self._notify(
                        status_callback,
                        STATUS_ATTEMPTING.format(
                            attempt=attempt + 1,
                            max_retries=self.max_retries,
                        ),
                    )
                    try:
                        profiler.generation_attempts += 1
                        with profiler.phase("generation_seconds"):
                            response_text = self._call_api(
                                prompt,
                                batch.contents,
                                cancel_event,
                                budget,
                            )
                        event_models = self._parse_response_models(response_text)
                        break
                    except (CalendarAPIError, CancelledError):
                        raise
                    except Exception as exc:
                        if not self._handle_retry(
                            exc,
                            attempt,
                            status_callback,
                            cancel_event,
                            budget=budget,
                            profiler=profiler,
                        ):
                            raise
                if event_models is None:
                    raise RetryExhaustedError(self.max_retries)
            finally:
                if batch.remote_files:
                    self._notify(status_callback, "Cleaning up temporary uploads...")
                    cleanup_budget = RequestBudget(API_CONFIG.cleanup_budget_seconds)
                    with profiler.phase("cleanup_seconds"):
                        self._delete_remote_files(
                            batch.remote_files,
                            cleanup_budget,
                            profiler,
                        )

            metrics = profiler.snapshot()
            events = [event.to_dict() for event in event_models]
            self._log_profile(metrics, succeeded=True)
            self._notify(status_callback, STATUS_SUCCESS.format(count=len(event_models)))
            return ExtractionResult(
                events=events,
                warnings=warnings,
                event_models=event_models,
                metrics=metrics,
            )
        except BaseException:
            self._log_profile(profiler.snapshot(), succeeded=False)
            raise

    def get_event_data(
        self,
        event_description: str,
        image_data: List[Tuple[str, str, Optional[str]]],
        status_callback: Callable[[str], None],
    ) -> List[Dict]:
        """Backward-compatible list-returning extraction helper."""
        return self.extract_events(event_description, image_data, status_callback).events

    def _build_prompt(self, event_description: str) -> str:
        if not event_description:
            event_description = "Event details are provided via attached images."
        current_date = datetime.now()
        try:
            import tzlocal

            user_timezone = tzlocal.get_localzone_name()
        except Exception:
            user_timezone = str(current_date.astimezone().tzinfo)
        return self.USER_PROMPT_TEMPLATE.format(
            event_description=event_description,
            day_name=current_date.strftime("%A"),
            formatted_date=current_date.strftime("%B %d, %Y"),
            user_timezone=user_timezone,
        )

    def _prepare_images(
        self,
        image_data: List[Tuple[str, str, Optional[str]]],
        cancel_event: Optional[threading.Event],
        status_callback: Optional[Callable[[str], None]] = None,
        budget: Optional[RequestBudget] = None,
        profiler: Optional[SubmissionProfiler] = None,
    ) -> PreparedMediaBatch:
        """Preprocess serially, inline small transient media, upload only overflow."""
        batch = PreparedMediaBatch()
        budget = budget or RequestBudget(API_CONFIG.request_deadline_seconds)
        profiler = profiler or SubmissionProfiler(len(image_data))
        inline_bytes = 0
        try:
            for index, (file_path, mime_type, _unused_base64) in enumerate(image_data):
                self._check_cancelled(cancel_event)
                budget.timeout_for(API_CONFIG.upload_timeout_seconds)
                if not file_path:
                    batch.failures.append("An attachment had no file path.")
                    continue
                try:
                    self._notify(
                        status_callback,
                        f"Optimizing image {index + 1} of {len(image_data)}...",
                    )
                    with profiler.phase("preprocessing_seconds"):
                        processed = preprocess_image_for_upload(file_path, mime_type)
                    try:
                        size_bytes = Path(processed.path).stat().st_size
                        profiler.input_bytes += size_bytes
                        can_inline = (
                            hasattr(self._types, "Part")
                            and inline_bytes + size_bytes
                            <= API_CONFIG.inline_image_budget_bytes
                        )
                        if can_inline:
                            with profiler.phase("preprocessing_seconds"):
                                data = Path(processed.path).read_bytes()
                                part = self._types.Part.from_bytes(
                                    data=data,
                                    mime_type=processed.mime_type or "application/octet-stream",
                                )
                            batch.contents.append(part)
                            inline_bytes += size_bytes
                            profiler.inline_images += 1
                            self._notify(
                                status_callback,
                                f"Attached image {index + 1} of {len(image_data)} directly.",
                            )
                        else:
                            remote_name = f"files/eventcalendar-{uuid.uuid4().hex}"
                            # Keep the deterministic name before starting I/O so an
                            # accepted-but-response-lost upload is still cleanable.
                            batch.remote_files.append(RemoteFileRef(remote_name))
                            self._notify(
                                status_callback,
                                f"Uploading large image {index + 1} of {len(image_data)}...",
                            )
                            with profiler.phase("upload_seconds"):
                                uploaded = self._upload_with_retry(
                                    processed.path,
                                    processed.mime_type,
                                    Path(file_path).name,
                                    remote_name,
                                    status_callback,
                                    cancel_event,
                                    budget,
                                    profiler,
                                )
                            batch.contents.append(uploaded)
                            profiler.uploaded_images += 1
                    finally:
                        processed.cleanup()
                except CancelledError:
                    raise
                except (ImageProcessingError, RetryExhaustedError) as exc:
                    reason = getattr(exc, "reason", str(exc))
                    batch.failures.append(f"{Path(file_path).name}: {reason}")
                except CalendarAPIError:
                    # Credential and application errors apply to the request, not
                    # just one attachment, so partial-batch fallback is unsafe.
                    raise
                except Exception as exc:
                    reason = getattr(exc, "reason", str(exc))
                    batch.failures.append(f"{Path(file_path).name}: {reason}")
            return batch
        except Exception:
            cleanup_budget = RequestBudget(API_CONFIG.cleanup_budget_seconds)
            self._delete_remote_files(batch.remote_files, cleanup_budget, profiler)
            batch.remote_files.clear()
            raise

    def _upload_with_retry(
        self,
        path: str,
        mime_type: Optional[str],
        display_name: str,
        remote_name: str,
        status_callback: Optional[Callable[[str], None]],
        cancel_event: Optional[threading.Event],
        budget: RequestBudget,
        profiler: SubmissionProfiler,
    ):
        """Retry one preprocessed file without repeating preprocessing."""
        for attempt in range(self.max_retries):
            self._check_cancelled(cancel_event)
            try:
                profiler.upload_attempts += 1
                return self._upload_once(
                    path,
                    mime_type,
                    remote_name,
                    cancel_event,
                    budget,
                )
            except CalendarAPIError:
                raise
            except Exception as exc:
                if not classify_retry(exc).retryable:
                    self._handle_retry(
                        exc,
                        attempt,
                        status_callback,
                        cancel_event,
                        context=f"Uploading {display_name}",
                        budget=budget,
                        profiler=profiler,
                    )
                    raise
                recovered = self._recover_uploaded_file(
                    remote_name,
                    cancel_event,
                    budget,
                    profiler,
                )
                if recovered is not None:
                    logger.info("Recovered completed upload %s after response loss", remote_name)
                    return recovered
                if not self._handle_retry(
                    exc,
                    attempt,
                    status_callback,
                    cancel_event,
                    context=f"Uploading {display_name}",
                    budget=budget,
                    profiler=profiler,
                ):
                    raise
        raise RetryExhaustedError(self.max_retries)

    def _recover_uploaded_file(
        self,
        remote_name: str,
        cancel_event: Optional[threading.Event],
        budget: RequestBudget,
        profiler: SubmissionProfiler,
    ) -> Optional[object]:
        """Resolve an upload whose server acceptance outlived its response."""
        if not hasattr(self._types, "GetFileConfig"):
            return None
        timeout = budget.timeout_for(min(3.0, API_CONFIG.upload_timeout_seconds))
        config = self._types.GetFileConfig(http_options=self._http_options(timeout))
        profiler.reconciliation_attempts += 1
        try:
            return self._run_network_call(
                lambda: self.client.aio.files.get(name=remote_name, config=config),
                lambda: self.client.files.get(name=remote_name, config=config),
                cancel_event,
                budget,
            )
        except (CancelledError, RequestDeadlineExceeded):
            raise
        except Exception as exc:
            decision = classify_retry(exc)
            if decision.category == RetryCategory.CREDENTIALS:
                raise wrap_api_key_error(exc, self.api_key_masked) from exc
            logger.debug("Upload reconciliation did not find %s: %s", remote_name, exc)
            return None

    def _delete_remote_files(
        self,
        uploaded_files: List[object],
        budget: Optional[RequestBudget] = None,
        profiler: Optional[SubmissionProfiler] = None,
    ) -> None:
        budget = budget or RequestBudget(API_CONFIG.cleanup_budget_seconds)
        for uploaded in uploaded_files:
            name = getattr(uploaded, "name", None)
            if not name:
                continue
            for attempt in range(API_CONFIG.cleanup_retries):
                try:
                    timeout = budget.timeout_for(API_CONFIG.cleanup_timeout_seconds)
                    config_kwargs = {}
                    http_options = self._http_options(timeout)
                    if http_options is not None:
                        config_kwargs["http_options"] = http_options
                    config = self._types.DeleteFileConfig(**config_kwargs)
                    if profiler is not None:
                        profiler.cleanup_attempts += 1
                    self._run_network_call(
                        lambda: self.client.aio.files.delete(name=name, config=config),
                        lambda: self.client.files.delete(name=name, config=config),
                        None,
                        budget,
                    )
                    break
                except RequestDeadlineExceeded:
                    logger.warning(
                        "Remote cleanup budget exhausted; files expire server-side: %s",
                        name,
                    )
                    return
                except Exception as exc:
                    decision = classify_retry(exc)
                    if not decision.retryable or attempt >= API_CONFIG.cleanup_retries - 1:
                        logger.warning("Failed to delete remote upload %s: %s", name, exc)
                        break
                    delay = min(0.25, budget.remaining)
                    if delay > 0:
                        time.sleep(delay)

    def _call_api(
        self,
        prompt: str,
        media_contents: List[object],
        cancel_event: Optional[threading.Event],
        budget: RequestBudget,
    ) -> str:
        logger.debug(
            "Sending extraction request (prompt_chars=%d, attachments=%d)",
            len(prompt),
            len(media_contents),
        )
        timeout = budget.timeout_for(API_CONFIG.generation_timeout_seconds)
        config = self.generation_config
        if hasattr(config, "model_copy"):
            config = config.model_copy(
                update={"http_options": self._http_options(timeout)},
            )
        response = self._run_network_call(
            lambda: self.client.aio.models.generate_content(
                model=API_CONFIG.model_name,
                contents=[prompt, *media_contents],
                config=config,
            ),
            lambda: self.client.models.generate_content(
                model=API_CONFIG.model_name,
                contents=[prompt, *media_contents],
                config=config,
            ),
            cancel_event,
            budget,
        )
        response_text = getattr(response, "text", None)
        if not response_text:
            raise ValueError("Received empty response from API")
        logger.debug("Received extraction response (chars=%d)", len(response_text))
        return response_text

    @staticmethod
    def _log_profile(metrics: SubmissionMetrics, *, succeeded: bool) -> None:
        logger.info(
            "Gemini submission profile success=%s total=%.3fs preprocess=%.3fs "
            "upload=%.3fs generation=%.3fs cleanup=%.3fs images=%d inline=%d "
            "uploaded=%d bytes=%d sdk_calls=%d retries=%d",
            succeeded,
            metrics.total_seconds,
            metrics.preprocessing_seconds,
            metrics.upload_seconds,
            metrics.generation_seconds,
            metrics.cleanup_seconds,
            metrics.image_count,
            metrics.inline_images,
            metrics.uploaded_images,
            metrics.input_bytes,
            metrics.sdk_calls,
            metrics.retries,
        )

    def _parse_response_models(self, response_text: str) -> Tuple[CalendarEvent, ...]:
        """Decode the model response once into the domain boundary type."""
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            cleaned = cleaned[first_newline + 1:] if first_newline != -1 else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        try:
            decoded = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise APIResponseError(f"LLM returned invalid JSON: {exc}") from exc
        if not isinstance(decoded, list):
            raise APIResponseError("LLM response must be a JSON array")
        if len(decoded) > 64:
            raise APIResponseError("LLM response exceeded the 64-event safety limit")

        validated: List[CalendarEvent] = []
        for index, raw_event in enumerate(decoded):
            try:
                validated.append(CalendarEvent.from_dict(raw_event))
            except Exception as exc:
                raise APIResponseError(f"LLM event {index + 1} failed validation: {exc}") from exc
        return tuple(validated)

    def _handle_retry(
        self,
        error: Exception,
        attempt: int,
        status_callback: Optional[Callable[[str], None]],
        cancel_event: Optional[threading.Event],
        *,
        context: str = "Request",
        budget: Optional[RequestBudget] = None,
        profiler: Optional[SubmissionProfiler] = None,
    ) -> bool:
        decision = classify_retry(error)
        if decision.category == RetryCategory.CREDENTIALS:
            raise wrap_api_key_error(error, self.api_key_masked) from error
        if not decision.retryable:
            self._notify(
                status_callback,
                f"{context} failed ({decision.category.value}); it cannot be retried.",
            )
            return False
        if attempt >= self.max_retries - 1:
            self._notify(status_callback, STATUS_MAX_RETRIES)
            raise RetryExhaustedError(self.max_retries, error) from error

        exponential_delay = self.base_delay * (2 ** attempt)
        requested_delay = decision.retry_after_seconds or 0.0
        delay = min(max(exponential_delay, requested_delay), API_CONFIG.max_backoff)
        if budget is not None:
            if budget.remaining <= 0:
                raise RequestDeadlineExceeded(budget.seconds)
            delay = min(delay, budget.remaining)
        if profiler is not None:
            profiler.retries += 1
        self._notify(
            status_callback,
            f"{context} failed ({decision.category.value}), retrying in {delay:.1f} seconds...",
        )
        if cancel_event is not None:
            if cancel_event.wait(delay):
                raise CancelledError("Event extraction was cancelled")
        else:
            time.sleep(delay)
        return True

    def create_calendar_event(
        self,
        event_description: str,
        image_data: List[Tuple[str, str, Optional[str]]],
        status_callback: Callable[[str], None],
    ) -> str:
        events = self.get_event_data(event_description, image_data, status_callback)
        if not events:
            raise APIResponseError("API returned no event data")
        ics_strings, warnings = build_ics_from_events(events)
        if not ics_strings:
            raise APIResponseError("Failed to build ICS content from event data")
        if warnings:
            self._notify(status_callback, " | ".join(warnings))
        return combine_ics_strings(ics_strings)

    def close(self) -> None:
        """Reject new work and close the transport after active cleanup finishes."""
        should_close = False
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            if self._active_operations == 0 and not self._transport_close_started:
                self._transport_close_started = True
                should_close = True
        if should_close:
            try:
                self._close_transport()
            except Exception:
                # Closing is terminal and best-effort; callers still need to
                # finish their own executor and temporary-file cleanup.
                logger.warning("API client transport close failed", exc_info=True)

    def _close_transport(self) -> None:
        """Close sync/async transports and retire the cancellable network loop."""
        runtime = getattr(self, "_network_runtime", None)
        if runtime is None:
            self.client.close()
            return
        runtime.close(API_CONFIG.cleanup_budget_seconds)

    def __enter__(self) -> "CalendarAPIClient":
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()
