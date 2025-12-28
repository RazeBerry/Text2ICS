"""High-level API key management."""

import logging
import os
from typing import Optional, Tuple

from dotenv import set_key

from eventcalendar.config.constants import PREFERRED_ENV_VAR, PRIMARY_ENV_VAR
from eventcalendar.storage.keyring_storage import load_from_keyring, save_to_keyring
from eventcalendar.storage.env_storage import (
    get_env_file_path,
    get_legacy_env_path,
    get_executable_dir_env_path,
    load_from_env_file,
    store_in_env_file,
    harden_file_permissions,
)

logger = logging.getLogger(__name__)


def get_api_key_source() -> Tuple[Optional[str], str]:
    """Determine which storage location is currently being used for the API key.

    Returns:
        Tuple of (api_key, source_description).
    """
    # Check environment variables first
    env_key = os.environ.get(PREFERRED_ENV_VAR) or os.environ.get(PRIMARY_ENV_VAR)
    if env_key:
        source_name = PREFERRED_ENV_VAR if os.environ.get(PREFERRED_ENV_VAR) else PRIMARY_ENV_VAR
        return env_key, f"Environment Variable ({source_name})"

    # Check keyring
    keyring_key = load_from_keyring()
    if keyring_key:
        return keyring_key, "macOS Keychain (Secure)"

    # Check user config .env
    env_file_key = load_from_env_file(get_env_file_path())
    if env_file_key:
        return env_file_key, f"User Config: {get_env_file_path()}"

    # Check for .env next to executable (packaged builds)
    executable_env_key = load_from_env_file(get_executable_dir_env_path())
    if executable_env_key:
        exe_path = get_executable_dir_env_path()
        return executable_env_key, f"Executable Directory: {exe_path}"

    # Check legacy location
    legacy_key = load_from_env_file(get_legacy_env_path())
    if legacy_key:
        return legacy_key, f"LEGACY (Insecure): {get_legacy_env_path()}"

    return None, "No API Key Found"


def migrate_legacy_key() -> Tuple[bool, str]:
    """Migrate API key from legacy .env (project directory) to secure storage.

    Returns:
        Tuple of (success, message).
    """
    legacy_path = get_legacy_env_path()

    # Check if legacy key exists
    if not legacy_path.exists():
        return False, "No legacy key file found"

    legacy_key = load_from_env_file(legacy_path)
    if not legacy_key:
        return False, "Legacy file exists but contains no valid key"

    # Check if we already have the key in secure storage
    keyring_key = load_from_keyring()
    if keyring_key:
        if keyring_key == legacy_key:
            logger.info("API key already migrated to keyring")
            return True, "Key already in keyring - you can safely delete legacy .env"
        else:
            logger.warning("Different key in keyring vs legacy - keeping both")
            return False, "Conflicting keys detected - manual intervention required"

    # Migrate to secure storage
    logger.info("Migrating API key from legacy location to secure storage...")
    if save_api_key(legacy_key):
        logger.info("Migration successful!")
        return True, f"Migrated to secure storage. You can now safely delete: {legacy_path}"
    else:
        logger.error("Migration failed")
        return False, "Failed to save key to secure storage"


def load_api_key() -> Optional[str]:
    """Load the Gemini API key.

    Priority:
        1. GEMINI_API_KEY_FREE environment variable
        2. GEMINI_API_KEY environment variable
        3. OS keyring
        4. User config .env
        5. Legacy .env

    Automatically attempts migration if only legacy key exists.

    Returns:
        The API key if found, None otherwise.
    """
    # Check environment variables first
    env_key = os.environ.get(PREFERRED_ENV_VAR) or os.environ.get(PRIMARY_ENV_VAR)
    if env_key:
        return env_key

    # Check keyring
    keyring_key = load_from_keyring()
    if keyring_key:
        return keyring_key

    # Check user config .env
    env_file_key = load_from_env_file(get_env_file_path())
    if env_file_key:
        return env_file_key

    # Check legacy location and attempt migration
    legacy_key = load_from_env_file(get_legacy_env_path())
    if legacy_key:
        logger.warning("Using legacy API key storage - attempting migration...")
        success, message = migrate_legacy_key()
        if success:
            logger.info(message)
        else:
            logger.warning("Migration issue: %s", message)
        return legacy_key

    return None


def save_api_key(api_key: str) -> bool:
    """Save the API key securely.

    Primary: OS keyring (encrypted, persistent)
    Fallback: .env in per-user config dir with secure permissions

    Note: Also sets os.environ for current process to avoid reload overhead.

    Args:
        api_key: The API key to save.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        # Sanitize input: remove quotes, whitespace, control characters
        api_key = api_key.strip().strip("'\"").strip()

        # Try keyring first
        keyring_ok = save_to_keyring(api_key)
        if keyring_ok:
            logger.info("API key saved to keyring successfully")
        else:
            logger.warning("Keyring unavailable, using file storage instead")

        # Always persist a copy to per-user config file
        store_in_env_file(api_key)

        # Set in current process environment for immediate use
        os.environ[PREFERRED_ENV_VAR] = api_key
        os.environ[PRIMARY_ENV_VAR] = api_key

        return True

    except FileExistsError:
        # File was created between check and open - just update permissions and retry
        logger.debug("File created concurrently, retrying...")
        harden_file_permissions(get_env_file_path())
        set_key(str(get_env_file_path()), PRIMARY_ENV_VAR, api_key)
        os.environ[PRIMARY_ENV_VAR] = api_key
        return True

    except Exception as e:
        logger.error("Failed to save API key: %s", e)
        return False


def check_and_warn_legacy_storage() -> Optional[str]:
    """Check for legacy storage and return a warning message if found.

    Returns:
        Warning message if legacy storage is in use, None otherwise.
    """
    legacy_path = get_legacy_env_path()
    if not legacy_path.exists():
        return None

    # Check if we also have secure storage
    keyring_key = load_from_keyring()
    env_file_key = load_from_env_file(get_env_file_path())

    if keyring_key or env_file_key:
        return (
            f"Legacy .env file found at {legacy_path}. "
            "Your key has been migrated to secure storage. "
            "You can safely delete the legacy file."
        )

    return (
        f"Your API key is stored insecurely at {legacy_path}. "
        "Consider migrating to secure storage using the Settings menu."
    )
