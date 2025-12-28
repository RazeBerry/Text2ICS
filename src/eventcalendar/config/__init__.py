"""Configuration module for EventCalendarGenerator."""

from eventcalendar.config.settings import API_CONFIG, UI_CONFIG, APIConfig, UIConfig
from eventcalendar.config.constants import (
    KEYRING_SERVICE_NAME,
    KEYRING_ACCOUNT_NAME,
    PREFERRED_ENV_VAR,
    PRIMARY_ENV_VAR,
    SUPPORTED_IMAGE_EXTENSIONS,
    DEFAULT_REMINDER_MINUTES,
    ICS_PRODID,
)

__all__ = [
    "API_CONFIG",
    "UI_CONFIG",
    "APIConfig",
    "UIConfig",
    "KEYRING_SERVICE_NAME",
    "KEYRING_ACCOUNT_NAME",
    "PREFERRED_ENV_VAR",
    "PRIMARY_ENV_VAR",
    "SUPPORTED_IMAGE_EXTENSIONS",
    "DEFAULT_REMINDER_MINUTES",
    "ICS_PRODID",
]
