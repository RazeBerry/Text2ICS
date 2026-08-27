"""
EventCalendarGenerator - Natural Language Calendar Event Creator

A PyQt6 desktop application that converts natural language descriptions
and images into calendar events using Google's Gemini AI.
"""

__version__ = "2.0.0"

# Public API - import commonly used components
from eventcalendar.config.settings import API_CONFIG, UI_CONFIG
from eventcalendar.exceptions.errors import (
    CalendarAPIError,
    EventValidationError,
    RequestDeadlineExceeded,
    RetryExhaustedError,
)
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
from eventcalendar.core.submission_runtime import SubmissionMetrics


def __getattr__(name: str):
    """Lazily expose the GUI class without importing PyQt during core use."""
    if name == "NLCalendarCreator":
        from eventcalendar.ui.main_window import NLCalendarCreator

        return NLCalendarCreator
    raise AttributeError(name)

__all__ = [
    # Version
    "__version__",
    # Config
    "API_CONFIG",
    "UI_CONFIG",
    # Exceptions
    "CalendarAPIError",
    "EventValidationError",
    "RetryExhaustedError",
    "RequestDeadlineExceeded",
    # Core
    "CalendarAPIClient",
    "ExtractionResult",
    "SubmissionMetrics",
    "CalendarEvent",
    "build_ics_from_events",
    "build_ics_batch",
    "build_merged_ics",
    "ICSBatchResult",
    "ICSMergedResult",
    "combine_ics_strings",
    "NLCalendarCreator",
]
