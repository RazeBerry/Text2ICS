"""
EventCalendarGenerator - Backward Compatibility Layer

This file re-exports all public symbols from the refactored package
to maintain backward compatibility with existing imports.

DEPRECATED: Import from eventcalendar package directly instead.
Example: from eventcalendar.ui import NLCalendarCreator
"""

import sys
import os
import warnings

# Add src to path for package imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Emit deprecation warning on import (only once)
warnings.warn(
    "Importing from Calender.py is deprecated. "
    "Use 'from eventcalendar import ...' instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export datetime for test monkeypatching compatibility
from datetime import datetime, timedelta

# Re-export UI components
from eventcalendar.ui.main_window import NLCalendarCreator
from eventcalendar.ui.widgets.api_key_dialog import APIKeySetupDialog
from eventcalendar.ui.widgets.image_area import ImageAttachmentArea, ImageAttachmentPayload

# Re-export theme system
from eventcalendar.ui.theme.manager import ThemeManager, set_theme, toggle_theme
from eventcalendar.ui.theme.colors import get_color, COLORS
from eventcalendar.ui.theme.palettes import LIGHT_PALETTE, DARK_PALETTE
from eventcalendar.ui.theme.scales import TYPOGRAPHY_SCALE, SPACING_SCALE, BORDER_RADIUS
from eventcalendar.ui.styles.base import px

# Re-export error handling
from eventcalendar.ui.error_messages import get_user_friendly_error

# Re-export storage functions
from eventcalendar.storage.key_manager import (
    load_api_key,
    save_api_key,
    get_api_key_source,
    migrate_legacy_key,
    check_and_warn_legacy_storage,
)
from eventcalendar.storage.env_storage import (
    get_user_config_dir,
    get_env_file_path,
    get_legacy_env_path,
    get_executable_dir_env_path,
)

# Re-export ICS builder
from eventcalendar.core.ics_builder import combine_ics_strings

# Re-export utilities
from eventcalendar.utils.paths import get_resource_path

# Re-export constants
from eventcalendar.config.constants import (
    KEYRING_SERVICE_NAME,
    KEYRING_ACCOUNT_NAME,
    PREFERRED_ENV_VAR,
    PRIMARY_ENV_VAR,
    SUPPORTED_IMAGE_EXTENSIONS,
)

# For test compatibility - some tests define patterns locally
TIME_PATTERNS = None  # Placeholder for compatibility
DATE_PATTERNS = None  # Placeholder for compatibility

__all__ = [
    # datetime for monkeypatching
    'datetime',
    'timedelta',
    # UI
    'NLCalendarCreator',
    'APIKeySetupDialog',
    'ImageAttachmentArea',
    'ImageAttachmentPayload',
    # Theme
    'ThemeManager',
    'set_theme',
    'toggle_theme',
    'get_color',
    'COLORS',
    'LIGHT_PALETTE',
    'DARK_PALETTE',
    'TYPOGRAPHY_SCALE',
    'SPACING_SCALE',
    'BORDER_RADIUS',
    'px',
    # Error handling
    'get_user_friendly_error',
    # Storage
    'load_api_key',
    'save_api_key',
    'get_api_key_source',
    'migrate_legacy_key',
    'check_and_warn_legacy_storage',
    'get_user_config_dir',
    'get_env_file_path',
    'get_legacy_env_path',
    'get_executable_dir_env_path',
    # ICS
    'combine_ics_strings',
    # Utils
    'get_resource_path',
    # Constants
    'KEYRING_SERVICE_NAME',
    'KEYRING_ACCOUNT_NAME',
    'PREFERRED_ENV_VAR',
    'PRIMARY_ENV_VAR',
    'SUPPORTED_IMAGE_EXTENSIONS',
]

# Entry point for backward compatibility
if __name__ == '__main__':
    from eventcalendar.__main__ import main
    main()
