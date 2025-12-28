"""
exceptions.py - Backward Compatibility Layer

This file re-exports all public symbols from the refactored package
to maintain backward compatibility with existing imports.

DEPRECATED: Import from eventcalendar.exceptions instead.
Example: from eventcalendar.exceptions import CalendarAPIError
"""

import sys
import os
import warnings

# Add src to path for package imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Emit deprecation warning on import
warnings.warn(
    "Importing from exceptions.py is deprecated. "
    "Use 'from eventcalendar.exceptions import ...' instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export exceptions
from eventcalendar.exceptions.errors import (
    CalendarAPIError,
    TimezoneResolutionError,
    EventValidationError,
    ImageProcessingError,
    APIResponseError,
    RetryExhaustedError,
)

__all__ = [
    'CalendarAPIError',
    'TimezoneResolutionError',
    'EventValidationError',
    'ImageProcessingError',
    'APIResponseError',
    'RetryExhaustedError',
]
