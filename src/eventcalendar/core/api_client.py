"""Gemini API client for validated calendar-event extraction."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from string import Formatter
from typing import Callable, Dict, List, Optional, Tuple

from eventcalendar.config.constants import (
    STATUS_ATTEMPTING,
    STATUS_MAX_RETRIES,
    STATUS_SUCCESS,
)
from eventcalendar.config.settings import API_CONFIG
from eventcalendar.core.event_model import CalendarEvent
from eventcalendar.core.ics_builder import build_ics_from_events, combine_ics_strings
from eventcalendar.core.image_preprocessing import preprocess_image_for_upload
from eventcalendar.core.retry import is_api_key_error, is_retryable_error, wrap_api_key_error
from eventcalendar.exceptions.errors import (
    APIResponseError,
    CalendarAPIError,
    ImageProcessingError,
    RetryExhaustedError,
)
from eventcalendar.utils.masking import mask_key

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionResult:
    """Validated extraction output plus non-fatal attachment warnings."""

    events: List[Dict]
    warnings: List[str] = field(default_factory=list)


@dataclass
class UploadedImageBatch:
    """Remote uploads retained until generation is complete."""

    files: List[object] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)


class CalendarAPIClient:
    """Per-instance client for Google's supported ``google-genai`` SDK."""

    SYSTEM_PROMPT = """
Extract every distinct calendar event from the text and images.

Return a JSON array and nothing else. For each event:
- title, date, timezone, description, location, and all_day are required.
- date/end_date use YYYY-MM-DD.
- start_time/end_time each contain one clock time, never a range or date.
- omit start_time/end_time only when all_day is true.
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
            "required": ["title", "date", "timezone", "description", "location", "all_day"],
            "additionalProperties": False,
        },
    }

    def __init__(self, api_key: str):
        from google import genai
        from google.genai import types

        self.api_key_masked = mask_key(api_key)
        self.base_delay = API_CONFIG.base_delay
        self.max_retries = API_CONFIG.max_retries
        self.timeout_seconds = API_CONFIG.timeout_seconds
        self._closed = False
        self._close_lock = threading.Lock()
        self._types = types

        self._validate_prompt_template()
        http_options = types.HttpOptions(
            timeout=max(1, int(self.timeout_seconds * 1000)),
            # The app owns retry policy and status reporting; avoid nested retries.
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        self.client = genai.Client(api_key=api_key, http_options=http_options)
        self.generation_config = types.GenerateContentConfig(
            system_instruction=self.SYSTEM_PROMPT,
            temperature=API_CONFIG.temperature,
            top_p=API_CONFIG.top_p,
            top_k=API_CONFIG.top_k,
            max_output_tokens=API_CONFIG.max_output_tokens,
            response_mime_type="application/json",
            response_json_schema=self.RESPONSE_JSON_SCHEMA,
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

    def upload_to_gemini(self, path: str, mime_type: Optional[str] = None):
        """Upload one verified file through this client's credential boundary."""
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found: {path}")
        try:
            return self.client.files.upload(
                file=path,
                config=self._types.UploadFileConfig(mime_type=mime_type),
            )
        except Exception as exc:
            logger.warning("Image upload failed for %s: %s", Path(path).name, exc)
            if is_api_key_error(exc):
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
        self._check_cancelled(cancel_event)
        if self._closed:
            raise CalendarAPIError("API client is closed")

        prompt = self._build_prompt(event_description)
        if image_data:
            self._notify(status_callback, f"Preparing {len(image_data)} image(s)...")

        batch = self._prepare_images(image_data, cancel_event)
        warnings = list(batch.failures)
        if image_data and not batch.files:
            reason = "; ".join(batch.failures) or "no valid image could be uploaded"
            raise ImageProcessingError("attachments", reason)
        if warnings:
            self._notify(status_callback, f"Continuing with {len(batch.files)} image(s); {len(warnings)} failed.")

        try:
            for attempt in range(self.max_retries):
                self._check_cancelled(cancel_event)
                self._notify(
                    status_callback,
                    STATUS_ATTEMPTING.format(attempt=attempt + 1, max_retries=self.max_retries),
                )
                try:
                    response_text = self._call_api(prompt, batch.files)
                    events = self._parse_response(response_text)
                    self._notify(status_callback, STATUS_SUCCESS.format(count=len(events)))
                    return ExtractionResult(events=events, warnings=warnings)
                except (CalendarAPIError, CancelledError):
                    raise
                except Exception as exc:
                    if not self._handle_retry(exc, attempt, status_callback, cancel_event):
                        raise
        finally:
            self._delete_remote_files(batch.files)

        raise RetryExhaustedError(self.max_retries)

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
    ) -> UploadedImageBatch:
        batch = UploadedImageBatch()
        try:
            for file_path, mime_type, _unused_base64 in image_data:
                self._check_cancelled(cancel_event)
                if not file_path:
                    batch.failures.append("An attachment had no file path.")
                    continue
                try:
                    processed = preprocess_image_for_upload(file_path, mime_type)
                    try:
                        uploaded = self.upload_to_gemini(processed.path, processed.mime_type)
                        batch.files.append(uploaded)
                    finally:
                        processed.cleanup()
                except CalendarAPIError:
                    raise
                except Exception as exc:
                    reason = getattr(exc, "reason", str(exc))
                    batch.failures.append(f"{Path(file_path).name}: {reason}")
            return batch
        except Exception:
            self._delete_remote_files(batch.files)
            batch.files.clear()
            raise

    def _delete_remote_files(self, uploaded_files: List[object]) -> None:
        for uploaded in uploaded_files:
            name = getattr(uploaded, "name", None)
            if not name:
                continue
            try:
                self.client.files.delete(name=name)
            except Exception as exc:
                logger.warning("Failed to delete remote upload %s: %s", name, exc)

    def _call_api(self, prompt: str, uploaded_files: List[object]) -> str:
        logger.debug(
            "Sending extraction request (prompt_chars=%d, attachments=%d)",
            len(prompt),
            len(uploaded_files),
        )
        response = self.client.models.generate_content(
            model=API_CONFIG.model_name,
            contents=[prompt, *uploaded_files],
            config=self.generation_config,
        )
        response_text = getattr(response, "text", None)
        if not response_text:
            raise ValueError("Received empty response from API")
        logger.debug("Received extraction response (chars=%d)", len(response_text))
        return response_text

    def _parse_response(self, response_text: str) -> List[Dict]:
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

        validated: List[Dict] = []
        for index, raw_event in enumerate(decoded):
            try:
                validated.append(CalendarEvent.from_dict(raw_event).to_dict())
            except Exception as exc:
                raise APIResponseError(f"LLM event {index + 1} failed validation: {exc}") from exc
        return validated

    def _handle_retry(
        self,
        error: Exception,
        attempt: int,
        status_callback: Optional[Callable[[str], None]],
        cancel_event: Optional[threading.Event],
    ) -> bool:
        if is_api_key_error(error):
            raise wrap_api_key_error(error, self.api_key_masked) from error
        if not is_retryable_error(error):
            self._notify(status_callback, f"Error: {type(error).__name__} cannot be retried.")
            return False
        if attempt >= self.max_retries - 1:
            self._notify(status_callback, STATUS_MAX_RETRIES)
            raise RetryExhaustedError(self.max_retries, error) from error

        delay = min(self.base_delay * (2 ** attempt), API_CONFIG.max_backoff)
        self._notify(
            status_callback,
            f"Error occurred ({type(error).__name__}), retrying in {delay:.0f} seconds...",
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
        """Release the SDK HTTP client. Safe to call more than once."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self.client.close()

    def __enter__(self) -> "CalendarAPIClient":
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()
