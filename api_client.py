"""
api_client.py - Backward Compatibility Layer

This file re-exports all public symbols from the refactored package
to maintain backward compatibility with existing imports.

DEPRECATED: Import from eventcalendar.core instead.
Example: from eventcalendar.core import CalendarAPIClient
"""

import sys
import os
import warnings

# Add src to path for package imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Emit deprecation warning on import
warnings.warn(
    "Importing from api_client.py is deprecated. "
    "Use 'from eventcalendar.core import ...' instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export core components
from eventcalendar.core.api_client import CalendarAPIClient
from eventcalendar.core.ics_builder import build_ics_from_events
from eventcalendar.core.event_model import CalendarEvent
from eventcalendar.core.retry import is_retryable_error as _is_retryable_error

# Re-export utilities
from eventcalendar.utils.masking import mask_key as _mask_key

__all__ = [
    'CalendarAPIClient',
    'build_ics_from_events',
    'CalendarEvent',
    '_is_retryable_error',
    '_mask_key',
]
