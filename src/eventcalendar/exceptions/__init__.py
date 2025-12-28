"""Custom exceptions for EventCalendarGenerator."""

from eventcalendar.exceptions.errors import (
    CalendarAPIError,
    TimezoneResolutionError,
    EventValidationError,
    ImageProcessingError,
    APIResponseError,
    RetryExhaustedError,
)

__all__ = [
    "CalendarAPIError",
    "TimezoneResolutionError",
    "EventValidationError",
    "ImageProcessingError",
    "APIResponseError",
    "RetryExhaustedError",
]
