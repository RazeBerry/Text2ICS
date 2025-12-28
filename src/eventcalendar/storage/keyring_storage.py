"""Keyring-based secure storage for API keys."""

import logging
from typing import Optional

from eventcalendar.config.constants import KEYRING_SERVICE_NAME, KEYRING_ACCOUNT_NAME

logger = logging.getLogger(__name__)

# Track whether we've seen the OS keyring fail this session
_keyring_available = True


def is_keyring_available() -> bool:
    """Check if keyring is available for use."""
    return _keyring_available


def load_from_keyring() -> Optional[str]:
    """Load the API key from the OS keyring if available.

    Returns:
        The API key if found, None otherwise.
    """
    global _keyring_available
    if not _keyring_available:
        return None

    try:
        import keyring
    except ImportError:
        _keyring_available = False
        return None

    try:
        return keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_ACCOUNT_NAME)
    except Exception as e:
        logger.warning("Keyring lookup failed: %s", e)
        _keyring_available = False
        return None


def save_to_keyring(api_key: str) -> bool:
    """Persist the API key to the OS keyring if available.

    Args:
        api_key: The API key to save.

    Returns:
        True if saved successfully, False otherwise.
    """
    global _keyring_available
    if not _keyring_available:
        return False

    try:
        import keyring
    except ImportError:
        _keyring_available = False
        return False

    try:
        keyring.set_password(KEYRING_SERVICE_NAME, KEYRING_ACCOUNT_NAME, api_key)
        return True
    except Exception as e:
        logger.warning("Keyring save failed: %s", e)
        _keyring_available = False
        return False


def delete_from_keyring() -> bool:
    """Delete the API key from the OS keyring.

    Returns:
        True if deleted successfully, False otherwise.
    """
    global _keyring_available
    if not _keyring_available:
        return False

    try:
        import keyring
    except ImportError:
        _keyring_available = False
        return False

    try:
        keyring.delete_password(KEYRING_SERVICE_NAME, KEYRING_ACCOUNT_NAME)
        return True
    except Exception as e:
        logger.warning("Keyring delete failed: %s", e)
        return False


# Backward compatibility aliases
_load_from_keyring = load_from_keyring
_save_to_keyring = save_to_keyring
