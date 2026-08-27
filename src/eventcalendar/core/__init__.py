"""Core business logic for EventCalendarGenerator."""

from eventcalendar.core.api_client import CalendarAPIClient, ExtractionResult
from eventcalendar.core.event_model import CalendarEvent
from eventcalendar.core.ics_builder import (
    ICSBatchResult,
    ICSMergedResult,
    build_ics_batch,
    build_ics_from_events,
    build_merged_ics,
    combine_ics_strings,
)
from eventcalendar.core.retry import is_retryable_error
from eventcalendar.core.submission_runtime import SubmissionMetrics

__all__ = [
    "CalendarAPIClient",
    "ExtractionResult",
    "SubmissionMetrics",
    "CalendarEvent",
    "ICSBatchResult",
    "ICSMergedResult",
    "build_ics_batch",
    "build_ics_from_events",
    "build_merged_ics",
    "combine_ics_strings",
    "is_retryable_error",
]
