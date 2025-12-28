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
    RetryExhaustedError,
)
from eventcalendar.core.api_client import CalendarAPIClient
from eventcalendar.core.event_model import CalendarEvent
from eventcalendar.core.ics_builder import build_ics_from_events, combine_ics_strings

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
    # Core
    "CalendarAPIClient",
    "CalendarEvent",
    "build_ics_from_events",
    "combine_ics_strings",
]
