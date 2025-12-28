"""
config.py - Backward Compatibility Layer

This file re-exports all public symbols from the refactored package
to maintain backward compatibility with existing imports.

DEPRECATED: Import from eventcalendar.config instead.
Example: from eventcalendar.config import API_CONFIG
"""

import sys
import os
import warnings

# Add src to path for package imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Emit deprecation warning on import
warnings.warn(
    "Importing from config.py is deprecated. "
    "Use 'from eventcalendar.config import ...' instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export configuration
from eventcalendar.config.settings import APIConfig, UIConfig, API_CONFIG, UI_CONFIG

__all__ = [
    'APIConfig',
    'UIConfig',
    'API_CONFIG',
    'UI_CONFIG',
]
